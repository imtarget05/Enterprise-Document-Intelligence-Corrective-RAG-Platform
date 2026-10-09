"""
Model Context Protocol (MCP) tool server endpoints.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request

import state

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/mcp",
    tags=["mcp"],
    dependencies=[Depends(state.verify_and_rate_limit)],
)


@router.get("/info")
async def mcp_server_info():
    if state._mcp_server is None:
        raise HTTPException(status_code=503, detail="MCP Server not initialized")
    return state._mcp_server.get_server_info()


@router.get("/tools")
async def mcp_list_tools():
    if state._mcp_server is None:
        raise HTTPException(status_code=503, detail="MCP Server not initialized")
    return {"tools": state._mcp_server.list_tools(), "total": len(state._mcp_server.list_tools())}


@router.post("/call")
async def mcp_call_tool(request: Request):
    if state._mcp_server is None:
        raise HTTPException(status_code=503, detail="MCP Server not initialized")
    payload = await request.json()
    name = payload.get("name", "")
    arguments = payload.get("arguments", {})
    if not name:
        raise HTTPException(status_code=400, detail="Tool name is required")
    result = await state._mcp_server.call_tool(name, arguments)
    return {
        "tool_name": result.tool_name,
        "status": result.status.value,
        "result": result.result,
        "error": result.error,
        "latency_seconds": result.latency_seconds,
    }


@router.get("/stats")
async def mcp_stats():
    if state._mcp_server is None:
        raise HTTPException(status_code=503, detail="MCP Server not initialized")
    return state._mcp_server.get_stats()
