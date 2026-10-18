"""Cold-chain logistics assistant: 45 deterministic tests (stdlib only)."""
import sqlite3
from pathlib import Path
from unittest import mock
from urllib.error import URLError

import pytest

from coldchain import audit as audit_mod
from coldchain import escalation as esc_mod
from coldchain import text2sql
from coldchain.audit import AuditLog
from coldchain.escalation import ConfirmationGate, guard_action
from coldchain.orchestrator import Orchestrator
from coldchain.sop_rag import SopIndex, answer_question, load_sops
from coldchain.telemetry import RISK_CLASSES, build_dataset, classify_risk
from coldchain.views import SecureGateway, SecurityDenial, VIEW_DEFS, create_views
from coldchain.weather import (FakeWeather, OpenMeteoBackend,
                               WeatherResult, derive_corridor_risk)

SOP_DIR = Path(__file__).resolve().parent.parent / "docs" / "sops"


# -- fixtures ----------------------------------------------------------
@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "fleet.db")
    build_dataset(path, seed=99, n_trucks=8, readings_per_truck=10)
    return path


@pytest.fixture
def conn(db_path):
    connection = sqlite3.connect(db_path)
    create_views(connection)
    yield connection
    connection.close()


@pytest.fixture
def gw(conn):
    return SecureGateway(conn)


@pytest.fixture
def sop_index():
    return SopIndex(load_sops(SOP_DIR))


@pytest.fixture
def orch(gw, sop_index):
    return Orchestrator(gw, sop_index, FakeWeather())


# -- telemetry ---------------------------------------------------------
def test_build_creates_expected_rows(db_path):
    connection = sqlite3.connect(db_path)
    n_trucks = connection.execute("SELECT COUNT(*) FROM trucks").fetchone()[0]
    n_readings = connection.execute(
        "SELECT COUNT(*) FROM telemetry").fetchone()[0]
    connection.close()
    assert n_trucks == 8
    assert n_readings == 8 * 10 + 4  # generated + injected anchors


def test_injected_breach_anchor(gw):
    rows = gw.execute(
        "SELECT truck_id, iot_temp_c FROM v_temp_breaches "
        "WHERE truck_id = 'TRK-001'")
    assert any(r["iot_temp_c"] == 7.2 for r in rows)


def test_risk_classes_are_valid(db_path):
    connection = sqlite3.connect(db_path)
    classes = {row[0] for row in
               connection.execute("SELECT DISTINCT risk_class FROM telemetry")}
    connection.close()
    assert classes <= set(RISK_CLASSES)
    assert "critical" in classes  # injected anchor


def test_dataset_is_deterministic(tmp_path):
    a = str(tmp_path / "a.db")
    b = str(tmp_path / "b.db")
    build_dataset(a, seed=1234, n_trucks=4, readings_per_truck=5)
    build_dataset(b, seed=1234, n_trucks=4, readings_per_truck=5)
    ca, cb = sqlite3.connect(a), sqlite3.connect(b)
    qa = ca.execute("SELECT iot_temp_c FROM telemetry ORDER BY reading_id"
                    ).fetchall()
    qb = cb.execute("SELECT iot_temp_c FROM telemetry ORDER BY reading_id"
                    ).fetchall()
    ca.close()
    cb.close()
    assert qa == qb


def test_warehouses_seeded(db_path):
    connection = sqlite3.connect(db_path)
    count = connection.execute(
        "SELECT COUNT(*) FROM warehouses").fetchone()[0]
    connection.close()
    assert count == 3


def test_classify_risk_boundaries():
    assert classify_risk(7.2, 0.85) == "critical"
    assert classify_risk(7.2, 0.30) == "high"
    assert classify_risk(2.0, 0.75) == "high"
    assert classify_risk(2.0, 0.50) == "medium"
    assert classify_risk(2.0, 0.10) == "low"
    assert classify_risk(-1.0, 0.10) == "high"  # below 0 C is a breach


