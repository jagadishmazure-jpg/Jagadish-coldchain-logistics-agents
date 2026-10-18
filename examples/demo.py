"""Dispatcher questions against a synthetic reefer fleet (in-memory SQLite)."""
from pathlib import Path

from coldchain.orchestrator import Orchestrator
from coldchain.sop_rag import SopIndex, load_sops
from coldchain.telemetry import build_dataset
from coldchain.views import SecureGateway, SecurityDenial, create_views
from coldchain.weather import FakeWeather

ROOT = Path(__file__).resolve().parent.parent
conn = build_dataset(":memory:", seed=20260801)
create_views(conn)
gateway = SecureGateway(conn)
orch = Orchestrator(gateway, SopIndex(load_sops(ROOT / "docs" / "sops")), FakeWeather())

for q in ["Show temperature breaches and what does the SOP say about the breach protocol?",
          "Which shipments have high delay risk and what are the escalation tiers?"]:
    a = orch.run(q)
    print(f"> {q}\n{a.text}\nSources: {a.sources}\n")

print("SQL guard (agent-issued SQL that must be refused):")
for sql in ["SELECT * FROM v_temp_breaches; DROP TABLE telemetry",
            "SELECT * FROM telemetry",
            "SELECT name FROM sqlite_master"]:
    try:
        gateway.execute(sql)
        print("  ALLOWED", sql)
    except SecurityDenial as e:
        print("  BLOCKED", sql, "->", e)
print("\naudit chain intact:", orch.audit.verify_chain())
