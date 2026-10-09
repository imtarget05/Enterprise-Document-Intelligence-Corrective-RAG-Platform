"""Local LoRA training runner implementing the TRAINING_RUNNER_URL contract.

``agent/training_jobs.py`` (TrainingRunnerClient) expects an external GPU
runner reachable at TRAINING_RUNNER_URL:

    POST /jobs   {dataset_uri, callback_url, callback_token} -> {job_id}
    GET  /jobs/{job_id} -> {job_id, status, adapter_uri, sha256, metrics,
                            model_version, failure_reason}

This module is that runner, running locally (Apple Silicon / MPS): each job
spawns ``finetune/lora_trainer.py`` as a subprocess, then reports the real
result back to the agent via POST callback_url with header
``X-Callback-Token: <callback_token>`` (the agent route
``/v1/training-jobs/{job_id}/callback`` validates it against the per-job
token).

Config (env):
    RUNNER_PORT            — default 8791
    AGENT_BASE_URL         — base for relative callback URLs (default
                             http://localhost:8080)
    LORA_BASE_MODEL        — default Qwen/Qwen2.5-0.5B-Instruct (trains on
                             M1 in ~1 min; 1.5B also works, just slower)
    LORA_EPOCHS            — default 1
    LORA_MAX_LENGTH        — default 512
    LORA_BATCH_SIZE        — default 2
    LORA_VALID_PATH        — default <dataset dir>/valid.jsonl if present

Run from the repo root (stdlib-only, no web framework needed):
    python -m agent.local_training_runner
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO_ROOT = Path(__file__).resolve().parents[1]
TRAINER = REPO_ROOT / "finetune" / "lora_trainer.py"
ADAPTERS_DIR = REPO_ROOT / "finetune" / "adapters"
AGENT_BASE_URL = os.getenv("AGENT_BASE_URL", "http://localhost:8080").rstrip("/")

# In-memory job registry (one process, local dev — same JSON-durability
# philosophy as the agent's TrainingJobStore is not required here because
# the agent's job row is the durable record; this is just runner state).
_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_metrics(output_dir: Path) -> Dict[str, float]:
    """Pull real train/eval losses out of the Trainer's trainer_state.json."""
    metrics: Dict[str, float] = {}
    state_path = output_dir / "trainer_state.json"
    if not state_path.exists():
        # transformers 5.x writes the final state inside the last checkpoint
        candidates = sorted(output_dir.glob("checkpoint-*/trainer_state.json"))
        state_path = candidates[-1] if candidates else state_path
    if not state_path.exists():
        return metrics
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return metrics
    log_history = state.get("log_history") or []
    eval_losses = [e["eval_loss"] for e in log_history if "eval_loss" in e]
    train_losses = [e["loss"] for e in log_history if "loss" in e and "eval_loss" not in e]
    if eval_losses:
        metrics["eval_loss"] = float(min(eval_losses))
        metrics["perplexity"] = float(math.exp(min(eval_losses)))
    if train_losses:
        metrics["train_loss"] = float(train_losses[-1])
    return metrics


def _post_callback(callback_url: str, callback_token: str, body: Dict[str, Any]) -> None:
    """POST the immutable result back to the agent (best-effort, logged)."""
    url = callback_url if callback_url.startswith("http") else f"{AGENT_BASE_URL}{callback_url}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Callback-Token": callback_token,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
    except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001 — logged, job stays SUCCEEDED locally
        print(f"[runner] callback to {url} failed: {exc}", file=sys.stderr)


