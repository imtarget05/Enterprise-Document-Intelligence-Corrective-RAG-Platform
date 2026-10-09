"""
Qdrant Hybrid Search Tool - Phase 1.

Combines:
  1. Semantic search  - Qdrant cosine similarity via @cf/baai/bge-base-en-v1.5 embeddings
  2. BM25 keyword     - rank-bm25 scored against the semantic result subset
  3. RRF fusion       - Reciprocal Rank Fusion merges both ranked lists

The combined score is more robust than either approach alone,
especially for short/keyword-heavy queries.

Scalability note (issue #16):
    BM25 is applied ONLY to the semantic search results (top_k * 3), NOT to
    the entire corpus. This keeps the BM25 step O(m) where m = top_k * 3,
    making it safe for corpora > 100k chunks. For a full-corpus BM25 search,
    use a dedicated BM25 backend (e.g., Elasticsearch/OpenSearch) or Qdrant's
    built-in sparse vector support.
"""

import hashlib
import json

from memory.context_trim import CHUNK_CHARS, truncate


def defensive_truncate_chunk(chunk: dict, max_chars: int = CHUNK_CHARS) -> dict:
    """WP2 defensive truncate: page/payload text cứng đầu từ Qdrant bị capped,
    chunk gốc không bị mutate."""
    c2 = dict(chunk)
    if "text" in c2 and isinstance(c2["text"], str):
        c2["text"] = truncate(c2["text"], max_chars)
    if "page_content" in c2 and isinstance(c2["page_content"], str):
        c2["page_content"] = truncate(c2["page_content"], max_chars)
    return c2
import logging
import time
from typing import Any, Dict, List, Optional

import httpx
from rank_bm25 import BM25Okapi
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log

from settings import settings

logger = logging.getLogger(__name__)

# ── Simple circuit breaker for Qdrant (no extra dependency) ──
class _CircuitBreaker:
    def __init__(self, name: str, fail_max: int = 5, reset_timeout: float = 30.0):
        self.name = name
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self._failures = 0
        self._state = "closed"  # closed | open | half_open
        self._opened_at: Optional[float] = None

    def _emit(self):
        try:
            from metrics import circuit_breaker_state
            m = {"closed": 0, "half_open": 1, "open": 2}.get(self._state, 0)
            circuit_breaker_state.labels(agent_id=self.name).set(m)
        except Exception:
            pass

    def can_execute(self) -> bool:
        if self._state == "closed":
            return True
        if self._state == "open":
            if time.monotonic() - (self._opened_at or 0) >= self.reset_timeout:
                self._state = "half_open"
                self._emit()
                return True
            return False
        return True  # half_open: allow one trial

    def record_success(self):
        self._failures = 0
        if self._state != "closed":
            self._state = "closed"
            self._emit()

    def record_failure(self):
        self._failures += 1
        try:
            from metrics import circuit_breaker_failures
            circuit_breaker_failures.labels(agent_id=self.name).inc()
        except Exception:
            pass
        if self._state == "half_open" or self._failures >= self.fail_max:
            self._state = "open"
            self._opened_at = time.monotonic()
            self._emit()
            logger.warning("Circuit breaker OPEN for %s after %d failures", self.name, self._failures)

_qdrant_breaker = _CircuitBreaker("qdrant", fail_max=5, reset_timeout=30)
_embed_breaker = _CircuitBreaker("qdrant_embed", fail_max=5, reset_timeout=30)

# Optional Redis cache for RAG queries.
# Issue #48: Previously, a Redis import failure was silently swallowed and
# _redis_client was set to None with no log. Now we log a warning so operators
# know caching is disabled.
_redis_client = None
if getattr(settings, "redis_url", None):
    try:
        import redis

        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        logger.info("RAG Redis cache enabled: %s", settings.redis_url)
    except ImportError:
        logger.warning(
            "redis package not installed - RAG query caching disabled. "
            "Install with: pip install redis"
        )
    except Exception as exc:
        logger.warning(
            "RAG Redis cache init failed (%s) - caching disabled. "
            "Queries will hit Qdrant directly.",
            exc,
        )
else:
    logger.info("REDIS_URL not set - RAG query caching disabled.")


def _cache_key(query: str, collection_id: str, top_k: int) -> str:
    h = hashlib.sha256(f"{query}:{collection_id}:{top_k}".encode()).hexdigest()[:16]
    return f"rag_cache:{h}"


def _cache_index_key(collection_id: str) -> str:
    """Reverse index of the cache keys written for a collection.

    Cache keys are hashes of (query, collection, top_k), so a document delete
    cannot recompute them. Every write registers its key here, which makes a
    document's cache entries discoverable — and therefore invalidatable.
    """
    return f"rag_cache_idx:{collection_id}"


