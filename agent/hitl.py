"""
Human-in-the-Loop (HITL) approval store — Governance gate for agentic actions.

Any orchestrated action (send_email, create_jira, create_notion,
webhook...) must be approved by a human before it executes. The LangGraph
`hitl_gate` node creates requests and the /agent/approvals endpoints decide
them.

Backends — selected by ``HITL_STORE_BACKEND`` (default ``auto``):
  * ``memory`` — in-process dict with TTL. Local dev / single replica only.
    Pending approvals are LOST on restart and invisible to other replicas.
  * ``redis`` — shared Redis: record key ``hitl:req:{id}`` (JSON + SETEX
    TTL) plus a pending-index set ``hitl:pending`` (drift cleaned lazily on
    read). REQUIRED for multi-replica / production deployments so a pending
    approval survives restarts and is visible to every replica.
  * ``auto`` — Redis when ``REDIS_URL`` is set, otherwise in-memory.

Failure semantics — ``HITL_FAIL_CLOSED`` (default: fail closed everywhere
except local/dev/development/test, same convention as rate_limiter.py):
  * fail-closed → a Redis outage raises :class:`HITLStoreUnavailable`. The
    gate refuses to execute the action and the approvals API answers 503.
    Governance must never silently degrade in production.
  * fail-open → degrade to a per-process in-memory store with a loud error
    log (dev convenience only).

Pause-time snapshots — so APPROVE resumes instead of restarting from
scratch: the gate captures the workflow state via
:func:`encode_workflow_snapshot` and stores it next to the approval
(``hitl:snap:{id}`` in Redis, sidecar dict in memory, same TTL). The
approve endpoint restores whitelisted keys (retrieval results, history,
flags) and only enforces the routing overrides. Missing/undecodable/
oversize snapshots degrade gracefully to the previous fresh-state resume.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from settings import settings

logger = logging.getLogger(__name__)

try:  # redis is optional at import time (minimal / test envs lack it)
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - exercised when redis is missing
    class RedisError(Exception):
        """Fallback so `except RedisError` keeps working without redis installed."""


# ---------------------------------------------------------------------------
# Redis key layout
# ---------------------------------------------------------------------------
_REQUEST_KEY_PREFIX = "hitl:req:"
_PENDING_SET_KEY = "hitl:pending"
_SNAPSHOT_KEY_PREFIX = "hitl:snap:"

# Pause-time snapshots larger than this are skipped (resume falls back to a
# fresh state). Bounds Redis memory when retrieved_chunks are huge.
SNAPSHOT_MAX_BYTES = 256 * 1024

# State keys carried into a resume. Deliberately excludes outputs
# (final_answer/action_result/report_path), governance flags (hitl_*) and
# run metrics — those are rebuilt on the resume path.
_SNAPSHOT_FIELDS = (
    "query",
    "session_id",
    "user_id",
    "document_ids",
    "messages",
    "long_term_history",
    "detected_language",
    "language_instruction",
    "retrieved_chunks",
    "confidence_score",
    "hybrid_search_enabled",
    "agent_plan",
    "agent_type",
    "intent_override",
    "use_web_search",
    "context_summary",
    "ab_config",
    "sources",
    "report_path",
)

# Envs where degrading (fail-open) is acceptable. Mirrors rate_limiter.py.
_PERMISSIVE_ENVS = {"local", "dev", "development", "test"}

_VALID_BACKENDS = {"auto", "redis", "memory"}


class HITLStoreUnavailable(RuntimeError):
    """Raised when the approval store cannot serve a request (fail-closed).

    Callers (LangGraph gate, approvals API) must treat this as "the action
    may NOT execute" — never bypass human approval because the store is down.
    """


def _resolve_fail_closed(explicit: Optional[bool]) -> bool:
    """Explicit HITL_FAIL_CLOSED wins; otherwise derive from APP_ENV."""
    if explicit is not None:
        return explicit
    env = os.getenv("APP_ENV", "production").strip().lower()
    return env not in _PERMISSIVE_ENVS


def _new_record(
    query: str,
    session_id: str,
    user_id: str,
    agent_plan: str = "",
    document_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "request_id": f"hitl-{uuid.uuid4().hex[:12]}",
        "query": query,
        "session_id": session_id,
        "user_id": user_id,
        "agent_plan": agent_plan,
        "document_ids": list(document_ids or []),
        "status": "pending",  # pending | approved | rejected | expired
        "approver": None,
        "note": None,
        "has_snapshot": False,
        "created_at": time.time(),
    }


def _messages_to_dicts(messages: Any) -> Optional[List[Dict[str, Any]]]:
    """Serialize LangChain messages; None when unavailable/unserializable."""
    try:
        from langchain_core.messages import messages_to_dict
    except ImportError:
        return None
    try:
        return messages_to_dict(messages)
    except Exception:
        return None


def encode_workflow_snapshot(state: Any) -> Optional[str]:
    """Serialize pause-time workflow state for approve-time resume.

    Returns a JSON string, or None when the state is not serializable /
    oversize — callers then resume from a fresh state (previous behavior).
    """
    try:
        raw = {k: state[k] for k in _SNAPSHOT_FIELDS if k in state and state[k] is not None}
    except Exception:
        return None
    messages = raw.get("messages")
    if messages:
        try:
            json.dumps(messages)
        except (TypeError, ValueError):
            converted = _messages_to_dicts(messages)
            if converted is None:
                logger.warning("HITL snapshot skipped: messages not serializable")
                return None
            raw["messages"] = converted
    try:
        payload = json.dumps(raw, ensure_ascii=False)
    except (TypeError, ValueError):
        logger.warning("HITL snapshot skipped: state not JSON-serializable")
        return None
    if len(payload.encode("utf-8")) > SNAPSHOT_MAX_BYTES:
        logger.warning(
            "HITL snapshot skipped: %d bytes exceeds %d cap",
            len(payload.encode("utf-8")),
            SNAPSHOT_MAX_BYTES,
        )
        return None
    return payload


def _looks_langchain_serialized(messages: Any) -> bool:
    return (
        isinstance(messages, list)
        and len(messages) > 0
        and isinstance(messages[0], dict)
        and "type" in messages[0]
        and "data" in messages[0]
    )


def decode_workflow_snapshot(payload: Any) -> Optional[Dict[str, Any]]:
    """Restore a snapshot dict; None when missing/corrupt (resume fresh)."""
    if not payload or not isinstance(payload, str):
        return None
    try:
        raw = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        logger.warning("HITL snapshot undecodable — resuming from fresh state")
        return None
    if not isinstance(raw, dict):
        return None
    if _looks_langchain_serialized(raw.get("messages")):
        try:
            from langchain_core.messages import messages_from_dict

            raw["messages"] = messages_from_dict(raw["messages"])
        except Exception:
            logger.warning("HITL snapshot messages unrestorable — dropping messages")
            raw["messages"] = []
    return raw


class HITLStore:
    """In-memory store of pending human-approval requests with TTL expiry."""

    def __init__(self, ttl_seconds: Optional[int] = None):
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.hitl_approval_ttl_seconds
        self._lock = asyncio.Lock()
        self._requests: Dict[str, Dict[str, Any]] = {}
        self._snapshots: Dict[str, Dict[str, Any]] = {}  # rid -> {payload, created_at}

    # ------------------------------------------------------------------
    def _evict_expired(self) -> None:
        now = time.time()
        expired = [
            rid
            for rid, r in self._requests.items()
            if r["status"] == "pending" and now - r["created_at"] > self._ttl
        ]
        for rid in expired:
            self._requests[rid]["status"] = "expired"
            logger.info("HITL request %s expired after %ss", rid, self._ttl)
        stale_snaps = [
            rid
            for rid, s in self._snapshots.items()
            if now - s["created_at"] > self._ttl
        ]
        for rid in stale_snaps:
            del self._snapshots[rid]

    # ------------------------------------------------------------------
    async def create(
        self,
        query: str,
        session_id: str,
        user_id: str,
        agent_plan: str = "",
        document_ids: Optional[List[str]] = None,
        snapshot: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with self._lock:
            self._evict_expired()
            record = _new_record(query, session_id, user_id, agent_plan, document_ids)
            record["has_snapshot"] = snapshot is not None
            self._requests[record["request_id"]] = record
            if snapshot is not None:
                self._snapshots[record["request_id"]] = {
                    "payload": snapshot,
                    "created_at": time.time(),
                }
            logger.info("HITL request created: %s (query=%s)", record["request_id"], query[:80])
            return dict(record)

    # ------------------------------------------------------------------
    async def get(self, request_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            self._evict_expired()
            record = self._requests.get(request_id)
            return dict(record) if record else None

    # ------------------------------------------------------------------
    async def get_snapshot(self, request_id: str) -> Optional[str]:
        """Return the pause-time snapshot payload, or None (resume fresh)."""
        async with self._lock:
            entry = self._snapshots.get(request_id)
            if entry is None:
                return None
            if time.time() - entry["created_at"] > self._ttl:
                del self._snapshots[request_id]
                return None
            return entry["payload"]

    # ------------------------------------------------------------------
    async def decide(
        self, request_id: str, decision: str, approver: str, note: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Mark a pending request approved/rejected. Returns updated record."""
        if decision not in {"approved", "rejected"}:
            raise ValueError(f"Invalid decision: {decision}")
        async with self._lock:
            self._evict_expired()
            record = self._requests.get(request_id)
            if record is None or record["status"] != "pending":
                return None
            record["status"] = decision
            record["approver"] = approver
            record["note"] = note
            self._snapshots.pop(request_id, None)
            logger.info(
                "HITL request %s %s by %s", request_id, decision, approver
            )
            return dict(record)

    # ------------------------------------------------------------------
    async def list_pending(self) -> List[Dict[str, Any]]:
        async with self._lock:
            self._evict_expired()
            return [
                dict(r)
                for r in self._requests.values()
                if r["status"] == "pending"
            ]


