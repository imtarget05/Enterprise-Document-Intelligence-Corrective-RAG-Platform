"""
Graph Memory (GraphRAG) endpoints for knowledge graph retrieval.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request

import state

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/agent/memory/graph",
    tags=["memory"],
    dependencies=[Depends(state.verify_and_rate_limit)],
)


@router.get("/stats")
async def graph_memory_stats():
    """Get graph memory statistics."""
    if state._graph_memory is None:
        raise HTTPException(status_code=503, detail="Graph memory not initialized")
    stats = await state._graph_memory.get_stats()
    return {"status": "ok", **stats}


@router.post("/extract")
async def graph_memory_extract(request: Request):
    """Extract and store entities from a conversation."""
    if state._graph_memory is None:
        raise HTTPException(status_code=503, detail="Graph memory not initialized")
    payload = await request.json()
    session_id = payload.get("session_id", "default")
    user_id = payload.get("user_id", "default")
    conversation_turns = payload.get("conversation_turns", [])

    entities, relationships = await state._graph_memory.extract_and_store(
        session_id=session_id,
        user_id=user_id,
        conversation_turns=conversation_turns,
    )
    return {
        "status": "ok",
        "entities_extracted": len(entities),
        "relationships_extracted": len(relationships),
        "entities": [e.to_dict() for e in entities],
        "relationships": [r.to_dict() for r in relationships],
    }


@router.get("/entity/{entity_name:path}")
async def graph_memory_entity(entity_name: str):
    """Get all facts about an entity."""
    if state._graph_memory is None:
        raise HTTPException(status_code=503, detail="Graph memory not initialized")
    context = await state._graph_memory.get_entity_context(entity_name)
    return {"status": "ok", **context}


@router.get("/related/{entity_name:path}")
async def graph_memory_related(entity_name: str, depth: int = 2):
    """Find related entities using graph traversal."""
    if state._graph_memory is None:
        raise HTTPException(status_code=503, detail="Graph memory not initialized")
    related = await state._graph_memory.retrieve_related(entity_name, depth=depth)
    return {"status": "ok", "entity": entity_name, "related": related, "count": len(related)}


@router.get("/path")
async def graph_memory_path(entity_a: str = "", entity_b: str = ""):
    """Find relationship path between two entities."""
    if state._graph_memory is None:
        raise HTTPException(status_code=503, detail="Graph memory not initialized")
    if not entity_a or not entity_b:
        raise HTTPException(status_code=400, detail="entity_a and entity_b are required")
    path = await state._graph_memory.find_path(entity_a, entity_b)
    return {"status": "ok", **(path or {"found": False})}


@router.get("/session/{session_id}")
async def graph_memory_session(session_id: str):
    """Get all entities mentioned in a session."""
    if state._graph_memory is None:
        raise HTTPException(status_code=503, detail="Graph memory not initialized")
    entities = await state._graph_memory.get_session_entities(session_id)
    return {"status": "ok", "session_id": session_id, "entities": entities, "count": len(entities)}


@router.get("/search")
async def graph_memory_search(query: str = "", limit: int = 10):
    """Search entities by name."""
    if state._graph_memory is None:
        raise HTTPException(status_code=503, detail="Graph memory not initialized")
    if not query:
        raise HTTPException(status_code=400, detail="query parameter is required")
    entities = await state._graph_memory.search_entities(query, limit=limit)
    return {"status": "ok", "query": query, "entities": entities, "count": len(entities)}
