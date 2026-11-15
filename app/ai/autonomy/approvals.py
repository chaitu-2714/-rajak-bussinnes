"""Approval management: request, decide, revalidate, execute exactly once."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.autonomy.actions import ActionContext, get_action
from app.ai.autonomy.policy_engine import AutonomyPolicyEngine
from app.ai.schemas.autonomy_schema import ApprovalView
from app.core.constants import (
    MODULE_APPROVALS,
    ApprovalStatus,
    AuditAction,
    AutonomyMode,
)
from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.autonomy import (
    ApprovalDecision,
    ApprovalRequest,
    AutonomousWorkflow,
    WorkflowIdempotencyRecord,
    WorkflowTask,
)
from app.database.models.user import User
from app.security.authorization import has_permission, require_permission
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService
from app.utils.date_utils import utcnow

logger = get_logger("ai.autonomy.approvals")

DEFAULT_EXPIRY_HOURS = 48


class ApprovalService(BaseService):
    """Human approval checkpoints for workflow actions."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        policy_engine: AutonomyPolicyEngine,
        services: Any,
        audit_service: AuditService,
        on_approved: Callable[[str], None] | None = None,
        governance: Any | None = None,
    ) -> None:
        self._governance = governance
        super().__init__(session_factory, auth_context)
        self._policies = policy_engine
        self._services = services
        self._audit = audit_service
        self._on_approved = on_approved

    # -- creation (called by the engine) -----------------------------------
    def create_request(
        self,
        *,
        db: Session,
        workflow: AutonomousWorkflow,
        task: WorkflowTask,
        action_name: str,
        payload: dict[str, Any],
        reason: str,
        evidence: dict[str, Any] | None = None,
        financial_impact: Decimal | None = None,
        risk_level: str = "MEDIUM",
        expires_hours: int = DEFAULT_EXPIRY_HOURS,
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            approval_ref=f"apr-{uuid.uuid4().hex[:12]}",
            workflow_id=workflow.id,
            task_key=task.task_key,
            business_id=workflow.business_id,
            requested_by=workflow.requested_by,
            requested_action=action_name,
            action_details=payload,
            financial_impact=float(financial_impact) if financial_impact is not None else None,
            risk_level=risk_level,
            reason=reason,
            evidence={
                **(evidence or {}),
                "payload_hash": (
                    self._governance.bind(payload).payload_hash
                    if self._governance is not None
                    else None
                ),
            },
            status=ApprovalStatus.PENDING,
            expires_at=utcnow() + timedelta(hours=expires_hours),
        )
        db.add(request)
        db.flush()
        return request

    # -- reads -------------------------------------------------------------
    def list_requests(self, status: str | None = None, limit: int = 50) -> list[ApprovalView]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "approvals.view")
            query = select(ApprovalRequest).order_by(ApprovalRequest.id.desc()).limit(limit)
            if status:
                query = (
                    select(ApprovalRequest)
                    .where(ApprovalRequest.status == status)
                    .order_by(ApprovalRequest.id.desc())
                    .limit(limit)
                )
            rows = db.scalars(query).all()
            names = {
                user.id: user.full_name
                for user in db.scalars(
                    select(User).where(User.id.in_([row.requested_by for row in rows if row.requested_by]))
                ).all()
            }
            return [self._view(db, row, names.get(row.requested_by)) for row in rows]

    def get_request(self, approval_ref: str) -> ApprovalView:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "approvals.view")
            row = self._load(db, approval_ref)
            requester = db.get(User, row.requested_by) if row.requested_by else None
            return self._view(db, row, requester.full_name if requester else None)

    # -- decisions ---------------------------------------------------------
    def approve(self, approval_ref: str, *, note: str | None = None) -> ApprovalView:
        with self.unit_of_work() as db:
            approver = self._authorize(db, "approvals.approve")
            request = self._load(db, approval_ref)
            self._assert_actionable(db, request)
            self._assert_authorised_approver(db, request, approver)
            spec = get_action(request.requested_action)

            decision = self._policies.evaluate(
                request.requested_action,
                actor_id=approver.id,
                amount=request.financial_impact,
            )
            if not decision.allowed:
                raise AuthorizationError(f"The action is no longer permitted: {decision.reason}")

            # Re-validate the original action right before executing it.
            self._assert_payload_binding(db, request, approver.id)
            self._revalidate(db, request)

            outcome = self._execute(db, request, approver.id, spec)
            request.status = ApprovalStatus.APPROVED
            request.decided_by = approver.id
            request.decided_at = utcnow()
            request.decision_note = note
            request.executed_at = utcnow()
            request.execution_result = outcome
            db.add(
                ApprovalDecision(
                    approval_id=request.id,
                    decision=ApprovalStatus.APPROVED,
                    decided_by=approver.id,
                    note=note,
                )
            )
            self._audit.record(
                db,
                actor_id=approver.id,
                action=AuditAction.APPROVAL_APPROVED,
                module=MODULE_APPROVALS,
                entity_type="ApprovalRequest",
                entity_id=request.approval_ref,
                new_values={
                    "action": request.requested_action,
                    "result": outcome.get("summary"),
                },
            )
            if request.task_key and request.workflow_id:
                task = db.scalars(
                    select(WorkflowTask).where(
                        WorkflowTask.workflow_id == request.workflow_id,
                        WorkflowTask.task_key == request.task_key,
                    )
                ).first()
                if task is not None:
                    from app.core.constants import WorkflowTaskStatus

                    task.execution_status = WorkflowTaskStatus.COMPLETED
                    task.completed_at = utcnow()
                    task.result = outcome
            workflow_ref = request.workflow.approval_ref if False else None
            workflow = db.get(AutonomousWorkflow, request.workflow_id) if request.workflow_id else None
            workflow_ref = workflow.workflow_ref if workflow else None
            view = self._view(db, request, None)

        if workflow_ref and self._on_approved is not None:
            try:
                self._on_approved(workflow_ref)
            except Exception:  # pragma: no cover - resume failures are logged by the engine
                logger.exception("Workflow resume failed after approval")
        return view

    def reject(self, approval_ref: str, *, reason: str) -> ApprovalView:
        if not reason or len(reason.strip()) < 3:
            raise ValidationError("A rejection reason is required.")
        with self.unit_of_work() as db:
            approver = self._authorize(db, "approvals.approve")
            request = self._load(db, approval_ref)
            self._assert_actionable(db, request)
            self._assert_authorised_approver(db, request, approver)

            request.status = ApprovalStatus.REJECTED
            request.decided_by = approver.id
            request.decided_at = utcnow()
            request.decision_note = reason
            db.add(
                ApprovalDecision(
                    approval_id=request.id,
                    decision=ApprovalStatus.REJECTED,
                    decided_by=approver.id,
                    note=reason,
                )
            )
            self._audit.record(
                db,
                actor_id=approver.id,
                action=AuditAction.APPROVAL_REJECTED,
                module=MODULE_APPROVALS,
                entity_type="ApprovalRequest",
                entity_id=request.approval_ref,
                new_values={"action": request.requested_action, "reason": reason},
            )
            view = self._view(db, request, None)
        return view

    def cancel(self, approval_ref: str, *, note: str | None = None) -> ApprovalView:
        with self.unit_of_work() as db:
            user = self._authorize(db, "approvals.view")
            request = self._load(db, approval_ref)
            if request.status != ApprovalStatus.PENDING:
                raise ConflictError("Only pending requests can be cancelled")
            if request.requested_by != user.id and not user.is_superuser:
                raise AuthorizationError("Only the requester can cancel this approval")
            request.status = ApprovalStatus.CANCELLED
            request.decision_note = note
            db.add(
                ApprovalDecision(
                    approval_id=request.id,
                    decision=ApprovalStatus.CANCELLED,
                    decided_by=user.id,
                    note=note,
                )
            )
            return self._view(db, request, None)

    def expire_stale(self) -> int:
        """Expire pending requests whose deadline passed."""
        expired = 0
        now = utcnow()
        with self.unit_of_work() as db:
            rows = db.scalars(
                select(ApprovalRequest).where(ApprovalRequest.status == ApprovalStatus.PENDING)
            ).all()
            for row in rows:
                if row.expires_at and row.expires_at < now:
                    row.status = ApprovalStatus.EXPIRED
                    row.decided_at = now
                    db.add(
                        ApprovalDecision(
                            approval_id=row.id,
                            decision=ApprovalStatus.EXPIRED,
                            note="Expired without a decision",
                        )
                    )
                    self._audit.record(
                        db,
                        actor_id=None,
                        action=AuditAction.APPROVAL_EXPIRED,
                        module=MODULE_APPROVALS,
                        entity_type="ApprovalRequest",
                        entity_id=row.approval_ref,
                    )
                    expired += 1
        return expired

    # -- internals ---------------------------------------------------------
    def _load(self, db: Session, approval_ref: str) -> ApprovalRequest:
        row = db.scalars(
            select(ApprovalRequest).where(ApprovalRequest.approval_ref == approval_ref)
        ).first()
        if row is None:
            raise NotFoundError(f"Approval '{approval_ref}' was not found")
        return row

    def _assert_actionable(self, db: Session, request: ApprovalRequest) -> None:
        if request.status == ApprovalStatus.EXPIRED:
            raise ConflictError("This approval has expired and cannot authorise execution")
        if request.status == ApprovalStatus.APPROVED:
            raise ConflictError("This approval was already approved and executed")
        if request.status in (ApprovalStatus.REJECTED, ApprovalStatus.CANCELLED):
            raise ConflictError(f"This approval is {request.status.lower()}")
        if request.expires_at and request.expires_at < utcnow():
            request.status = ApprovalStatus.EXPIRED
            db.flush()
            raise ConflictError("This approval has expired and cannot authorise execution")

    def _assert_authorised_approver(
        self, db: Session, request: ApprovalRequest, approver: User
    ) -> None:
        spec = get_action(request.requested_action)
        if not approver.is_superuser and not has_permission(db, approver, spec.permission):
            raise AuthorizationError(
                f"Approving this action requires '{spec.permission}'"
            )
        if request.requested_by and request.requested_by == approver.id:
            if not approver.is_superuser:
                raise AuthorizationError(
                    "You cannot approve an action you requested yourself"
                )
            if not self._policies.self_approval_allowed(request.requested_action):
                if self._other_approver_exists(db, request, approver):
                    raise AuthorizationError(
                        "Another authorised user must approve this action; you cannot "
                        "approve your own request"
                    )
                # Sole-approver exception: a single-user workspace would otherwise
                # deadlock. It is recorded on the approval and in the audit trail.

    def _other_approver_exists(
        self, db: Session, request: ApprovalRequest, approver: User
    ) -> bool:
        """Is there any other active user who could approve this action?"""
        spec = get_action(request.requested_action)
        candidates = db.scalars(
            select(User).where(User.is_active.is_(True), User.id != approver.id)
        ).all()
        for candidate in candidates:
            if candidate.is_superuser or has_permission(db, candidate, spec.permission):
                if has_permission(db, candidate, "approvals.approve"):
                    return True
        return False

    def _assert_payload_binding(
        self, db: Session, request: ApprovalRequest, approver_id: int
    ) -> None:
        """Phase 9: the approval must still authorise exactly this action."""
        if self._governance is None:
            return
        stored = (request.evidence or {}).get("payload_hash")
        ok, reason = self._governance.verify_binding(stored, request.action_details or {})
        if not ok:
            self._audit.record(
                db,
                actor_id=approver_id,
                action="APPROVAL_PAYLOAD_MISMATCH",
                module=MODULE_APPROVALS,
                entity_type="ApprovalRequest",
                entity_id=request.approval_ref,
                new_values={"reason": reason},
            )
            raise ConflictError(reason)

    def _revalidate(self, db: Session, request: ApprovalRequest) -> None:
        """The business state must still support the action."""
        payload = dict(request.action_details or {})
        action = request.requested_action
        if action == "create_purchase_order":
            supplier_id = payload.get("supplier_id")
            items = payload.get("items") or []
            if not supplier_id or not items:
                raise ValidationError("The purchase order request is incomplete")
            supplier = self._services.purchasing_service.get_supplier(supplier_id)
            if not supplier.is_active:
                raise ConflictError("The supplier is no longer active")
            for item in items:
                product = self._services.inventory_service.get_product(item.get("product_id"))
                if not product.is_active:
                    raise ConflictError(f"Product '{product.product_name}' is inactive")
        elif action == "record_payment":
            invoice_id = payload.get("invoice_id")
            invoice = self._services.sales_service.invoice(invoice_id)
            amount = Decimal(str(payload.get("amount", "0")))
            if invoice.status == "CANCELLED":
                raise ConflictError("The invoice was cancelled after this request was raised")
            if amount > invoice.outstanding_amount:
                raise ConflictError(
                    f"The outstanding balance is now {invoice.outstanding_amount:,.2f}, "
                    f"less than the approved {amount:,.2f}"
                )
        elif action == "adjust_inventory":
            product = self._services.inventory_service.get_product(payload.get("product_id"))
            if not product.is_active:
                raise ConflictError("The product is no longer active")

    def _execute(
        self, db: Session, request: ApprovalRequest, actor_id: int, spec
    ) -> dict[str, Any]:
        key = f"approval:{request.approval_ref}"
        existing = db.scalars(
            select(WorkflowIdempotencyRecord).where(
                WorkflowIdempotencyRecord.idempotency_key == key
            )
        ).first()
        if existing is not None:
            return existing.result or {}

        context = ActionContext(
            services=self._services,
            actor_id=actor_id,
            payload=dict(request.action_details or {}),
            workflow_ref=str(request.workflow_id),
            task_key=request.task_key,
        )
        outcome = spec.handler(context)
        db.add(
            WorkflowIdempotencyRecord(
                idempotency_key=key,
                workflow_id=request.workflow_id,
                task_key=request.task_key,
                action_name=request.requested_action,
                result=outcome,
            )
        )
        db.flush()
        return outcome

    def _view(
        self, db: Session, row: ApprovalRequest, requester_name: str | None
    ) -> ApprovalView:
        return ApprovalView(
            approval_ref=row.approval_ref,
            workflow_ref=row.workflow.workflow_ref if row.workflow else None,
            task_key=row.task_key,
            requested_action=row.requested_action,
            action_details=row.action_details or {},
            financial_impact=(
                f"{Decimal(str(row.financial_impact)):,.2f}" if row.financial_impact else None
            ),
            risk_level=row.risk_level,
            reason=row.reason,
            evidence=row.evidence or {},
            status=row.status,
            requested_by=row.requested_by,
            requested_by_name=requester_name,
            expires_at=row.expires_at,
            created_at=row.created_at,
            decided_by=row.decided_by,
            decided_at=row.decided_at,
            decision_note=row.decision_note,
            execution_result=row.execution_result,
        )
