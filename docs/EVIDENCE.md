# Evidence — SmartDocumentChatbot

| Field | Content |
|-------|---------|
| Project | SmartDocumentChatbot (RAG document QA chatbot) |
| Version | Commit `0d6dd7f` (`0d6dd7fc1f1c58b65902e8d82a66af22248096b9`, `feat(obs): support LANGFUSE_BASE_URL alias in llm-router observability`); tag `v1.0.0-rc1` |
| Real vs Simulated | Backend (Java 17, Spring Boot 3.2.3, Flyway) runs on real H2 / Neon PostgreSQL for tests. Agent (Python) retrieval uses Qdrant dense + BM25 + RRF; live Qdrant and the LLM provider are not exercised in fast tests — ground truth is fixture/mock-based (abstention when no evidence). Frontend (React 18 + Vite + Tailwind) is UI-tested for real. |
| Environment Tested | Backend: `mvn test` (Java 17, Spring Boot 3.2.3, Flyway, H2/Neon). Agent: `pytest agent/tests` (fast, non-integration). Frontend: Vitest (`npm test`, jsdom). Cloud-native k8s manifests (Qdrant, LLM router, backend, frontend Deployments/Services/HPA/probes, non-root securityContext) validated as YAML. |
| Results | Backend Java tests: 319 passed, 0 failures, 0 errors. Agent Python fast tests: 219 passed. Frontend Vitest: 104 passed. Fixture benchmark smoke: 28 passed; live benchmark scoring: 6 passed. Production smoke (CSRF/JWT/DOC UPLOAD/OWNER ISOLATION/CHAT/ROUTER AUTH/LLM RESPONSE) and fixture baseline (HTTP 3/3, retrieval 100%, correctness 3/3, hallucination 0%) documented. |
| Limits / Not Proven | Live retrieval benchmark requires a running LLM provider / Qdrant — blocked by external dependency; the 96.8% figure is a fixture pass rate (mock, 31 questions), not live accuracy. RAG ground-truth abstention fixed; HITL badge fixed. No production deployment; k8s YAMLs validated but not applied to a live cluster. Lexical (no-stemming) retrieval only. |