# -- views / gateway ---------------------------------------------------
def test_v_fleet_status_columns(gw):
    rows = gw.execute("SELECT * FROM v_fleet_status LIMIT 1")
    assert set(rows[0]) >= {"truck_id", "depot", "iot_temp_c",
                            "delay_probability", "risk_class"}


def test_v_temp_breaches_only_breaches(gw):
    rows = gw.execute("SELECT iot_temp_c FROM v_temp_breaches")
    assert rows
    assert all(r["iot_temp_c"] > 4.0 or r["iot_temp_c"] < 0.0 for r in rows)


def test_gateway_allows_view_select(gw):
    rows = gw.execute("SELECT truck_id FROM v_delay_risk LIMIT 5")
    assert len(rows) <= 5


def test_gateway_caps_missing_limit(gw):
    rows = gw.execute("SELECT truck_id FROM v_fleet_status")
    assert len(rows) <= SecureGateway.MAX_LIMIT


def test_insert_denied(gw):
    with pytest.raises(SecurityDenial) as exc:
        gw.execute("INSERT INTO telemetry (truck_id) VALUES ('TRK-001')")
    assert exc.value.rule_id == "SEC-SELECT-01"


def test_update_denied(gw):
    with pytest.raises(SecurityDenial) as exc:
        gw.execute("UPDATE telemetry SET fuel_pct = 0")
    assert exc.value.rule_id == "SEC-SELECT-01"


def test_delete_denied(gw):
    with pytest.raises(SecurityDenial) as exc:
        gw.execute("DELETE FROM telemetry")
    assert exc.value.rule_id == "SEC-SELECT-01"


def test_write_keyword_inside_string_literal_allowed(gw):
    rows = gw.execute(
        "SELECT truck_id FROM v_fleet_status "
        "WHERE cargo_condition = 'insert' LIMIT 5")
    assert rows == []


def test_write_keyword_as_identifier_denied(gw):
    with pytest.raises(SecurityDenial) as exc:
        gw.execute("SELECT truck_id AS delete FROM v_fleet_status")
    assert exc.value.rule_id == "SEC-WRITE-02"


def test_select_on_base_table_denied(gw):
    with pytest.raises(SecurityDenial) as exc:
        gw.execute("SELECT * FROM telemetry LIMIT 1")
    assert exc.value.rule_id == "SEC-VIEW-03"


def test_multi_statement_denied(gw):
    with pytest.raises(SecurityDenial) as exc:
        gw.execute("SELECT * FROM v_fleet_status; DROP TABLE telemetry")
    assert exc.value.rule_id == "SEC-SELECT-01"


def test_drop_denied(gw):
    with pytest.raises(SecurityDenial) as exc:
        gw.execute("DROP VIEW v_fleet_status")
    assert exc.value.rule_id in ("SEC-SELECT-01", "SEC-WRITE-02")


# -- text2sql ----------------------------------------------------------
def test_intent_temp_breach(gw):
    (result,) = text2sql.run("Show me temperature breaches", gw)
    assert result["plan"]["view"] == "v_temp_breaches"
    assert result["rows"]
    assert all(r["iot_temp_c"] > 4.0 or r["iot_temp_c"] < 0.0
               for r in result["rows"])


def test_intent_delay_risk_ranked(gw):
    (result,) = text2sql.run("Which shipments have the highest delay "
                             "probability?", gw)
    assert result["plan"]["view"] == "v_delay_risk"
    probs = [r["delay_probability"] for r in result["rows"]]
    assert probs == sorted(probs, reverse=True)


def test_intent_port_congestion(gw):
    (result,) = text2sql.run("What is the port congestion impact?", gw)
    assert result["plan"]["view"] == "v_port_impact"
    assert all(r["port_congestion"] in ("high", "severe")
               for r in result["rows"])


def test_intent_low_fuel(gw):
    (result,) = text2sql.run("Which trucks are low on fuel?", gw)
    assert result["plan"]["view"] == "v_fleet_status"
    assert result["rows"]
    assert all(r["fuel_pct"] < 25.0 for r in result["rows"])


