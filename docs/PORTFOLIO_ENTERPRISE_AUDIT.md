# SmartDocumentChatbot — enterprise architecture and interview audit

**Initial audit base:** `8b6d394db8ce1a881479c0f1cc58a24cd656d646`
(clean starting tree inspected 2026-10-21). **Latest verified HEAD:**
`744386bf0de600f06f888f20710be39362f192a8` (external auth commits
`2af9b50` and `744386b` landed during this work). Portfolio audit, safeguards,
demos and one LoginPage test compatibility fix remain uncommitted on top of that
HEAD. No test result below is represented as CI evidence for the base commit.
`VERIFIED_LIVE` means a dated external smoke artifact, not a permanent uptime
claim. `VERIFIED_LOCAL` means the listed command passed locally. `CODE_ONLY`
means the branch exists in source but its end-to-end runtime result is not proved.

## Business thread and claim matrix

| Use case → decision | State / environment | Code and evidence | Reproduce command | Result / limit |
|---|---|---|---|---|
| Private document upload → durable job, idempotent enqueue, retry/DLQ | `CODE_ONLY` plus historical Azure API smoke | `DocumentController`, `DocumentJobService`, `DocumentJobExecutor`; `docs/adr/0004-durable-ingestion-job-queue.md`; README production status | `cd backend && mvn -Dtest=DocumentControllerTest,DocumentJobServiceTest,DocumentJobExecutorTest test` | Unit tests exercise contract; old Azure upload smoke is dated 2026-10-10. No new live upload in this audit. |
| Ask question → Spring retrieval, evidence gate, citation or abstention | `CODE_ONLY` plus dated Azure RAG smoke | `ChatService`, `RetrievalService`, `ChatServiceCitationTest`, `docs/EVALUATION.md` | `cd backend && mvn -Dtest=ChatServiceCitationTest,ChatServiceFallbackHardeningTest,RetrievalServiceTest test` | Spring path is lexical over PostgreSQL chunks; Qdrant hybrid search is the Python agent path, not this fallback. Fixture eval is synthetic. |
| Owner access → document/chat scoped to caller | `CODE_ONLY` plus dated Azure owner-isolation smoke | `DocumentController`, `DocumentAccessService`, `DocumentServiceOwnerCacheIsolationTest`; README production status | `cd backend && mvn -Dtest=DocumentServiceOwnerCacheIsolationTest,DocumentControllerTest test` | Access control is tested; unsafe cross-principal document/list cache and batch-delete role/purge bypass fixed locally; no cross-tenant red-team audit or new live run here. |
| Agent-first call → Spring CRAG fallback on failure | `CODE_CONNECTED`, live agent `NOT_VERIFIED` | `ChatService.processQuery*`, `AgentClient`; README production status `ragStrategy=direct` on Azure | `cd backend && mvn -Dtest=AgentClientTest,ChatServiceFallbackHardeningTest test` | Spring calls agent by default in source; most recent recorded Azure smoke fell back to CRAG. |
| Multi-agent orchestration → specialist routing | `VERIFIED_LOCAL` only | `agent/graph/workflow.py`, `agent/tests/test_workflow_checkpointer.py`; offline `eval/portfolio_demo/agent_hitl.py` | `agent/.venv/bin/python -m pytest -q eval/tests/test_portfolio_agent_hitl.py` | Offline demo routes retrieval/answer/action nodes; no live agent claim. |
| Side effect → human approval | `CODE_ONLY`; separate offline `VERIFIED_LOCAL` demo | `agent/graph/workflow.py`, `agent/routers/hitl.py`, `agent/hitl.py`; offline demo and tests | `agent/.venv/bin/python -m eval.portfolio_demo.agent_hitl --db /tmp/smartdoc-hitl-demo.sqlite` | Serving path has a post-claim crash window; offline demo uses true LangGraph interrupt + SQLite checkpoint and a simulated idempotent action ledger. |
| Routing feedback → contextual bandit | `VERIFIED_LOCAL` synthetic demo only | `eval/portfolio_demo/bandit.py`, tests | `agent/.venv/bin/python -m eval.portfolio_demo.bandit --output /tmp/smartdoc-bandit.json` | Every latency, cost and citation outcome is synthetic; no online user traffic or production policy change. |
| Preference learning → tiny RLHF-style loop | `VERIFIED_LOCAL` educational demo only | `eval/portfolio_demo/rlhf_tiny.py`, `rlhf_preferences.json`, `eval/results/portfolio-rlhf-2026-10-21.json` | `agent/.venv/bin/python -m eval.portfolio_demo.rlhf_tiny --device mps --output /tmp/smartdoc-rlhf.json` | Synthetic, author-created preferences (no actual human raters), A/B answer choice, final transformer block update; no chatbot-quality claim. |

