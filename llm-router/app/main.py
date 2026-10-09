import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, status
from fastapi.responses import StreamingResponse

from .config import Settings, settings
from .models import ChatRequest
from .observability import (
    enabled as langfuse_enabled,
    flush as langfuse_flush,
    generation as langfuse_generation,
    trace_id_from_headers,
    update_generation as langfuse_update_generation,
)
from .document_ocr import classify_document_type, extract_text
from .providers import CloudflareProvider, LocalProviderBusyError, ProviderError
from .service import LLMRouter


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)


def create_app(
    app_settings: Settings = settings, router: LLMRouter | None = None
) -> FastAPI:
    service = router or LLMRouter(app_settings, CloudflareProvider(app_settings))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await service.close()

    app = FastAPI(
        title="Smart Document Chatbot - LLM Router",
        version="3.0.0",
        description="Routes Ollama-compatible chat requests to Cloudflare Workers AI.",
        lifespan=lifespan,
    )
    app.state.router = service
    app.state.settings = app_settings

    def verify_internal_token(request: Request) -> None:
        expected = app_settings.internal_token
        if not expected or not hmac.compare_digest(
            request.headers.get("X-Internal-Token", ""), expected
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
            )

    @app.post("/classify", dependencies=[Depends(verify_internal_token)])
    async def classify_document(request: Request):
        """Classify document type (PO/Invoice/ASN/OTHER) from extracted text."""
        body = await request.json()
        text = body.get("text", "")
        filename = body.get("filename", "")
        doc_type = classify_document_type(text, filename)
        return {"document_type": doc_type}


    @app.post("/extract", dependencies=[Depends(verify_internal_token)])
    async def extract_text_endpoint(request: Request):
        """Extract text from PDF/DOCX/TXT bytes."""
        body = await request.json()
        file_bytes = body.get("file_bytes", b"")
        file_type = body.get("file_type", "txt")
        if isinstance(file_bytes, str):
            import base64
            try:
                file_bytes = base64.b64decode(file_bytes)
            except Exception:
                file_bytes = b""
        text = extract_text(file_bytes, file_type)
        tables: list = []
        if file_type == "pdf":
            from .document_ocr import extract_tables_from_pdf
            tables = extract_tables_from_pdf(file_bytes)
        return {"text": text, "chars": len(text), "tables": tables}

    @app.post("/document/workflow", dependencies=[Depends(verify_internal_token)])
    async def document_workflow(request: Request):
        """Document workflow agent (Phase 2): classify → extract → map → match."""
        body = await request.json()
        trace_id = trace_id_from_headers(dict(request.headers))
        try:
            from agent.document_graph import run_document_workflow
        except ImportError:
            from ..agent.document_graph import run_document_workflow

        result = run_document_workflow(
            text=body.get("text", ""),
            filename=body.get("filename", ""),
            counterpart_fields=body.get("counterpart_fields"),
            trace_id=trace_id,
        )
        langfuse_flush()
        return result

    @app.post("/agent/invoke", dependencies=[Depends(verify_internal_token)])
    async def agent_invoke(request: Request):
        """Run the LangGraph agent (Phase 0-2) with a user message."""
        body = await request.json()
        message = body.get("message", "")
        trace_id = trace_id_from_headers(dict(request.headers))
        try:
            from agent.graph import run_agent  # type: ignore[attr-defined]
        except ImportError:
            from ..agent.graph import run_agent

        answer = await run_agent(
            message, trace_id=trace_id, tool_params=body.get("params")
        )
        langfuse_flush()
        return {"answer": answer}

    @app.post("/agent/jobs", dependencies=[Depends(verify_internal_token)])
    async def agent_jobs_submit(request: Request):
        """Submit async agent job (Phase 4: queue + worker). Trả job_id."""
        body = await request.json()
        from . import jobs
        trace_id = trace_id_from_headers(dict(request.headers))
        message = body.get("message", "")
        params = body.get("params")
        idempotency_key = str(body.get("idempotency_key") or "").strip()
        _pg_url = ""
        if idempotency_key:
            # Plan 03: replayed keys return the existing job without enqueueing twice.
            import os as _os

            _pg_url = _os.environ.get("DATABASE_URL", "")
            if _pg_url.startswith(("postgresql://", "postgres://")):
                import psycopg

                from . import db_jobs as _db_jobs

                with psycopg.connect(_pg_url) as _pg_conn:
                    existing = _db_jobs.find_job_by_idempotency_key(
                        _pg_conn, idempotency_key
                    )
                if existing is not None:
                    return {"job_id": existing, "status": "queued", "replay": True}
        job_id = await jobs.create_job("agent_invoke", {"message": message})
        if idempotency_key and _pg_url.startswith(("postgresql://", "postgres://")):
            with psycopg.connect(_pg_url) as _pg_conn:
                _db_jobs.record_job_idempotency_key(
                    _pg_conn, idempotency_key, job_id
                )
        try:
            from agent.graph import run_agent  # type: ignore[attr-defined]
        except ImportError:
            from ..agent.graph import run_agent
        asyncio.get_running_loop().create_task(
            jobs.run_job(job_id, lambda: run_agent(message, trace_id=trace_id, tool_params=params))
        )
        return {"job_id": job_id, "status": "queued"}

    @app.get("/agent/jobs/{job_id}", dependencies=[Depends(verify_internal_token)])
    async def agent_jobs_get(job_id: str):
        from . import jobs
        job = await jobs.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job_not_found")
        return job

    @app.websocket("/ws/agent/{job_id}")
    async def agent_jobs_ws(websocket: WebSocket, job_id: str):
        expected = app_settings.internal_token
        if not expected or not hmac.compare_digest(
            websocket.headers.get("X-Internal-Token", ""), expected
        ):
            await websocket.close(code=1008)
            return
        """Stream job status cho client tới khi done/failed."""
        from . import jobs
        await websocket.accept()
        last_status = None
        while True:
            job = await jobs.get_job(job_id)
            if job is None:
                await websocket.send_json({"error": "job_not_found"})
                break
            if job["status"] != last_status:
                await websocket.send_json(job)
                last_status = job["status"]
            if job["status"] in ("done", "failed"):
                break
            await asyncio.sleep(0.5)
        await websocket.close()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "llm-router",
            "providers": {
                "cloudflare": getattr(
                    service.providers, "configured", False
                ),
            },
        }

    @app.get("/health/live")
    async def health_live() -> dict[str, Any]:
        """Liveness: process can serve. No dependency checks."""
        return {"status": "ok", "service": "llm-router"}

    @app.get("/health/ready")
    async def health_ready() -> dict[str, Any]:
        """Readiness: at least one serving path (local or cloudflare) usable.

        Read-only: local probe is the cached non-mutating availability check;
        cloudflare is a config presence check. Opens no model sessions,
        writes nothing.
        """
        try:
            local_available = await service.local.is_available()
        except Exception as exc:
            local_available = False
            local_detail = f"not-ready: {exc}"
        else:
            local_detail = "ok" if local_available else "not-ready: local unavailable"
        cloudflare_configured = bool(
            getattr(service.providers, "configured", False)
        )
        checks = {
            "local": local_detail,
            "cloudflare": (
                "ok" if cloudflare_configured else "not-ready: cloudflare unconfigured"
            ),
        }
        ready = bool(local_available or cloudflare_configured)
        return {
            "status": "ready" if ready else "not-ready",
            "checks": checks,
        }

    @app.post("/api/chat", dependencies=[Depends(verify_internal_token)])
    async def chat(request: Request, payload: ChatRequest):
        trace_id = trace_id_from_headers(dict(request.headers))
        try:
            if payload.stream:
                return StreamingResponse(
                    service.stream_chat(payload), media_type="application/x-ndjson"
                )
            result = await service.chat(payload)
            # Join to the backend-originated trace (Phase 2 glue).
            if langfuse_enabled() and trace_id is not None:
                model = result.get("model", app_settings.cloudflare_chat_model)
                langfuse_generation(
                    trace_id, "router_generate", model,
                    input={"message_count": len(payload.messages)},
                    metadata={"stream": False},
                )
                langfuse_update_generation(
                    trace_id, "router_generate",
                    output=result.get("message", {}).get("content"),
                    metadata={"backend": "cloudflare"},
                )
                langfuse_flush()
            return result
        except ProviderError as exc:
            if langfuse_enabled() and trace_id is not None:
                langfuse_update_generation(
                    trace_id, "router_generate",
                    output=None, metadata={"error": str(exc)},
                )
                langfuse_flush()
            # DEPLOYMENT CHỐT Local-First: CONFIDENTIAL + local lỗi -> lỗi bảo
            # mật 403, không lén đẩy cloud. Các lỗi provider khác giữ 503.
            if str(exc).startswith("policy_violation"):
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            # WP3: local busy -> 503 + Retry-After để client backoff.
            if isinstance(exc, LocalProviderBusyError):
                raise HTTPException(
                    status_code=503,
                    detail="local busy, retry",
                    headers={"Retry-After": "2"},
                ) from exc
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/embeddings", dependencies=[Depends(verify_internal_token)])
    async def embeddings(request: Request, payload: dict[str, Any]):
        trace_id = trace_id_from_headers(dict(request.headers))
        try:
            # Local tier first (LM Studio → Ollama), Cloudflare otherwise —
            # same no-mid-request-fallback contract as chat routing.
            lmstudio = getattr(service, "lmstudio", None)
            if lmstudio is not None and await lmstudio.is_available():
                result = await lmstudio.embeddings(payload)
                if langfuse_enabled() and trace_id is not None:
                    langfuse_generation(
                        trace_id, "router_embeddings",
                        model=app_settings.local_lmstudio_embed_model,
                        metadata={"stream": False, "backend": "local_lmstudio"},
                    )
                    langfuse_flush()
                return result
            local = getattr(service, "local", None)
            if local is not None and await local.is_available():
                result = await local.embeddings(payload)  # type: ignore[attr-defined]
                if langfuse_enabled() and trace_id is not None:
                    langfuse_generation(
                        trace_id, "router_embeddings",
                        model=app_settings.local_ollama_embed_model,
                        metadata={"stream": False, "backend": "local_ollama"},
                    )
                    langfuse_flush()
                return result
            result = await service.providers.embeddings(payload)  # type: ignore[attr-defined]
            if langfuse_enabled() and trace_id is not None:
                langfuse_generation(
                    trace_id, "router_embeddings",
                    model=app_settings.cloudflare_embed_model,
                    metadata={"stream": False},
                )
                langfuse_flush()
            return result
        except Exception as exc:
            if langfuse_enabled() and trace_id is not None:
                langfuse_update_generation(
                    trace_id, "router_embeddings",
                    output=None, metadata={"error": str(exc)},
                )
                langfuse_flush()
            raise HTTPException(
                status_code=503, detail="embedding_unavailable"
            ) from exc

    return app


app = create_app()