def test_intent_fatigue(gw):
    (result,) = text2sql.run("Flag driver fatigue risks", gw)
    assert result["plan"]["view"] == "v_fleet_status"
    assert result["rows"]
    assert all(r["driver_fatigue_score"] >= 0.8 for r in result["rows"])


def test_unknown_query_raises(gw):
    with pytest.raises(text2sql.NoIntentFound):
        text2sql.run("Tell me a joke about trucks", gw)


def test_limit_cap_enforced():
    plan = text2sql.build_plan("delay_risk", limit=5000)
    assert plan["limit"] == text2sql.MAX_ROWS
    assert plan["params"][-1] == text2sql.MAX_ROWS


def test_identifier_allowlist_rejects_unknown_column():
    plan = text2sql.build_plan("temp_breach")
    plan["columns"] = ["truck_id", "credit_card_number"]
    with pytest.raises(text2sql.GuardrailViolation):
        text2sql._validate_plan("temp_breach", plan)


def test_self_correction_retries_simplified(gw):
    plan = text2sql.build_plan("temp_breach")
    plan["sql"] = "SELECT nope_col FROM v_temp_breaches"
    plan["params"] = ()
    result = text2sql.run_plan(plan, gw)
    assert result["retried"] is True
    assert result["rows"]  # simplified query succeeded


def test_double_failure_escalates():
    class BrokenGateway:
        def execute(self, sql, params=()):
            raise sqlite3.OperationalError("boom")

    plan = text2sql.build_plan("temp_breach")
    with pytest.raises(text2sql.EscalationNeeded):
        text2sql.run_plan(plan, BrokenGateway())


# -- SOP RAG -----------------------------------------------------------
def test_breach_query_finds_breach_protocol(sop_index):
    answer = answer_question("What is the temperature breach protocol?",
                             sop_index)
    assert answer.found
    assert any("sop-02" in source for source in answer.sources)


def test_temp_rule_query_finds_control_standard(sop_index):
    answer = answer_question(
        "What temperature must fresh perishables be kept at?", sop_index)
    assert answer.found
    assert any("sop-01" in source for source in answer.sources)


def test_diversion_query_finds_playbook(sop_index):
    answer = answer_question(
        "When should we divert for port congestion?", sop_index)
    assert answer.found
    assert any("sop-03" in source for source in answer.sources)


def test_citations_name_doc_and_section(sop_index):
    answer = answer_question("escalation tiers for high delay risk", sop_index)
    assert answer.found
    assert all("§" in source and ".md" in source
               for source in answer.sources)


def test_unrelated_query_says_not_found(sop_index):
    answer = answer_question("quantum payroll regulations", sop_index)
    assert answer.found is False
    assert answer.sources == []
    assert "could not find" in answer.text.lower()


# -- weather -----------------------------------------------------------
def test_fake_weather_deterministic():
    backend = FakeWeather()
    first = backend.get(34.05, -118.24)
    second = backend.get(34.05, -118.24)
    assert first == second
    assert first.gap is False
    assert 18.0 <= first.temp_c <= 41.0


def test_weather_gap_on_backend_failure():
    with mock.patch("coldchain.weather.urllib.request.urlopen",
                    side_effect=URLError("network down")):
        result = OpenMeteoBackend().get(34.05, -118.24)
    assert isinstance(result, WeatherResult)
    assert result.gap is True
    assert result.temp_c is None
    assert result.corridor_risk == "unknown"
    assert "unavailable" in result.note


def test_corridor_risk_derivation():
    assert derive_corridor_risk(39.0, 10.0) == "severe"
    assert derive_corridor_risk(25.0, 80.0) == "severe"
    assert derive_corridor_risk(33.0, 10.0) == "elevated"
    assert derive_corridor_risk(25.0, 10.0) == "low"


# -- orchestrator ------------------------------------------------------
def test_orchestrator_telemetry_answer(orch):
    answer = orch.run("Show me temperature breaches")
    assert answer.rows
    assert any("v_temp_breaches" in source for source in answer.sources)
    assert any(call["tool"] == "telemetry" for call in answer.tool_calls)


