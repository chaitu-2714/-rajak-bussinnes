"""The central AI orchestrator.

Pipeline: command → intent → plan → validation → execution → response, with every
workflow persisted in SQLite. Events from Phase 2 enter through the same pipeline
so user commands and automation share one code path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.orchestrator.intent_classifier import IntentClassifier
from app.ai.orchestrator.task_planner import PlanningError, TaskPlanner
from app.ai.orchestrator.workflow_executor import WorkflowExecutor
from app.ai.registry.agent_registry import AgentRegistry
from app.ai.registry.tool_registry import ToolRegistry
from app.ai.routing.model_router import ModelRouter
from app.ai.schemas.intent_schema import ClassifiedBy, Intent, IntentResult
from app.ai.schemas.workflow_schema import (
    ExecutionPlan,
    PlanStep,
    StepResult,
    WorkflowPreview,
    WorkflowResult,
    WorkflowView,
)
from app.ai.validators.plan_validator import PlanValidator
from app.ai.validators.response_validator import ResponseValidator
from app.ai.validators.security import sanitise_command
from app.core.constants import (
    AIProviderName,
    AITriggerType,
    AIWorkflowStatus,
    MODULE_AGENTS,
    EventType,
    AuditAction,
)
from app.core.exceptions import AuthorizationError, BizPilotError, NotFoundError
from app.core.logging_config import get_logger
from app.database.models.ai import AIWorkflow, AIWorkflowStep
from app.database.models.events import BusinessEvent
from app.database.models.user import User
from app.security.authorization import has_permission
from app.services.audit_service import AuditService
from app.utils.date_utils import utcnow

logger = get_logger("ai.orchestrator")

#: Which analysis a business event triggers.
EVENT_INTENT_MAP: dict[str, Intent] = {
    EventType.SALE_COMPLETED: Intent.ANALYZE_SALES,
    EventType.SALE_CANCELLED: Intent.ANALYZE_SALES,
    EventType.STOCK_BELOW_MINIMUM: Intent.LOW_STOCK_ANALYSIS,
    EventType.EXPENSE_RECORDED: Intent.GET_EXPENSES,
    EventType.PAYMENT_RECEIVED: Intent.GET_CASH_FLOW,
    EventType.CUSTOMER_CREATED: Intent.CUSTOMER_ANALYSIS,
    EventType.PURCHASE_ORDER_CREATED: Intent.GET_SUPPLIER_DETAILS,
    EventType.GOODS_RECEIVED: Intent.CHECK_STOCK,
}


@dataclass
class OrchestratorConfig:
    max_steps: int = 8
    max_seconds: float = 180.0
    max_events_per_run: int = 10


class BizPilotOrchestrator:
    """Coordinates classification, planning, tools, execution and narration."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        services: Any,
        registry: ToolRegistry,
        agents: AgentRegistry,
        router: ModelRouter,
        executor: WorkflowExecutor,
        audit_service: AuditService,
        checkpoint_path: Path,
        config: OrchestratorConfig | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._services = services
        self._registry = registry
        self._agents = agents
        self._router = router
        self._executor = executor
        self._audit = audit_service
        self._config = config or OrchestratorConfig()
        self._classifier = IntentClassifier(router)
        self._planner = TaskPlanner(registry, max_steps=self._config.max_steps)
        self._validator = PlanValidator(registry, max_steps=self._config.max_steps)
        self._responses = ResponseValidator()
        self._checkpoint_path = Path(checkpoint_path)

    # -- accessors ---------------------------------------------------------
    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def agents(self) -> AgentRegistry:
        return self._agents

    @property
    def router(self) -> ModelRouter:
        return self._router

    @property
    def classifier(self) -> IntentClassifier:
        return self._classifier

    @property
    def executor(self) -> WorkflowExecutor:
        return self._executor

    # -- permissions -------------------------------------------------------
    def permission_checker(self, user_id: int) -> Callable[[str], bool]:
        """Return a checker bound to one user, evaluated against the database."""

        def check(permission: str) -> bool:
            with self._session_factory() as db:
                user = db.get(User, user_id)
                if user is None or not user.is_active:
                    return False
                return has_permission(db, user, permission)

        return check

    # -- command entry point ----------------------------------------------
    def begin_command(
        self,
        user_id: int,
        command: str,
        *,
        conversation_id: int | None = None,
        trigger_type: str = AITriggerType.COMMAND,
    ) -> WorkflowPreview:
        """Classify and plan a command, persisting the workflow before execution."""
        checker = self.permission_checker(user_id)
        if not checker("agents.execute"):
            raise AuthorizationError("Your role cannot run AI commands")

        text, flagged = sanitise_command(command)
        if not text:
            raise BizPilotError("Enter a command first.")

        classification = self._classifier.classify(text)
        logger.info(
            "Command %r → %s (%.2f, %s)",
            text[:80],
            classification.intent.value,
            classification.confidence,
            classification.classified_by.value,
        )

        # Unknown or ambiguous commands still get a workflow record for the history.
        if classification.intent is Intent.UNKNOWN_INTENT or classification.requires_clarification:
            workflow_id = self._new_workflow_id()
            message = (
                classification.clarification_question
                or "I could not map that to a supported business operation. Try asking about "
                "revenue, expenses, profit, stock, sales, customers, suppliers or reports."
            )
            row = self._create_workflow(
                workflow_id=workflow_id,
                user_id=user_id,
                conversation_id=conversation_id,
                intent=classification.intent,
                command=text,
                plan=None,
                trigger_type=trigger_type,
                status=AIWorkflowStatus.COMPLETED,
                provider=classification.classified_by.value,
                result={"message": message},
            )
            self._audit_ai(
                user_id,
                AuditAction.AI_COMMAND,
                row.id,
                {
                    "intent": classification.intent.value,
                    "confidence": classification.confidence,
                    "outcome": "clarification",
                },
            )
            return WorkflowPreview(
                workflow_id=workflow_id,
                intent=classification.intent,
                confidence=classification.confidence,
                classified_by=classification.classified_by.value,
                steps=[],
                clarification_question=message,
            )

        try:
            plan = self._planner.plan(classification)
        except PlanningError as exc:
            workflow_id = self._new_workflow_id()
            row = self._create_workflow(
                workflow_id=workflow_id,
                user_id=user_id,
                conversation_id=conversation_id,
                intent=classification.intent,
                command=text,
                plan=None,
                trigger_type=trigger_type,
                status=AIWorkflowStatus.FAILED,
                provider=classification.classified_by.value,
                result={"message": exc.user_message},
                error=exc.user_message,
            )
            self._audit_ai(
                user_id,
                AuditAction.AI_COMMAND,
                row.id,
                {"intent": classification.intent.value, "outcome": "planning_failed"},
            )
            return WorkflowPreview(
                workflow_id=workflow_id,
                intent=classification.intent,
                confidence=classification.confidence,
                classified_by=classification.classified_by.value,
                steps=[],
                clarification_question=exc.user_message,
            )

        validation = self._validator.validate(plan, permission_checker=checker)
        if not validation.is_valid:
            workflow_id = self._new_workflow_id()
            message = "This request cannot run: " + "; ".join(validation.errors)
            row = self._create_workflow(
                workflow_id=workflow_id,
                user_id=user_id,
                conversation_id=conversation_id,
                intent=classification.intent,
                command=text,
                plan=plan.model_dump(mode="json"),
                trigger_type=trigger_type,
                status=AIWorkflowStatus.FAILED,
                provider=classification.classified_by.value,
                result={"message": message},
                error=message,
            )
            self._audit_ai(
                user_id,
                AuditAction.AI_COMMAND,
                row.id,
                {
                    "intent": classification.intent.value,
                    "outcome": "validation_failed",
                    "errors": validation.errors[:5],
                },
            )
            return WorkflowPreview(
                workflow_id=workflow_id,
                intent=classification.intent,
                confidence=classification.confidence,
                classified_by=classification.classified_by.value,
                steps=plan.steps,
                requires_approval=validation.requires_approval,
                clarification_question=message,
            )

        workflow_id = self._new_workflow_id()
        # Preparation steps are read-only, so the workflow runs them and then
        # parks in WAITING_FOR_APPROVAL before any data-changing action.
        status = AIWorkflowStatus.PENDING
        row = self._create_workflow(
            workflow_id=workflow_id,
            user_id=user_id,
            conversation_id=conversation_id,
            intent=classification.intent,
            command=text,
            plan=plan.model_dump(mode="json"),
            trigger_type=trigger_type,
            status=status,
            provider=classification.classified_by.value,
        )
        self._audit_ai(
            user_id,
            AuditAction.AI_COMMAND,
            row.id,
            {
                "intent": classification.intent.value,
                "confidence": classification.confidence,
                "steps": plan.tool_names,
                "requires_approval": validation.requires_approval,
            },
        )
        return WorkflowPreview(
            workflow_id=workflow_id,
            intent=classification.intent,
            confidence=classification.confidence,
            classified_by=classification.classified_by.value,
            steps=plan.steps,
            requires_approval=validation.requires_approval,
        )

    def process_command(
        self,
        user_id: int,
        business_id: int | None,
        command: str,
        *,
        conversation_id: int | None = None,
    ) -> WorkflowResult:
        """Classify, plan, execute and narrate a command in one call."""
        preview = self.begin_command(user_id, command, conversation_id=conversation_id)
        if preview.clarification_question and not preview.steps:
            return WorkflowResult(
                workflow_id=preview.workflow_id,
                intent=preview.intent,
                status=AIWorkflowStatus.COMPLETED,
                response_text=preview.clarification_question,
                provider=AIProviderName.FALLBACK,
            )
        if preview.requires_approval:
            return self._waiting_result(preview)
        return self.execute_workflow(preview.workflow_id)

    # -- execution ---------------------------------------------------------
    def execute_workflow(self, workflow_id: str) -> WorkflowResult:
        """Run (or return) one workflow and build the user-facing response."""
        with self._session_factory() as db:
            row = self._load(db, workflow_id)
            if row is None:
                raise NotFoundError(f"Workflow {workflow_id} was not found")
            if row.status in AIWorkflowStatus.TERMINAL:
                return self._result_from_row(db, row)
            if row.status == AIWorkflowStatus.WAITING_FOR_APPROVAL:
                plan = ExecutionPlan.model_validate(row.execution_plan or {})
                return self._waiting_result(
                    WorkflowPreview(
                        workflow_id=workflow_id,
                        intent=plan.intent,
                        steps=plan.steps,
                        requires_approval=True,
                    )
                )
            user_id = row.user_id or 0

        checker = self.permission_checker(user_id)
        result = self._executor.execute(workflow_id, permission_checker=checker)

        plan = self._plan_of(workflow_id)
        if result.status == AIWorkflowStatus.WAITING_FOR_APPROVAL:
            # The draft is ready; the action itself needs a human decision.
            draft_note = next(
                (
                    step.data.get("summary", "")
                    for step in result.steps
                    if step.data.get("draft_action")
                ),
                "",
            )
            waiting_text = (
                "Prepared and waiting for your approval.\n"
                + (draft_note + "\n" if draft_note else "")
                + "Approve this workflow to apply the change."
            )
            validated_waiting = self._responses.validate(waiting_text)
            with self._session_factory() as db:
                row = self._load(db, workflow_id)
                if row is not None:
                    row.result = {
                        "steps": [step.model_dump(mode="json") for step in result.steps],
                        "message": validated_waiting.text,
                        "provider": AIProviderName.FALLBACK,
                        "requires_approval": True,
                    }
                    row.provider = AIProviderName.FALLBACK
                    db.commit()
            self._audit_ai(
                user_id,
                AuditAction.AI_WORKFLOW_COMPLETED,
                None,
                {"workflow_id": workflow_id, "intent": result.intent.value, "status": "WAITING_FOR_APPROVAL"},
                entity_id=workflow_id,
            )
            return result.model_copy(
                update={
                    "response_text": validated_waiting.text,
                    "provider": AIProviderName.FALLBACK,
                    "requires_approval": True,
                }
            )
        response_text, provider = self._compose_response(
            intent=result.intent, results=result.steps, user_id=user_id
        )
        validated = self._responses.validate(response_text)

        with self._session_factory() as db:
            row = self._load(db, workflow_id)
            if row is not None:
                row.result = {
                    "steps": [step.model_dump(mode="json") for step in result.steps],
                    "message": validated.text,
                    "provider": provider,
                }
                row.provider = provider
                if result.status in AIWorkflowStatus.TERMINAL:
                    row.completed_at = utcnow()
                db.commit()

        self._audit_ai(
            user_id,
            AuditAction.AI_WORKFLOW_COMPLETED
            if result.status == AIWorkflowStatus.COMPLETED
            else AuditAction.AI_WORKFLOW_FAILED,
            None,
            {
                "workflow_id": workflow_id,
                "intent": result.intent.value,
                "status": result.status,
                "steps": [step.tool_name for step in result.steps],
                "error": result.error,
            },
            entity_id=workflow_id,
        )

        return result.model_copy(
            update={
                "response_text": validated.text,
                "provider": provider,
                "requires_approval": bool(plan.requires_approval) if plan else False,
            }
        )

    def cancel_workflow(self, workflow_id: str) -> bool:
        with self._session_factory() as db:
            row = self._load(db, workflow_id)
            if row is None:
                raise NotFoundError(f"Workflow {workflow_id} was not found")
            if row.status in AIWorkflowStatus.TERMINAL:
                return False
            user_id = row.user_id or 0
        self._executor.cancel(workflow_id)
        self._audit_ai(
            user_id, AuditAction.AI_WORKFLOW_CANCELLED, None, {"workflow_id": workflow_id},
            entity_id=workflow_id,
        )
        return True

    def approve_workflow(self, workflow_id: str) -> WorkflowResult:
        """Execute the action a workflow was waiting on."""
        with self._session_factory() as db:
            row = self._load(db, workflow_id)
            if row is None:
                raise NotFoundError(f"Workflow {workflow_id} was not found")
            if row.status != AIWorkflowStatus.WAITING_FOR_APPROVAL:
                raise BizPilotError("This workflow is not waiting for approval")
            plan = ExecutionPlan.model_validate(row.execution_plan or {})
            user_id = row.user_id or 0
            steps = db.scalars(
                select(AIWorkflowStep)
                .where(AIWorkflowStep.workflow_id == row.id)
                .order_by(AIWorkflowStep.step_number)
            ).all()
            pending_payload: dict[str, Any] = {}
            for step in steps:
                if step.output_data and step.output_data.get("draft_action"):
                    pending_payload = dict(step.output_data)

        checker = self.permission_checker(user_id)
        action = pending_payload.get("draft_action")
        try:
            message = self._execute_approved_action(action, pending_payload, checker)
        except BizPilotError as exc:
            with self._session_factory() as db:
                row = self._load(db, workflow_id)
                if row is not None:
                    row.status = AIWorkflowStatus.FAILED
                    row.completed_at = utcnow()
                    row.error_message = exc.user_message
                    db.commit()
            raise

        with self._session_factory() as db:
            row = self._load(db, workflow_id)
            if row is not None:
                row.status = AIWorkflowStatus.COMPLETED
                row.completed_at = utcnow()
                row.result = {**(row.result or {}), "message": message, "approved": True}
                db.commit()
        self._audit_ai(
            user_id,
            AuditAction.AI_WORKFLOW_APPROVED,
            None,
            {"workflow_id": workflow_id, "action": action},
            entity_id=workflow_id,
        )
        return WorkflowResult(
            workflow_id=workflow_id,
            intent=plan.intent,
            status=AIWorkflowStatus.COMPLETED,
            response_text=message,
            provider=AIProviderName.FALLBACK,
            requires_approval=False,
        )

    def _execute_approved_action(
        self, action: str | None, payload: dict[str, Any], checker: Callable[[str], bool]
    ) -> str:
        """Run the approved business action through the real Phase 2 service."""
        if action == "CREATE_SALES_ORDER":
            if not checker("sales.create"):
                raise AuthorizationError("You no longer have permission to create sales")
            items = [
                {"product_id": item["product_id"], "quantity": item["quantity"]}
                for item in payload.get("items", [])
            ]
            if not items:
                raise BizPilotError("The approved order has no line items")
            order = self._services.sales_service.create_order(
                {
                    "customer_id": payload["customer_id"],
                    "items": items,
                    "notes": "Created from an approved AI workflow",
                }
            )
            return (
                f"Sales order {order.order_number} was created as a draft for "
                f"{order.customer_name} ({order.total_amount:,.2f}). "
                "Open the Sales page to confirm and complete it."
            )
        if action == "CREATE_EXPENSE":
            if not checker("finance.create"):
                raise AuthorizationError("You no longer have permission to record expenses")
            expense = self._services.finance_service.create_expense(
                {
                    "expense_category": payload.get("expense_category", "OTHER"),
                    "description": payload.get("description", "Approved AI expense"),
                    "vendor_name": payload.get("vendor_name"),
                    "amount": str(payload.get("amount", "")).replace(",", "").strip(),
                    "payment_method": payload.get("payment_method", "CASH"),
                    "expense_date": utcnow(),
                }
            )
            return (
                f"Expense {expense.expense_number} for {expense.amount:,.2f} was recorded "
                f"({expense.expense_category})."
            )
        raise BizPilotError("This workflow has no approvable action")

    # -- events ------------------------------------------------------------
    def process_event(self, event_id: int) -> WorkflowResult | None:
        """Run the analysis a business event triggers (idempotent per event)."""
        with self._session_factory() as db:
            event = db.get(BusinessEvent, event_id)
            if event is None:
                return None
            existing = db.scalars(
                select(AIWorkflow).where(AIWorkflow.source_event_id == event_id)
            ).first()
            if existing is not None:
                logger.debug("Event %s already processed by workflow %s", event_id, existing.workflow_id)
                return None
            intent = EVENT_INTENT_MAP.get(event.event_type)
            if intent is None:
                return None
            owner = db.scalars(
                select(User).where(User.is_superuser.is_(True), User.is_active.is_(True))
            ).first()
            if owner is None:
                return None
            owner_id = owner.id

        classification = IntentResult(
            intent=intent,
            confidence=0.99,
            classified_by=ClassifiedBy.FALLBACK,
            rationale=f"Triggered by the {event.event_type} business event",
            entities={},
        )
        try:
            plan = self._planner.plan(classification)
        except PlanningError as exc:  # pragma: no cover - all mapped intents plan
            logger.warning("No plan for event %s: %s", event_id, exc.user_message)
            return None

        workflow_id = self._new_workflow_id()
        row = self._create_workflow(
            workflow_id=workflow_id,
            user_id=owner_id,
            conversation_id=None,
            intent=intent,
            command=f"Event: {event.event_type}",
            plan=plan.model_dump(mode="json"),
            trigger_type=AITriggerType.EVENT,
            status=AIWorkflowStatus.PENDING,
            provider=AIProviderName.FALLBACK,
            source_event_id=event_id,
        )
        result = self.execute_workflow(workflow_id)
        self._audit_ai(
            owner_id,
            AuditAction.AI_EVENT_PROCESSED,
            row.id,
            {"event_id": event_id, "event_type": event.event_type, "status": result.status},
        )
        return result

    def process_pending_events(self, limit: int | None = None) -> int:
        """Process business events that have no AI workflow yet."""
        processed = 0
        with self._session_factory() as db:
            events = db.scalars(
                select(BusinessEvent)
                .order_by(BusinessEvent.id.desc())
                .limit(limit or self._config.max_events_per_run)
            ).all()
            candidates = [
                event.id
                for event in events
                if db.scalars(
                    select(AIWorkflow.id).where(AIWorkflow.source_event_id == event.id)
                ).first()
                is None
            ]
        for event_id in reversed(candidates):
            try:
                if self.process_event(event_id) is not None:
                    processed += 1
            except BizPilotError as exc:
                logger.warning("Event %s could not be processed: %s", event_id, exc.message)
        return processed

    # -- status ------------------------------------------------------------
    def get_workflow_status(self, workflow_id: str) -> WorkflowView:
        with self._session_factory() as db:
            row = self._load(db, workflow_id)
            if row is None:
                raise NotFoundError(f"Workflow {workflow_id} was not found")
            steps = db.scalars(
                select(AIWorkflowStep)
                .where(AIWorkflowStep.workflow_id == row.id)
                .order_by(AIWorkflowStep.step_number)
            ).all()
            return WorkflowView(
                id=row.id,
                workflow_id=row.workflow_id,
                intent=row.intent,
                status=row.status,
                command=row.command,
                trigger_type=row.trigger_type,
                provider=row.provider,
                current_step=row.current_step,
                step_count=len(steps),
                error_message=row.error_message,
                created_at=row.created_at,
                completed_at=row.completed_at,
                steps=[
                    {
                        "step_number": step.step_number,
                        "tool": step.tool_name,
                        "status": step.status,
                        "risk": step.risk_level,
                        "permission": step.required_permission,
                        "duration_ms": step.duration_ms,
                        "error": step.error_message,
                        "output": step.output_data,
                    }
                    for step in steps
                ],
            )

    def recover(self) -> int:
        """Mark workflows interrupted by a restart as failed (retryable)."""
        return self._executor.recover_interrupted()

    # -- narration ---------------------------------------------------------
    def _compose_response(
        self, *, intent: Intent, results: list[StepResult], user_id: int
    ) -> tuple[str, str]:
        summaries = [result.summary for result in results if result.summary]
        warnings: list[str] = []
        for result in results:
            for warning in result.data.get("warnings", []) or []:
                warnings.append(str(warning))

        business_name = "your business"
        with self._session_factory() as db:
            business = self._services.business_repository.get_primary(db)
            if business is not None:
                business_name = business.business_name

        prompt = (
            f"Business: {business_name}\n"
            f"Request type: {intent.value}\n"
            "Verified results (authoritative, do not change the numbers):\n"
            + "\n".join(f"- {summary}" for summary in summaries)
            + ("\nWarnings:\n" + "\n".join(f"- {warning}" for warning in warnings) if warnings else "")
            + "\nWrite a short answer for the owner using only these figures."
        )
        reply = self._router.explain(prompt)
        if reply is not None and reply.text.strip():
            return reply.text.strip(), reply.provider

        return (
            self._router.narrator.compose(
                intent_label=intent.value.replace("_", " ").title(),
                step_summaries=summaries,
                business_name=business_name,
                warnings=warnings,
            ),
            AIProviderName.FALLBACK,
        )

    # -- persistence helpers ----------------------------------------------
    @staticmethod
    def _new_workflow_id() -> str:
        return f"wf-{uuid.uuid4().hex[:16]}"

    def _create_workflow(
        self,
        *,
        workflow_id: str,
        user_id: int,
        conversation_id: int | None,
        intent: Intent,
        command: str | None,
        plan: dict[str, Any] | None,
        trigger_type: str,
        status: str,
        provider: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        source_event_id: int | None = None,
    ) -> AIWorkflow:
        with self._session_factory() as db:
            row = AIWorkflow(
                workflow_id=workflow_id,
                conversation_id=conversation_id,
                user_id=user_id,
                intent=intent.value,
                command=command,
                execution_plan=plan,
                status=status,
                trigger_type=trigger_type,
                source_event_id=source_event_id,
                provider=provider,
                result=result,
                error_message=error,
                started_at=utcnow() if status == AIWorkflowStatus.RUNNING else None,
                completed_at=utcnow() if status in AIWorkflowStatus.TERMINAL else None,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def _load(self, db: Session, workflow_id: str) -> AIWorkflow | None:
        return db.scalars(
            select(AIWorkflow).where(AIWorkflow.workflow_id == workflow_id)
        ).first()

    def _plan_of(self, workflow_id: str) -> ExecutionPlan | None:
        with self._session_factory() as db:
            row = self._load(db, workflow_id)
            if row is None or not row.execution_plan:
                return None
            try:
                return ExecutionPlan.model_validate(row.execution_plan)
            except Exception:  # pragma: no cover - defensive
                return None

    def _waiting_result(self, preview: WorkflowPreview) -> WorkflowResult:
        steps = ", ".join(step.tool_name for step in preview.steps)
        return WorkflowResult(
            workflow_id=preview.workflow_id,
            intent=preview.intent,
            status=AIWorkflowStatus.WAITING_FOR_APPROVAL,
            response_text=(
                "This request changes business data, so it is waiting for your approval.\n"
                f"Planned action: {steps}. Review it and approve to continue."
            ),
            provider=AIProviderName.FALLBACK,
            requires_approval=True,
        )

    def _result_from_row(self, db: Session, row: AIWorkflow) -> WorkflowResult:
        stored = row.result or {}
        steps = [
            StepResult.model_validate(item)
            for item in stored.get("steps", [])
            if isinstance(item, dict)
        ]
        try:
            intent = Intent(row.intent)
        except ValueError:  # pragma: no cover - defensive
            intent = Intent.UNKNOWN_INTENT
        return WorkflowResult(
            workflow_id=row.workflow_id,
            intent=intent,
            status=row.status,
            steps=steps,
            response_text=str(stored.get("message", "")),
            provider=row.provider or AIProviderName.FALLBACK,
            error=row.error_message,
            completed_at=row.completed_at,
        )

    def _audit_ai(
        self,
        user_id: int | None,
        action: str,
        workflow_row_id: int | None,
        details: dict[str, Any],
        *,
        entity_id: str | None = None,
    ) -> None:
        try:
            with self._session_factory() as db:
                self._audit.record(
                    db,
                    actor_id=user_id,
                    action=action,
                    module=MODULE_AGENTS,
                    entity_type="AIWorkflow",
                    entity_id=entity_id or (str(workflow_row_id) if workflow_row_id else None),
                    new_values=details,
                )
                db.commit()
        except Exception:  # pragma: no cover - auditing must never break a workflow
            logger.exception("Failed to write AI audit entry")
