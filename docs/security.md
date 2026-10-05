# Security Architecture & Guardrails: SmartDocument

This document details the enterprise security posture, data boundaries, and threat defenses across SmartDocument's hybrid-cloud architecture. For the OWASP Top 10 for LLMs compliance matrix, see [SECURITY.md](file:///Users/mainguyenbinhtan/Downloads/TMA/Smart-Document-Chatbot/SECURITY.md).

---

## 1. Network & Ingress Boundaries

SmartDocument segregates external traffic from internal document retrieval pipelines:

```
[Browser / Enterprise User]
        │
        ▼ (HTTPS / TLS 1.3)
[Cloudflare Edge] (DNS, TLS, WAF, DDoS Mitigation, Rate Limiting)
        │
        ▼
[Spring Boot Backend API] (Port 8080 / Azure Container Apps)
   • JWT authentication via HttpOnly cookies (anti-XSS)
   • Strict CORS origin allowlist & CSRF protection
   • Document owner isolation at database query layer
        │
        ├──────────────────────┬──────────────────────┐
        ▼                      ▼                      ▼
[Azure Blob Storage]   [Azure AI Search]      [Azure Service Bus]
• Private containers   • Managed Identity     • Durable queue
• SSE AES-256          • Hybrid + Vector RRF  • Dead-letter queue
• Ephemeral access     • Tenant-filtered      • Deduplication
```

---

## 2. Authentication & Credential Isolation

1. **HttpOnly Cookie JWT Delivery**: Eliminates `localStorage` token storage to protect session tokens against Cross-Site Scripting (XSS).
2. **Password Reset Verification**: Reset tokens require cryptographic generation, single-use invalidation, and strict time expiry (`V20__password_reset_token.sql`).
3. **Azure Managed Identity**: In Azure Container Apps (`production` profile), backend services connect to Azure Blob Storage, Azure AI Search, and Azure Service Bus using User-Assigned Managed Identity, removing static credentials from container configurations.

---

## 3. Storage & Document Data Residency

- **Azure Blob Storage**: Internal contracts, SOPs, and policy documents reside in encrypted private storage (`allowBlobPublicAccess = false`).
- **Cloudflare R2**: Used in the `portfolio` profile for zero-egress public demo storage.
- **Tenant & Owner Isolation**: Chunks and vector indexes are indexed with strict `owner_username` and `tenant_id` fields. Queries without valid owner matches are rejected at retrieval time.

---

## 4. AI Guardrails & Integrity Controls

- **Prompt Injection Defense**: Sanitization filters strip instruction overrides (`ignore previous instructions`, `system override`) before LLM ingestion.
- **Evidence Threshold Gate**: Chunks scoring below lexical threshold 0.3 are discarded. Queries with zero qualifying evidence trigger honest refusal rather than hallucinations.
- **Auditable Citations**: LLM responses must link statements to addressable legal evidence units (Article, Clause, Point) or return explicit uncertainty.
