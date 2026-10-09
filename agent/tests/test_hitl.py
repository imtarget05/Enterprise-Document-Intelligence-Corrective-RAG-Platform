"""
Tests for Human-in-the-Loop (HITL) approval gate — Governance layer.

Covers: HITLStore lifecycle (create/get/decide/TTL), the LangGraph hitl_gate
node pausing action runs, conditional routing, and the /agent/approvals API
endpoints (list → approve → execute / reject).
"""

import asyncio
import builtins
import json as _json
import time

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

import hitl as hitl_module
from hitl import (
    HITLStore,
    HITLStoreUnavailable,
    RedisError,
    RedisHITLStore,
    _resolve_fail_closed,
    build_hitl_store,
    decode_workflow_snapshot,
    encode_workflow_snapshot,
)


# ---------------------------------------------------------------------------
# HITLStore unit tests
# ---------------------------------------------------------------------------
@pytest.fixture()
def store():
    return HITLStore(ttl_seconds=60)


def test_create_returns_pending_record(store):
    record = asyncio.run(
        store.create(query="Send report", session_id="s1", user_id="u1", agent_plan="p")
    )
    assert record["request_id"].startswith("hitl-")
    assert record["status"] == "pending"
    assert record["query"] == "Send report"
    assert record["approver"] is None


def test_decide_approves_pending_request(store):
    record = asyncio.run(store.create(query="q", session_id="s", user_id="u"))
    updated = asyncio.run(store.decide(record["request_id"], "approved", "admin@example.com"))
    assert updated["status"] == "approved"
    assert updated["approver"] == "admin@example.com"


def test_decide_rejects_and_cannot_redecide(store):
    record = asyncio.run(store.create(query="q", session_id="s", user_id="u"))
    rid = record["request_id"]
    assert asyncio.run(store.decide(rid, "rejected", "boss"))["status"] == "rejected"
    # Already decided → None (idempotency safety)
    assert asyncio.run(store.decide(rid, "approved", "boss")) is None


def test_decide_invalid_decision_raises(store):
    record = asyncio.run(store.create(query="q", session_id="s", user_id="u"))
    with pytest.raises(ValueError):
        asyncio.run(store.decide(record["request_id"], "maybe", "boss"))


def test_ttl_expiry_moves_request_to_expired():
    store = HITLStore(ttl_seconds=0)
    record = asyncio.run(store.create(query="q", session_id="s", user_id="u"))
    import time

    time.sleep(0.01)
    assert asyncio.run(store.get(record["request_id"]))["status"] == "expired"
    assert asyncio.run(store.list_pending()) == []


def test_list_pending_only_returns_pending(store):
    r1 = asyncio.run(store.create(query="q1", session_id="s", user_id="u"))
    asyncio.run(store.create(query="q2", session_id="s", user_id="u"))
    asyncio.run(store.decide(r1["request_id"], "approved", "boss"))
    pending = asyncio.run(store.list_pending())
    assert len(pending) == 1
    assert pending[0]["query"] == "q2"


# ---------------------------------------------------------------------------
# Workflow gate: action route must pause for approval
# ---------------------------------------------------------------------------
def test_hitl_gate_pauses_without_approval():
    import asyncio

    from graph.workflow import hitl_gate_node, route_after_hitl

    state = {"query": "send email", "session_id": "s", "user_id": "u",
             "agent_plan": "", "document_ids": [], "hitl_auto_approved": False}
    result = asyncio.run(hitl_gate_node(state))
    assert result["hitl_pending"] is True
    assert result["hitl_approval_id"].startswith("hitl-")
    assert result["action_result"]["status"] == "pending_approval"
    assert route_after_hitl(result) == "__end__"


