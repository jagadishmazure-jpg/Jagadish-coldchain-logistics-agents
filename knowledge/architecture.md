# Architecture

## Legacy vs target

```mermaid
flowchart LR
    subgraph Legacy["Legacy: static reporting"]
        T1[(SQL Server<br/>fleet telemetry)] --> BI[Static BI dashboards]
        PDF[PDF SOPs<br/>on a shared drive] -.-> D[Dispatcher<br/>guesses]
        BI --> D
    end
    subgraph Target["Target: agentic assistant"]
        T2[(SQL Server<br/>+ read-only views)] --> G[Secure gateway<br/>SELECT-only]
        SOPs[(SOP corpus<br/>RAG index)] --> RAG[RAG tool<br/>cited answers]
        WX[Weather API] --> W[Weather tool<br/>gap-safe]
        G --> ORCH[ReAct orchestrator]
        RAG --> ORCH
        W --> ORCH
        ORCH --> UI[Dispatcher UI]
        ORCH --> AUDIT[(Audit log<br/>hash-chained)]
        ORCH --> GATE[Confirmation gate<br/>human approval]
    end
```

## ReAct loop

```mermaid
flowchart TD
    Q[Dispatcher query] --> REASON[Reasoner node<br/>which tools? which intents?]
    REASON --> FAN[Fan-out dispatch]
    FAN --> T1[Telemetry tool<br/>text-to-SQL over views]
    FAN --> T2[SOP tool<br/>TF-IDF retrieval]
    FAN --> T3[Weather tool<br/>fake or Open-Meteo]
    T1 --> OBS[Observations]
    T2 --> OBS
    T3 --> OBS
    OBS --> ESC[Escalation tier<br/>worst shipment]
    ESC --> SYNTH[Synthesize answer<br/>with citations]
    SYNTH --> A[Audit every step]
    SYNTH --> ANS[Answer + sources<br/>+ gate tokens]
```

## Security model

```mermaid
flowchart TD
    AGENT[Agent process] --> GW[SecureGateway]
    GW -->|allow| V1[v_fleet_status]
    GW -->|allow| V2[v_temp_breaches]
    GW -->|allow| V3[v_delay_risk]
    GW -->|allow| V4[v_port_impact]
    GW -->|deny SEC-VIEW-03| BT[(Base tables<br/>telemetry, trucks)]
    GW -->|deny SEC-WRITE-02| W[INSERT / UPDATE / DELETE / DDL]
    GW -->|deny SEC-SELECT-01| M[Multi-statement]
    V1 --> BT
    V2 --> BT
    V3 --> BT
    V4 --> BT
```

The database role behind the gateway would additionally hold only
`SELECT` on the views in production — defense in depth, not prompt
wishes.

## Deploy topology (production path)

```mermaid
flowchart LR
    subgraph Cloud["Azure"]
        AKS[AKS cluster<br/>orchestrator service] --> SQL[(Managed SQL<br/>read-only views)]
        AKS --> SEARCH[AI Search / Pinecone<br/>SOP index]
        AKS --> MON[App Insights<br/>+ audit table]
    end
    UI[Streamlit dispatcher UI] --> AKS
    WX2[Open-Meteo] --> AKS
    GH[GitHub Actions<br/>test → image → deploy] --> AKS
```
