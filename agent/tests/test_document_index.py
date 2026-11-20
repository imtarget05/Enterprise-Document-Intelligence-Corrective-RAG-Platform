import pytest
from fastapi import HTTPException

from routers.documents import DocumentIndexRequest, index_document


@pytest.mark.asyncio
async def test_index_document_passes_chunks_to_pipeline(monkeypatch):
    captured = {}

    async def fake_index(self, document_id, user_id, title, chunks):
        captured.update(document_id=document_id, user_id=user_id, title=title, chunks=chunks)
        return {"status": "indexed", "document_id": document_id, "chunk_count": len(chunks)}

    from ingestion.pipeline import ConnectorIngestionPipeline
    monkeypatch.setattr(ConnectorIngestionPipeline, "index_backend_document", fake_index)
    result = await index_document("42", DocumentIndexRequest(
        user_id="alice", document_name="facts.txt", chunks=["Paris, France"]
    ))
    assert result["status"] == "indexed"
    assert captured == {"document_id": "42", "user_id": "alice", "title": "facts.txt",
                        "chunks": ["Paris, France"]}


@pytest.mark.asyncio
async def test_index_document_rejects_invalid_id():
    with pytest.raises(HTTPException) as error:
        await index_document("../other", DocumentIndexRequest(
            user_id="alice", document_name="facts.txt", chunks=["Paris, France"]
        ))
    assert error.value.status_code == 400
