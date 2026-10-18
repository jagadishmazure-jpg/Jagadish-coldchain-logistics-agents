# Cold-Chain Logistics AI Assistant

An end-to-end agentic AI showcase for a logistics enterprise, built the way a
Forward Deployed Engineer would deliver it: from the business problem, through
discovery and design, to a working system with guardrails, audit, and a
production path.

## Problem

A Southern California refrigerated carrier runs its fleet on telemetry that
lands in a SQL database — GPS fixes, reefer IoT temperatures, fuel, ETA
variance, traffic, port congestion, driver fatigue scores, delay
probabilities — and dispatchers read it through static BI dashboards.

That breaks down exactly where money is lost:

- A reefer drifts to 7.2 °C and nobody notices until the customer rejects
  the load.
- Delay risk is visible only as a column nobody sorts by.
- Compliance SOPs live in PDFs; during a breach, dispatchers guess.
- Weather on the corridor is a separate browser tab, or a guess.
- There is no audit trail of who decided what, and no confirmation gate
  before a high-impact reroute.

## Approach

A ReAct-style orchestrator fronts three tools and answers dispatcher
questions in plain language, with every claim traceable:

| Module | What it does |
|---|---|
| `coldchain/telemetry.py` | Synthetic fleet telemetry store (SQLite); seeded Southern California reefer fleet generator |
| `coldchain/views.py` | Least-privilege layer: clean read-only views; the agent may only `SELECT` from an allowlisted view set — writes, DDL, and base tables are denied with cited rule IDs |
| `coldchain/text2sql.py` | Rule-based NL→SQL planner (breaches, delay risk, port congestion, low fuel, fatigue); guardrails: SELECT-only, LIMIT cap, identifier allowlist; one self-correction retry, then human escalation |
| `coldchain/sop_rag.py` | RAG over bundled cold-chain SOPs (`docs/sops/`); hand-rolled TF-IDF; every answer cites sources; "not found" is stated explicitly, never guessed |
| `coldchain/weather.py` | Injectable weather backend: deterministic fake for tests, Open-Meteo for live runs; API failures return an explicit data gap — never hallucinated weather |
| `coldchain/orchestrator.py` | ReAct loop: reasoner + tool dispatch, multi-intent fan-out, synthesized answer with citations |
| `coldchain/escalation.py` | Risk × delay-probability tiers (T1–T4) per the SOPs; confirmation gates for reroutes, diversions, cancellations |
| `coldchain/audit.py` | SHA-256 hash-chained immutable log over queries, tool calls, SQL issued, and decisions |

See [`knowledge/fde-approach.md`](knowledge/fde-approach.md) for the
engagement method and [`knowledge/architecture.md`](knowledge/architecture.md)
for the architecture diagrams.

## Outcome

Ask: *"Show temperature breaches and what does the SOP say about the breach
protocol?"* — the assistant fans out to telemetry and SOPs in one turn,
returns the breaching trailers with their readings, quotes the breach
protocol with citations, classifies the worst shipment into an escalation
tier, and parks the reroute behind a human confirmation gate. The whole
exchange — query, SQL, sources, decision — sits in a tamper-evident audit
log.

Design rules, stated plainly:

- **Least privilege at the data layer**, not in a prompt.
- **Graceful degradation**: a dead weather API is reported as a gap, never
  papered over.
- **No autonomous high-impact actions**: reroutes and diversions wait for a
  human.

## Quickstart

```bash
python -m pytest tests/ -q   # 45 tests, stdlib only, no installs
python - <<'EOF'
import sqlite3
from coldchain.telemetry import build_dataset
from coldchain.views import SecureGateway, create_views
from coldchain.sop_rag import SopIndex, load_sops
from coldchain.weather import FakeWeather
from coldchain.orchestrator import Orchestrator

conn = build_dataset("/tmp/fleet.db", seed=20260801)
create_views(conn)
orch = Orchestrator(SecureGateway(conn),
                    SopIndex(load_sops("docs/sops")),
                    FakeWeather())
answer = orch.run("Show temperature breaches and what does the SOP say "
                  "about the breach protocol?")
print(answer.text)
print("Sources:", answer.sources)
EOF
```

## Production path

| Prototype here | Production |
|---|---|
| SQLite telemetry | Client MSSQL / Postgres behind read-only views + dedicated login |
| Hand-rolled TF-IDF | Pinecone / Azure AI Search over the SOP corpus |
| FakeWeather | Open-Meteo (or enterprise weather feed) with the same gap contract |
| In-process orchestrator | Containerized service on AKS; Streamlit dispatcher UI |
| Hash-chained JSONL audit | Append-only audit table in the client's own database |
| `ci.yml` (this repo) | GitHub Actions: test → build image → deploy via OIDC |

## Disclaimer

All fleet data, SOPs, companies, people, and incidents in this repository are
**synthetic and fictional**, generated for demonstration. This project is an
independent portfolio showcase and is not affiliated with, endorsed by, or
connected to any logistics company or vendor.
