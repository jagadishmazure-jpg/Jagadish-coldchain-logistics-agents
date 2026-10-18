# Implementation guide: from offline build to Azure

> Status: **planned**. Nothing here has been deployed. The offline build in this
> repository is what exists today; this guide is how it would be taken to a
> real Azure environment.

## Azure service mapping

| Offline component | Azure service (planned) | Notes |
|---|---|---|
| Telemetry | IoT Hub into Event Hubs, then Azure Data Explorer or Fabric Real-Time Intelligence |  |
| Governed views | Views with a read-only database role in Azure SQL or Fabric warehouse | Agent identity gets only that role |
| SOP retrieval | Azure AI Search over the SOP library | Keep citation to section |
| Orchestration | Azure OpenAI tool calling in Container Apps | Gate stays in code |
| Confirmation | Teams adaptive card or a dispatcher console |  |

## Steps

1. Keep the gateway and templates; let a model choose the template and fill parameters.
2. Stream readings and compute breaches as events, not on demand.
3. Index the full SOP library in Azure AI Search with section-level chunks.
4. Route T3/T4 confirmations to the on-call dispatcher with a timeout.

## Guardrails to keep when going live

- Read-only access through allowlisted views; one statement; base and system tables refused by the gateway's rules and, behind them, by a SQLite authorizer that only allows reads of the four views. At most 100 rows are fetched.
- SQL comes from templates, not from a model.
- SOP text is quoted with a citation, not paraphrased.
- Reroutes and other T3/T4 actions return a confirmation token; nothing is executed automatically.
- Every step is written to a hash-chained audit log.
- Feedback corrections are capped at 2,000 characters, and emails, phone numbers (including `(555) 123-4567`), SSNs and long numbers are redacted before they reach the append-only audit log.

## What to measure before calling it production-ready

- Time from breach to dispatcher acknowledgement.
- Share of answers whose SOP citation a reviewer agrees with.
- Blocked SQL attempts and their reason codes.
