"""WP3-T1 (TDD RED): local LLM concurrency limit.

RED tests — they MUST FAIL until WP3-T2+ implements:
  - app.providers.LocalProviderBusyError
  - LocalOllamaProvider._sem / chat_with_slot (Semaphore max 2)
  - app.service fallback to cloudflare on busy (non-CONFIDENTIAL)

Do NOT touch app/ in this task.
"""

import asyncio
from typing import Any

from app.config import Settings
from app.models import ChatRequest, RouteDecision, RoutingContext
from app.providers import LocalOllamaProvider, LocalProviderBusyError, ProviderError
from app.service import LLMRouter

MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"


def _settings() -> Settings:
    return Settings(
        cloudflare_chat_model=MODEL,
        cloudflare_timeout_seconds=3.0,
        internal_token="router-test-secret",
    )


def _request(classification: str = "internal") -> ChatRequest:
    return ChatRequest(
        messages=[{"role": "user", "content": "hello local"}],
        routing=RoutingContext(classification=classification, request_id="req-busy-1"),
    )


def _decision() -> RouteDecision:
    return RouteDecision(
        provider="local_ollama",
        model="qwen2.5:3b",
        reason="test",
        task_type="chat",
    )


def test_5_concurrent_max_2_running():
    """5 concurrent chat_with_slot calls: at most 2 run at the same time."""
    settings = _settings()
    provider = LocalOllamaProvider(settings)
    running = 0
    max_running = 0

    async def fake_chat(
        request: ChatRequest, decision: RouteDecision, request_id: str
    ) -> dict[str, Any]:
        nonlocal running, max_running
        running += 1
        max_running = max(max_running, running)
        await asyncio.sleep(0.05)
        running -= 1
        return {
            "model": decision.model,
            "message": {"role": "assistant", "content": "ok"},
            "done": True,
        }

    async def run() -> list[dict[str, Any]]:
        provider.chat = fake_chat  # type: ignore[method-assign]
        return await asyncio.gather(
            *[provider.chat_with_slot(_request(), _decision(), f"r{i}") for i in range(5)]
        )

    results = asyncio.run(run())
    assert len(results) == 5
    assert all(r["done"] for r in results)
    assert max_running <= 2, f"expected max 2 concurrent, saw {max_running}"


def test_busy_timeout_raises_LocalProviderBusyError():
    """With both slots occupied, the next call raises LocalProviderBusyError fast."""
    settings = _settings()
    provider = LocalOllamaProvider(settings)
    entered = 0
    entered_evt = asyncio.Event()
    release_evt = asyncio.Event()

    async def blocking_chat(
        request: ChatRequest, decision: RouteDecision, request_id: str
    ) -> dict[str, Any]:
        nonlocal entered
        entered += 1
        if entered >= 2:
            entered_evt.set()
        await release_evt.wait()
        return {
            "model": decision.model,
            "message": {"role": "assistant", "content": "ok"},
            "done": True,
        }

    async def run() -> None:
        provider.chat = blocking_chat  # type: ignore[method-assign]
        t1 = asyncio.create_task(provider.chat_with_slot(_request(), _decision(), "r1"))
        t2 = asyncio.create_task(provider.chat_with_slot(_request(), _decision(), "r2"))
        await asyncio.wait_for(entered_evt.wait(), timeout=5)
        try:
            await asyncio.wait_for(
                provider.chat_with_slot(_request(), _decision(), "busy"), timeout=5
            )
            raise AssertionError("expected LocalProviderBusyError")
        except LocalProviderBusyError:
            pass
        finally:
            release_evt.set()
            await asyncio.gather(t1, t2)

    asyncio.run(run())


