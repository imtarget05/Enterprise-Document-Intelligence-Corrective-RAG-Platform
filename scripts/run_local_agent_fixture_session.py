"""Run one local Qdrant -> Python agent -> HITL rejection evidence session.

Prerequisites: local Qdrant, PostgreSQL, and Ollama from docker-compose.local;
agent dependencies installed in a Python environment. This indexes a synthetic
fixture directly into Qdrant, not through the Spring document upload route.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = "The Eiffel Tower is located in Paris, France. It was completed in 1889."
QUESTION = "Where is the Eiffel Tower located?"


def call(url: str, method: str = "GET", body: dict | None = None,
         token: str | None = None, timeout: int = 90) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Internal-Token"] = token
    request = Request(url, method=method, headers=headers,
                      data=json.dumps(body).encode() if body is not None else None)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)


def require_ok(status: int, body: dict, step: str) -> dict:
    if status < 200 or status >= 300:
        raise RuntimeError(f"{step} returned HTTP {status}: {str(body)[:300]}")
    return body


def wait_ready(base_url: str, process: subprocess.Popen, timeout: int = 40) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Agent exited with status {process.returncode}")
        try:
            status, body = call(f"{base_url}/v1/ready", timeout=2)
            if status == 200 and body.get("status") == "ok":
                return
        except (OSError, URLError, ValueError):
            pass
        time.sleep(0.5)
    raise TimeoutError("Local agent did not become ready")


def run(agent_python: Path, model: str, port: int, output: Path) -> dict:
    agent_python = agent_python.resolve()
    if not agent_python.is_file():
        raise FileNotFoundError(f"Agent Python not found: {agent_python}")
    if not 1024 <= port <= 65535:
        raise ValueError("Port must be in 1024..65535")

    ollama = "http://127.0.0.1:11434"
    qdrant = "http://127.0.0.1:6333"
    agent_url = f"http://127.0.0.1:{port}"
    model_names = [item["name"] for item in require_ok(*call(f"{ollama}/api/tags"), "Ollama models").get("models", [])]
    if model not in model_names:
        raise RuntimeError(f"Ollama model {model!r} is not installed")
    if not any(name.startswith("nomic-embed-text") for name in model_names):
        raise RuntimeError("Ollama nomic-embed-text is not installed")

    run_id = uuid.uuid4().hex[:12]
    collection_id = f"demo_agent_{run_id}"
    trace_id = f"local-agent-{run_id}"
    session_id = trace_id
    owner_id = f"local-owner-{run_id}"
    token = secrets.token_urlsafe(32)
    env = os.environ.copy()
    env.update({
        "APP_ENV": "local", "PYTHONPATH": str(ROOT / "agent"),
        "QDRANT_HOST": "127.0.0.1", "QDRANT_PORT": "6333",
        "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5434",
        "POSTGRES_DB": "smartdoc", "POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": "postgres",
        "LOCAL_OLLAMA_URL": ollama, "LOCAL_OLLAMA_CHAT_MODEL": model,
        "LOCAL_OLLAMA_EMBED_MODEL": "nomic-embed-text",
        "LOCAL_LMSTUDIO_URL": "", "LLM_BASE_URL": "http://127.0.0.1:18001",
        "INTERNAL_SERVICE_TOKEN": token, "DATABASE_URL": "", "REDIS_URL": "",
        "HITL_STORE_BACKEND": "memory",
    })
    with tempfile.TemporaryFile(mode="w+t") as log:
        process = subprocess.Popen(
            [str(agent_python), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT / "agent", env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            wait_ready(agent_url, process)
            embedding = require_ok(*call(f"{ollama}/api/embeddings", "POST", {
                "model": "nomic-embed-text", "prompt": DOCUMENT,
            }), "embedding").get("embedding", [])
            if not embedding:
                raise RuntimeError("Ollama returned no embedding")
            require_ok(*call(f"{qdrant}/collections/{collection_id}", "PUT", {
                "vectors": {"size": len(embedding), "distance": "Cosine"},
            }), "Qdrant collection")
            require_ok(*call(f"{qdrant}/collections/{collection_id}/points", "PUT", {
                "points": [{"id": 1, "vector": embedding, "payload": {
                    "text": DOCUMENT, "document_name": "paris-facts.txt", "chunk_index": 0,
                    "source_type": "document", "user_id": owner_id,
                }}],
            }), "Qdrant upsert")

            query_vector = require_ok(*call(f"{ollama}/api/embeddings", "POST", {
                "model": "nomic-embed-text", "prompt": QUESTION,
            }), "query embedding").get("embedding", [])
            if not query_vector:
                raise RuntimeError("Ollama returned no query embedding")
            retrieval_started = time.monotonic()
            retrieval = require_ok(*call(f"{qdrant}/collections/{collection_id}/points/search", "POST", {
                "vector": query_vector, "limit": 5, "with_payload": True,
            }), "Qdrant search").get("result", [])
            retrieval_ms = round((time.monotonic() - retrieval_started) * 1000)
            if not retrieval or retrieval[0].get("payload", {}).get("text") != DOCUMENT:
                raise RuntimeError("Qdrant did not retrieve the uploaded fixture")

            started = time.monotonic()
            answer = require_ok(*call(f"{agent_url}/v1/agent/invoke", "POST", {
                "query": QUESTION, "session_id": session_id, "user_id": owner_id,
                "document_ids": [collection_id], "intent_override": "rag", "trace_id": trace_id,
            }, token, 180), "agent answer")
            answer_ms = round((time.monotonic() - started) * 1000)
            if (answer.get("agent_type") != "rag" or "Paris" not in answer.get("answer", "")
                    or not any(s.get("document_name") == "paris-facts.txt" for s in answer.get("sources", []))):
                raise RuntimeError(f"Agent answer lacks grounded Paris citation: {answer}")

            action = require_ok(*call(f"{agent_url}/v1/agent/invoke", "POST", {
                "query": "Send the Paris document summary by email to the team.",
                "session_id": session_id, "user_id": owner_id,
                "document_ids": [collection_id], "intent_override": "action", "trace_id": trace_id,
            }, token, 90), "HITL request")
            approval_id = action.get("hitl_approval_id")
            if not action.get("hitl_pending") or not approval_id:
                raise RuntimeError(f"Action was not paused for approval: {action}")
            rejection = require_ok(*call(
                f"{agent_url}/v1/agent/approvals/{approval_id}/reject", "POST",
                {"approver": "local-reviewer", "note": "local demo rejects external action"}, token,
            ), "HITL rejection")
            if rejection.get("decision") != "rejected":
                raise RuntimeError(f"Action was not rejected: {rejection}")

            result = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
                "scope": "Local Python agent and Qdrant; synthetic fixture indexed directly, not Spring upload",
                "model": model, "embedding_model": "nomic-embed-text", "embedding_dimensions": len(embedding),
                "document_sha256": hashlib.sha256(DOCUMENT.encode()).hexdigest(),
                "document_id": collection_id, "session_id": session_id, "trace_id": trace_id,
                "retrieval_latency_ms": retrieval_ms, "retrieval": retrieval,
                "answer_latency_ms": answer_ms, "answer": answer,
                "hitl_request": action, "hitl_rejection": rejection,
                "complete": True,
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            return result
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-python", type=Path, default=ROOT / "agent/.venv/bin/python")
    parser.add_argument("--model", default="qwen2.5:1.5b")
    parser.add_argument("--port", type=int, default=19001)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "eval/results/local_agent_fixture_session_2026-11-20.json")
    args = parser.parse_args()
    report = run(args.agent_python, args.model, args.port, args.output)
    print(json.dumps({"complete": report["complete"], "output": str(args.output),
                      "answer_latency_ms": report["answer_latency_ms"]}))


if __name__ == "__main__":
    main()
