# Local upload → agent → HITL drill

`local_upload_agent_hitl_2026-11-20.json` is raw output from `scripts/demo_agent_upload_hitl.py` on 2026-11-20. The script registers a fresh local user, uploads a text file through Spring, explicitly indexes that user's document in Qdrant, asks a document-scoped question through Spring chat, then requests a Jira action in the same session and rejects its approval through the internal Python API. No Jira action is executed.

Run after starting PostgreSQL, Redis, Qdrant, Ollama (`qwen2.5:1.5b` and `nomic-embed-text`), the Python agent and Spring backend as described in `docs/DEPLOYMENT_LOCAL_FIRST.md`:

```bash
INTERNAL_SERVICE_TOKEN=<same-local-agent-token> python3 scripts/demo_agent_upload_hitl.py \
  --backend http://127.0.0.1:18085/api \
  --agent http://127.0.0.1:19003/v1 \
  --output eval/results/local_upload_agent_hitl_2026-11-20.json
```

The agent must have `LOCAL_OLLAMA_URL=http://127.0.0.1:11434` and the backend must have `AGENT_BASE_URL=http://127.0.0.1:19003` plus the same `INTERNAL_SERVICE_TOKEN`. This is a localhost fixture with a new one-chunk text document, not a hosted production quality or user-traffic measurement. Indexing is explicit through `POST /api/documents/{id}/agent-index`; it is not an asynchronous ingest job. Reindexing currently recreates the per-document Qdrant collection, so a failure between delete and upsert can temporarily leave that document unsearchable. The script checks a grounded answer and rejected HITL state; it does not evaluate retrieval quality across a corpus.
