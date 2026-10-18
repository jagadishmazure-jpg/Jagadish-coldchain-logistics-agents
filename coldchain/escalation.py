"""Risk x delay-probability escalation tiers (mirrors sop-04).

T4 Critical: reefer breach with delay probability >= 0.7, or high risk
             with delay probability >= 0.8.
T3 High:     delay probability >= 0.7 (or high risk class).
T2 Watch:    delay probability >= 0.4 (or medium risk class).
T1 Normal:   everything else.

High-impact actions (reroute, port diversion, cancellation) always pass
through a confirmation gate: nothing irreversible happens without an
explicit human approval recorded in the audit log.
"""
from __future__ import annotations

from dataclasses import dataclass, field

HIGH_IMPACT_ACTIONS = frozenset({
    "reroute_shipment",
    "divert_port",
    "cancel_shipment",
})


@dataclass
class Tier:
    code: str
    name: str
    actions: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    notify: list[str] = field(default_factory=list)


def classify(delay_probability: float, risk_class: str) -> Tier:
    risk = (risk_class or "").lower()
    if risk == "critical" or (risk == "high" and delay_probability >= 0.8):
        return Tier(
            code="T4", name="Critical",
            actions=["Quarantine trailer and start breach protocol",
                     "Prepare reroute / diversion options",
                     "Proactive customer notification"],
            requires_confirmation=True,
            notify=["dispatcher", "qa", "customer"],
        )
    if delay_probability >= 0.7 or risk == "high":
        return Tier(
            code="T3", name="High",
            actions=["Proactive customer notification",
                     "Evaluate port diversion playbook"],
            requires_confirmation=True,
            notify=["dispatcher", "customer"],
        )
    if delay_probability >= 0.4 or risk == "medium":
        return Tier(
            code="T2", name="Watch",
            actions=["Increase tracking cadence", "Monitor next readings"],
            requires_confirmation=False,
            notify=["dispatcher"],
        )
    return Tier(
        code="T1", name="Normal",
        actions=["Routine monitoring"],
        requires_confirmation=False,
        notify=[],
    )


class ConfirmationGate:
    """In-memory human-approval gate for high-impact actions."""

    def __init__(self) -> None:
        self._states: dict[str, dict] = {}
        self._counter = 0

    def request(self, action: str, detail: str = "") -> str:
        self._counter += 1
        token = f"{action}-{self._counter:04d}"
        self._states[token] = {"action": action, "detail": detail,
                               "state": "pending"}
        return token

    def approve(self, token: str) -> str:
        state = self._require(token)
        state["state"] = "approved"
        return "approved"

    def deny(self, token: str) -> str:
        state = self._require(token)
        state["state"] = "denied"
        return "denied"

    def status(self, token: str) -> str:
        return self._require(token)["state"]

    def _require(self, token: str) -> dict:
        if token not in self._states:
            raise KeyError(f"Unknown confirmation token '{token}'.")
        return self._states[token]


def guard_action(action: str, gate: ConfirmationGate,
                 detail: str = "") -> str:
    """Route an action through the gate; returns 'auto-approved' or a token."""
    if action in HIGH_IMPACT_ACTIONS:
        return gate.request(action, detail)
    return "auto-approved"