def test_hitl_gate_passes_through_when_auto_approved():
    import asyncio

    from graph.workflow import hitl_gate_node, route_after_hitl

    state = {"query": "send email", "session_id": "s", "user_id": "u",
             "hitl_auto_approved": True}
    result = asyncio.run(hitl_gate_node(state))
    assert result["hitl_pending"] is False
    assert route_after_hitl(result) == "action"


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
def test_approvals_api_list_approve_reject_flow():
    from main import app

    client = TestClient(app)
    # A workflow run that routes to action must pause (mocked sub-agents in CI)
    resp = client.post(
        "/v1/agent/invoke",
        json={"query": "Send the summary to compliance", "session_id": "hitl-s",
              "user_id": "u1", "intent_override": "action"},
    )
    assert resp.status_code == 200
    body = resp.json()

    listing = client.get("/v1/agent/approvals").json()
    assert listing["status"] == "ok"

    pending = listing["pending"]
    if body.get("hitl_pending") or body.get("approval_id") or pending:
        rid = body.get("approval_id") or (pending[0]["request_id"] if pending else None)
        assert rid is not None
        # Detail view
        detail = client.get(f"/v1/agent/approvals/{rid}").json()
        assert detail["request"]["status"] == "pending"
        # Reject → nothing executes
        rej = client.post(
            f"/v1/agent/approvals/{rid}/reject",
            json={"approver": "admin@test", "note": "not now"},
        )
        assert rej.status_code == 200
        assert rej.json()["decision"] == "rejected"
        # Double decision → 404
        assert client.post(
            f"/v1/agent/approvals/{rid}/approve", json={"approver": "admin@test"}
        ).status_code == 404


def test_approvals_404_for_unknown_id():
    from main import app

    client = TestClient(app)
    assert client.get("/v1/agent/approvals/hitl-doesnotexist").status_code == 404
    assert client.post(
        "/v1/agent/approvals/hitl-doesnotexist/approve", json={"approver": "a"}
    ).status_code == 404


# ---------------------------------------------------------------------------
# Redis backend — fakeredis is not installed here, so a minimal fake of
# redis.asyncio (with SETEX expiry semantics) stands in for the client.
# ---------------------------------------------------------------------------
class FakeRedisError(RedisError):
    """Simulated connection failure."""


class FakeAsyncRedis:
    """Minimal in-memory stand-in for redis.asyncio."""

    def __init__(self, down=False):
        self._kv = {}    # key -> (value, expire_at|None)
        self._sets = {}  # key -> set
        self.down = down

    def _check(self):
        if self.down:
            raise FakeRedisError("connection refused (fake)")

    def _purge(self, key):
        val = self._kv.get(key)
        if val is not None:
            _, exp = val
            if exp is not None and time.time() >= exp:
                del self._kv[key]
                return True
        return False

    async def ping(self):
        self._check()
        return True

    async def set(self, key, value, ex=None):
        self._check()
        # NB: ex=0 means "expire immediately" in real Redis (falsy but not None)
        self._kv[key] = (value, time.time() + ex if ex is not None else None)
        return True

    async def get(self, key):
        self._check()
        self._purge(key)
        val = self._kv.get(key)
        return val[0] if val is not None else None

    async def ttl(self, key):
        self._check()
        if self._purge(key) or key not in self._kv:
            return -2
        _, exp = self._kv[key]
        if exp is None:
            return -1
        return max(0, int(exp - time.time()))

    async def delete(self, *keys):
        self._check()
        n = 0
        for k in keys:
            if k in self._kv:
                del self._kv[k]
                n += 1
        return n

    async def sadd(self, key, *members):
        self._check()
        s = self._sets.setdefault(key, set())
        before = len(s)
        s.update(members)
        return len(s) - before

    async def srem(self, key, *members):
        self._check()
        s = self._sets.setdefault(key, set())
        before = len(s)
        for m in members:
            s.discard(m)
        return before - len(s)

    async def smembers(self, key):
        self._check()
        return set(self._sets.get(key, set()))

    async def mget(self, keys):
        self._check()
        return [await self.get(k) for k in keys]


def _redis_store(ttl=60, fail_closed=True, down=False):
    return RedisHITLStore(FakeAsyncRedis(down=down), ttl_seconds=ttl, fail_closed=fail_closed)


def test_redis_store_create_get_decide_flow():
    store = _redis_store()
    record = asyncio.run(store.create(query="q", session_id="s", user_id="u", agent_plan="p"))
    assert record["request_id"].startswith("hitl-")
    assert record["status"] == "pending"

    fetched = asyncio.run(store.get(record["request_id"]))
    assert fetched["query"] == "q"

    updated = asyncio.run(store.decide(record["request_id"], "approved", "boss"))
    assert updated["status"] == "approved"
    assert updated["approver"] == "boss"
    # Decided records stay readable until TTL, but leave the pending queue
    assert asyncio.run(store.get(record["request_id"]))["status"] == "approved"
    assert asyncio.run(store.list_pending()) == []


