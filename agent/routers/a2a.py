"""
Agent-to-Agent (A2A) protocol hub endpoints.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request

import state

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/a2a",
    tags=["a2a"],
    dependencies=[Depends(state.verify_and_rate_limit)],
)


@router.get("/agents")
async def list_a2a_agents():
    if state._a2a_hub is None:
        raise HTTPException(status_code=503, detail="A2A Hub not initialized")
    agents = [card.to_dict() for card in state._a2a_hub.discover_all()]
    return {"agents": agents, "total": len(agents)}


@router.get("/agents/{capability}")
async def discover_a2a_agents(capability: str):
    if state._a2a_hub is None:
        raise HTTPException(status_code=503, detail="A2A Hub not initialized")
    agents = [card.to_dict() for card in state._a2a_hub.discover_agents(capability)]
    return {"capability": capability, "agents": agents, "total": len(agents)}


@router.post("/delegate")
async def delegate_a2a_task(request: Request):
    if state._a2a_hub is None:
        raise HTTPException(status_code=503, detail="A2A Hub not initialized")
    payload = await request.json()
    capability = payload.get("capability", "")
    input_data = payload.get("input", {})
    if not capability:
        raise HTTPException(status_code=400, detail="capability is required")
    task = await state._a2a_hub.delegate(capability, input_data)
    return {
        "task_id": task.task_id,
        "agent_id": task.agent_id,
        "status": task.status.value,
        "result": task.result,
        "error": task.error,
        "latency_ms": round(task.latency_ms(), 2),
    }


@router.get("/stats")
async def a2a_stats():
    if state._a2a_hub is None:
        raise HTTPException(status_code=503, detail="A2A Hub not initialized")
    return state._a2a_hub.get_stats()
