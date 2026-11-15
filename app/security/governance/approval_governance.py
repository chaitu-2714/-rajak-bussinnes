"""Approval security: payload binding, separation of duties and lifecycle rules."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.core.logging_config import get_logger

logger = get_logger("security.approvals")

# Fields that change what an approval actually authorises.
MATERIAL_FIELDS = (
    "amount", "total_amount", "supplier_id", "customer_id", "product_id",
    "quantity", "ordered_quantity", "unit_cost", "items", "invoice_id",
    "expense_category", "action_name", "selling_price", "movement_type",
)


@dataclass(frozen=True)
class ApprovalBinding:
    payload_hash: str
    material_fields: dict[str, Any]

    def matches(self, other_hash: str) -> bool:
        return self.payload_hash == other_hash


def canonicalise(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Extract the fields that materially define the action, in a stable form."""
    payload = payload or {}
    material: dict[str, Any] = {}
    for field in MATERIAL_FIELDS:
        if field in payload:
            material[field] = _normalise(payload[field])
    return material


def _normalise(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalise(value[key]) for key in sorted(value)}
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    if isinstance(value, str):
        try:
            return round(float(value.replace(",", "")), 2)
        except ValueError:
            return value.strip()
    return value


def payload_hash(payload: dict[str, Any] | None) -> str:
    """A canonical hash bound to the exact action details."""
    material = canonicalise(payload)
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ApprovalGovernanceService:
    """Validates that an approval still authorises the action being executed."""

    def bind(self, payload: dict[str, Any] | None) -> ApprovalBinding:
        return ApprovalBinding(payload_hash=payload_hash(payload), material_fields=canonicalise(payload))

    def verify_binding(
        self, stored_hash: str | None, payload: dict[str, Any] | None
    ) -> tuple[bool, str]:
        if not stored_hash:
            return False, "This approval was created before payload binding and cannot be reused"
        current = payload_hash(payload)
        if current != stored_hash:
            return (
                False,
                "The action details changed after approval; a new approval is required",
            )
        return True, "The approval matches the action exactly"

    def check_separation_of_duties(
        self,
        *,
        requester_id: int | None,
        approver_id: int | None,
        approver_type: str = "USER",
        approver_permissions: set[str] | None = None,
        other_approver_exists: bool = False,
    ) -> tuple[bool, str]:
        if approver_type in ("AGENT", "SYSTEM"):
            return False, "An AI agent or system identity cannot approve an action"
        if approver_id is None:
            return False, "The approver could not be identified"
        if requester_id is not None and requester_id == approver_id:
            if not other_approver_exists:
                return (
                    False,
                    "A user cannot approve their own request. Add a second authorised "
                    "approver for this action.",
                )
            return False, "A user cannot approve their own request"
        permissions = approver_permissions or set()
        if "approvals.approve" not in permissions:
            return False, "The approver lacks 'approvals.approve'"
        return True, "Separation of duties satisfied"

    def check_state(self, *, status: str, expires_at: Any, now: Any) -> tuple[bool, str]:
        if status != "PENDING":
            return False, f"This approval is {status.lower()} and cannot authorise execution"
        if expires_at is not None and expires_at < now:
            return False, "This approval has expired"
        return True, "The approval is pending and valid"

    def requires_new_approval(self, *, previous_hash: str | None, new_payload: dict) -> bool:
        return previous_hash != payload_hash(new_payload)

    def multi_stage_plan(self, *, amount: Any, stages: list[dict] | None = None) -> list[dict]:
        """How many approvals an amount needs, by the configured rules."""
        if stages:
            return stages
        try:
            value = float(amount or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value >= 100000:
            return [
                {"stage": 1, "role": "Finance Manager", "description": "Financial review"},
                {"stage": 2, "role": "Super Admin", "description": "Final authorisation"},
            ]
        if value >= 25000:
            return [
                {"stage": 1, "role": "Business Admin", "description": "Management approval"},
            ]
        return [
            {"stage": 1, "role": "Any authorised approver", "description": "Single approval"},
        ]
