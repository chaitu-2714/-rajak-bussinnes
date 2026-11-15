"""Controlled agent-to-agent message bus.

Agents never call each other: they publish validated messages that the
collaboration manager persists and routes. The bus enforces the communication
rules — known participants only, no unbounded loops, duplicate rejection and
size limits.
"""

from __future__ import annotations

import uuid
from typing import Callable

from app.ai.schemas.message_schema import AgentMessage
from app.core.constants import CollaborationMessageType
from app.core.exceptions import ValidationError
from app.core.logging_config import get_logger
from app.utils.date_utils import utcnow

logger = get_logger("ai.collaboration.bus")

MAX_MESSAGES_PER_COLLABORATION = 200
MAX_MESSAGES_PER_PAIR = 40


class MessageBusError(ValidationError):
    default_user_message = "The collaboration message could not be delivered."


class MessageBus:
    """Validated, logged, per-collaboration message channel."""

    def __init__(
        self,
        *,
        collaboration_id: str,
        participants: set[str],
        on_message: Callable[[AgentMessage], None] | None = None,
        max_messages: int = MAX_MESSAGES_PER_COLLABORATION,
        max_per_pair: int = MAX_MESSAGES_PER_PAIR,
    ) -> None:
        self._collaboration_id = collaboration_id
        self._participants = {agent for agent in participants if agent}
        self._on_message = on_message
        self._max_messages = max_messages
        self._max_per_pair = max_per_pair
        self._messages: list[AgentMessage] = []
        self._seen_ids: set[str] = set()
        self._pair_counts: dict[tuple[str, str], int] = {}

    # -- properties --------------------------------------------------------
    @property
    def participants(self) -> set[str]:
        return set(self._participants)

    def messages(self) -> list[AgentMessage]:
        return list(self._messages)

    def count(self) -> int:
        return len(self._messages)

    def messages_of_type(self, message_type: str) -> list[AgentMessage]:
        return [message for message in self._messages if message.message_type == message_type]

    # -- sending -----------------------------------------------------------
    def send(
        self,
        *,
        sender: str,
        receiver: str,
        message_type: str,
        payload: dict | None = None,
        task_id: str | None = None,
        evidence_refs: list[str] | None = None,
        message_id: str | None = None,
    ) -> AgentMessage:
        """Validate and deliver one message."""
        if sender not in self._participants:
            raise MessageBusError(f"Unknown sender agent '{sender}'")
        if receiver not in self._participants:
            raise MessageBusError(f"Unknown receiver agent '{receiver}'")
        if sender == receiver and message_type != CollaborationMessageType.CLARIFICATION_REQUEST:
            raise MessageBusError("An agent cannot send this message type to itself")

        if len(self._messages) >= self._max_messages:
            raise MessageBusError(
                f"Message limit reached for this collaboration ({self._max_messages})"
            )
        pair = (sender, receiver)
        if self._pair_counts.get(pair, 0) >= self._max_per_pair:
            raise MessageBusError(
                f"Message limit reached between {sender} and {receiver}"
            )

        try:
            message = AgentMessage(
                message_id=message_id or f"msg-{uuid.uuid4().hex[:12]}",
                collaboration_id=self._collaboration_id,
                sender_agent=sender,
                receiver_agent=receiver,
                message_type=message_type,
                task_id=task_id,
                payload=payload or {},
                evidence_references=evidence_refs or [],
                timestamp=utcnow(),
            )
        except Exception as exc:  # pydantic validation
            raise MessageBusError(str(exc)) from exc

        if message.message_id in self._seen_ids:
            raise MessageBusError(f"Duplicate message id '{message.message_id}'")

        self._seen_ids.add(message.message_id)
        self._pair_counts[pair] = self._pair_counts.get(pair, 0) + 1
        self._messages.append(message)

        if self._on_message is not None:
            try:
                self._on_message(message)
            except Exception:  # pragma: no cover - persistence must not break routing
                logger.exception("Failed to persist collaboration message")

        logger.debug(
            "message %s %s → %s (%s)",
            message.message_id,
            sender,
            receiver,
            message_type,
        )
        return message

    def request_context(self, *, sender: str, receiver: str, task_id: str | None, keys: list[str]):
        return self.send(
            sender=sender,
            receiver=receiver,
            message_type=CollaborationMessageType.CONTEXT_REQUEST,
            payload={"requested_keys": keys},
            task_id=task_id,
        )

    def share_context(self, *, sender: str, receiver: str, task_id: str | None, context: dict):
        return self.send(
            sender=sender,
            receiver=receiver,
            message_type=CollaborationMessageType.CONTEXT_RESPONSE,
            payload={"context": context},
            task_id=task_id,
        )

    def report_finding(self, *, sender: str, receiver: str, task_id: str | None, finding: dict):
        return self.send(
            sender=sender,
            receiver=receiver,
            message_type=CollaborationMessageType.FINDING,
            payload={"finding": finding},
            task_id=task_id,
            evidence_refs=[
                str(item.get("source"))
                for item in finding.get("evidence", [])
                if isinstance(item, dict) and item.get("source")
            ],
        )

    def notify_conflict(self, *, sender: str, receiver: str, conflict: dict):
        return self.send(
            sender=sender,
            receiver=receiver,
            message_type=CollaborationMessageType.CONFLICT_NOTIFICATION,
            payload={"conflict": conflict},
        )
