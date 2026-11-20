# Selected-document retrieval failure drill

`local_agent_retrieval_failure_2026-11-20.json` is the raw result of `scripts/demo_agent_retrieval_failure.py` against the local Python agent, Ollama and Qdrant. The script chooses an absent numeric Qdrant collection and verifies a 404 before asking a document-scoped question. The agent returns an explicit `answer_origin=abstention`, no citation and no factual answer. The run used `qwen2.5:1.5b` through Ollama.

```bash
INTERNAL_SERVICE_TOKEN=<same-local-agent-token> python3 scripts/demo_agent_retrieval_failure.py \
  --output eval/results/local_agent_retrieval_failure_2026-11-20.json
```

This is a controlled missing-collection case, not a total Qdrant outage or a multi-run latency estimate. The agent API returns HTTP 200 with a structured abstention; callers must check `answer_origin`. It does not prove answer quality on an ordinary corpus.
