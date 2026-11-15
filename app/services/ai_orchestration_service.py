"""AI orchestration service — the only AI entry point the UI uses.

It owns conversations, message history, provider settings and the workflow
history, and delegates every decision to :class:`BizPilotOrchestrator`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session, sessionmaker

from app.ai.events.event_processor import EventProcessingReport, EventProcessor
from app.ai.orchestrator.orchestrator import BizPilotOrchestrator
from app.ai.registry.agent_registry import AgentRegistry
from app.ai.registry.tool_registry import ToolRegistry
from app.ai.routing.model_router import ModelRouter, ProviderSetting
from app.ai.schemas.workflow_schema import (
    ConversationView,
    MessageView,
    WorkflowPreview,
    WorkflowResult,
    WorkflowView,
)
from app.core.constants import (
    AIProviderName,
    AIWorkflowStatus,
    MODULE_AGENTS,
    AuditAction,
)
from app.core.exceptions import AuthorizationError, BizPilotError, NotFoundError
from app.core.logging_config import get_logger
from app.database.models.ai import AIConversation, AIMessage
from app.database.repositories.ai_repository import AIRepository
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService
from app.utils.date_utils import utcnow

logger = get_logger("services.ai")

ROUTER_SETTING_PROVIDER = "router"
DEFAULT_ROUTER_CONFIG = {"cloud_sharing_enabled": False, "preferred_provider": "auto"}


@dataclass
class AISettingsView:
    providers: list[dict[str, Any]]
    cloud_sharing_enabled: bool
    preferred_provider: str
    credentials: dict[str, str]


class AIOrchestrationService(BaseService):
    """Conversation + workflow façade over the orchestrator."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        orchestrator: BizPilotOrchestrator,
        router: ModelRouter,
        registry: ToolRegistry,
        agents: AgentRegistry,
        ai_repository: AIRepository,
        audit_service: AuditService,
        event_processor: EventProcessor,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._orchestrator = orchestrator
        self._router = router
        self._registry = registry
        self._agents = agents
        self._ai = ai_repository
        self._audit = audit_service
        self._events = event_processor
        self._initialised = False

    # -- bootstrap ---------------------------------------------------------
    def bootstrap(self) -> None:
        """Seed tool rows and provider settings, then configure the router."""
        if self._initialised:
            return
        with self._unit():
            pass
        self._initialised = True

    def _unit(self):
        return self.unit_of_work()

    def sync_registries(self) -> None:
        """Mirror the tool registry and provider defaults into SQLite."""
        with self.unit_of_work() as db:
            self._ai.sync_tools(
                db,
                [
                    {
                        "tool_name": tool.name,
                        "description": tool.description,
                        "category": tool.category,
                        "required_permission": tool.required_permission,
                        "risk_level": tool.risk_level,
                        "is_enabled": tool.enabled,
                    }
                    for tool in self._registry.list_tools()
                ],
            )
            for provider in (AIProviderName.OLLAMA, AIProviderName.GEMINI):
                if self._ai.get_setting(db, provider) is None:
                    self._ai.upsert_setting(
                        db,
                        provider=provider,
                        model_name="llama3.2"
                        if provider == AIProviderName.OLLAMA
                        else "gemini-2.0-flash",
                        is_enabled=True,
                        priority=10 if provider == AIProviderName.OLLAMA else 20,
                    )
            if self._ai.get_setting(db, ROUTER_SETTING_PROVIDER) is None:
                self._ai.upsert_setting(
                    db,
                    provider=ROUTER_SETTING_PROVIDER,
                    model_name="n/a",
                    is_enabled=True,
                    priority=0,
                    configuration=dict(DEFAULT_ROUTER_CONFIG),
                )
            self._apply_settings(db)

    def _apply_settings(self, db: Session) -> None:
        settings = [
            ProviderSetting(
                provider=row.provider,
                model_name=row.model_name,
                is_enabled=row.is_enabled,
                priority=row.priority,
                configuration=dict(row.configuration or {}),
            )
            for row in self._ai.list_settings(db)
            if row.provider in (AIProviderName.OLLAMA, AIProviderName.GEMINI)
        ]
        router_row = self._ai.get_setting(db, ROUTER_SETTING_PROVIDER)
        config = dict(router_row.configuration or {}) if router_row else dict(DEFAULT_ROUTER_CONFIG)
        self._router.configure(
            settings=settings or None,
            cloud_sharing_enabled=bool(config.get("cloud_sharing_enabled", False)),
            preferred_provider=str(config.get("preferred_provider", "auto")),
        )

    # -- conversations -----------------------------------------------------
    def create_conversation(self, title: str | None = None) -> ConversationView:
        with self.unit_of_work() as db:
            user = self._authorize(db, "agents.execute")
            conversation = AIConversation(
                user_id=user.id,
                title=(title or "New conversation")[:160],
            )
            self._ai.add_conversation(db, conversation)
            return ConversationView(
                id=conversation.id,
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                message_count=0,
            )

    def list_conversations(self, limit: int = 30) -> list[ConversationView]:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "agents.view")
            return [
                ConversationView(
                    id=conversation.id,
                    title=conversation.title,
                    created_at=conversation.created_at,
                    updated_at=conversation.updated_at,
                    message_count=self._ai.count_messages(db, conversation.id),
                )
                for conversation in self._ai.list_conversations(db, user_id=user.id, limit=limit)
            ]

    def messages(self, conversation_id: int) -> list[MessageView]:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "agents.view")
            conversation = self._owned(db, conversation_id, user.id)
            return [
                MessageView(
                    id=message.id,
                    sender_type=message.sender_type,
                    content=message.message_content,
                    created_at=message.created_at,
                    meta=message.meta,
                )
                for message in self._ai.list_messages(db, conversation.id)
            ]

    def clear_conversation(self, conversation_id: int) -> int:
        with self.unit_of_work() as db:
            user = self._authorize(db, "agents.execute")
            conversation = self._owned(db, conversation_id, user.id)
            removed = self._ai.delete_messages(db, conversation.id)
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.AI_COMMAND,
                module=MODULE_AGENTS,
                entity_type="AIConversation",
                entity_id=conversation.id,
                new_values={"cleared_messages": removed},
            )
            return removed

    # -- commands ----------------------------------------------------------
    def begin_command(self, conversation_id: int, command: str) -> WorkflowPreview:
        """Record the user message and build the plan (no execution yet)."""
        with self.unit_of_work() as db:
            user = self._authorize(db, "agents.execute")
            conversation = self._owned(db, conversation_id, user.id)
            self._ai.add_message(
                db,
                AIMessage(
                    conversation_id=conversation.id,
                    sender_type="USER",
                    message_content=(command or "")[:2000],
                ),
            )
            if conversation.title in ("New conversation", "") and command:
                conversation.title = command.strip()[:60] or "New conversation"
            self._ai.touch_conversation(db, conversation)
            conversation_row_id = conversation.id
            user_id = user.id

        preview = self._orchestrator.begin_command(
            user_id, command, conversation_id=conversation_row_id
        )
        if preview.clarification_question and not preview.steps:
            self._store_assistant_message(
                conversation_row_id, preview.clarification_question, preview
            )
        return preview

    def execute_workflow(self, workflow_id: str) -> WorkflowResult:
        """Run a prepared workflow and store the assistant reply."""
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "agents.execute")
            row = self._ai.get_workflow(db, workflow_id)
            if row is None:
                raise NotFoundError(f"Workflow {workflow_id} was not found")
            if row.user_id != user.id:
                raise AuthorizationError("This workflow belongs to another user")
            conversation_id = row.conversation_id

        result = self._orchestrator.execute_workflow(workflow_id)
        if conversation_id is not None:
            self._store_assistant_message(
                conversation_id,
                result.response_text,
                WorkflowPreview(
                    workflow_id=result.workflow_id,
                    intent=result.intent,
                    steps=[],
                    requires_approval=result.requires_approval,
                ),
                status=result.status,
                provider=result.provider,
            )
        return result

    def run_command(self, conversation_id: int, command: str) -> WorkflowResult:
        """Convenience: classify, plan and execute in one call."""
        preview = self.begin_command(conversation_id, command)
        if preview.clarification_question and not preview.steps:
            return WorkflowResult(
                workflow_id=preview.workflow_id,
                intent=preview.intent,
                status=AIWorkflowStatus.COMPLETED,
                response_text=preview.clarification_question,
            )
        if preview.requires_approval:
            result = WorkflowResult(
                workflow_id=preview.workflow_id,
                intent=preview.intent,
                status=AIWorkflowStatus.WAITING_FOR_APPROVAL,
                response_text=(
                    "This request changes business data, so it is waiting for your approval. "
                    "Review the plan and approve it to continue."
                ),
                requires_approval=True,
            )
            return result
        return self.execute_workflow(preview.workflow_id)

    def approve_workflow(self, workflow_id: str) -> WorkflowResult:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "agents.execute")
            row = self._ai.get_workflow(db, workflow_id)
            if row is None:
                raise NotFoundError(f"Workflow {workflow_id} was not found")
            if row.user_id != user.id:
                raise AuthorizationError("This workflow belongs to another user")
            conversation_id = row.conversation_id

        result = self._orchestrator.approve_workflow(workflow_id)
        if conversation_id is not None:
            self._store_assistant_message(
                conversation_id,
                result.response_text,
                WorkflowPreview(workflow_id=workflow_id, intent=result.intent, steps=[]),
                status=AIWorkflowStatus.COMPLETED,
                provider=result.provider,
            )
        return result

    def cancel_workflow(self, workflow_id: str) -> bool:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "agents.execute")
            row = self._ai.get_workflow(db, workflow_id)
            if row is None:
                raise NotFoundError(f"Workflow {workflow_id} was not found")
            if row.user_id != user.id:
                raise AuthorizationError("This workflow belongs to another user")
        return self._orchestrator.cancel_workflow(workflow_id)

    def retry_workflow(self, workflow_id: str) -> WorkflowResult:
        with self.unit_of_work() as db:
            user = self._authorize(db, "agents.execute")
            row = self._ai.get_workflow(db, workflow_id)
            if row is None:
                raise NotFoundError(f"Workflow {workflow_id} was not found")
            if row.user_id != user.id:
                raise AuthorizationError("This workflow belongs to another user")
            if row.status not in (AIWorkflowStatus.FAILED, AIWorkflowStatus.CANCELLED):
                raise BizPilotError("Only failed or cancelled workflows can be retried")
            if not row.execution_plan:
                raise BizPilotError("This workflow has no plan to retry")
            row.status = AIWorkflowStatus.PENDING
            row.error_message = None
            conversation_id = row.conversation_id
        result = self._orchestrator.execute_workflow(workflow_id)
        if conversation_id is not None:
            self._store_assistant_message(
                conversation_id,
                result.response_text,
                WorkflowPreview(workflow_id=workflow_id, intent=result.intent, steps=[]),
                status=result.status,
                provider=result.provider,
            )
        return result

    # -- history -----------------------------------------------------------
    def list_workflows(
        self, *, conversation_id: int | None = None, limit: int = 20
    ) -> list[WorkflowView]:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "agents.view")
            rows = self._ai.list_workflows(
                db, conversation_id=conversation_id, user_id=user.id, limit=limit
            )
            return [
                WorkflowView(
                    id=row.id,
                    workflow_id=row.workflow_id,
                    intent=row.intent,
                    status=row.status,
                    command=row.command,
                    trigger_type=row.trigger_type,
                    provider=row.provider,
                    current_step=row.current_step,
                    step_count=len(row.steps),
                    error_message=row.error_message,
                    created_at=row.created_at,
                    completed_at=row.completed_at,
                    steps=[
                        {
                            "step_number": step.step_number,
                            "tool": step.tool_name,
                            "status": step.status,
                            "risk": step.risk_level,
                            "duration_ms": step.duration_ms,
                            "error": step.error_message,
                            "output": step.output_data,
                        }
                        for step in row.steps
                    ],
                )
                for row in rows
            ]

    def workflow_detail(self, workflow_id: str) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "agents.view")
            row = self._ai.get_workflow(db, workflow_id)
            if row is None:
                raise NotFoundError(f"Workflow {workflow_id} was not found")
            if row.user_id != user.id:
                raise AuthorizationError("This workflow belongs to another user")
            steps = self._ai.steps_for(db, row.id)
            return {
                "workflow_id": row.workflow_id,
                "intent": row.intent,
                "status": row.status,
                "command": row.command,
                "trigger": row.trigger_type,
                "provider": row.provider,
                "created_at": row.created_at,
                "completed_at": row.completed_at,
                "error": row.error_message,
                "plan": row.execution_plan,
                "result": row.result,
                "steps": [
                    {
                        "number": step.step_number,
                        "tool": step.tool_name,
                        "status": step.status,
                        "risk": step.risk_level,
                        "permission": step.required_permission,
                        "duration_ms": step.duration_ms,
                        "input": step.input_data,
                        "output": step.output_data,
                        "error": step.error_message,
                    }
                    for step in steps
                ],
            }

    # -- status / catalogue ------------------------------------------------
    def provider_health(self) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.view")
        return self._router.health()

    def agent_health(self) -> list[dict[str, Any]]:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "agents.view")
            checker = self._orchestrator.permission_checker(user.id)
        return [
            {
                "agent_id": health.agent_id,
                "name": health.name,
                "status": health.status,
                "detail": health.detail,
                "intents": health.intents,
                "tools": health.tools,
            }
            for health in self._agents.health(checker)
        ]

    def tool_catalogue(self) -> list[dict[str, Any]]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.view")
            return [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "category": tool.category,
                    "permission": tool.required_permission,
                    "risk": tool.risk_level,
                }
                for tool in self._registry.list_tools()
            ]

    def workflow_stats(self) -> dict[str, int]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.view")
            return {
                "total": self._ai.count_workflows(db),
                "completed": self._ai.count_workflows(db, status=AIWorkflowStatus.COMPLETED),
                "failed": self._ai.count_workflows(db, status=AIWorkflowStatus.FAILED),
                "waiting": self._ai.count_workflows(
                    db, status=AIWorkflowStatus.WAITING_FOR_APPROVAL
                ),
            }

    # -- events ------------------------------------------------------------
    def process_pending_events(self, limit: int = 5) -> EventProcessingReport:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.execute")
        return self._events.process_pending(limit)

    # -- settings ----------------------------------------------------------
    def get_settings(self) -> AISettingsView:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.view")
            rows = self._ai.list_settings(db)
            router_row = self._ai.get_setting(db, ROUTER_SETTING_PROVIDER)
            config = dict(router_row.configuration or {}) if router_row else {}
            providers = [
                {
                    "provider": row.provider,
                    "model_name": row.model_name,
                    "is_enabled": row.is_enabled,
                    "priority": row.priority,
                }
                for row in rows
                if row.provider in (AIProviderName.OLLAMA, AIProviderName.GEMINI)
            ]
            credentials = {
                provider: self._router._credentials.describe(provider)  # noqa: SLF001
                for provider in (AIProviderName.OLLAMA, AIProviderName.GEMINI)
            }
            return AISettingsView(
                providers=providers,
                cloud_sharing_enabled=bool(config.get("cloud_sharing_enabled", False)),
                preferred_provider=str(config.get("preferred_provider", "auto")),
                credentials=credentials,
            )

    def update_settings(
        self,
        *,
        providers: list[dict[str, Any]] | None = None,
        cloud_sharing_enabled: bool | None = None,
        preferred_provider: str | None = None,
    ) -> AISettingsView:
        with self.unit_of_work() as db:
            user = self._authorize(db, "agents.configure")
            for entry in providers or []:
                provider = str(entry.get("provider", "")).lower()
                if provider not in (AIProviderName.OLLAMA, AIProviderName.GEMINI):
                    continue
                self._ai.upsert_setting(
                    db,
                    provider=provider,
                    model_name=str(entry.get("model_name", "unknown"))[:80],
                    is_enabled=bool(entry.get("is_enabled", True)),
                    priority=int(entry.get("priority", 100)),
                )
            router_row = self._ai.get_setting(db, ROUTER_SETTING_PROVIDER)
            config = dict(router_row.configuration or {}) if router_row else dict(DEFAULT_ROUTER_CONFIG)
            if cloud_sharing_enabled is not None:
                config["cloud_sharing_enabled"] = bool(cloud_sharing_enabled)
            if preferred_provider is not None:
                config["preferred_provider"] = str(preferred_provider)
            self._ai.upsert_setting(
                db,
                provider=ROUTER_SETTING_PROVIDER,
                model_name="n/a",
                is_enabled=True,
                priority=0,
                configuration=config,
            )
            self._apply_settings(db)
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.AI_SETTINGS_UPDATED,
                module=MODULE_AGENTS,
                entity_type="AIModelSettings",
                entity_id=ROUTER_SETTING_PROVIDER,
                new_values=config,
            )
        return self.get_settings()

    def set_api_key(self, provider: str, api_key: str) -> str:
        with self.unit_of_work() as db:
            user = self._authorize(db, "agents.configure")
            self._router._credentials.set_api_key(provider, api_key)  # noqa: SLF001
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.AI_SETTINGS_UPDATED,
                module=MODULE_AGENTS,
                entity_type="AICredentials",
                entity_id=provider,
                new_values={"provider": provider, "api_key": "***redacted***"},
            )
        return self._router._credentials.describe(provider)  # noqa: SLF001

    def clear_api_key(self, provider: str) -> None:
        with self.unit_of_work() as db:
            user = self._authorize(db, "agents.configure")
            self._router._credentials.delete_api_key(provider)  # noqa: SLF001
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.AI_SETTINGS_UPDATED,
                module=MODULE_AGENTS,
                entity_type="AICredentials",
                entity_id=provider,
                new_values={"provider": provider, "api_key": "cleared"},
            )

    # -- helpers -----------------------------------------------------------
    def _owned(self, db: Session, conversation_id: int, user_id: int) -> AIConversation:
        conversation = self._ai.get_conversation(db, conversation_id)
        if conversation is None:
            raise NotFoundError(f"Conversation {conversation_id} was not found")
        if conversation.user_id != user_id:
            raise AuthorizationError("This conversation belongs to another user")
        return conversation

    def _store_assistant_message(
        self,
        conversation_id: int,
        text: str,
        preview: WorkflowPreview,
        *,
        status: str = AIWorkflowStatus.COMPLETED,
        provider: str = AIProviderName.FALLBACK,
    ) -> None:
        with self.unit_of_work() as db:
            conversation = self._ai.get_conversation(db, conversation_id)
            if conversation is None:
                return
            self._ai.add_message(
                db,
                AIMessage(
                    conversation_id=conversation.id,
                    sender_type="ASSISTANT",
                    message_content=(text or "")[:8000],
                    meta={
                        "workflow_id": preview.workflow_id,
                        "intent": preview.intent.value,
                        "status": status,
                        "provider": provider,
                        "requires_approval": preview.requires_approval,
                    },
                ),
            )
            self._ai.touch_conversation(db, conversation)