**Measured offline demo run (2026-10-21, M1 Pro MPS):** Bandit synthetic held-out
mean reward `0.815` versus always-RAG `0.700` (80 contexts; full event log in
`eval/results/portfolio-bandit-2026-10-21.json`). Tiny RLHF used 8 synthetic
author-created training preference pairs and 4 held-out pairs: reward model pair ranking
`4/4`, LLM preferred-choice accuracy `2/4 → 2/4`, mean preferred-choice
probability `0.5094 → 0.5110`, final-block parameter delta L2 `0.01746`.
The number is a small probability shift, **not** a quality gain claim.
`eval/results/portfolio-rlhf-2026-10-21.json` records seed, pinned revision,
device, learning rate, per-update rewards, and before/after metrics. The HITL
trace and audit events are in `eval/results/portfolio-hitl-2026-10-21.json`.
An independent second run with the same seed/model/device produced identical
JSON metrics (`repeat_equal=True`); this is reproducibility for this machine,
not a cross-hardware determinism guarantee.

**Working-tree verification (2026-10-21, latest verified HEAD `744386b` plus
uncommitted edits):** `mvn test -B -q` returned 0 after
the principal, batch-deletion and cache-isolation fixes; 75 Surefire XML suites total 395 tests,
0 failure/error/skip. The full Maven run started while HEAD was `2af9b50`;
`744386b` changed only frontend files, so its backend source was identical.
An independent verifier's earlier first full
Maven run had one intermittent timing failure in
`EventDrivenIngestionIntegrationTest.workflowFailure_handledGracefully`; that
test passed alone, and the verifier's full retry passed 395/395. This remains
a test-stability limit rather than evidence of consistently green first runs.
Targeted `mvn test -B -q -Dtest=DocumentServiceTest,DocumentControllerTest`
also returned 0; cache-specific target `-Dtest=DocumentServiceOwnerCacheIsolationTest,DocumentServiceCacheTest,DocumentServiceTest,DocumentControllerTest`
returned 0. The first parallel frontend suite started at `2af9b50` and returned 204/205 with
a 5-second timeout in `ChatPage` SSE test; isolated `ChatPage` then passed
11/11. After external `744386b`, a full frontend suite returned 204/205:
`LoginPage` expected a button named `Đóng` but the committed UI intentionally
labels its modal cancel button `Hủy`; isolated test confirmed the mismatch
(17/18). The test now asserts `Hủy` and closing behavior. Focused `LoginPage`
passed 18/18, full `npm test -- --run` passed 205/205 across 29 files, and
`npm run build` passed on `744386b` plus the test edit. Agent fast suite after route guards: 347 passed, 1
deselected. Eval suite: 40 passed, including 8 new portfolio-demo tests.
Focused agent/HITL/bandit tests were rerun after the auth commits: 15 passed.
`git diff --check` passes. These are local results after uncommitted edits,
so do not present them as a GitHub CI result for either HEAD.

## Side-effect inventory and trust boundary

HITL applies to the **orchestrated action branch only**. An internal service
token is service authentication, not evidence of a human decision. This is a
route inventory, not a claim that every mutation has approval.

| Surface | Actual effect and reachability | Gate and remaining limit |
|---|---|---|
| `POST /v1/agent/action`, `/report`, `/connector/ingest` | Direct action can invoke email/Jira/webhook; connector changes index; report creates local PDF. | Internal token plus 403 by default; even production flag override cannot reopen. Local/dev/test demo opt-in only. |
| Orchestrated graph action and `/agent/approvals/*` | Graph requests approval before `ActionAgent`; backend proxy exposes decisions to ADMIN/ENGINEER. | Direct agent approval API still trusts the shared internal token; serving approval claim precedes effect and has a crash window. No global exactly-once guarantee. |
| `POST /v1/agent/improve` | Generates/evaluates a proposal; `deploy_automatically=true` calls `ImprovementPipeline.deploy`, which currently changes only an in-memory status field. No live agent config or model is changed. | Internal token and rate limit. “Deployed” status is a simulation; the API must not be cited as a production rollout gate. |
| Training job submit/result/callback/promote/rollback | Submit may call external training runner; successful result registers a candidate; explicit promote/rollback changes model-registry stage. | Internal token for operator routes; per-job callback secret for runner result. No separate human approval record on promote/rollback, and serving consumption of registry stage is not proved here. This operator workflow is outside agent HITL. |
| `POST /v1/agent/memory/graph/extract` | Stores extracted entities/relations in graph memory from caller-supplied `user_id` and turns. | Internal token and rate limit only; no user principal binding at agent ingress. Treat internal callers as trusted and do not expose this route through an end-user proxy without owner binding. |
| `POST /v1/mcp/call` | Registered `web_search` calls Tavily, `document_retrieval` reads Qdrant, and `generate_report` currently returns a path string without writing a PDF. | Internal token and rate limit. The registered MCP tool set has no real arbitrary action handler in `agent/main.py`; the retrieval tool's fixed `default` scope still needs owner-isolation review before user exposure. |
| `POST /v1/a2a/delegate` | Factory advertises many agents, including action/ingestion, but startup wires only `rag_agent` handler. RAG answers questions **and updates conversation memory** (periodically extracting long-term facts); action has no executable handler in current composition. | Internal token and rate limit. Agent cards are advertised capabilities, not proof of working or approved external actions. Caller-supplied `user_id` needs owner binding before user exposure. |
| `DELETE /api/documents/{id}` and `/batch` → agent purge | User-facing deletion removes backend row/blob/chunks and asks agent to purge vectors/cache/memory. Agent `POST /v1/agent/documents/{id}/purge` itself accepts shared internal token without checking document ownership. | Single delete checks role/owner. Batch now rejects ROLE_USER and purges only IDs actually deleted by the authorized backend path. Direct agent purge remains service-trust-only; keep its token out of user clients. Failed agent purge is logged but backend delete succeeds, leaving a replay requirement. |

