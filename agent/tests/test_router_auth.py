import llm_factory
from unittest.mock import AsyncMock
import pytest


def test_router_model_sends_internal_token(monkeypatch):
    monkeypatch.setattr(llm_factory.settings, 'local_lmstudio_url', '')
    monkeypatch.setattr(llm_factory.settings, 'local_ollama_url', '')
    monkeypatch.setattr(llm_factory.settings, 'internal_service_token', 'fixture-token')
    model = llm_factory.LLMFactory.get_model()
    assert model.headers['X-Internal-Token'] == 'fixture-token'


@pytest.mark.asyncio
async def test_embedding_request_sends_internal_token(monkeypatch):
    from tools.qdrant_tool import QdrantHybridSearch
    from settings import settings
    monkeypatch.setattr(settings, 'internal_service_token', 'fixture-token')
    search = object.__new__(QdrantHybridSearch)
    search._embed_url = 'http://router/api/embeddings'
    search._http = AsyncMock()
    response = search._http.post.return_value
    from unittest.mock import Mock
    response.raise_for_status = Mock()
    response.json = Mock(return_value={'embedding': [1.0]})
    await search._embed_inner({'prompt': 'fixture'})
    assert search._http.post.call_args.kwargs['headers']['X-Internal-Token'] == 'fixture-token'
