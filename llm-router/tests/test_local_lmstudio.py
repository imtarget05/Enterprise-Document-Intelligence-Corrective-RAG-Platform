"""Contract tests for the LocalLMStudioProvider (LM Studio local tier).

2026-09-19: LM Studio (OpenAI-compatible server, ``LOCAL_LMSTUDIO_URL``) is
the DEFAULT local tier ahead of Ollama and Cloudflare. These tests lock the
wire contract that the (previously untested) provider must keep:

  - health probe ``GET {base}/models`` (Bearer auth);
  - chat ``POST {base}/chat/completions`` (OpenAI shape) -> Ollama envelope;
  - streaming OpenAI SSE -> newline-delimited Ollama-compatible JSON;
  - embeddings ``POST {base}/embeddings`` for both single ({'prompt'}) and
    batch ({'input': [...]}) request shapes;
  - disabled (URL unset) / unreachable -> ``is_available()`` False so the
    router falls through (never a silent mid-request fallback);
  - ``LLMRouter`` tier priority: LM Studio before Ollama, and the response
    envelope reports ``provider=local_lmstudio``.
"""

import asyncio
import json

import httpx

from app.config import Settings
from app.models import ChatRequest, RouteDecision, RoutingContext
from app.providers import LocalLMStudioProvider, ProviderError
from app.service import LLMRouter

LM_MODEL = "qwen2.5-vl-3b-instruct"
LM_EMBED_MODEL = "text-embedding-nomic-embed-text-v1.5"
CF_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"

LM_SETTINGS = Settings(
    internal_token="router-test-secret",
    local_lmstudio_url="http://localhost:1234/v1",
    local_lmstudio_model=LM_MODEL,
    local_lmstudio_embed_model=LM_EMBED_MODEL,
    local_lmstudio_api_key="lm-studio",
    cloudflare_chat_model=CF_MODEL,
    cloudflare_timeout_seconds=3.0,
)


def _request(stream: bool = False) -> ChatRequest:
    return ChatRequest(
        messages=[{"role": "user", "content": "xin chao"}],
        stream=stream,
        routing=RoutingContext(task_type="chat", request_id="req-lm-1"),
    )


def _decision() -> RouteDecision:
    return RouteDecision(
        provider="cloudflare",
        model=CF_MODEL,
        reason="test",
        task_type="chat",
    )


def _provider(handler) -> LocalLMStudioProvider:
    return LocalLMStudioProvider(
        LM_SETTINGS, httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def test_lmstudio_disabled_when_url_unset():
    provider = LocalLMStudioProvider(Settings(local_lmstudio_url=""))

    async def run() -> tuple[bool, bool]:
        return provider.enabled, await provider.is_available()

    enabled, available = asyncio.run(run())
    assert enabled is False
    assert available is False


def test_lmstudio_unavailable_when_health_probe_fails():
    def handler(request):
        assert request.url.path == "/v1/models"
        return httpx.Response(503)

    provider = _provider(handler)

    async def run() -> bool:
        return await provider.is_available()

    assert asyncio.run(run()) is False


def test_lmstudio_health_probe_and_chat_translates_to_ollama_shape():
    seen = []

    def handler(request):
        if request.method == "GET":
            assert request.url.path == "/v1/models"
            assert request.headers["authorization"] == "Bearer lm-studio"
            return httpx.Response(200, json={"data": [{"id": LM_MODEL}]})
        seen.append((str(request.url), json.loads(request.content)))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "chao ban"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    provider = _provider(handler)

    async def run():
        assert await provider.is_available() is True
        return await provider.chat(_request(), _decision(), "req-lm-1")

    response = asyncio.run(run())

    url, body = seen[0]
    assert url == "http://localhost:1234/v1/chat/completions"
    assert body["model"] == LM_MODEL
    assert body["stream"] is False
    assert body["messages"][0]["content"] == "xin chao"
    assert response["model"] == LM_MODEL
    assert response["message"]["content"] == "chao ban"
    assert response["done"] is True
    assert response["router"]["request_id"] == "req-lm-1"


def test_lmstudio_stream_parses_openai_sse():
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            text=(
                'data: {"choices":[{"delta":{"content":"Xin "}}]}\n'
                'data: {"choices":[{"delta":{"content":"chao"}}]}\n'
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n'
                "data: [DONE]\n"
            ),
        )

    provider = _provider(handler)

    async def run():
        chunks = []
        async for raw in provider.stream_chat(
            _request(stream=True), _decision(), "req-s"
        ):
            chunks.append(json.loads(raw))
        return chunks

    chunks = asyncio.run(run())

    assert [c["message"]["content"] for c in chunks] == ["Xin ", "chao", ""]
    assert chunks[-1]["done"] is True
    assert all(c["model"] == LM_MODEL for c in chunks)
    assert all(c["router"]["request_id"] == "req-s" for c in chunks)


