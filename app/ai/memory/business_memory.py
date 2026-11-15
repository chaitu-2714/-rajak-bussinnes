"""Limited, auditable business memory for agents."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import AgentMemoryType
from app.core.logging_config import get_logger
from app.database.models.agents import Agent, AgentMemory
from app.utils.date_utils import utcnow

logger = get_logger("ai.memory")

MAX_MEMORIES_PER_AGENT = 200


class BusinessMemory:
    """Stores analysis snapshots and recommendation history.

    Memory is *not* treated as verified fact: it is context that an agent may read
    when it is relevant, and every row points at the execution that produced it.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def _agent_row(self, db: Session, agent_code: str) -> Agent | None:
        return db.scalars(select(Agent).where(Agent.agent_code == agent_code)).first()

    def remember(
        self,
        *,
        agent_code: str,
        memory_type: str,
        content: dict[str, Any],
        source_execution_id: int | None = None,
    ) -> int | None:
        with self._session_factory() as db:
            agent = self._agent_row(db, agent_code)
            if agent is None:
                logger.debug("No agent row for %s; memory not stored", agent_code)
                return None
            row = AgentMemory(
                agent_id=agent.id,
                memory_type=memory_type,
                memory_content=content,
                source_execution_id=source_execution_id,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            self._trim(db, agent.id)
            return row.id

    def _trim(self, db: Session, agent_id: int) -> None:
        rows = db.scalars(
            select(AgentMemory)
            .where(AgentMemory.agent_id == agent_id)
            .order_by(AgentMemory.id.desc())
        ).all()
        for stale in rows[MAX_MEMORIES_PER_AGENT:]:
            db.delete(stale)
        db.commit()

    def recent(
        self, *, agent_code: str, memory_type: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            agent = self._agent_row(db, agent_code)
            if agent is None:
                return []
            stmt = select(AgentMemory).where(AgentMemory.agent_id == agent.id)
            if memory_type:
                stmt = stmt.where(AgentMemory.memory_type == memory_type)
            rows = db.scalars(stmt.order_by(AgentMemory.id.desc()).limit(limit)).all()
            return [
                {
                    "id": row.id,
                    "memory_type": row.memory_type,
                    "content": row.memory_content,
                    "source_execution_id": row.source_execution_id,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    def record_execution_snapshot(
        self, *, agent_code: str, execution_id: int, metrics: dict[str, Any], summary: str
    ) -> int | None:
        return self.remember(
            agent_code=agent_code,
            memory_type=AgentMemoryType.SNAPSHOT,
            content={
                "summary": summary[:500],
                "metrics": metrics,
                "recorded_at": utcnow().isoformat(),
            },
            source_execution_id=execution_id,
        )

    def record_recommendations(
        self, *, agent_code: str, execution_id: int, recommendations: list[dict[str, Any]]
    ) -> int | None:
        if not recommendations:
            return None
        return self.remember(
            agent_code=agent_code,
            memory_type=AgentMemoryType.RECOMMENDATION,
            content={"recommendations": recommendations[:10]},
            source_execution_id=execution_id,
        )
