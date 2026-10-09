"""Training-job API: authenticated submission + immutable result polling.

Plan 2026-09-18 Task 3. Airflow and operators submit a dataset URI here;
this endpoint talks to the external GPU runner (TRAINING_RUNNER_URL) and
returns a job identity. Serving traffic never changes until an explicit,
authenticated promotion.
"""

import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from settings import settings
import state
from training_jobs import (
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    TrainingJobError,
    TrainingJobStore,
    TrainingRunnerClient,
    apply_runner_result,
    register_candidate_from_job,
    submit_training_job,
    validate_training_result,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["training"])

_store = TrainingJobStore()


@router.post("/training-jobs", dependencies=[Depends(state.verify_internal_token)])
async def create_training_job(request: Request):
    """Submit an asynchronous training job for a dataset URI."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON body required")
    dataset_uri = str(payload.get("dataset_uri") or payload.get("dataset_path") or "").strip()
    if not dataset_uri:
        raise HTTPException(status_code=400, detail="dataset_uri is required")
    try:
        job = submit_training_job(dataset_uri, store=_store, runner=TrainingRunnerClient())
    except TrainingJobError as exc:
        logger.error("Training job submission failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"TRAINING_RUNNER_UNAVAILABLE: {exc}")
    return {"job_id": job.job_id, "status": job.status}


@router.get("/training-jobs/{job_id}", dependencies=[Depends(state.verify_internal_token)])
async def get_training_job(job_id: str):
    """Poll one job's authoritative, immutable result."""
    job = _store.load(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="TRAINING_JOB_NOT_FOUND")
    return job.result_payload()


def _record_result(job, payload: dict):
    """Validate + persist a runner result; register a Candidate on success.

    Shared by the internal-token ``/result`` route and the per-job
    ``/callback`` route so both enforce the exact same immutability rules.
    """
    ok, reason = validate_training_result(payload)
    if not ok:
        apply_runner_result(job, payload, store=_store)
        raise HTTPException(status_code=422, detail=f"INVALID_TRAINING_RESULT: {reason}")
    job = apply_runner_result(job, payload, store=_store)
    candidate = None
    if job.status == STATUS_SUCCEEDED:
        try:
            candidate = register_candidate_from_job(job)
        except Exception as exc:  # registration must not mask the job result
            logger.warning("Candidate registration skipped: %s", exc)
    return {**job.result_payload(), "candidate_version": candidate}


@router.post("/training-jobs/{job_id}/result", dependencies=[Depends(state.verify_internal_token)])
async def record_training_job_result(job_id: str, request: Request):
    """Record the runner's immutable result for one specific job."""
    job = _store.load(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="TRAINING_JOB_NOT_FOUND")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON body required")
    return _record_result(job, payload)


@router.post("/training-jobs/{job_id}/callback")
async def training_job_callback(job_id: str, request: Request):
    """Runner callback: authenticated by the per-job ``callback_token``.

    This is the endpoint the runner receives as ``callback_url`` at submit
    time. The token is generated with the job and compared in constant time;
    it is never derivable from the job id.
    """
    job = _store.load(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="TRAINING_JOB_NOT_FOUND")
    token = request.headers.get("X-Callback-Token", "")
    if not job.callback_token or not hmac.compare_digest(token, job.callback_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON body required")
    return _record_result(job, payload)


@router.post("/training-jobs/{job_id}/promote", dependencies=[Depends(state.verify_internal_token)])
async def promote_training_job_candidate(job_id: str):
    """Explicit, audited rollout of a candidate version to Production."""
    from model_registry import registry

    job = _store.load(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="TRAINING_JOB_NOT_FOUND")
    if job.status != STATUS_SUCCEEDED or not job.model_version:
        raise HTTPException(status_code=409, detail="TRAINING_JOB_NOT_SUCCEEDED")
    version = job.model_version
    if not registry.set_stage("rag-retriever", version, "Production"):
        raise HTTPException(status_code=404, detail="CANDIDATE_VERSION_NOT_FOUND")
    registry.promote_model("rag-retriever", version, "Production")
    return {"status": "PROMOTED", "model_version": version}


@router.post("/training-jobs/{job_id}/rollback", dependencies=[Depends(state.verify_internal_token)])
async def rollback_training_job_candidate(job_id: str, request: Request):
    """Reversibly return serving traffic to a previously approved version."""
    from model_registry import registry

    job = _store.load(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="TRAINING_JOB_NOT_FOUND")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    target = str(payload.get("to_version") or "").strip()
    if not target:
        versions = [v for v in registry.list_versions("rag-retriever") if v.stage == "Archived"]
        if not versions:
            raise HTTPException(status_code=409, detail="NO_ROLLBACK_TARGET")
        target = versions[-1].version
    if not registry.rollback("rag-retriever", target):
        raise HTTPException(status_code=404, detail="ROLLBACK_TARGET_NOT_FOUND")
    return {"status": "ROLLED_BACK", "model_version": target}