def _run_training(job_id: str, dataset_uri: str, callback_url: str, callback_token: str) -> None:
    """Worker: train a real LoRA adapter, then report the real result."""
    out_dir = ADAPTERS_DIR / f"runner-{job_id}"
    valid_path = os.getenv("LORA_VALID_PATH") or str(Path(dataset_uri).parent / "valid.jsonl")
    if not Path(valid_path).exists():
        valid_path = ""  # trainer tolerates only if we pass existing path; handled below

    cmd = [
        sys.executable,
        str(TRAINER),
        "--base-model",
        os.getenv("LORA_BASE_MODEL", "Qwen/Qwen2.5-0.5B-Instruct"),
        "--train-path",
        dataset_uri,
        "--output-dir",
        str(out_dir),
        "--epochs",
        os.getenv("LORA_EPOCHS", "1"),
        "--max-length",
        os.getenv("LORA_MAX_LENGTH", "512"),
        "--batch-size",
        os.getenv("LORA_BATCH_SIZE", "2"),
    ]
    if valid_path:
        cmd += ["--valid-path", valid_path]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=3600,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"trainer exited {proc.returncode}: {proc.stderr[-2000:]}"
            )

        adapter_file = out_dir / "adapter_model.safetensors"
        if not adapter_file.exists():
            raise RuntimeError("trainer succeeded but adapter_model.safetensors missing")

        sha = _sha256(adapter_file)
        metrics = _read_metrics(out_dir)
        if not metrics:
            metrics = {"trained": 1.0}  # explicit non-empty, honest about no eval
        version = f"lora-{datetime.now().strftime('%Y%m%d.%H%M%S')}-{job_id[-6:]}"
        result = {
            "status": "SUCCEEDED",
            "model_version": version,
            "adapter_uri": f"file://{adapter_file}",
            "sha256": sha,
            "metrics": metrics,
        }
    except Exception as exc:  # noqa: BLE001 — failure is a first-class outcome
        result = {
            "status": "FAILED",
            "failure_reason": str(exc)[:500],
            "model_version": "",
            "adapter_uri": "",
            "sha256": "",
            "metrics": {},
        }

    with _lock:
        _jobs[job_id].update(result)
        _jobs[job_id]["status"] = result["status"]
        _jobs[job_id]["updated_at"] = _now()

    if callback_url:
        _post_callback(callback_url, callback_token, result)


class _Handler(BaseHTTPRequestHandler):
    """Tiny JSON router: POST /jobs, GET /jobs/{id}."""

    def _send(self, code: int, body: Dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet access log
        print(f"[runner] {self.address_string()} {fmt % args}")

    def do_POST(self) -> None:  # noqa: N802 — http.server API
        if self.path != "/jobs":
            self._send(404, {"detail": "NOT_FOUND"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send(400, {"detail": "JSON body required"})
            return
        dataset_uri = str(payload.get("dataset_uri") or "").strip()
        if not dataset_uri:
            self._send(400, {"detail": "dataset_uri is required"})
            return
        job_id = f"LR-{uuid.uuid4().hex[:12].upper()}"
        callback_url = str(payload.get("callback_url") or "")
        callback_token = str(payload.get("callback_token") or "")
        with _lock:
            _jobs[job_id] = {
                "job_id": job_id,
                "status": "RUNNING",
                "dataset_uri": dataset_uri,
                "requested_at": _now(),
                "updated_at": _now(),
                "adapter_uri": None,
                "sha256": None,
                "metrics": {},
                "model_version": None,
                "failure_reason": None,
            }
        threading.Thread(
            target=_run_training,
            args=(job_id, dataset_uri, callback_url, callback_token),
            daemon=True,
        ).start()
        self._send(200, {"job_id": job_id, "status": "RUNNING"})

    def do_GET(self) -> None:  # noqa: N802 — http.server API
        prefix = "/jobs/"
        if not self.path.startswith(prefix):
            self._send(404, {"detail": "NOT_FOUND"})
            return
        job_id = self.path[len(prefix):]
        with _lock:
            job = _jobs.get(job_id)
        if job is None:
            self._send(404, {"detail": "RUNNER_JOB_NOT_FOUND"})
            return
        self._send(200, dict(job))


def main() -> None:
    port = int(os.getenv("RUNNER_PORT", "8791"))
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"[runner] Local LoRA training runner on :{port} (agent base {AGENT_BASE_URL})")
    server.serve_forever()


if __name__ == "__main__":
    main()
