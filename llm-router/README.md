# LLM Router Service

FastAPI service placed between the application and the LLM backend. It exposes
Ollama-compatible endpoints used by the existing CRAG code, while the actual
inference is handled by **Cloudflare Workers AI** exclusively (no local Ollama
fallback).

- `POST /api/chat`: routes chat requests to Cloudflare Workers AI.
- `POST /api/embeddings`: proxies embeddings to Cloudflare Workers AI.
- `GET /health`: reports service provider configuration status.

## Routing
## Testing

The router has its **own virtualenv** at `llm-router/.venv` — the repo-root
`.venv` does not contain `pdfplumber`, so running pytest with the root
interpreter fails during collection of `tests/test_document_graph.py`.
Always run tests through the local venv:

```bash
make test-router          # equivalent to the command below
cd llm-router && .venv/bin/python -m pytest -q
```

For the top_p sampling end-to-end chain (mock Ollama + real router app):

```bash
make e2e-top-p            # runs scripts/local_top_p_e2e.py (10 checks)
```

## Routing

The router serves **Cloudflare Workers AI** as the only provider. The routing
logic still classifies request complexity for observability (logs include the
task type and reason), but all requests go to the same Cloudflare model.

1. Complex tasks (`compare`, `summarize`, `summarize_long`) → logged as `complex_task`.
2. More than 2 documents or more than 10 pages → logged as `complex_task`.
3. `confidence_score` below `ROUTER_CONFIDENCE_THRESHOLD` (default 0.7) → logged as `low_confidence`.
4. Everything else (Q&A, extraction, keyword search) → logged as `simple_task`.

When `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` are set, requests are
translated to the Workers AI REST API (`/accounts/{id}/ai/run/{model}`) with
the model `@cf/meta/llama-3.3-70b-instruct-fp8-fast`. Responses and streaming
are converted back to the Ollama wire format so callers never change.

## Request metadata

Existing Ollama requests continue to work. Callers can add optional metadata:

```json
{
  "model": "ignored-by-router",
  "messages": [{"role": "user", "content": "Compare these contracts"}],
  "stream": false,
  "routing": {
    "task_type": "compare",
    "document_count": 3,
    "page_count": 24,
    "confidence_score": 0.82,
    "has_image": false,
    "attachments": ["contract-a.pdf", "contract-b.pdf"],
    "request_id": "optional-correlation-id"
  }
}
```

Every response includes a `router` object. Logs are JSON and include the
selected provider ("cloudflare"), model, reason, request ID, and latency for
cost tracking.

## Configuration

Use `.env.example` at the repository root. Cloudflare credentials:

- `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN` — Workers AI API auth.
- `CLOUDFLARE_CHAT_MODEL` — inference model (default `@cf/meta/llama-3.3-70b-instruct-fp8-fast`).
- `CLOUDFLARE_EMBED_MODEL` — embedding model (default `@cf/baai/bge-base-en-v1.5`).
- `CLOUDFLARE_TIMEOUT_SECONDS` — request timeout (default 60s).
- `ROUTER_CONFIDENCE_THRESHOLD` — confidence threshold for task classification (default 0.7).
- `ROUTER_INTERNAL_TOKEN` — required; all protected HTTP routes and the agent WebSocket fail closed when it is unset. Callers must send it in `X-Internal-Token`.

Run tests from this directory:

```bash
uv run --python 3.12 pytest -q
```

Smoke-test against real Cloudflare from this directory:

```bash
set -a && source ../.env && set +a
uv run --python 3.12 python - <<'PY'
import asyncio
from app.config import Settings
from app.providers import CloudflareProvider
from app.models import ChatRequest, RoutingContext, RouteDecision

async def main():
    p = CloudflareProvider(Settings())
    resp = await p.chat(
        ChatRequest(messages=[{"role": "user", "content": "Say hello"}],
                     routing=RoutingContext()),
        RouteDecision(provider="cloudflare", model="x", reason="smoke", task_type="general"),
        "smoke",
    )
    print(resp["message"]["content"])
    await p.close()

asyncio.run(main())
PY
```