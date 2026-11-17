# Architecture Diagram — Multi-Cloud System Design

Generated: 2026-11-12
Format: Mermaid

```mermaid
graph TB
    %% Users
    User((End User)):::user
    Admin((Admin / Auditor)):::user

    %% Edge
    CFP[Cloudflare Pages<br/>smart-doc-chatbot]:::cf
    CWA[Cloudflare Workers AI<br/>Embedding + LLM]:::cf
    CFR[Cloudflare R2<br/>Object Storage]:::cf

    %% Azure (Canonical Backend)
    ACA[Azure Container Apps<br/>smart-doc-backend<br/>Spring Boot + MongoDB]:::azure
    AKS[Azure Kubernetes Service<br/>QuanLyKho FastAPI<br/>ArgoCD GitOps]:::azure
    NEON[Neon Postgres<br/>LangGraph checkpoints]:::azure
    QDRANT[Qdrant<br/>Vector index]:::azure

    %% Render (Standby Mirror)
    RENDER[Render<br/>Keycloak + mirror services<br/>FREE tier - standby]:::render

    %% IncidentIQ (Cloudflare Workers)
    CW[Cloudflare Workers<br/>IncidentIQ API + MCP]:::cfw
    D1[Cloudflare D1<br/>SQLite DB]:::cfw
    VEC[Cloudflare Vectorize<br/>Vector index]:::cfw
    Q[Cloudflare Queues<br/>ETL + DLQ]:::cfw

    %% Flows - Enterprise RAG
    User -->|HTTPS| CFP
    CFP -->|API calls| ACA
    ACA -->|embedding| CWA
    ACA -->|object storage| CFR
    ACA -->|checkpoints| NEON
    ACA -->|vector search| QDRANT
    ACA -.->|standby failover| RENDER
    RENDER -.->|Keycloak SSO| ACA

    %% Flows - IncidentIQ
    User -->|HTTPS| CW
    CW -->|D1 queries| D1
    CW -->|vector upsert| VEC
    CW -->|ETL jobs| Q
    Admin -->|MCP tools| CW

    %% Flows - QuanLyKho
    User -->|HTTPS| CFP
    CFP -->|API calls| AKS
    AKS -->|AI assessment| CWA
    AKS -->|migration jobs| ArgoCD[ArgoCD<br/>GitOps sync]:::azure

    classDef user fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    classDef cf fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef cfw fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
    classDef azure fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    classDef render fill:#ffebee,stroke:#b71c1c,stroke-width:2px,stroke-dasharray: 5 5

    linkStyle default stroke:#666,stroke-width:2px
    linkStyle 11 stroke:#b71c1c,stroke-width:2px,stroke-dasharray: 5 5
    linkStyle 12 stroke:#b71c1c,stroke-width:2px,stroke-dasharray: 5 5
```

## Cloud Responsibilities

| Cloud | Role | Services | SLA Tier |
|-------|------|----------|----------|
| **Azure** | Canonical backend | Container Apps, AKS, Neon Postgres, Qdrant | Production (paid) |
| **Cloudflare** | Edge + AI | Pages, Workers AI, R2, Workers, D1, Vectorize, Queues | Production (paid/free) |
| **Render** | Standby mirror | Keycloak, legacy services | Free (standby only) |
| **Neon** | Managed Postgres | LangGraph checkpoints, QuanLyKho metadata | Production (paid) |

## Data Flow — RAG Query

1. User → Cloudflare Pages (frontend)
2. Pages → Azure Container Apps API (`/api/rag/chat`)
3. Backend → Qdrant (vector search) + Workers AI (embedding/LLM)
4. Backend → Neon Postgres (LangGraph checkpoint, HITL pause/resume)
5. Backend → R2 (document storage, signed URLs)
6. Response → Pages → User

## Data Flow — HITL Approval

1. Action agent → HITL gate → pause workflow
2. Checkpoint stored in Neon Postgres (shared, survives redeploy)
3. Admin approves via `POST /agent/approvals/{id}/approve`
4. Workflow resumes from checkpoint, executes action

## Failure Modes

| Scenario | Behavior |
|----------|----------|
| Azure API down | Render standby (manual failover, documented) |
| Redis down | HITL fail-closed — actions blocked, reads continue |
| Qdrant down | RAG returns degraded fallback (keyword search) |
| Render free spin-down | No impact — Azure is canonical; Render is standby only |
