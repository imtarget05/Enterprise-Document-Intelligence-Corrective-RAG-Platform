"""
Document lifecycle endpoints.

Phase 2: a document delete must not leave the document's content reachable.
The backend deletes the document row, the PostgreSQL chunks and the storage
blob; this endpoint purges what the agent service owns — the vector store
points (chunks + embeddings), the retrieval cache entries that could still
answer from those chunks, and the memory entries that reference the document.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

import document_purge
from document_purge import DocumentPurgeService
import state

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/agent/documents",
    tags=["documents"],
    dependencies=[Depends(state.verify_internal_token)],
)


class DocumentPurgeRequest(BaseModel):
    # Owner of the document — scopes the memory purge when supplied.
    user_id: str = ""
    # Used to match memory entries that quote the document by name.
    document_name: str = ""
    # Shared collections to tombstone the document's points out of (the
    # per-document collection is always dropped).
    collection_ids: Optional[List[str]] = None


@router.post("/{document_id}/purge")
async def purge_document(
    document_id: str,
    req: Optional[DocumentPurgeRequest] = Body(default=None),
):
    """Purge every store that holds a copy of a deleted document.

    Returns the per-component report. A component that fails is reported as an
    error (status "partial") instead of failing the request: the document is
    already gone from the backend, and a later retry must be possible.
    """
    service: DocumentPurgeService = document_purge.build_purge_service()
    try:
        result = await service.purge_document(
            document_id,
            user_id=(req.user_id if req else ""),
            document_name=(req.document_name if req else ""),
            collection_ids=(req.collection_ids if req else None),
        )
    finally:
        await service.aclose()
    logger.info(
        "Document purge document_id=%s status=%s errors=%s",
        result.document_id,
        result.status,
        result.errors,
    )

    if result.status == "failed":
        raise HTTPException(
            status_code=400,
            detail={"message": "document_id is required", **result.to_dict()},
        )

    return {"status": result.status, **result.to_dict()}
