"""ReAct-style orchestrator: reasoner node + tool dispatch.

For each dispatcher query the orchestrator:
  1. Reasons about which tools are needed (telemetry intents, SOP
     guidance, weather) — multi-intent queries fan out to several tools.
  2. Dispatches the tools and collects observations.
  3. Synthesizes one answer with cited sources (views, SOP sections).

Every step is written to the audit log: query received, tool calls,
SQL issued, and the final decision.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import escalation as escalation_mod
from . import text2sql
from .audit import AuditLog
from .escalation import ConfirmationGate, guard_action
from .sop_rag import SopAnswer, SopIndex, answer_question
from .views import SecureGateway
from .weather import WeatherResult

_LATLON_RE = re.compile(r"(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)")
_SOP_HINTS = ("sop", "protocol", "procedure", "compliance", "playbook",
              "what should we do", "how should", "rule", "escalat")
_WEATHER_HINTS = ("weather", "corridor", "los angeles", "long beach",
                  "san diego", "ontario", "fresno", "bakersfield",
                  "heatwave", "heat wave", "storm")
# Default corridor anchor: Los Angeles basin.
_DEFAULT_LAT, _DEFAULT_LON = 34.05, -118.24


@dataclass
class AgentAnswer:
    text: str
    sources: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    weather: WeatherResult | None = None
    escalation: dict | None = None


class Orchestrator:
    def __init__(self, gateway: SecureGateway, sop_index: SopIndex,
                 weather_backend, audit: AuditLog | None = None,
                 gate: ConfirmationGate | None = None) -> None:
        self.gateway = gateway
        self.sop_index = sop_index
        self.weather = weather_backend
        self.audit = audit or AuditLog()
        self.gate = gate or ConfirmationGate()

    # -- reasoning -----------------------------------------------------
    def _needs_sop(self, query: str) -> bool:
        lowered = query.lower()
        return any(hint in lowered for hint in _SOP_HINTS)

    def _needs_weather(self, query: str) -> bool:
        lowered = query.lower()
        return bool(_LATLON_RE.search(query)) or any(
            hint in lowered for hint in _WEATHER_HINTS)

    def _coords(self, query: str) -> tuple[float, float]:
        match = _LATLON_RE.search(query)
        if match:
            return float(match.group(1)), float(match.group(2))
        return _DEFAULT_LAT, _DEFAULT_LON

    # -- execution -----------------------------------------------------
    def run(self, query: str) -> AgentAnswer:
        self.audit.record("query.received", {"query": query})
        sections: list[str] = []
        sources: list[str] = []
        tool_calls: list[dict] = []
        rows: list[dict] = []
        weather: WeatherResult | None = None
        escalation_info: dict | None = None

        # Tool 1: telemetry via text-to-SQL (multi-intent fan-out).
        intents = text2sql.detect_all(query)
        for intent in intents:
            plan = text2sql.build_plan(intent)
            tool_calls.append({"tool": "telemetry",
                               "intent": intent, "sql": plan["sql"]})
            self.audit.record("tool.telemetry.called",
                              {"intent": intent, "view": plan["view"]})
            self.audit.record("sql.issued",
                              {"sql": plan["sql"],
                               "params": list(plan["params"])})
            try:
                result = text2sql.run_plan(plan, self.gateway)
            except text2sql.EscalationNeeded as exc:
                self.audit.record("tool.telemetry.escalated",
                                  {"intent": intent, "error": str(exc)})
                sections.append(
                    f"Telemetry for '{intent}' could not be retrieved "
                    f"after a retry; escalated to a human. No data was "
                    f"guessed.")
                continue
            rows.extend(result["rows"])
            sources.append(f"view {plan['view']}")
            note = (" (simplified retry after a SQL error)"
                    if result["retried"] else "")
            sections.append(
                f"Telemetry — {plan['description']}{note}: "
                f"{len(result['rows'])} row(s) returned.")

        # Tool 2: SOP RAG.
        if self._needs_sop(query):
            tool_calls.append({"tool": "sop"})
            self.audit.record("tool.sop.called", {"query": query})
            sop_answer: SopAnswer = answer_question(query, self.sop_index)
            sections.append("Compliance — " + sop_answer.text)
            sources.extend(sop_answer.sources)
            self.audit.record("tool.sop.answered",
                              {"found": sop_answer.found,
                               "sources": sop_answer.sources})

        # Tool 3: weather.
        if self._needs_weather(query):
            lat, lon = self._coords(query)
            tool_calls.append({"tool": "weather",
                               "lat": lat, "lon": lon})
            self.audit.record("tool.weather.called",
                              {"lat": lat, "lon": lon})
            weather = self.weather.get(lat, lon)
            if weather.gap:
                sections.append("Weather — " + weather.note)
            else:
                sections.append(
                    f"Weather — corridor near ({lat}, {lon}): "
                    f"{weather.temp_c} C, wind {weather.wind_kmh} km/h; "
                    f"corridor risk: {weather.corridor_risk}.")
            sources.append(f"weather:{weather.source}")
            self.audit.record("tool.weather.answered",
                              {"gap": weather.gap,
                               "corridor_risk": weather.corridor_risk})

        # Escalation: worst observed shipment drives the tier.
        if rows:
            worst = max(rows,
                        key=lambda r: float(r.get("delay_probability", 0.0)))
            tier = escalation_mod.classify(
                float(worst.get("delay_probability", 0.0)),
                str(worst.get("risk_class", "low")))
            escalation_info = {
                "tier": tier.code, "name": tier.name,
                "actions": tier.actions, "notify": tier.notify,
                "worst_truck": worst.get("truck_id"),
            }
            if tier.requires_confirmation:
                token = guard_action("reroute_shipment", self.gate,
                                     detail=f"tier {tier.code} shipment "
                                            f"{worst.get('truck_id')}")
                escalation_info["confirmation_token"] = token
                escalation_info["confirmation_state"] = "pending"
                sections.append(
                    f"Escalation — tier {tier.code} ({tier.name}) for "
                    f"truck {worst.get('truck_id')}. High-impact actions "
                    f"require human confirmation (gate token {token}); "
                    f"nothing was rerouted automatically.")
            else:
                sections.append(
                    f"Escalation — tier {tier.code} ({tier.name}); "
                    f"no confirmation gate required.")
            self.audit.record("decision.escalation", escalation_info)

        if not sections:
            sections.append(
                "I could not map this request to telemetry, SOPs, or "
                "weather. Please ask about fleet status, temperature "
                "breaches, delay risk, port congestion, fuel, driver "
                "fatigue, compliance SOPs, or corridor weather.")
        text = "\n\n".join(sections)
        self.audit.record("answer.synthesized",
                          {"sources": sources,
                           "tool_calls": len(tool_calls)})
        return AgentAnswer(text=text, sources=sources, tool_calls=tool_calls,
                           rows=rows, weather=weather,
                           escalation=escalation_info)
