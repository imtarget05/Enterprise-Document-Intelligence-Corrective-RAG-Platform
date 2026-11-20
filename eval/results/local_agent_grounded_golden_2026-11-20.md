# Local agent golden evaluation — 2026-11-20

The [raw run](local_agent_grounded_golden_2026-11-20.json) uses the six chunks and 13 cases in `eval/agent_grounded_golden.json` (SHA-256 `ba6050e51cb4c0b90f5d158306c1a9924457776065832a4b9713b5772c80364b`). The runner embeds all chunks with local Ollama `nomic-embed-text`, inserts them into one temporary Qdrant collection, queries Qdrant through `QdrantHybridSearch`, and calls the real LangGraph agent with Ollama `qwen2.5:1.5b`. It deletes the collection at the end.

Run with the local Qdrant, Ollama, PostgreSQL, and Python agent up:

```bash
APP_ENV=local QDRANT_HOST=127.0.0.1 LOCAL_OLLAMA_URL=http://127.0.0.1:11434 \
  LOCAL_OLLAMA_EMBED_MODEL=nomic-embed-text INTERNAL_SERVICE_TOKEN=<same-local-agent-token> \
  python eval/run_agent_grounded_golden.py \
  --output eval/results/local_agent_grounded_golden_2026-11-20.json
```

| Metric | This run |
| --- | ---: |
| Retrieval hybrid Recall@5 / MRR | 1.00 / 1.00 (6 questions) |
| Simple lexical overlap Recall@5 / MRR | 1.00 / 1.00 (same corpus and 6 questions) |
| Answer fact **and** gold source | 3/3 |
| Prompt injection rejected | 1/1 (HTTP 400) |
| No-answer and missing-collection cases | 2/2 by case-specific rules |
| Action routed to HITL and rejected | 1/1 |
| Overall task completion | 7/7 |
| Agent latency p50 / p95 | 22,705 / 59,516 ms (7 cases, includes rejection setup) |
| Metered API cost | USD 0 (local Ollama; hardware/electricity not measured) |

The lexical baseline ties hybrid on this tiny, easy corpus; **there is no observed search improvement**. BM25 is reranking only the semantic candidate subset, not searching the full corpus. The no-answer case is judged by an explicit absence statement in the answer but currently returns `answer_origin=agent`; the missing-collection case returns structured `answer_origin=abstention`. The 1.5B model's answers and A/B variant assignment can vary between runs. This synthetic local result does not establish production quality, prompt-injection coverage beyond one case, or real user traffic. The controlled failure case opens the current Qdrant circuit breaker after repeated missing-collection requests; the run places it near the end to avoid affecting the ordinary retrieval cases.
