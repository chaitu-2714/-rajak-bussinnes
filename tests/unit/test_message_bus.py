"""Unit tests: the collaboration message bus."""

from __future__ import annotations

import pytest

from app.ai.collaboration.message_bus import MessageBus, MessageBusError
from app.core.constants import CollaborationMessageType

PARTICIPANTS = {"finance_agent", "sales_agent", "collaboration_manager"}


def _bus(**kwargs) -> MessageBus:
    return MessageBus(collaboration_id="collab-test", participants=PARTICIPANTS, **kwargs)


def test_message_is_delivered_and_persisted() -> None:
    persisted = []
    bus = _bus(on_message=persisted.append)
    message = bus.send(
        sender="collaboration_manager",
        receiver="finance_agent",
        message_type=CollaborationMessageType.TASK_REQUEST,
        payload={"objective": "analyse revenue"},
        task_id="finance_review",
    )
    assert message.message_id.startswith("msg-")
    assert bus.count() == 1
    assert persisted and persisted[0].message_id == message.message_id
    assert bus.messages_of_type(CollaborationMessageType.TASK_REQUEST)


def test_unknown_sender_or_receiver_is_rejected() -> None:
    bus = _bus()
    with pytest.raises(MessageBusError):
        bus.send(sender="intruder", receiver="finance_agent", message_type="TASK_REQUEST")
    with pytest.raises(MessageBusError):
        bus.send(sender="finance_agent", receiver="intruder", message_type="TASK_RESPONSE")


def test_unregistered_message_type_is_rejected() -> None:
    bus = _bus()
    with pytest.raises(MessageBusError):
        bus.send(
            sender="finance_agent",
            receiver="sales_agent",
            message_type="EXECUTE_SQL",
        )


def test_self_message_is_rejected_except_clarification() -> None:
    bus = _bus()
    with pytest.raises(MessageBusError):
        bus.send(sender="finance_agent", receiver="finance_agent", message_type="FINDING")
    message = bus.send(
        sender="finance_agent",
        receiver="finance_agent",
        message_type=CollaborationMessageType.CLARIFICATION_REQUEST,
        payload={"question": "which period?"},
    )
    assert message.message_type == CollaborationMessageType.CLARIFICATION_REQUEST


def test_duplicate_message_id_is_rejected() -> None:
    bus = _bus()
    bus.send(
        sender="finance_agent",
        receiver="sales_agent",
        message_type="FINDING",
        message_id="msg-fixed",
    )
    with pytest.raises(MessageBusError):
        bus.send(
            sender="finance_agent",
            receiver="sales_agent",
            message_type="FINDING",
            message_id="msg-fixed",
        )


def test_total_message_limit_stops_runaway_loops() -> None:
    bus = _bus(max_messages=3, max_per_pair=10)
    for _ in range(3):
        bus.send(sender="finance_agent", receiver="sales_agent", message_type="FINDING")
    with pytest.raises(MessageBusError):
        bus.send(sender="sales_agent", receiver="finance_agent", message_type="FINDING")


def test_per_pair_limit_is_enforced() -> None:
    bus = _bus(max_messages=50, max_per_pair=2)
    for _ in range(2):
        bus.send(sender="finance_agent", receiver="sales_agent", message_type="FINDING")
    with pytest.raises(MessageBusError):
        bus.send(sender="finance_agent", receiver="sales_agent", message_type="FINDING")


def test_payload_size_is_bounded() -> None:
    bus = _bus()
    with pytest.raises(MessageBusError):
        bus.send(
            sender="finance_agent",
            receiver="sales_agent",
            message_type="FINDING",
            payload={"blob": "x" * 25_000},
        )


def test_context_and_finding_helpers_record_evidence_refs() -> None:
    bus = _bus()
    bus.request_context(
        sender="sales_agent", receiver="finance_agent", task_id="t1", keys=["available_budget"]
    )
    bus.share_context(
        sender="finance_agent", receiver="sales_agent", task_id="t1", context={"cash": "100.00"}
    )
    finding = bus.report_finding(
        sender="sales_agent",
        receiver="collaboration_manager",
        task_id="t1",
        finding={
            "description": "sales up",
            "evidence": [{"source": "get_sales_summary", "metric": "sales_value", "value": "10"}],
        },
    )
    assert finding.evidence_references == ["get_sales_summary"]
    assert bus.count() == 3
