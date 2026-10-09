"""
Human-in-the-loop (HITL) approval governance queue endpoints.
"""

import functools
import logging
from fastapi import APIRouter, Depends, HTTPException

from hitl import HITLStoreUnavailable, hitl_store
from models import ApprovalDecisionRequest
import state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent/approvals", tags=["hitl"])


def _map_store_errors(func):
    """Map a down approval store to HTTP 503 (fail-closed, never 500)."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except HITLStoreUnavailable as exc:
            logger.error("HITL approval store unavailable: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="Approval store temporarily unavailable — action NOT executed. Retry shortly.",
            )

    return wrapper


@router.get("", dependencies=[Depends(state.verify_and_rate_limit)])
@_map_store_errors
async def list_approvals():
    """List all pending human-approval requests (HITL governance queue)."""
    pending = await hitl_store.list_pending()
    return {"status": "ok", "pending": pending, "count": len(pending)}


@router.get("/{request_id}", dependencies=[Depends(state.verify_and_rate_limit)])
@_map_store_errors
async def get_approval(request_id: str):
    record = await hitl_store.get(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Approval request not found or expired")
    return {"status": "ok", "request": record}


@router.post("/{request_id}/approve", dependencies=[Depends(state.verify_and_rate_limit)])
@_map_store_errors
async def approve_action(request_id: str, req: ApprovalDecisionRequest):
    """Human approves the paused action -> execute it immediately."""
    record = await hitl_store.decide(request_id, "approved", req.approver, req.note)
    if record is None:
        raise HTTPException(status_code=404, detail="Approval request not found, already decided, or expired")

    if state._workflow is None:
        raise HTTPException(status_code=503, detail="LangGraph workflow unavailable")

    result = await state._workflow.ainvoke(
        {
            "query": record["query"],
            "session_id": record["session_id"],
            "user_id": record["user_id"],
            "document_ids": record.get("document_ids") or [],
            "messages": [],
            "long_term_history": [],
            "retrieved_chunks": [],
            "confidence_score": 0.0,
            "agent_plan": record.get("agent_plan", ""),
            "agent_type": "action",
            "intent_override": "action",
            "final_answer": "",
            "sources": [],
            "action_result": None,
            "report_path": None,
            "use_web_search": False,
            "hybrid_search_enabled": True,
            "hitl_auto_approved": True,
        }
    )
    return {
        "status": "ok",
        "decision": "approved",
        "approver": req.approver,
        "request_id": request_id,
        "workflow_result": result,
    }


@router.post("/{request_id}/reject", dependencies=[Depends(state.verify_and_rate_limit)])
@_map_store_errors
async def reject_action(request_id: str, req: ApprovalDecisionRequest):
    """Human rejects the paused action -> nothing executes."""
    record = await hitl_store.decide(request_id, "rejected", req.approver, req.note)
    if record is None:
        raise HTTPException(status_code=404, detail="Approval request not found, already decided, or expired")
    return {
        "status": "ok",
        "decision": "rejected",
        "approver": req.approver,
        "request_id": request_id,
    }