def test_redis_store_reject_then_no_redecide():
    store = _redis_store()
    record = asyncio.run(store.create(query="q", session_id="s", user_id="u"))
    rid = record["request_id"]
    assert asyncio.run(store.decide(rid, "rejected", "boss"))["status"] == "rejected"
    assert asyncio.run(store.decide(rid, "approved", "boss")) is None


def test_redis_store_decide_invalid_decision_raises():
    store = _redis_store()
    record = asyncio.run(store.create(query="q", session_id="s", user_id="u"))
    with pytest.raises(ValueError):
        asyncio.run(store.decide(record["request_id"], "maybe", "boss"))


def test_redis_store_missing_ids_return_none():
    store = _redis_store()
    assert asyncio.run(store.get("hitl-nope")) is None
    assert asyncio.run(store.decide("hitl-nope", "approved", "boss")) is None


def test_redis_store_ttl_zero_expires_immediately():
    store = _redis_store(ttl=0)
    record = asyncio.run(store.create(query="q", session_id="s", user_id="u"))
    # Redis evicts the key at once; the stale index member is cleaned on read
    assert asyncio.run(store.get(record["request_id"])) is None
    assert asyncio.run(store.list_pending()) == []


def test_redis_store_list_pending_cleans_stale_index():
    fake = FakeAsyncRedis()
    store = RedisHITLStore(fake, ttl_seconds=60, fail_closed=True)
    r1 = asyncio.run(store.create(query="q1", session_id="s", user_id="u"))
    r2 = asyncio.run(store.create(query="q2", session_id="s", user_id="u"))
    # Simulate TTL expiry of r1 + a bogus index member (e.g. manual SADD)
    asyncio.run(fake.delete(f"hitl:req:{r1['request_id']}"))
    asyncio.run(fake.sadd("hitl:pending", "hitl-bogus"))

    pending = asyncio.run(store.list_pending())
    assert [r["request_id"] for r in pending] == [r2["request_id"]]
    # Stale members were purged from the index
    assert asyncio.run(fake.smembers("hitl:pending")) == {r2["request_id"]}


def test_redis_store_fail_closed_raises_on_all_ops():
    store = _redis_store(fail_closed=True, down=True)
    with pytest.raises(HITLStoreUnavailable):
        asyncio.run(store.create(query="q", session_id="s", user_id="u"))
    with pytest.raises(HITLStoreUnavailable):
        asyncio.run(store.get("hitl-x"))
    with pytest.raises(HITLStoreUnavailable):
        asyncio.run(store.decide("hitl-x", "approved", "boss"))
    with pytest.raises(HITLStoreUnavailable):
        asyncio.run(store.list_pending())


