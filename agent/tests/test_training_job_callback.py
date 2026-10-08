"""Callback-route contract tests (closes the runner callback loop).

``training_jobs.TrainingRunnerClient`` submits ``callback_url =
/v1/training-jobs/{job_id}/callback`` to the runner — this suite proves that
route exists, authenticates with the per-job ``callback_token``, and records
results with the exact same immutability rules as the internal ``/result``
route.
"""
from __future__ import annotations

import hmac
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "agent") not in sys.path:
    sys.path.insert(0, str(ROOT / "agent"))

import training_jobs as tj  # noqa: E402
from routers import training_jobs as router_mod  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _valid_result(**overrides) -> dict:
    result = {
        "model_version": "lora-20261009.000000",
        "adapter_uri": "file:///tmp/adapter_model.safetensors",
        "sha256": "c" * 64,
        "metrics": {"eval_loss": 2.67, "perplexity": 14.46},
    }
    result.update(overrides)
    return result


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated job store + no-op candidate registration, real router code."""
    store = tj.TrainingJobStore(base_dir=str(tmp_path / "jobs"))
    monkeypatch.setattr(router_mod, "_store", store)
    monkeypatch.setattr(router_mod, "register_candidate_from_job", lambda job: "vTEST")
    app = FastAPI()
    app.include_router(router_mod.router, prefix="/v1")
    return TestClient(app), store


def _job(store) -> tuple[str, str]:
    job = tj.submit_training_job(
        "finetune/data/train.jsonl",
        store=store,
        runner=type("R", (), {
            "configured": True,
            "submit": lambda self, dataset_uri, callback_url, callback_token: "LR-1",
        })(),
    )
    assert job.callback_token
    return job.job_id, job.callback_token


def test_callback_route_exists_and_token_is_required(env):
    client, store = env
    job_id, _ = _job(store)

    resp = client.post(f"/v1/training-jobs/{job_id}/callback", json=_valid_result())
    assert resp.status_code == 401  # no token -> rejected

    resp = client.post(
        f"/v1/training-jobs/{job_id}/callback",
        json=_valid_result(),
        headers={"X-Callback-Token": "wrong"},
    )
    assert resp.status_code == 401  # wrong token -> rejected
    assert store.load(job_id).status == tj.STATUS_RUNNING  # untouched


def test_callback_with_valid_token_records_immutable_result(env):
    client, store = env
    job_id, token = _job(store)

    resp = client.post(
        f"/v1/training-jobs/{job_id}/callback",
        json=_valid_result(),
        headers={"X-Callback-Token": token},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SUCCEEDED"
    assert body["sha256"] == "c" * 64
    assert body["metrics"]["perplexity"] == 14.46
    assert body["candidate_version"] == "vTEST"

    job = store.load(job_id)
    assert job.status == tj.STATUS_SUCCEEDED
    assert job.sha256 == "c" * 64

    # second callback cannot rewrite a terminal result
    resp2 = client.post(
        f"/v1/training-jobs/{job_id}/callback",
        json=_valid_result(model_version="lora-EVIL", sha256="d" * 64),
        headers={"X-Callback-Token": token},
    )
    assert resp2.status_code == 200
    job = store.load(job_id)
    assert job.model_version == "lora-20261009.000000"
    assert job.sha256 == "c" * 64


def test_callback_rejects_invalid_result_but_marks_job_failed(env):
    client, store = env
    job_id, token = _job(store)

    resp = client.post(
        f"/v1/training-jobs/{job_id}/callback",
        json={"status": "FAILED", "failure_reason": "trainer exited 1"},
        headers={"X-Callback-Token": token},
    )
    assert resp.status_code == 422
    job = store.load(job_id)
    assert job.status == tj.STATUS_FAILED
    assert job.adapter_uri is None


def test_callback_token_is_per_job_and_not_guessable(env):
    """Two jobs get distinct tokens; token must match byte-for-byte."""
    client, store = env
    job_a, token_a = _job(store)
    job_b, token_b = _job(store)
    assert token_a != token_b
    assert not hmac.compare_digest(token_a, token_b)

    # job A's token must not open job B
    resp = client.post(
        f"/v1/training-jobs/{job_b}/callback",
        json=_valid_result(),
        headers={"X-Callback-Token": token_a},
    )
    assert resp.status_code == 401
