# Threat Model: SmartDocument

This document models threats to the SmartDocument Enterprise Knowledge Retrieval System following the STRIDE methodology.

---

## 1. System Assets

- Proprietary enterprise documents (SOPs, contracts, HR policies, financial filings).
- Ingested text chunks and vector embeddings (Azure AI Search / Qdrant).
- User authentication tokens and audit logs.
- Background ingestion queue messages on Azure Service Bus.

---

## 2. STRIDE Assessment & Mitigations

### S - Spoofing Identity
* **Threat**: Attacker crafts fake JWT tokens or steals session credentials to impersonate an executive.
* **Mitigation**:
  - Tokens signed with cryptographic keys and delivered via secure `HttpOnly`, `SameSite=Lax` cookies.
  - Revocation and expiry enforced on every request via `JwtAuthenticationFilter`.

### T - Tampering
* **Threat**: Malicious document uploads inject malicious payloads into vector embeddings or modify legal clause citations.
* **Mitigation**:
  - Ingestion documents undergo MIME-type validation, PDF structure parsing, and size checks.
  - Chunk IDs and legal ordinal metadata are deterministically generated and stored in PostgreSQL with foreign keys.

### R - Repudiation
* **Threat**: User denies querying or downloading confidential executive salary data.
* **Mitigation**:
  - Centralized `AuditLog` records every search query, document upload, chunk retrieval, and administrative action with timestamp and user ID.

### I - Information Disclosure
* **Threat**: Cross-tenant data leakage where User A's search query returns chunks belonging to User B.
* **Mitigation**:
  - `RetrievalService.java` enforces mandatory owner isolation: checks document ownership before reading chunks.
  - Vector search filters strictly apply `ownerUsername == currentUser` predicate.
  - Storage containers reject anonymous public downloads.

### D - Denial of Service (DoS)
* **Threat**: Uploading 500-page corrupt PDFs to exhaust memory or flooding the RAG endpoint with unbounded queries.
* **Mitigation**:
  - Asynchronous background ingestion offloaded to Azure Service Bus with concurrency limits.
  - Rate limiting enforced on chat and search endpoints (`RateLimitStore`).
  - Container Apps autoscale to meet burst loads without dropping requests.

### E - Elevation of Privilege
* **Threat**: Non-admin user attempts to view all tenant documents or invoke admin ingestion APIs.
* **Mitigation**:
  - Spring Security RBAC annotations (`@PreAuthorize("hasRole('ADMIN')")`) guard administrative routes.
  - Internal service tokens (`InternalTokenFilter`) authenticate internal worker calls.