def test_redis_store_fail_open_falls_back_to_memory():
    store = _redis_store(fail_closed=False, down=True)
    record = asyncio.run(store.create(query="q", session_id="s", user_id="u"))
    assert record["status"] == "pending"
    assert asyncio.run(store.get(record["request_id"]))["query"] == "q"
    assert asyncio.run(store.decide(record["request_id"], "approved", "boss"))["status"] == "approved"
    assert asyncio.run(store.list_pending()) == []


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------
def _cfg(**overrides):
    base = dict(
        hitl_store_backend="auto",
        redis_url="",
        hitl_approval_ttl_seconds=60,
        hitl_fail_closed=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_store_auto_selects_memory_without_redis_url():
    store = build_hitl_store(_cfg())
    assert isinstance(store, HITLStore)
    assert not isinstance(store, RedisHITLStore)


def test_build_store_explicit_memory_ignores_redis_url():
    store = build_hitl_store(_cfg(hitl_store_backend="memory", redis_url="redis://x:6379/0"))
    assert type(store) is HITLStore


def test_build_store_explicit_redis_requires_url():
    with pytest.raises(ValueError, match="REDIS_URL"):
        build_hitl_store(_cfg(hitl_store_backend="redis", redis_url=""))


def test_build_store_rejects_invalid_backend():
    with pytest.raises(ValueError, match="hitl_store_backend"):
        build_hitl_store(_cfg(hitl_store_backend="bogus"))


def test_build_store_injected_client_skips_redis_package():
    store = build_hitl_store(
        _cfg(redis_url="redis://fake:6379/0"), redis_client=FakeAsyncRedis()
    )
    assert isinstance(store, RedisHITLStore)


def test_build_store_missing_redis_package(monkeypatch):
    real_import = builtins.__import__

    def _no_redis(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "redis" or name.startswith("redis."):
            raise ImportError("No module named 'redis' (test simulation)")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _no_redis)
    cfg = _cfg(redis_url="redis://fake:6379/0", hitl_fail_closed=True)
    with pytest.raises(RuntimeError, match="fail-closed"):
        build_hitl_store(cfg)
    # Fail-open degrades to memory with a warning
    store = build_hitl_store(_cfg(redis_url="redis://fake:6379/0", hitl_fail_closed=False))
    assert type(store) is HITLStore


def test_resolve_fail_closed_explicit_wins(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert _resolve_fail_closed(True) is True
    monkeypatch.setenv("APP_ENV", "local")
    assert _resolve_fail_closed(False) is False


def test_resolve_fail_closed_derives_from_app_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert _resolve_fail_closed(None) is True
    monkeypatch.setenv("APP_ENV", "staging")
    assert _resolve_fail_closed(None) is True
    monkeypatch.setenv("APP_ENV", "local")
    assert _resolve_fail_closed(None) is False
    monkeypatch.setenv("APP_ENV", "test")
    assert _resolve_fail_closed(None) is False


# ---------------------------------------------------------------------------
# Slice 2 — HITL response contract (invoke + stream surfaces hitl fields)
#
# NOTE: TestClient does not run the app lifespan, so state._workflow is None
# (ADK fallback). These tests stub the compiled workflow with the exact dict
# the real hitl_gate pause produces, isolating the chat.py mapping contract.
# ---------------------------------------------------------------------------
class _FakeWorkflow:
    """Stand-in for the compiled LangGraph workflow."""

    def __init__(self, result):
        self._result = result

    async def ainvoke(self, inputs):
        return dict(self._result)


def _paused_action_result(approval_id="hitl-test123"):
    return {
        "final_answer": "⏸ approval needed",
        "agent_type": "action",
        "sources": [],
        "confidence_score": 0.5,
        "action_result": {"hitl": True, "approval_id": approval_id, "status": "pending_approval"},
        "hitl_pending": True,
        "hitl_approval_id": approval_id,
        "report_path": None,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }


def test_invoke_response_exposes_hitl_fields(monkeypatch):
    import state as agent_state
    from main import app

    monkeypatch.setattr(agent_state, "_workflow", _FakeWorkflow(_paused_action_result()))
    client = TestClient(app)
    resp = client.post(
        "/v1/agent/invoke",
        json={"query": "Send the summary to compliance", "session_id": "hitl-s2",
              "user_id": "u1", "intent_override": "action"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["hitl_pending"] is True
    assert body["hitl_approval_id"] == "hitl-test123"


def test_invoke_returns_503_when_store_unavailable(monkeypatch):
    import state as agent_state
    from main import app

    result = _paused_action_result(approval_id=None)
    result["hitl_pending"] = True
    result["hitl_approval_id"] = None
    result["action_result"] = {"hitl": True, "approval_id": None, "status": "store_unavailable"}
    result["final_answer"] = "store down"
    monkeypatch.setattr(agent_state, "_workflow", _FakeWorkflow(result))
    client = TestClient(app)
    resp = client.post(
        "/v1/agent/invoke",
        json={"query": "Send the summary to compliance", "session_id": "hitl-s3",
              "user_id": "u1", "intent_override": "action"},
    )
    assert resp.status_code == 503


def test_stream_complete_event_includes_hitl_fields(monkeypatch):
    import json as _json

    import state as agent_state
    from main import app

    monkeypatch.setattr(agent_state, "_workflow", _FakeWorkflow(_paused_action_result()))
    client = TestClient(app)
    resp = client.post(
        "/v1/agent/invoke-stream",
        json={"query": "Send the summary to compliance", "session_id": "hitl-s4",
              "user_id": "u1", "intent_override": "action"},
    )
    assert resp.status_code == 200
    # Parse the data line that follows the complete event
    lines = resp.text.splitlines()
    payload = None
    for i, line in enumerate(lines):
        if line.strip() == "event: complete" and i + 1 < len(lines):
            data_line = lines[i + 1]
            assert data_line.startswith("data: ")
            payload = _json.loads(data_line[len("data: "):])
    assert payload is not None, "stream must yield a complete event"
    assert payload["hitl_pending"] is True
    assert payload["hitl_approval_id"] == "hitl-test123"
class _DownStore:
    """Store whose every op raises (simulates a Redis outage, fail-closed)."""

    async def create(self, *a, **k):
        raise HITLStoreUnavailable("redis down (fake)")

    async def get(self, *a, **k):
        raise HITLStoreUnavailable("redis down (fake)")

    async def decide(self, *a, **k):
        raise HITLStoreUnavailable("redis down (fake)")

    async def list_pending(self, *a, **k):
        raise HITLStoreUnavailable("redis down (fake)")

    async def get_snapshot(self, *a, **k):
        raise HITLStoreUnavailable("redis down (fake)")


def test_hitl_gate_blocks_action_when_store_unavailable(monkeypatch):
    import graph.workflow as workflow_module
    from graph.workflow import hitl_gate_node, route_after_hitl

    monkeypatch.setattr(workflow_module, "hitl_store", _DownStore())
    state = {"query": "send email", "session_id": "s", "user_id": "u",
             "agent_plan": "", "document_ids": [], "hitl_auto_approved": False}
    result = asyncio.run(hitl_gate_node(state))
    assert result["hitl_pending"] is True
    assert result["hitl_approval_id"] is None
    assert result["action_result"]["status"] == "store_unavailable"
    assert route_after_hitl(result) == "__end__"


def test_approvals_api_returns_503_when_store_unavailable(monkeypatch):
    import routers.hitl as hitl_router_module
    from main import app

    monkeypatch.setattr(hitl_router_module, "hitl_store", _DownStore())
    client = TestClient(app)
    assert client.get("/v1/agent/approvals").status_code == 503
    assert client.get("/v1/agent/approvals/hitl-x").status_code == 503
    assert client.post(
        "/v1/agent/approvals/hitl-x/approve", json={"approver": "a"}
    ).status_code == 503
    assert client.post(
        "/v1/agent/approvals/hitl-x/reject", json={"approver": "a"}
    ).status_code == 503


# ---------------------------------------------------------------------------
# Risk 1 fix — pause-time snapshots: APPROVE resumes instead of restarting
# ---------------------------------------------------------------------------
def test_encode_snapshot_round_trip_with_messages():
    lc = pytest.importorskip("langchain_core.messages")
    state = {
        "query": "send email",
        "session_id": "s",
        "user_id": "u",
        "messages": [lc.HumanMessage(content="hi"), lc.AIMessage(content="ok")],
        "retrieved_chunks": [{"chunk": "c1", "score": 0.9}],
        "agent_plan": "plan",
        "agent_type": "action",
        "use_web_search": True,
        "final_answer": "⏸ paused",
        "action_result": {"hitl": True},
        "hitl_pending": True,
        "hitl_approval_id": "hitl-x",
    }
    payload = encode_workflow_snapshot(state)
    assert isinstance(payload, str)

    restored = decode_workflow_snapshot(payload)
    assert restored["query"] == "send email"
    assert restored["retrieved_chunks"] == [{"chunk": "c1", "score": 0.9}]
    assert restored["use_web_search"] is True
    assert [type(m).__name__ for m in restored["messages"]] == ["HumanMessage", "AIMessage"]
    assert restored["messages"][0].content == "hi"
    # Pause artifacts are rebuilt on resume — never restored
    assert "final_answer" not in restored
    assert "action_result" not in restored
    assert "hitl_pending" not in restored
    assert "hitl_approval_id" not in restored


def test_encode_snapshot_skips_unserializable_state():
    assert encode_workflow_snapshot({"query": "q", "ab_config": {"fn": object()}}) is None
    assert encode_workflow_snapshot(None) is None


def test_encode_snapshot_enforces_size_cap(monkeypatch):
    monkeypatch.setattr(hitl_module, "SNAPSHOT_MAX_BYTES", 32)
    assert encode_workflow_snapshot({"query": "a much longer query than 32 bytes"}) is None


def test_decode_snapshot_invalid_returns_none():
    assert decode_workflow_snapshot(None) is None
    assert decode_workflow_snapshot("") is None
    assert decode_workflow_snapshot("{not json") is None
    assert decode_workflow_snapshot("[1,2]") is None


def test_memory_store_snapshot_lifecycle():
    store = HITLStore(ttl_seconds=60)
    payload = _json.dumps({"retrieved_chunks": [{"chunk": "c"}]})
    record = asyncio.run(
        store.create(query="q", session_id="s", user_id="u", snapshot=payload)
    )
    assert record["has_snapshot"] is True
    assert asyncio.run(store.get_snapshot(record["request_id"])) == payload
    # Queue listings stay light — snapshot lives outside the record
    pending = asyncio.run(store.list_pending())
    assert pending[0]["has_snapshot"] is True
    assert "payload" not in pending[0]
    # Decide drops the snapshot
    asyncio.run(store.decide(record["request_id"], "approved", "boss"))
    assert asyncio.run(store.get_snapshot(record["request_id"])) is None


def test_memory_store_without_snapshot():
    store = HITLStore(ttl_seconds=60)
    record = asyncio.run(store.create(query="q", session_id="s", user_id="u"))
    assert record["has_snapshot"] is False
    assert asyncio.run(store.get_snapshot(record["request_id"])) is None


def test_redis_store_snapshot_lifecycle():
    store = _redis_store()
    payload = _json.dumps({"retrieved_chunks": [{"chunk": "c"}]})
    record = asyncio.run(
        store.create(query="q", session_id="s", user_id="u", snapshot=payload)
    )
    assert record["has_snapshot"] is True
    assert asyncio.run(store.get_snapshot(record["request_id"])) == payload
    asyncio.run(store.decide(record["request_id"], "approved", "boss"))
    assert asyncio.run(store.get_snapshot(record["request_id"])) is None


def test_gate_captures_pause_snapshot(monkeypatch):
    import graph.workflow as workflow_module
    from graph.workflow import hitl_gate_node

    captured = {}

    class _SpyStore(HITLStore):
        async def create(self, *a, **k):
            captured.update(k)
            return await super().create(*a, **k)

    monkeypatch.setattr(workflow_module, "hitl_store", _SpyStore(ttl_seconds=60))
    state = {"query": "send email", "session_id": "s", "user_id": "u",
             "agent_plan": "do it", "document_ids": [], "hitl_auto_approved": False}
    result = asyncio.run(hitl_gate_node(state))
    assert result["hitl_pending"] is True
    assert isinstance(captured.get("snapshot"), str)
    restored = decode_workflow_snapshot(captured["snapshot"])
    assert restored["query"] == "send email"
    assert restored["agent_plan"] == "do it"


class _CapturingWorkflow:
    """Stub workflow that records its invoke input."""

    def __init__(self, result):
        self._result = result
        self.inputs = []

    async def ainvoke(self, inputs):
        self.inputs.append(dict(inputs))
        return dict(self._result)


def test_approve_resumes_from_snapshot(monkeypatch):
    import state as agent_state
    from main import app

    snapshot = _json.dumps({
        "retrieved_chunks": [{"chunk": "snap-chunk", "score": 0.99}],
        "use_web_search": True,
        "agent_plan": "snap plan",
    })
    record = asyncio.run(
        hitl_module.hitl_store.create(
            query="q", session_id="s", user_id="u", agent_plan="snap plan",
            snapshot=snapshot,
        )
    )
    workflow = _CapturingWorkflow({"final_answer": "executed"})
    monkeypatch.setattr(agent_state, "_workflow", workflow)

    client = TestClient(app)
    resp = client.post(
        f"/v1/agent/approvals/{record['request_id']}/approve",
        json={"approver": "boss"},
    )
    assert resp.status_code == 200
    assert len(workflow.inputs) == 1
    resumed = workflow.inputs[0]
    # Pause-time state survived instead of restarting blank
    assert resumed["retrieved_chunks"] == [{"chunk": "snap-chunk", "score": 0.99}]
    assert resumed["use_web_search"] is True
    assert resumed["agent_plan"] == "snap plan"
    # Routing overrides are still enforced
    assert resumed["agent_type"] == "action"
    assert resumed["intent_override"] == "action"
    assert resumed["hitl_auto_approved"] is True


def test_approve_without_snapshot_resumes_fresh(monkeypatch):
    import state as agent_state
    from main import app

    record = asyncio.run(
        hitl_module.hitl_store.create(query="q", session_id="s", user_id="u")
    )
    assert record["has_snapshot"] is False
    workflow = _CapturingWorkflow({"final_answer": "executed"})
    monkeypatch.setattr(agent_state, "_workflow", workflow)

    client = TestClient(app)
    resp = client.post(
        f"/v1/agent/approvals/{record['request_id']}/approve",
        json={"approver": "boss"},
    )
    assert resp.status_code == 200
    resumed = workflow.inputs[0]
    assert resumed["retrieved_chunks"] == []
    assert resumed["messages"] == []
    assert resumed["hitl_auto_approved"] is True