There is no demonstrated end-user route from MCP, A2A, graph-memory extraction,
training promotion, or direct agent purge in the Spring controller. These are
still security boundaries if the shared token leaks or an internal caller is
compromised. The inventory was traced from `agent/main.py` router composition,
the registered handlers, and Spring `DocumentController`.

## Priority gaps and alternatives

| Priority | Gap / enterprise effect | Simpler alternative and trade-off | Acceptance probe |
|---|---|---|---|
| P0 mitigated locally | `POST /v1/agent/action` invoked `ActionAgent.execute` directly behind an internal token and bypassed graph HITL; connector ingestion and report routes also sat outside the gate. | All three routes now return 403 by default, including production even when the demo flag is set. Explicit local/dev/test opt-in preserves sandbox demos. This may break callers of direct production routes; migrate them to a reviewed approval executor. | `agent/tests/test_direct_mutation_guard.py`: valid internal token still gets 403; production override cannot reopen routes; explicit test-mode opt-in works. |
| P0 mitigated locally | Spring `/api/agent/invoke` previously trusted caller-supplied `X-User` as the document owner; any authenticated caller could name another owner. | The controller now takes the authenticated `Principal` and rejects missing identity with 401. This is a contract change for clients using `X-User` as an identity override. | `AgentControllerTest` asserts principal-scoped call and missing-principal rejection; retest full authenticated HTTP flow before a new live claim. |
| P0 mitigated locally | Spring batch document delete formerly used a read/owner check without the ROLE_USER delete rule, and purged agent artifacts for every requested ID even if no primary deletion occurred. | Reject ROLE_USER at service boundary; return successful IDs and purge only those. This narrows the purge trust boundary without adding human approval to ordinary authorized document deletion. | `DocumentServiceTest` rejects ROLE_USER and omits a foreign ID; `DocumentControllerTest` proves the omitted ID is not sent to agent purge. |
| P0 mitigated locally | `DocumentService` cached owner/role-aware reads under document ID alone; admin or owner cache warming could leak a document to another principal. Role-aware list cache keyed only by username could leak an admin-warmed list after a role change. | Remove caching on identity-dependent document/list reads and the unscoped replacement cache write. This trades cache hit rate for authorization correctness. Existing cache entries are no longer read by these methods. | `DocumentServiceOwnerCacheIsolationTest` warms the same Spring cache proxy as admin/owner, then verifies foreign user denial and role-downgraded list isolation. |
| P0 | HITL serving approval is consumed before side effect succeeds. A crash can leave a request approved with no action; external tool idempotency is not universal. | Keep approval queue and add durable execution state/outbox plus tool-specific idempotency key; costs another persisted lifecycle. | Kill process after claim; restart and prove exactly one effect or a visible retryable failure. |
| P0 | Agent live path lacks a successful Azure end-to-end proof despite agent-first routing in code. | Make Spring CRAG the explicit default until agent readiness and owner-scoped retrieval pass; less agent capability, clearer reliability. | Live probe returns `ragStrategy=agentic`, correct citation, owner denial, HITL result, and trace ID on one exact revision. |
| P1 | Product docs formerly disagreed on agent connectivity and cloud status. | One status matrix per commit with code-connected versus live-proven labels; requires maintenance each deployment. | README, architecture and interview story cite the same status and dated evidence. |
| P1 | Direct RAG and agent retrieval use different stores and can return different evidence. | Keep one retriever until divergence is measured; fewer capabilities but simpler provenance. | Same owned document/question fixture compared across paths, with citation and abstention deltas recorded. |
| P1 | Internal graph-memory extract and A2A RAG accept caller-supplied user identity, and MCP retrieval uses `default` scope. | Bind identity at a trusted gateway or disable these interfaces for user traffic; less flexible interoperability, clearer tenancy. | Negative cross-owner tests at the actual HTTP gateway and retrieval store. |
| P1 | Agent purge is token-authorized but does not independently verify document ownership; a failed purge is best-effort after backend delete. | Restrict to backend network identity and add a durable purge retry/outbox; more operations state. | Foreign-ID purge denial and forced Qdrant failure followed by successful replay. |
| P1 | Batch delete catches per-ID exceptions inside one `@Transactional` method; a storage or database error may leave partial effects, and a later transaction rollback could disagree with the in-memory successful-ID list. | Move each deletion to an isolated transaction with a durable purge event, or make the batch atomic with an outbox; costs more transaction/orchestration state. | Inject failure after blob removal and after database delete; verify rollback/compensation, returned IDs and agent purge agree after retry. |
| P1 | Fixture quality numbers do not establish live retrieval/answer quality or cost/latency SLO. | Keep fixture as regression gate; run a separately labeled live benchmark only when provider is available. | Record dataset version, retrieval Hit@K/Recall@K/MRR, groundedness, p95, cost, error rate and CI SHA. |
| P2 | RL demos are synthetic and have no production-safe feedback collection or consent flow. | Maintain offline demos; promotion requires privacy review, feedback integrity and shadow evaluation. | No serving import of demo modules; no model/policy auto-promotion. |