def test_lmstudio_stream_without_finish_raises_provider_error():
    def handler(request):
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"partial"}}]}\n',
        )

    provider = _provider(handler)

    async def run() -> str | None:
        try:
            async for _ in provider.stream_chat(
                _request(stream=True), _decision(), "req-s"
            ):
                pass
        except ProviderError as exc:
            return str(exc)
        return None

    assert asyncio.run(run()) == "lmstudio_stream_empty"


def test_lmstudio_embeddings_single_and_batch():
    seen = []

    def handler(request):
        assert request.url.path == "/v1/embeddings"
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1, 0.2]},
                    {"embedding": [0.3, 0.4]},
                ]
            },
        )

    provider = _provider(handler)

    async def run():
        single = await provider.embeddings({"prompt": "a"})
        batch = await provider.embeddings({"input": ["a", "b"]})
        return single, batch

    single, batch = asyncio.run(run())

    assert single == {"model": LM_EMBED_MODEL, "embedding": [0.1, 0.2]}
    assert batch == {"model": LM_EMBED_MODEL, "embeddings": [[0.1, 0.2], [0.3, 0.4]]}
    assert seen[0] == {"model": LM_EMBED_MODEL, "input": "a"}
    assert seen[1] == {"model": LM_EMBED_MODEL, "input": ["a", "b"]}


def test_lmstudio_chat_http_error_raises_provider_error():
    def handler(request):
        return httpx.Response(500, text="boom")

    provider = _provider(handler)

    async def run() -> str | None:
        try:
            await provider.chat(_request(), _decision(), "req-lm-1")
        except ProviderError as exc:
            return str(exc)
        return None

    error = asyncio.run(run())
    assert error is not None and error.startswith("lmstudio_error")


def test_router_prefers_lmstudio_over_ollama_and_relabels():
    class FakeOllama:
        async def close(self) -> None:
            pass

        async def is_available(self) -> bool:
            return True

        def model_for_task(self, task_type: str | None) -> str:
            return "qwen2.5:3b"

    class FakeLMStudio:
        async def close(self) -> None:
            pass

        async def is_available(self) -> bool:
            return True

        def model_for_task(self, task_type: str | None) -> str:
            return LM_MODEL

    class FakeCloud:
        async def close(self) -> None:
            pass

    async def run():
        router = LLMRouter(
            LM_SETTINGS,
            providers=FakeCloud(),  # type: ignore[arg-type]
            local=FakeOllama(),  # type: ignore[arg-type]
            lmstudio=FakeLMStudio(),  # type: ignore[arg-type]
        )
        active = await router._active(_request())
        decision = router._relabel_decision(_decision(), active)
        return active, decision

    active, decision = asyncio.run(run())
    assert isinstance(active, FakeLMStudio)
    assert decision.provider == "local_lmstudio"
    assert decision.model == LM_MODEL


def test_embeddings_route_prefers_lmstudio():
    from fastapi.testclient import TestClient

    from app.main import create_app

    class FakeEmbedder:
        def __init__(self, name: str) -> None:
            self.name = name
            self.calls = 0

        async def is_available(self) -> bool:
            return True

        async def embeddings(self, body: dict) -> dict:
            self.calls += 1
            return {"backend": self.name, "prompt": body.get("prompt")}

    class FakeCloud:
        async def embeddings(self, body: dict) -> dict:
            return {"backend": "cloudflare", "prompt": body.get("prompt")}

    class FakeRouter:
        def __init__(self) -> None:
            self.lmstudio = FakeEmbedder("local_lmstudio")
            self.local = FakeEmbedder("local_ollama")
            self.providers = FakeCloud()

        async def close(self) -> None:
            pass

    router = FakeRouter()
    app = create_app(LM_SETTINGS, router=router)  # type: ignore[arg-type]
    with TestClient(app) as client:
        response = client.post(
            "/api/embeddings",
            json={"prompt": "hi"},
            headers={"X-Internal-Token": "router-test-secret"},
        )

    assert response.status_code == 200
    assert response.json()["backend"] == "local_lmstudio"
    assert router.lmstudio.calls == 1
    assert router.local.calls == 0