def test_busy_fallback_to_cloudflare_only_for_public():
    """WP3 chốt lại: LOCAL busy → CHỈ classification PUBLIC được fallback cloud."""

    class BusyLocal:
        async def close(self) -> None:
            pass

        async def is_available(self) -> bool:
            return True

        async def chat_with_slot(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise LocalProviderBusyError("local busy")

        async def chat(
            self, request: ChatRequest, decision: RouteDecision, request_id: str
        ) -> dict[str, Any]:
            return {
                "model": "local-should-not-win",
                "message": {"role": "assistant", "content": "local"},
                "done": True,
            }

        async def stream_chat(self, *args: Any, **kwargs: Any):  # pragma: no cover
            raise NotImplementedError
            yield b""

    class CloudFake:
        def __init__(self) -> None:
            self.calls = 0

        async def close(self) -> None:
            pass

        async def chat(
            self, request: ChatRequest, decision: RouteDecision, request_id: str
        ) -> dict[str, Any]:
            self.calls += 1
            return {
                "model": decision.model,
                "message": {"role": "assistant", "content": "cloud fallback"},
                "done": True,
                "router": {
                    "provider": "cloudflare",
                    "model": decision.model,
                    "reason": decision.reason,
                    "task_type": decision.task_type,
                    "request_id": request_id,
                },
            }

        async def stream_chat(self, *args: Any, **kwargs: Any):  # pragma: no cover
            raise NotImplementedError
            yield b""

    async def run() -> tuple[CloudFake, dict[str, Any]]:
        cloud = CloudFake()
        router = LLMRouter(_settings(), providers=cloud, local=BusyLocal())  # type: ignore[arg-type]
        return cloud, await router.chat(_request(classification="public"))

    cloud, response = asyncio.run(run())
    assert cloud.calls == 1, "expected exactly one cloudflare fallback call"
    assert response["message"]["content"] == "cloud fallback"


def test_service_confidential_busy_forbidden():
    """Local busy + CONFIDENTIAL doc -> policy_violation, cloud NEVER called."""

    class BusyLocal:
        async def close(self) -> None:
            pass

        async def is_available(self) -> bool:
            return True

        async def chat_with_slot(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise LocalProviderBusyError("local busy")

    class CloudMustNotRun:
        def __init__(self) -> None:
            self.calls = 0

        async def close(self) -> None:
            pass

        async def chat(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            return {"model": "cloud", "message": {"role": "assistant", "content": "cloud"}, "done": True}

    async def run() -> tuple[int, ProviderError | None]:
        cloud = CloudMustNotRun()
        router = LLMRouter(_settings(), providers=cloud, local=BusyLocal())  # type: ignore[arg-type]
        try:
            await router.chat(_request(classification="confidential"))
        except ProviderError as exc:
            return cloud.calls, exc
        return cloud.calls, None

    calls, exc = asyncio.run(run())
    assert calls == 0, "CONFIDENTIAL must never fall back to cloud"
    assert exc is not None and str(exc).startswith("policy_violation")


def test_busy_internal_no_fallback_busy_surfaces():
    """WP3 chốt lại: LOCAL busy + INTERNAL (không phải PUBLIC) → KHÔNG fallback
    cloud; LocalProviderBusyError lộ ra ngoài để main map 503 + Retry-After."""

    class BusyLocal:
        async def close(self) -> None:
            pass

        async def is_available(self) -> bool:
            return True

        async def chat_with_slot(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise LocalProviderBusyError("local busy")

    class CloudMustNotRun:
        def __init__(self) -> None:
            self.calls = 0

        async def close(self) -> None:
            pass

        async def chat(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            return {"model": "cloud", "message": {"role": "assistant", "content": "cloud"}, "done": True}

    async def run() -> tuple[int, LocalProviderBusyError | None]:
        cloud = CloudMustNotRun()
        router = LLMRouter(_settings(), providers=cloud, local=BusyLocal())  # type: ignore[arg-type]
        try:
            await router.chat(_request(classification="internal"))
        except LocalProviderBusyError as exc:
            return cloud.calls, exc
        return cloud.calls, None

    calls, exc = asyncio.run(run())
    assert calls == 0, "INTERNAL busy must NOT fall back to cloud"
    assert exc is not None, "busy phải lộ ra ngoài để main map 503 + Retry-After"


def test_main_busy_maps_503_retry_after():
    """Busy surfacing past the service (no fallback path) maps to 503 + Retry-After."""

    from fastapi.testclient import TestClient

    from app.main import create_app

    class AlwaysBusyRouter:
        async def close(self) -> None:
            pass

        async def chat(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise LocalProviderBusyError("local busy")

        async def stream_chat(self, *args: Any, **kwargs: Any):  # pragma: no cover
            raise NotImplementedError
            yield b""

    app = create_app(_settings(), router=AlwaysBusyRouter())  # type: ignore[arg-type]
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Internal-Token": "router-test-secret"},
        )
        assert r.status_code == 503
        assert "retry-after" in {k.lower() for k in r.headers}
        assert r.headers["retry-after"] == "2"

