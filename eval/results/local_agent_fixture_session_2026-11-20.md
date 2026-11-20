# Local Python agent fixture session — 2026-11-20

Run `python3 scripts/run_local_agent_fixture_session.py` after preparing the
local stack and agent environment described in the root README. The runner
starts the FastAPI agent itself, creates a fresh Qdrant collection, embeds a
synthetic text fixture with local Ollama `nomic-embed-text`, checks Qdrant
retrieval, calls the LangGraph RAG agent with that collection ID, then requests
an action in the **same session** and rejects it through the HITL API.

The [raw result](local_agent_fixture_session_2026-11-20.json) records source
commit `3e6b33e`, data SHA-256, document/collection ID, session and trace IDs,
Qdrant search response, full agent answer and sources, HITL request and
rejection. The run used Ollama `qwen2.5:1.5b` for chat and
`nomic-embed-text` for 768-dimensional embeddings. Qdrant returned one
matching chunk in 2 ms; the Python agent answered in 1,340 ms with “Paris,
France” and a citation to `paris-facts.txt`; HITL was pending, then rejected.
These are one-run measurements, not p50/p95 estimates.

The fixture is inserted **directly into local Qdrant**, not uploaded through
Spring. This run proves the Python agent retrieval and HITL path, but not a
shared ingestion flow from Spring to Qdrant or durable HITL across restarts.
The approval store was in memory, no external action executed, and the model
was local. `cost_usd=0` means no metered API charge; electricity and hardware
cost were not measured. The existing Java RAG benchmark is separate evidence.