## Five-minute walkthrough and hard questions

1. **Business:** an employee needs a cited answer from an owned policy document. Show upload `jobId`, retrieval, `[S1]` citation, then an unanswerable question that abstains. State that the Azure proof is historical and the agent fallback was observed there.
2. **Failure:** force agent unavailable in local tests; show Spring CRAG response and its different PostgreSQL retrieval path. Show owner isolation negative test.
3. **Governance:** run the offline HITL demo, stop after the interrupt, reopen the SQLite checkpoint, approve as a distinct checker, retry the same action key, then reject another request. Name the serving-path crash gap explicitly.
4. **Learning:** show bandit event log with context/action/propensity/reward and held-out synthetic baseline; show RLHF parameter delta and held-out metric before/after. Both are offline learning demonstrations.

The restart proof runs **separate Python processes** against one local SQLite
file; `pause` must report `paused=true` and no executed action before `approve`.
Repeat with a new thread and the same action key to see `already_executed`:

```bash
agent/.venv/bin/python -m eval.portfolio_demo.agent_hitl --db /tmp/smartdoc-demo.sqlite --step pause --thread first --trace interview --action-key action-1
agent/.venv/bin/python -m eval.portfolio_demo.agent_hitl --db /tmp/smartdoc-demo.sqlite --step approve --thread first --trace interview
agent/.venv/bin/python -m eval.portfolio_demo.agent_hitl --db /tmp/smartdoc-demo.sqlite --step pause --thread retry --trace interview --action-key action-1
agent/.venv/bin/python -m eval.portfolio_demo.agent_hitl --db /tmp/smartdoc-demo.sqlite --step approve --thread retry --trace interview
```

Use a fresh database path for each interview run. `--step reject` demonstrates
the other human decision. `eval/tests/test_portfolio_agent_hitl.py` includes
the same cross-process proof, self-approval denial and malformed-decision case.

| Interview lens | Difficult question | Evidence-backed answer |
|---|---|---|
| Solution Architect | Why two retrieval paths? | Spring's PostgreSQL lexical CRAG provides fallback; Python's Qdrant dense+BM25 is the agent path. They are different indexes and need parity checks before a unified product claim. |
| Solution Architect | Why not call every query through an agent? | Agent orchestration adds latency, cost and failure modes. The source tries agent first, but the latest Azure smoke fell back; a simpler Spring RAG path remains the reliable observed result. |
| AI Engineer | Is the agent live and is retrieval accuracy 96.8%? | Agent is wired in code but not proven live on Azure. The 96.8% result in `docs/CV_EVIDENCE.md` is a mock fixture pass rate, not live retrieval accuracy. |
| AI Engineer | Is this RLHF production-ready? | No. It is an RLHF-style loop with synthetic, author-created preference pairs, a trained reward model and a real policy-gradient update to a small model's A/B choice. It has no human raters, does not fine-tune full answers and does not prove user value. |
| Backend/Platform | Does approval guarantee exactly once external action? | No. The serving path claims approval before execution; a crash can lose the action. The local demo's SQLite unique key protects only its simulated effect. Production requires durable execution state and each tool's idempotency contract. |
| Backend/Platform | What happens on a missing source or agent timeout? | The Spring branch either abstains or uses its CRAG fallback; tests and API response metadata identify that route. A successful HTTP response alone does not prove the agent ran. |

**Rollout boundary:** all demos are local/offline and independent of production
routing. This audit performs no cloud mutation and adds no live-cost claim.