class RedisHITLStore:
    """Shared Redis-backed approval store for multi-replica deployments.

    Layout:
      * ``hitl:req:{request_id}`` — JSON record, written with SETEX so Redis
        itself enforces the TTL (no per-process eviction needed).
      * ``hitl:pending`` — SET of request ids used as the queue index.
        Index drift (stale members) is cleaned lazily inside
        :meth:`list_pending`, and decided/expired records are filtered by
        their payload status, so a stale index can never surface a decided
        request as pending.
    """

    def __init__(self, redis_client, ttl_seconds: Optional[int] = None,
                 fail_closed: bool = True) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.hitl_approval_ttl_seconds
        self._fail_closed = fail_closed
        # Fail-open dev fallback (never used when fail_closed=True).
        self._fallback: Optional[HITLStore] = None if fail_closed else HITLStore(ttl_seconds=self._ttl)
        self._fallback_warned = False

    # ------------------------------------------------------------------
    @staticmethod
    def _key(request_id: str) -> str:
        return f"{_REQUEST_KEY_PREFIX}{request_id}"

    @staticmethod
    def _snap_key(request_id: str) -> str:
        return f"{_SNAPSHOT_KEY_PREFIX}{request_id}"

    async def ping(self) -> bool:
        """Health-check helper for /health and startup probes."""
        await self._redis.ping()
        return True

    # ------------------------------------------------------------------
    def _unavailable(self, op: str, exc: Exception) -> HITLStoreUnavailable:
        return HITLStoreUnavailable(
            f"HITL Redis store unreachable during {op}: {exc}. "
            "Action NOT executed (fail-closed governance)."
        )

    async def _degraded(self, op: str, exc: Exception,
                        make_fallback: Callable[[], Any]) -> Any:
        """Fail-closed raise, or (dev only) degrade to in-memory fallback."""
        if self._fail_closed:
            raise self._unavailable(op, exc) from exc
        if not self._fallback_warned:
            logger.error(
                "HITL Redis store unreachable (%s) — degrading to in-memory "
                "fallback (fail-open, dev only). Pending approvals will NOT "
                "sync across replicas or survive restart.",
                exc,
            )
            self._fallback_warned = True
        return await make_fallback()

    # ------------------------------------------------------------------
    async def create(
        self,
        query: str,
        session_id: str,
        user_id: str,
        agent_plan: str = "",
        document_ids: Optional[List[str]] = None,
        snapshot: Optional[str] = None,
    ) -> Dict[str, Any]:
        record = _new_record(query, session_id, user_id, agent_plan, document_ids)
        record["has_snapshot"] = snapshot is not None
        try:
            # Snapshot first: if this write fails nothing observable exists yet
            # (fail-closed raise); a later record-write failure leaves an
            # orphan snapshot that self-expires with the same TTL.
            if snapshot is not None:
                await self._redis.set(
                    self._snap_key(record["request_id"]), snapshot, ex=self._ttl
                )
            await self._redis.set(
                self._key(record["request_id"]),
                json.dumps(record, ensure_ascii=False),
                ex=self._ttl,
            )
            await self._redis.sadd(_PENDING_SET_KEY, record["request_id"])
            logger.info("HITL request created: %s (query=%s)", record["request_id"], query[:80])
            return dict(record)
        except RedisError as exc:
            return await self._degraded(
                "create", exc,
                lambda: self._fallback.create(query, session_id, user_id, agent_plan, document_ids, snapshot=snapshot),
            )

    # ------------------------------------------------------------------
    async def get(self, request_id: str) -> Optional[Dict[str, Any]]:
        try:
            raw = await self._redis.get(self._key(request_id))
            if raw is None:
                return None  # never existed or TTL-expired (Redis auto-evicted)
            try:
                return dict(json.loads(raw))
            except (TypeError, json.JSONDecodeError):
                logger.warning("HITL record %s is not valid JSON — treating as missing", request_id)
                return None
        except RedisError as exc:
            return await self._degraded("get", exc, lambda: self._fallback.get(request_id))

    # ------------------------------------------------------------------
    async def get_snapshot(self, request_id: str) -> Optional[str]:
        """Return the pause-time snapshot payload, or None (resume fresh)."""
        try:
            return await self._redis.get(self._snap_key(request_id))
        except RedisError as exc:
            return await self._degraded(
                "get_snapshot", exc, lambda: self._fallback.get_snapshot(request_id)
            )

    # ------------------------------------------------------------------
    async def decide(
        self, request_id: str, decision: str, approver: str, note: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Mark a pending request approved/rejected. Returns updated record."""
        if decision not in {"approved", "rejected"}:
            raise ValueError(f"Invalid decision: {decision}")
        try:
            raw = await self._redis.get(self._key(request_id))
            if raw is None:
                return None
            try:
                record = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                logger.warning("HITL record %s is not valid JSON — treating as missing", request_id)
                return None
            if record.get("status") != "pending":
                return None
            record["status"] = decision
            record["approver"] = approver
            record["note"] = note
            # Preserve the original expiry window instead of extending it.
            remaining = await self._redis.ttl(self._key(request_id))
            if remaining is not None and remaining <= 0:
                await self._redis.srem(_PENDING_SET_KEY, request_id)
                return None
            await self._redis.set(
                self._key(request_id),
                json.dumps(record, ensure_ascii=False),
                ex=remaining if remaining else self._ttl,
            )
            await self._redis.srem(_PENDING_SET_KEY, request_id)
            # Snapshot cleanup is best-effort: the decision already succeeded,
            # and an orphan snapshot self-expires with its TTL.
            try:
                await self._redis.delete(self._snap_key(request_id))
            except RedisError as snap_exc:
                logger.warning(
                    "HITL snapshot orphan %s (self-expires in %ss): %s",
                    request_id, self._ttl, snap_exc,
                )
            logger.info("HITL request %s %s by %s", request_id, decision, approver)
            return dict(record)
        except RedisError as exc:
            return await self._degraded(
                "decide", exc,
                lambda: self._fallback.decide(request_id, decision, approver, note),
            )

    # ------------------------------------------------------------------
    async def list_pending(self) -> List[Dict[str, Any]]:
        try:
            ids = await self._redis.smembers(_PENDING_SET_KEY)
            if not ids:
                return []
            ids = list(ids)
            raws = await self._redis.mget([self._key(rid) for rid in ids])
            records: List[Dict[str, Any]] = []
            stale: List[str] = []
            for rid, raw in zip(ids, raws):
                if raw is None:
                    stale.append(rid)  # TTL-expired or never existed
                    continue
                try:
                    record = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    stale.append(rid)
                    continue
                if record.get("status") != "pending":
                    stale.append(rid)  # decided elsewhere / already expired
                    continue
                records.append(record)
            if stale:
                await self._redis.srem(_PENDING_SET_KEY, *stale)
            records.sort(key=lambda r: r.get("created_at", 0))
            return [dict(r) for r in records]
        except RedisError as exc:
            return await self._degraded("list_pending", exc, lambda: self._fallback.list_pending())


# ---------------------------------------------------------------------------
# Backend factory — mirrors the RateLimiter auto-select pattern
# ---------------------------------------------------------------------------
def build_hitl_store(cfg=None, redis_client=None):
    """Build the configured HITL store backend.

    ``cfg`` defaults to the global agent settings (``hitl_store_backend``,
    ``redis_url``, ``hitl_approval_ttl_seconds``, ``hitl_fail_closed``).
    ``redis_client`` is injectable for tests.
    """
    cfg = cfg if cfg is not None else settings
    backend = (getattr(cfg, "hitl_store_backend", "auto") or "auto").strip().lower()
    if backend not in _VALID_BACKENDS:
        raise ValueError(
            f"Invalid hitl_store_backend={backend!r} — expected one of {sorted(_VALID_BACKENDS)}"
        )
    ttl = getattr(cfg, "hitl_approval_ttl_seconds", 3600)
    fail_closed = _resolve_fail_closed(getattr(cfg, "hitl_fail_closed", None))
    redis_url = (getattr(cfg, "redis_url", "") or "").strip()

    if backend == "memory":
        logger.info("HITL store: using in-memory backend (single replica only).")
        return HITLStore(ttl_seconds=ttl)

    if not redis_url:
        if backend == "redis":
            raise ValueError("hitl_store_backend='redis' requires REDIS_URL to be set")
        logger.warning(
            "HITL store: REDIS_URL not set — using in-memory backend. "
            "Pending approvals are LOST on restart and NOT shared across replicas. "
            "For production, configure REDIS_URL."
        )
        return HITLStore(ttl_seconds=ttl)

    if redis_client is None:
        try:
            import redis.asyncio as aioredis
        except ImportError as exc:
            msg = (
                "HITL store: REDIS_URL is set but the redis package is not "
                "installed (pip install redis). "
            )
            if fail_closed or backend == "redis":
                raise RuntimeError(msg + "Refusing in-memory fallback (fail-closed).") from exc
            logger.warning(msg + "Falling back to in-memory (fail-open, dev only).")
            return HITLStore(ttl_seconds=ttl)
        redis_client = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=5,
        )
    logger.info(
        "HITL store: using Redis backend (%s, fail_closed=%s)",
        redis_url,
        fail_closed,
    )
    return RedisHITLStore(redis_client, ttl_seconds=ttl, fail_closed=fail_closed)


# Module-level singleton used by the workflow gate and the API endpoints.
hitl_store = build_hitl_store()
