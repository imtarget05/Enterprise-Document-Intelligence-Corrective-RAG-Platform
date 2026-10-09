"""
Action execution, PDF report generation, and external connectors.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status

from adk_runtime import run_demo_workflow
from models import ActionRequest, ConnectorIngestRequest, ReportRequest
from settings import settings
import state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["actions"])


@router.post("/adk/demo", dependencies=[Depends(state.verify_and_rate_limit)])
async def adk_demo(request: Request):
    payload = await request.json()
    user_request = payload.get("user_request", "")
    document_name = payload.get("document_name", "demo-document")
    if not user_request:
        raise HTTPException(status_code=400, detail="user_request is required")
    try:
        user_request = state.check_prompt_injection(user_request)
    except ValueError as inj_exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(inj_exc)
        )
    return run_demo_workflow(user_request=user_request, document_name=document_name)


@router.post("/report", dependencies=[Depends(state.verify_and_rate_limit)])
async def generate_report(req: ReportRequest):
    from agents.report_agent import ReportAgent

    agent = ReportAgent()
    path = await agent.generate_pdf_report(
        title=req.title,
        content=req.content,
        user_id=req.user_id,
    )
    return {"status": "ok", "report_path": path}


@router.post("/action", dependencies=[Depends(state.verify_and_rate_limit)])
async def execute_action(req: ActionRequest):
    from agents.action_agent import ActionAgent

    agent = ActionAgent()
    result = await agent.execute(req.action_type, req.payload)
    return {"status": "ok", "result": result}


@router.post("/connector/ingest", dependencies=[Depends(state.verify_internal_token)])
async def connector_ingest(req: ConnectorIngestRequest):
    from agents.ingestion_agent import IngestionAgent

    agent = IngestionAgent()
    if req.source not in agent.supported_sources():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown connector source: {req.source}. Supported: {agent.supported_sources()}",
        )

    result = await agent.ingest(
        source=req.source, user_id=req.user_id, params=req.params
    )

    # Auto-trigger retrain after connector ingestion
    try:
        from retrain import check_and_retrain

        decision = check_and_retrain(
            base_url="http://backend:8080/api",
            token=settings.internal_service_token,
            document_id=0,
            force=False,
        )
        if decision.should_retrain:
            logger.info(
                "Auto-retrain triggered after connector ingestion: %s", decision.reason
            )
    except Exception as exc:
        logger.warning("Auto-retrain trigger after connector ingest failed: %s", exc)

    return {"status": "ok", "ingested": result}
