"""Rule-based natural-language to SQL planner.

Maps dispatcher intents to parameterized SELECT statements over the
allowlisted read-only views (never base tables). Guardrails:

  * SELECT-only (enforced again by the SecureGateway),
  * LIMIT cap (MAX_ROWS),
  * identifier allowlist (views + their known columns),
  * self-correction: on a SQL error the planner retries once with a
    simplified query before escalating to a human.

Plans are plain dicts so the audit log can record exactly what ran.
"""
from __future__ import annotations

import re
import sqlite3

from .views import VIEW_COLUMNS, VIEW_DEFS, SecureGateway

MAX_ROWS = 100

# (intent, [regexes]) — order matters; first match wins per query, but
# detect_all() collects every matching intent for multi-intent fan-out.
INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("temp_breach", [
        r"temp(erature)?\s*breach", r"\bbreach", r"out of range",
        r"spoil", r"above\s*4", r"too warm", r"too cold", r"reefer.*(alarm|alert)",
    ]),
    ("delay_risk", [
        r"delay\s*(probability|risk)", r"highest delay", r"most delayed",
        r"at risk of (being )?delay", r"likely.*delay", r"running late",
    ]),
    ("port_congestion", [
        r"port\s*congestion", r"congested ports?", r"port impact",
        r"port delay", r"\bPOLA\b", r"\bPOLB\b",
    ]),
    ("low_fuel", [
        r"low(\s*-)?fuel", r"low on fuel", r"fuel\s*(below|under)",
        r"need (a )?refuel", r"running low on fuel",
    ]),
    ("fatigue", [
        r"fatig", r"drowsy", r"tired driver", r"hours.of.service",
        r"driver risk",
    ]),
]

_INTENT_SQL: dict[str, dict] = {
    "temp_breach": {
        "view": "v_temp_breaches",
        "columns": VIEW_COLUMNS["v_temp_breaches"],
        "sql": ("SELECT truck_id, ts, iot_temp_c, cargo_condition, "
                "risk_class, delay_probability FROM v_temp_breaches "
                "ORDER BY iot_temp_c DESC LIMIT ?"),
        "params": (),
        "description": "Reefer temperature breaches (outside 0-4 C).",
    },
    "delay_risk": {
        "view": "v_delay_risk",
        "columns": VIEW_COLUMNS["v_delay_risk"],
        "sql": ("SELECT truck_id, ts, delay_probability, risk_class, "
                "port_congestion, eta_variance_min FROM v_delay_risk "
                "ORDER BY delay_probability DESC LIMIT ?"),
        "params": (),
        "description": "Shipments ranked by delay probability.",
    },
    "port_congestion": {
        "view": "v_port_impact",
        "columns": VIEW_COLUMNS["v_port_impact"],
        "sql": ("SELECT truck_id, ts, port_id, port_congestion, "
                "delay_probability, risk_class FROM v_port_impact "
                "ORDER BY delay_probability DESC LIMIT ?"),
        "params": (),
        "description": "Shipments exposed to congested ports.",
    },
    "low_fuel": {
        "view": "v_fleet_status",
        "columns": ["truck_id", "depot", "fuel_pct", "ts"],
        "sql": ("SELECT truck_id, depot, fuel_pct, ts FROM v_fleet_status "
                "WHERE fuel_pct < ? ORDER BY fuel_pct ASC LIMIT ?"),
        "params": (25.0,),
        "description": "Trucks below the 25% fuel threshold.",
    },
    "fatigue": {
        "view": "v_fleet_status",
        "columns": ["truck_id", "ts", "driver_fatigue_score", "risk_class"],
        "sql": ("SELECT truck_id, ts, driver_fatigue_score, risk_class "
                "FROM v_fleet_status WHERE driver_fatigue_score >= ? "
                "ORDER BY driver_fatigue_score DESC LIMIT ?"),
        "params": (0.8,),
        "description": "Driver fatigue flags at or above 0.80.",
    },
}


class GuardrailViolation(Exception):
    """A planned query failed static guardrail validation."""


class NoIntentFound(Exception):
    """The query matched no known telemetry intent."""


class EscalationNeeded(Exception):
    """SQL failed twice (original + simplified retry); a human must step in."""


def detect_all(query: str) -> list[str]:
    """Return every telemetry intent mentioned in the query, in order."""
    lowered = query.lower()
    found: list[str] = []
    for intent, patterns in INTENT_PATTERNS:
        if any(re.search(p, lowered) for p in patterns):
            found.append(intent)
    return found


def _validate_plan(intent: str, plan: dict) -> None:
    view = plan["view"]
    if view not in VIEW_DEFS:
        raise GuardrailViolation(f"Unknown view '{view}' for intent '{intent}'.")
    for column in plan["columns"]:
        if column not in VIEW_COLUMNS[view]:
            raise GuardrailViolation(
                f"Column '{column}' is not exposed by view '{view}'.")


def build_plan(intent: str, limit: int = 25) -> dict:
    """Build the audited, guardrailed plan for one intent."""
    if intent not in _INTENT_SQL:
        raise NoIntentFound(f"No SQL template for intent '{intent}'.")
    template = _INTENT_SQL[intent]
    capped = max(1, min(int(limit), MAX_ROWS))
    plan = {
        "intent": intent,
        "view": template["view"],
        "columns": list(template["columns"]),
        # The template ends with "LIMIT ?"; bind the capped value.
        "sql": template["sql"],
        "params": tuple(template["params"]) + (capped,),
        "limit": capped,
        "description": template["description"],
    }
    _validate_plan(intent, plan)
    return plan


def _simplified_sql(plan: dict) -> tuple[str, tuple]:
    """Fallback query: same view, no filters or ordering, tiny limit."""
    columns = ", ".join(plan["columns"])
    return f"SELECT {columns} FROM {plan['view']} LIMIT 10", ()


def run_plan(plan: dict, gateway: SecureGateway) -> dict:
    """Execute one plan with a single self-correction retry.

    On sqlite error the planner retries once with a simplified query;
    if that also fails it escalates instead of guessing.
    """
    try:
        rows = gateway.execute(plan["sql"], plan["params"])
        return {"plan": plan, "rows": rows, "retried": False}
    except sqlite3.Error as first_error:
        simple_sql, simple_params = _simplified_sql(plan)
        try:
            rows = gateway.execute(simple_sql, simple_params)
            return {"plan": plan, "rows": rows, "retried": True,
                    "retry_sql": simple_sql,
                    "first_error": str(first_error)}
        except sqlite3.Error as second_error:
            raise EscalationNeeded(
                f"SQL failed twice for intent '{plan['intent']}': "
                f"{first_error} / {second_error}. Escalating to a human."
            ) from second_error


def run(query: str, gateway: SecureGateway, limit: int = 25) -> list[dict]:
    """Plan every detected intent and execute with self-correction."""
    intents = detect_all(query)
    if not intents:
        raise NoIntentFound(
            "No telemetry intent detected; nothing to query.")
    return [run_plan(build_plan(intent, limit), gateway) for intent in intents]
