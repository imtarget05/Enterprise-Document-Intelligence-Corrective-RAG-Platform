import pytest


@pytest.mark.asyncio
async def test_qdrant_search_uses_local_ollama_embedding_model(monkeypatch):
    from settings import settings
    from tools.qdrant_tool import QdrantHybridSearch

    monkeypatch.setattr(settings, "local_ollama_url", "http://localhost:11434/")
    monkeypatch.setattr(settings, "local_ollama_embed_model", "nomic-embed-text")
    search = QdrantHybridSearch()
    try:
        assert search._embed_url == "http://localhost:11434/api/embeddings"
        assert search._embed_model == "nomic-embed-text"
    finally:
        await search.aclose()


@pytest.mark.asyncio
async def test_qdrant_search_uses_router_without_local_ollama(monkeypatch):
    from settings import settings
    from tools.qdrant_tool import QdrantHybridSearch

    monkeypatch.setattr(settings, "local_ollama_url", "")
    monkeypatch.setattr(settings, "llm_base_url", "http://llm-router:8000/")
    monkeypatch.setattr(settings, "llm_embedding_model", "router-embed")
    search = QdrantHybridSearch()
    try:
        assert search._embed_url == "http://llm-router:8000/api/embeddings"
        assert search._embed_model == "router-embed"
    finally:
        await search.aclose()
