"""Data access for AI conversations, workflows, tools and settings."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database.models.ai import (
    AIConversation,
    AIMessage,
    AIModelSetting,
    AIToolRegistryEntry,
    AIWorkflow,
    AIWorkflowStep,
)


class AIRepository:
    """All SQL for the AI layer lives here."""

    # -- conversations -----------------------------------------------------
    def add_conversation(self, db: Session, conversation: AIConversation) -> AIConversation:
        db.add(conversation)
        db.flush()
        return conversation

    def get_conversation(self, db: Session, conversation_id: int) -> AIConversation | None:
        return db.get(AIConversation, conversation_id)

    def list_conversations(
        self, db: Session, *, user_id: int, limit: int = 30
    ) -> list[AIConversation]:
        return list(
            db.scalars(
                select(AIConversation)
                .where(AIConversation.user_id == user_id)
                .order_by(AIConversation.updated_at.desc())
                .limit(limit)
            ).all()
        )

    def touch_conversation(self, db: Session, conversation: AIConversation) -> None:
        from app.utils.date_utils import utcnow

        conversation.updated_at = utcnow()
        db.flush()

    # -- messages ----------------------------------------------------------
    def add_message(self, db: Session, message: AIMessage) -> AIMessage:
        db.add(message)
        db.flush()
        return message

    def list_messages(self, db: Session, conversation_id: int, *, limit: int = 200) -> list[AIMessage]:
        return list(
            db.scalars(
                select(AIMessage)
                .where(AIMessage.conversation_id == conversation_id)
                .order_by(AIMessage.id)
                .limit(limit)
            ).all()
        )

    def count_messages(self, db: Session, conversation_id: int) -> int:
        return int(
            db.scalar(
                select(func.count(AIMessage.id)).where(
                    AIMessage.conversation_id == conversation_id
                )
            )
            or 0
        )

    def delete_messages(self, db: Session, conversation_id: int) -> int:
        messages = db.scalars(
            select(AIMessage).where(AIMessage.conversation_id == conversation_id)
        ).all()
        for message in messages:
            db.delete(message)
        db.flush()
        return len(messages)

    # -- workflows ---------------------------------------------------------
    def get_workflow(self, db: Session, workflow_id: str) -> AIWorkflow | None:
        return db.scalars(
            select(AIWorkflow)
            .options(selectinload(AIWorkflow.steps))
            .where(AIWorkflow.workflow_id == workflow_id)
        ).first()

    def list_workflows(
        self,
        db: Session,
        *,
        conversation_id: int | None = None,
        user_id: int | None = None,
        limit: int = 20,
    ) -> list[AIWorkflow]:
        stmt = select(AIWorkflow).options(selectinload(AIWorkflow.steps))
        if conversation_id is not None:
            stmt = stmt.where(AIWorkflow.conversation_id == conversation_id)
        if user_id is not None:
            stmt = stmt.where(AIWorkflow.user_id == user_id)
        stmt = stmt.order_by(AIWorkflow.id.desc()).limit(limit)
        return list(db.scalars(stmt).unique().all())

    def workflow_for_event(self, db: Session, event_id: int) -> AIWorkflow | None:
        return db.scalars(
            select(AIWorkflow).where(AIWorkflow.source_event_id == event_id)
        ).first()

    def count_workflows(self, db: Session, *, status: str | None = None) -> int:
        stmt = select(func.count(AIWorkflow.id))
        if status:
            stmt = stmt.where(AIWorkflow.status == status)
        return int(db.scalar(stmt) or 0)

    def steps_for(self, db: Session, workflow_row_id: int) -> list[AIWorkflowStep]:
        return list(
            db.scalars(
                select(AIWorkflowStep)
                .where(AIWorkflowStep.workflow_id == workflow_row_id)
                .order_by(AIWorkflowStep.step_number)
            ).all()
        )

    # -- tool registry mirror ---------------------------------------------
    def sync_tools(self, db: Session, tools: list[dict]) -> int:
        existing = {row.tool_name: row for row in db.scalars(select(AIToolRegistryEntry)).all()}
        changed = 0
        for tool in tools:
            row = existing.get(tool["tool_name"])
            if row is None:
                row = AIToolRegistryEntry(
                    tool_name=tool["tool_name"],
                    description=tool["description"],
                    category=tool.get("category"),
                    required_permission=tool["required_permission"],
                    risk_level=tool["risk_level"],
                    is_enabled=tool.get("is_enabled", True),
                )
                db.add(row)
                changed += 1
            else:
                row.description = tool["description"]
                row.category = tool.get("category")
                row.required_permission = tool["required_permission"]
                row.risk_level = tool["risk_level"]
        db.flush()
        return changed

    def list_tool_entries(self, db: Session) -> list[AIToolRegistryEntry]:
        return list(db.scalars(select(AIToolRegistryEntry).order_by(AIToolRegistryEntry.tool_name)).all())

    # -- model settings ----------------------------------------------------
    def list_settings(self, db: Session) -> list[AIModelSetting]:
        return list(db.scalars(select(AIModelSetting).order_by(AIModelSetting.priority)).all())

    def get_setting(self, db: Session, provider: str) -> AIModelSetting | None:
        return db.scalars(
            select(AIModelSetting).where(AIModelSetting.provider == provider)
        ).first()

    def upsert_setting(
        self,
        db: Session,
        *,
        provider: str,
        model_name: str,
        is_enabled: bool,
        priority: int,
        configuration: dict | None = None,
    ) -> AIModelSetting:
        row = self.get_setting(db, provider)
        if row is None:
            row = AIModelSetting(
                provider=provider,
                model_name=model_name,
                is_enabled=is_enabled,
                priority=priority,
                configuration=configuration or {},
            )
            db.add(row)
        else:
            row.model_name = model_name
            row.is_enabled = is_enabled
            row.priority = priority
            if configuration is not None:
                row.configuration = configuration
        db.flush()
        return row