def test_orchestrator_multi_intent_fanout(orch):
    answer = orch.run("Show temperature breaches and what does the SOP say "
                      "about the breach protocol?")
    assert any(call["tool"] == "telemetry" for call in answer.tool_calls)
    assert any(call["tool"] == "sop" for call in answer.tool_calls)
    assert "Telemetry" in answer.text and "Compliance" in answer.text
    assert any("sop-02" in source for source in answer.sources)


def test_orchestrator_weather_section(orch):
    answer = orch.run("What is the weather at 34.05,-118.24?")
    assert answer.weather is not None
    assert answer.weather.gap is False
    assert "Weather" in answer.text


def test_orchestrator_reports_weather_gap(gw, sop_index):
    class GapBackend:
        def get(self, lat, lon):
            return WeatherResult(temp_c=None, wind_kmh=None,
                                 corridor_risk="unknown", source="test",
                                 gap=True,
                                 note="Weather data unavailable.")

    gap_orch = Orchestrator(gw, sop_index, GapBackend())
    answer = gap_orch.run("Weather at 34.05,-118.24 please")
    assert answer.weather.gap is True
    assert "unavailable" in answer.text


def test_orchestrator_audits_every_step(orch):
    orch.run("Which trucks are low on fuel?")
    event_types = [entry["event_type"] for entry in orch.audit.entries]
    assert "query.received" in event_types
    assert "tool.telemetry.called" in event_types
    assert "sql.issued" in event_types
    assert "answer.synthesized" in event_types
    assert orch.audit.verify_chain()


def test_orchestrator_escalation_gate_for_critical(orch):
    answer = orch.run("Show me temperature breaches")
    esc = answer.escalation
    assert esc is not None
    assert esc["tier"] in ("T3", "T4")
    assert "confirmation_token" in esc
    assert esc["confirmation_state"] == "pending"
    assert orch.gate.status(esc["confirmation_token"]) == "pending"


def test_orchestrator_no_intent_graceful(orch):
    answer = orch.run("Tell me a joke")
    assert answer.rows == []
    assert "could not map" in answer.text


# -- escalation --------------------------------------------------------
def test_escalation_tier_boundaries():
    assert esc_mod.classify(0.85, "critical").code == "T4"
    assert esc_mod.classify(0.85, "high").code == "T4"
    assert esc_mod.classify(0.75, "high").code == "T3"
    assert esc_mod.classify(0.75, "low").code == "T3"
    assert esc_mod.classify(0.50, "medium").code == "T2"
    assert esc_mod.classify(0.20, "low").code == "T1"


def test_confirmation_gate_flow():
    gate = ConfirmationGate()
    token = gate.request("reroute_shipment", detail="TRK-001")
    assert gate.status(token) == "pending"
    assert gate.approve(token) == "approved"
    token2 = gate.request("divert_port")
    assert gate.deny(token2) == "denied"
    with pytest.raises(KeyError):
        gate.status("nope-0000")


def test_guard_action_routes_high_impact():
    gate = ConfirmationGate()
    token = guard_action("reroute_shipment", gate, detail="TRK-001")
    assert gate.status(token) == "pending"
    assert guard_action("send_status_email", gate) == "auto-approved"


# -- audit -------------------------------------------------------------
def test_audit_chain_verifies():
    log = AuditLog()
    log.record("query.received", {"query": "hello"})
    log.record("sql.issued", {"sql": "SELECT 1"})
    assert len(log.entries) == 2
    assert log.verify_chain()


def test_audit_tamper_detected():
    log = AuditLog()
    log.record("query.received", {"query": "hello"})
    log.record("sql.issued", {"sql": "SELECT 1"})
    log.entries[0]["payload"]["query"] = "tampered"
    assert not log.verify_chain()


def test_audit_hash_linking():
    log = AuditLog()
    first = log.record("a", {})
    second = log.record("b", {})
    assert second["prev_hash"] == first["hash"]
    assert first["prev_hash"] == AuditLog.GENESIS_HASH
