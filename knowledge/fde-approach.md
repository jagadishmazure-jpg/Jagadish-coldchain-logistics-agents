# FDE Approach: From a Vague Ask to a Working System

Distilled notes on the Forward Deployed Engineer engagement method this
repository demonstrates.

## The arc

1. **Vague client ask.** It always starts fuzzy: *"can we chat with our
   fleet data?"* The FDE's first job is not to build — it is to find out
   what "chat with the data" actually means for a dispatcher at 2 AM.
2. **Discovery.** Ride along with dispatchers. Learn that the pain is not
   "we lack dashboards" but "a reefer breach costs us a customer and we
   find out too late." Map the legacy system: SQL Server, static BI, PDF
   SOPs, no audit trail, no external data.
3. **Solution discussion.** Agree on scope before architecture: which
   questions the assistant must answer, which actions it may take, and —
   critically — which actions it must *never* take autonomously.
4. **Technical design (HLD/LLD).** The design document is the contract:
   data flow, tool boundaries, the security model (least-privilege views,
   read-only role), the escalation tiers, the audit guarantees. Review it
   with the client before writing code.
5. **Business pitch.** A short deck for the non-technical stakeholders:
   problem, approach, what changes for dispatchers, what it costs, what
   could go wrong. If they cannot explain it back, the design is not done.
6. **Build.** Vertical slices, each demonstrable: telemetry Q&A first,
   then SOP grounding, then weather, then escalation gates, then audit.
   Deterministic tests at every layer so the demo never depends on luck.

## Documentation is half the job

In FDE work the documents *are* deliverables: the discovery notes, the
HLD/LLD, the pitch deck, the runbook. Code without them is a prototype;
code with them is a handoff the client's team can own. This repo keeps the
same ratio: every module has a design rationale in the README or
`knowledge/`, and the SOPs the RAG tool cites are real files you can read.

## Non-negotiables observed here

- Least privilege enforced at the data layer, not hoped for in a prompt.
- Every answer cites its sources; "not found" is an acceptable answer.
- External data (weather) degrades to an explicit gap, never a guess.
- High-impact actions wait for a human confirmation gate.
- The audit log is tamper-evident and lives where the client can see it.