def invalidate_rag_cache(collection_id: str) -> int:
    """Drop every cached retrieval result for a document/collection.

    Returns the number of cache entries removed (0 when Redis is disabled or
    nothing was cached). Best-effort: a Redis failure leaves a stale entry that
    is still bounded by its TTL, so it is logged and reported as 0 instead of
    failing the caller.
    """
    if not _redis_client or not collection_id:
        return 0
    try:
        index_key = _cache_index_key(collection_id)
        keys = list(_redis_client.smembers(index_key) or [])
        deleted = int(_redis_client.delete(*keys)) if keys else 0
        _redis_client.delete(index_key)
        if deleted:
            logger.info(
                "Invalidated %d RAG cache entries for collection %s",
                deleted,
                collection_id,
            )
        return deleted
    except Exception as exc:
        logger.warning(
            "RAG cache invalidation failed for collection %s: %s", collection_id, exc
        )
        return 0


def _tokenize(text: str) -> List[str]:
    """Simple whitespace + lower-case tokeniser for BM25."""
    return text.lower().split()


def _rrf_score(rank: int, k: int) -> float:
    """Reciprocal Rank Fusion score."""
    return 1.0 / (k + rank + 1)


class QdrantHybridSearch:
    """Async Qdrant wrapper with hybrid BM25 + semantic search."""

    def __init__(self):
        host = settings.qdrant_host.strip()
        if host.startswith("http://") or host.startswith("https://"):
            self._base_url = host.rstrip("/")
        else:
            use_https = (
                getattr(settings, "qdrant_use_https", False)
                or settings.qdrant_port == 443
                or "cloud.qdrant.io" in host
            )
            proto = "https" if use_https else "http"
            self._base_url = f"{proto}://{host}:{settings.qdrant_port}"
        self._api_key = settings.qdrant_api_key
        self._embed_url = f"{settings.llm_base_url}/api/embeddings"
        self._embed_model = settings.llm_embedding_model
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def hybrid_search(
        self,
        query: str,
        collection_id: str,
        top_k: int = 5,
        use_bm25: bool = True,
        rrf_k: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        Returns a list of chunk dicts sorted by hybrid score (descending).
        Each dict has keys: text, document_name, score, chunk_index.

        rrf_k controls the RRF constant: higher values = more weight to BM25 ranking.
        """
        # Try Redis cache first
        cache_ttl = getattr(settings, "rag_cache_ttl_sec", 300)
        if _redis_client:
            try:
                ck = _cache_key(query, collection_id, top_k)
                cached = _redis_client.get(ck)
                if cached:
                    logger.debug("RAG cache hit for query: %s", query[:40])
                    return json.loads(cached)
            except Exception as exc:
                logger.warning("RAG cache read failed: %s", exc)

        # 1. Semantic search via Qdrant
        semantic_results = await self._semantic_search(
            query, collection_id, top_k=top_k * 3
        )
        if not semantic_results:
            return []

        if not use_bm25 or len(semantic_results) <= 2:
            return semantic_results[:top_k]

        # 2. BM25 on the semantic result corpus (avoid extra Qdrant scroll)
        # NOTE: This is O(m) where m = len(semantic_results) = top_k * 3, NOT O(n)
        # over the full corpus. Safe for large corpora (issue #16).
        corpus = [r["text"] for r in semantic_results]
        bm25 = BM25Okapi([_tokenize(t) for t in corpus])
        bm25_scores = bm25.get_scores(_tokenize(query))

        # 3. RRF fusion
        # Build rank maps
        semantic_ranks = {r["text"]: i for i, r in enumerate(semantic_results)}
        bm25_indexed = sorted(enumerate(bm25_scores), key=lambda x: x[1], reverse=True)
        bm25_ranks = {
            semantic_results[i]["text"]: rank
            for rank, (i, _) in enumerate(bm25_indexed)
        }

        fused: Dict[str, float] = {}
        for chunk in semantic_results:
            text = chunk["text"]
            sem_rank = semantic_ranks.get(text, len(semantic_results))
            bm25_rank = bm25_ranks.get(text, len(semantic_results))
            fused[text] = _rrf_score(sem_rank, rrf_k) + _rrf_score(bm25_rank, rrf_k)

        # 4. Re-sort by fused score and normalise
        max_fused = max(fused.values()) or 1.0
        results_out: List[Dict[str, Any]] = []
        for chunk in semantic_results:
            merged = dict(chunk)
            merged["score"] = fused.get(chunk["text"], 0.0) / max_fused
            results_out.append(merged)

        results_out.sort(key=lambda x: x["score"], reverse=True)
        final = results_out[:top_k]

        # Write to Redis cache
        if _redis_client:
            try:
                ck = _cache_key(query, collection_id, top_k)
                _redis_client.setex(ck, cache_ttl, json.dumps(final))
                # Phase 2: register the key so a document delete can find it.
                _redis_client.sadd(_cache_index_key(collection_id), ck)
                _redis_client.expire(_cache_index_key(collection_id), cache_ttl)
            except Exception as exc:
                logger.warning("RAG cache write failed: %s", exc)

        return final

    # ------------------------------------------------------------------
    # Semantic search — with retry + circuit breaker
    # ------------------------------------------------------------------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError)),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
        reraise=True,
    )
    async def _semantic_search_inner(
        self, url: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        resp = await self._http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def _semantic_search(
        self, query: str, collection_id: str, top_k: int
    ) -> List[Dict[str, Any]]:
        if not _qdrant_breaker.can_execute():
            logger.warning("Qdrant circuit OPEN — skipping search for %s", collection_id)
            return []
        vector = await self._embed(query)
        if not vector:
            return []

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["api-key"] = self._api_key

        payload = {
            "vector": vector,
            "limit": top_k,
            "with_payload": True,
        }
        url = f"{self._base_url}/collections/{collection_id}/points/search"
        try:
            data = await self._semantic_search_inner(url, payload, headers)
            points = data.get("result", [])
            _qdrant_breaker.record_success()
        except Exception as exc:
            _qdrant_breaker.record_failure()
            logger.warning(
                "Qdrant search failed for collection %s: %s", collection_id, exc
            )
            return []

        results = []
        for p in points:
            pl = p.get("payload", {})
            results.append(
                defensive_truncate_chunk(
                    {
                        "text": pl.get("text", ""),
                        "document_name": pl.get("document_name", collection_id),
                        "chunk_index": pl.get("chunk_index", 0),
                        "source_type": pl.get("source_type", "document"),
                        "source": pl.get("source", ""),
                        "external_id": pl.get("external_id", ""),
                        "score": p.get("score", 0.0),
                    }
                )
            )
        return results

    # ------------------------------------------------------------------
    # Delete — best-effort: failures are reported, never raised
    # ------------------------------------------------------------------
    async def _request(
        self, method: str, url: str, payload: Optional[Dict[str, Any]] = None
    ) -> httpx.Response:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["api-key"] = self._api_key
        return await self._http.request(method, url, json=payload, headers=headers)

    async def aclose(self) -> None:
        """Close the shared HTTP connection pool."""
        await self._http.aclose()

    async def delete_document(
        self,
        document_id: str,
        collection_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Remove a deleted document's chunks and embeddings from Qdrant.

        Two shapes exist in this service:
          * the per-document collection named after the document id (agent
            retrieval uses document ids as collection names) — dropped whole,
            because it holds nothing but that document;
          * shared collections carrying the document in the point payload
            (connector ingestion writes source/external_id/document_name) —
            only this document's points are deleted (tombstone), leaving the
            other documents' points in place.

        Never raises: a missing collection (404) is not an error, and a failure
        is reported in the "errors" list so the purge of the remaining stores
        can continue. Returns a report dict.
        """
        report: Dict[str, Any] = {
            "document_id": document_id,
            "collections_deleted": [],
            "points_deleted": [],
            "errors": [],
        }
        if not document_id:
            report["errors"].append("document_id is required")
            return report

        shared = [c for c in (collection_ids or []) if c != document_id]

        try:
            resp = await self._request(
                "DELETE", f"{self._base_url}/collections/{document_id}"
            )
            if resp.status_code == 404:
                logger.info("Qdrant collection %s already absent", document_id)
            else:
                resp.raise_for_status()
                report["collections_deleted"].append(document_id)
        except Exception as exc:
            report["errors"].append(f"collection {document_id}: {exc}")
            logger.warning(
                "Qdrant collection delete failed for document %s: %s", document_id, exc
            )

        for collection_id in shared:
            try:
                status = await self._delete_points_by_document(
                    collection_id, document_id
                )
                report["points_deleted"].append(
                    {"collection_id": collection_id, "status": status}
                )
            except Exception as exc:
                report["errors"].append(f"points {collection_id}: {exc}")
                logger.warning(
                    "Qdrant point delete failed for document %s in %s: %s",
                    document_id,
                    collection_id,
                    exc,
                )

        return report

    async def _delete_points_by_document(
        self, collection_id: str, document_id: str
    ) -> str:
        """Delete only the points belonging to a document (match on payload).

        Returns Qdrant's acknowledgement status; a 404 (collection absent) is
        reported as "not_found" rather than raised.
        """
        payload = {
            "filter": {
                "should": [
                    {"key": "document_id", "match": {"value": document_id}},
                    {"key": "external_id", "match": {"value": document_id}},
                    {"key": "document_name", "match": {"value": document_id}},
                ]
            }
        }
        url = f"{self._base_url}/collections/{collection_id}/points/delete"
        resp = await self._request("POST", f"{url}?wait=true", payload)
        if resp.status_code == 404:
            return "not_found"
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {}) if isinstance(data, dict) else {}
        return str((result or {}).get("status", "unknown"))

    # ------------------------------------------------------------------
    # Embedding — with retry + circuit breaker
    # ------------------------------------------------------------------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError)),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
        reraise=True,
    )
    async def _embed_inner(self, payload: Dict[str, Any]):
        resp = await self._http.post(self._embed_url, json=payload)
        resp.raise_for_status()
        return resp.json()

    async def _embed(self, text: str) -> Optional[List[float]]:
        if not _embed_breaker.can_execute():
            logger.warning("Embedding circuit OPEN — skipping embed")
            return None
        try:
            data = await self._embed_inner({"model": self._embed_model, "prompt": text})
            _embed_breaker.record_success()
            return data.get("embedding", [])
        except Exception as exc:
            _embed_breaker.record_failure()
            logger.error("Embedding failed: %s", exc)
            return None
