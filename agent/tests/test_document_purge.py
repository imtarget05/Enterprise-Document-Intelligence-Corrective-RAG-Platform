"""
Phase 2 — document delete must purge every derived artefact.

These tests pin the contract: deleting a document removes its chunks and
embeddings from the vector store, invalidates the retrieval cache entries that
could still serve them, and tombstones the memory entries that reference it.
Vector store / cache / memory are substituted with fakes so the assertions are
about *which components get touched* and with which identifier, not about
Qdrant, Redis or PostgreSQL being up.

The last section goes further and asserts *state* rather than calls: with a
stateful fake Qdrant plus an in-memory cache/memory, the retrieval the agents
actually perform must return nothing for the deleted document, and its cached
answer and memory entries must be gone — the behaviour a user experiences.
"""

import asyncio
import json
from typing import List

import httpx
import pytest

import document_purge
from document_purge import DocumentPurgeService
from memory.graph_memory import GraphMemory
from memory.long_term import LongTermMemory


# ---------------------------------------------------------------------------
# Fakes — each records the calls it receives, one can fail on demand
# ---------------------------------------------------------------------------
class RecordingComponent:
    def __init__(self, name, fail_with=None):
        self.name = name
        self.fail_with = fail_with
        self.calls = []

    async def purge_document(self, document_id, **kwargs):
        self.calls.append({"document_id": document_id, **kwargs})
        if self.fail_with is not None:
            raise RuntimeError(self.fail_with)
        return {"component": self.name, "status": "ok"}


class FakeRedis:
    """Minimal stand-in for the RAG cache client (sets + strings)."""

    def __init__(self):
        self.data = {}
        self.sets = {}

    def setex(self, key, ttl, value):
        self.data[key] = value
        return True

    def get(self, key):
        return self.data.get(key)

    def sadd(self, key, *values):
        self.sets.setdefault(key, set()).update(values)
        return len(values)

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def expire(self, key, ttl):
        return True

    def delete(self, *keys):
        deleted = 0
        for key in keys:
            if key in self.data:
                self.data.pop(key)
                deleted += 1
            if key in self.sets:
                self.sets.pop(key)
                deleted += 1
        return deleted


# ---------------------------------------------------------------------------
# Purge service — which components are touched
# ---------------------------------------------------------------------------
async def test_purge_touches_vector_store_cache_and_memory():
    vector_store = RecordingComponent("vector_store")
    cache = RecordingComponent("cache")
    memory = RecordingComponent("memory")
    graph = RecordingComponent("graph_memory")
    service = DocumentPurgeService(
        vector_store=vector_store, cache=cache, memory=memory, graph_memory=graph
    )

    result = await service.purge_document("doc-42", user_id="alice")

    assert result.status == "ok", result.to_dict()
    assert result.errors == []
    for component in (vector_store, cache, memory, graph):
        assert len(component.calls) == 1, component.name
        assert component.calls[0]["document_id"] == "doc-42"
        assert component.calls[0]["user_id"] == "alice"
    assert [o.component for o in result.outcomes] == [
        "vector_store",
        "cache",
        "memory",
        "graph_memory",
    ]
    assert all(o.status == "ok" for o in result.outcomes)


async def test_purge_forwards_document_name_and_collections():
    vector_store = RecordingComponent("vector_store")
    service = DocumentPurgeService(vector_store=vector_store)

    result = await service.purge_document(
        "doc-42",
        user_id="alice",
        document_name="report.pdf",
        collection_ids=["doc-42", "shared-1"],
    )

    assert result.status == "ok"
    call = vector_store.calls[0]
    assert call["document_name"] == "report.pdf"
    assert call["collection_ids"] == ["doc-42", "shared-1"]


async def test_purge_continues_when_vector_store_fails():
    vector_store = RecordingComponent("vector_store", fail_with="qdrant down")
    cache = RecordingComponent("cache")
    memory = RecordingComponent("memory")
    service = DocumentPurgeService(
        vector_store=vector_store, cache=cache, memory=memory
    )

    result = await service.purge_document("doc-42")

    # A failing store must not stop the remaining components.
    assert len(cache.calls) == 1
    assert len(memory.calls) == 1
    assert result.status == "partial", result.to_dict()
    assert any("qdrant down" in err for err in result.errors)
    failed = [o for o in result.outcomes if o.component == "vector_store"][0]
    assert failed.status == "error"


async def test_purge_rejects_missing_document_id():
    vector_store = RecordingComponent("vector_store")
    service = DocumentPurgeService(vector_store=vector_store)

    result = await service.purge_document("")

    assert result.status == "failed"
    assert vector_store.calls == []
    assert "document_id" in result.errors[0]


async def test_purge_is_reported_skipped_without_components():
    result = await DocumentPurgeService().purge_document("doc-42")

    assert result.status == "skipped"
    assert [o.status for o in result.outcomes] == ["skipped"] * 4
    assert result.errors == []


async def test_purge_repeat_is_idempotent():
    memory = RecordingComponent("memory")
    service = DocumentPurgeService(memory=memory)

    first = await service.purge_document("doc-42")
    second = await service.purge_document("doc-42")

    assert first.status == second.status == "ok"
    assert len(memory.calls) == 2


# ---------------------------------------------------------------------------
# Vector store — Qdrant chunks/embeddings
# ---------------------------------------------------------------------------
async def test_qdrant_delete_drops_document_collection_and_tombstones_shared_points():
    from tools.qdrant_tool import QdrantHybridSearch

    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append((request.method, str(request.url)))
        if request.method == "DELETE":
            return httpx.Response(200, json={"result": True, "status": "ok"})
        return httpx.Response(200, json={"result": {"status": "completed"}})

    searcher = QdrantHybridSearch.__new__(QdrantHybridSearch)
    searcher._base_url = "http://qdrant.test"
    searcher._api_key = ""
    searcher._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        report = await searcher.delete_document(
            "doc-42", collection_ids=["doc-42", "shared-1"]
        )
    finally:
        await searcher._http.aclose()

    # The per-document collection (named after the document id) is dropped.
    assert ("DELETE", "http://qdrant.test/collections/doc-42") in requests_seen
    # A shared collection only loses this document's points.
    delete_points = [
        (method, url)
        for method, url in requests_seen
        if method == "POST" and "/points/delete" in url
    ]
    assert delete_points == [
        ("POST", "http://qdrant.test/collections/shared-1/points/delete?wait=true")
    ]
    assert report["collections_deleted"] == ["doc-42"]
    assert report["errors"] == []


async def test_qdrant_delete_treats_missing_collection_as_success():
    from tools.qdrant_tool import QdrantHybridSearch

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"status": {"error": "Not found"}})

    searcher = QdrantHybridSearch.__new__(QdrantHybridSearch)
    searcher._base_url = "http://qdrant.test"
    searcher._api_key = ""
    searcher._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        report = await searcher.delete_document("doc-42")
    finally:
        await searcher._http.aclose()

    assert report["errors"] == []
    assert report["collections_deleted"] == []


async def test_qdrant_delete_points_filters_on_document_identity():
    from tools.qdrant_tool import QdrantHybridSearch

    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"result": {"status": "completed"}})

    searcher = QdrantHybridSearch.__new__(QdrantHybridSearch)
    searcher._base_url = "http://qdrant.test"
    searcher._api_key = ""
    searcher._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await searcher.delete_document("doc-42", collection_ids=["shared-1"])
    finally:
        await searcher._http.aclose()

    keys = {clause["key"] for clause in bodies[0]["filter"]["should"]}
    assert keys == {"document_name", "external_id", "document_id"}
    values = {clause["match"]["value"] for clause in bodies[0]["filter"]["should"]}
    assert values == {"doc-42"}


# ---------------------------------------------------------------------------
# Retrieval cache — Redis rag_cache entries
# ---------------------------------------------------------------------------
async def test_invalidate_rag_cache_removes_only_that_documents_entries(monkeypatch):
    from tools import qdrant_tool

    fake = FakeRedis()
    monkeypatch.setattr(qdrant_tool, "_redis_client", fake)

    for collection in ("doc-42", "doc-99"):
        key = qdrant_tool._cache_key("what is in it?", collection, 5)
        fake.setex(key, 300, json.dumps([{"text": "chunk"}]))
        fake.sadd(qdrant_tool._cache_index_key(collection), key)

    removed = qdrant_tool.invalidate_rag_cache("doc-42")

    assert removed == 1
    survivor = qdrant_tool._cache_key("what is in it?", "doc-99", 5)
    assert fake.get(survivor) is not None
    assert fake.smembers(qdrant_tool._cache_index_key("doc-42")) == set()
    # Idempotent — a second purge of the same document removes nothing.
    assert qdrant_tool.invalidate_rag_cache("doc-42") == 0


async def test_invalidate_rag_cache_is_noop_without_redis(monkeypatch):
    from tools import qdrant_tool

    monkeypatch.setattr(qdrant_tool, "_redis_client", None)

    assert qdrant_tool.invalidate_rag_cache("doc-42") == 0


async def test_hybrid_search_registers_cache_keys_per_collection(monkeypatch):
    """A cached answer must be discoverable for invalidation after a delete."""
    from tools import qdrant_tool

    fake = FakeRedis()
    monkeypatch.setattr(qdrant_tool, "_redis_client", fake)

    class SemanticOnlySearch:
        async def _semantic_search(self, query, collection_id, top_k):
            return [
                {"text": f"chunk {idx}", "document_name": "doc-42", "chunk_index": idx,
                 "source_type": "document", "source": "", "external_id": "", "score": 0.9}
                for idx in range(3)
            ]

    searcher = SemanticOnlySearch()
    results = await qdrant_tool.QdrantHybridSearch.hybrid_search(
        searcher, "what is in it?", "doc-42", top_k=3, use_bm25=True
    )

    assert results
    cached_key = qdrant_tool._cache_key("what is in it?", "doc-42", 3)
    assert fake.get(cached_key) is not None
    assert cached_key in fake.smembers(qdrant_tool._cache_index_key("doc-42"))
    assert qdrant_tool.invalidate_rag_cache("doc-42") == 1
    assert fake.get(cached_key) is None


# ---------------------------------------------------------------------------
# Memory — long-term facts, conversation turns, graph mentions
# ---------------------------------------------------------------------------
async def test_long_term_memory_purge_removes_referencing_entries():
    memory = LongTermMemory()
    await memory.save_turn("alice", "s1", "user", "Please summarize contract-2024", "rag")
    await memory.save_turn("alice", "s1", "assistant", "contract-2024 has 3 sections", "rag")
    await memory.save_turn("alice", "s1", "user", "what is the weather today", "rag")
    await memory.save_turn("bob", "s2", "user", "contract-2024 is short", "rag")
    await memory.extract_and_store(
        "s1", "alice", [{"role": "user", "content": "I want a summary of contract-2024"}]
    )

    report = await memory.delete_document_memories("7", document_name="contract-2024")

    assert report["turns_deleted"] == 3
    assert report["facts_deleted"] == 1
    # The unrelated turn survives; the document's turns do not.
    history = await memory.get_history("s1", "alice", limit=50)
    assert [t["content"] for t in history] == ["what is the weather today"]
    assert await memory.retrieve("alice") == []


async def test_long_term_memory_purge_matches_bare_document_id():
    memory = LongTermMemory()
    await memory.save_turn("alice", "s1", "user", "Summarize document 7 please", "rag")
    await memory.save_turn("alice", "s1", "user", "Summarize document 70 please", "rag")

    report = await memory.delete_document_memories("7", user_id="alice")

    assert report["turns_deleted"] == 1
    history = await memory.get_history("s1", "alice", limit=50)
    assert [t["content"] for t in history] == ["Summarize document 70 please"]


async def test_long_term_memory_purge_without_reference_is_a_noop():
    memory = LongTermMemory()
    await memory.save_turn("alice", "s1", "user", "what is the weather today", "rag")

    report = await memory.delete_document_memories("7", document_name="missing.txt")

    assert report["turns_deleted"] == 0
    assert report["facts_deleted"] == 0
    assert len(await memory.get_history("s1", "alice", limit=50)) == 1


async def test_graph_memory_purge_removes_document_mentions():
    graph = GraphMemory()
    await graph._store_mention("e1", "s1", 0, "From contract-2024, section 2")
    await graph._store_mention("e2", "s1", 0, "Unrelated conversation context")

    report = await graph.delete_document_mentions("7", document_name="contract-2024")

    assert report["mentions_deleted"] == 1
    assert [m.context_text for m in graph._local_mentions] == [
        "Unrelated conversation context"
    ]


# ---------------------------------------------------------------------------
# End-to-end with the default (real) wiring
# ---------------------------------------------------------------------------
async def test_default_wiring_purges_every_component(monkeypatch):
    purged = []

    class Store:
        async def delete_document(self, document_id, collection_ids=None):
            purged.append(("vector_store", document_id, collection_ids))
            return {"collections_deleted": ["doc-42"]}

    class Cache:
        def invalidate_rag_cache(self, collection_id):
            purged.append(("cache", collection_id))
            return 2

    class Memory:
        async def delete_document_memories(self, document_id, user_id="", document_name=""):
            purged.append(("memory", document_id, user_id))
            return {"facts_deleted": 1, "turns_deleted": 2}

    import tools.qdrant_tool as qdrant_tool

    monkeypatch.setattr(qdrant_tool, "QdrantHybridSearch", Store)
    monkeypatch.setattr(qdrant_tool, "invalidate_rag_cache", Cache().invalidate_rag_cache)
    monkeypatch.setattr(
        document_purge, "LongTermMemory", lambda *a, **k: Memory(), raising=True
    )

    service = document_purge.build_purge_service()
    result = await service.purge_document("doc-42", user_id="alice")

    assert result.status == "ok", result.to_dict()
    assert purged == [
        ("vector_store", "doc-42", None),
        ("cache", "doc-42"),
        ("memory", "doc-42", "alice"),
    ]


# ---------------------------------------------------------------------------
# Component adapters — the real stores, driven through the purge contract
# ---------------------------------------------------------------------------
async def test_rag_cache_invalidator_drops_every_collection_entry(monkeypatch):
    from tools import qdrant_tool

    fake = FakeRedis()
    monkeypatch.setattr(qdrant_tool, "_redis_client", fake)
    for collection in ("doc-42", "shared-1", "doc-99"):
        key = qdrant_tool._cache_key("q", collection, 5)
        fake.setex(key, 300, "[]")
        fake.sadd(qdrant_tool._cache_index_key(collection), key)

    report = await document_purge.RagCacheInvalidator().purge_document(
        "doc-42", collection_ids=["doc-42", "shared-1"]
    )

    assert report == {
        "entries_removed": 2,
        "targets": ["doc-42", "shared-1"],
    }
    assert qdrant_tool.invalidate_rag_cache("doc-99") == 1


async def test_memory_adapters_delegate_with_document_identity():
    long_term_calls = []
    graph_calls = []

    class FakeLongTerm:
        async def delete_document_memories(self, document_id, user_id="", document_name=""):
            long_term_calls.append((document_id, user_id, document_name))
            return {"facts_deleted": 1, "turns_deleted": 1}

    class FakeGraph:
        async def delete_document_mentions(self, document_id, document_name="", user_id=""):
            graph_calls.append((document_id, document_name, user_id))
            return {"mentions_deleted": 2}

    long_term_report = await document_purge.LongTermMemoryPurge(FakeLongTerm()).purge_document(
        "doc-42", user_id="alice", document_name="contract-2024"
    )
    graph_report = await document_purge.GraphMemoryPurge(FakeGraph()).purge_document(
        "doc-42", user_id="alice", document_name="contract-2024"
    )

    assert long_term_report == {"facts_deleted": 1, "turns_deleted": 1}
    assert long_term_calls == [("doc-42", "alice", "contract-2024")]
    assert graph_report == {"mentions_deleted": 2}
    assert graph_calls == [("doc-42", "contract-2024", "alice")]


async def test_vector_store_adapter_passes_collections_through():
    calls = []

    class FakeSearch:
        async def delete_document(self, document_id, collection_ids=None):
            calls.append((document_id, collection_ids))
            return {"collections_deleted": [document_id]}

    await document_purge.QdrantDocumentStore(FakeSearch()).purge_document(
        "doc-42", collection_ids=["shared-1"]
    )

    assert calls == [("doc-42", ["shared-1"])]


async def test_service_aclose_releases_component_resources():
    closed = []

    class Closable:
        async def purge_document(self, document_id, **kwargs):
            return {}

        async def aclose(self):
            closed.append(True)

    service = DocumentPurgeService(vector_store=Closable(), cache=RecordingComponent("cache"))
    await service.purge_document("doc-42")
    await service.aclose()

    assert closed == [True]


# ---------------------------------------------------------------------------
# HTTP contract
# ---------------------------------------------------------------------------
def test_purge_endpoint_requires_internal_token(monkeypatch):
    from fastapi.testclient import TestClient

    import state
    from main import app

    monkeypatch.setattr(state.settings, "app_env", "production")
    monkeypatch.setattr(state.settings, "internal_service_token", "purge-test-secret")
    monkeypatch.setattr(
        document_purge, "build_purge_service", lambda: DocumentPurgeService()
    )

    response = TestClient(app).post("/v1/agent/documents/doc-42/purge")

    assert response.status_code == 401


def test_purge_endpoint_reports_every_component(monkeypatch):
    from fastapi.testclient import TestClient

    import state
    from main import app

    vector_store = RecordingComponent("vector_store")
    cache = RecordingComponent("cache")
    memory = RecordingComponent("memory")
    graph = RecordingComponent("graph_memory")
    monkeypatch.setattr(state.settings, "app_env", "production")
    monkeypatch.setattr(state.settings, "internal_service_token", "purge-test-secret")
    monkeypatch.setattr(
        document_purge,
        "build_purge_service",
        lambda: DocumentPurgeService(
            vector_store=vector_store, cache=cache, memory=memory, graph_memory=graph
        ),
    )

    response = TestClient(app).post(
        "/v1/agent/documents/doc-42/purge",
        json={"user_id": "alice", "document_name": "contract-2024"},
        headers={"X-Internal-Token": "purge-test-secret"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["document_id"] == "doc-42"
    assert [o["component"] for o in body["outcomes"]] == [
        "vector_store",
        "cache",
        "memory",
        "graph_memory",
    ]
    assert vector_store.calls[0]["document_name"] == "contract-2024"


# ---------------------------------------------------------------------------
# Proof — after the delete, retrieval can no longer serve the document
# ---------------------------------------------------------------------------
class FakeQdrant:
    """Stateful in-memory Qdrant: enough REST surface for index + search + delete.

    The fakes above record *calls*; this one records *state*, so a test can
    assert that a deleted document's chunks and embeddings are genuinely gone
    and that the retrieval call the agents actually make now returns nothing.
    """

    def __init__(self):
        self.collections = set()
        self.points: dict = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        parts = [p for p in path.split("/") if p]
        method = request.method

        if path.endswith("/api/embeddings"):
            return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})
        if method == "PUT" and path.endswith("/points"):
            self.points.setdefault(parts[1], []).extend(
                json.loads(request.content).get("points", [])
            )
            return httpx.Response(200, json={"result": {"status": "completed"}})
        if len(parts) >= 2 and parts[0] == "collections" and method == "PUT":
            self.collections.add(parts[1])
            return httpx.Response(200, json={"result": True})
        if method == "DELETE" and len(parts) == 2:
            # Drop the whole collection (chunks + embeddings) — deleting a
            # collection that was never created is not an error.
            existed = parts[1] in self.collections
            self.collections.discard(parts[1])
            self.points.pop(parts[1], None)
            return httpx.Response(200 if existed else 404, json={})
        if path.endswith("/points/delete"):
            needles = {
                clause["match"]["value"]
                for clause in json.loads(request.content)["filter"]["should"]
            }
            kept, dropped = [], 0
            for point in self.points.get(parts[1], []):
                payload = point.get("payload", {})
                if any(str(payload.get(f)) in needles for f in _PAYLOAD_ID_FIELDS):
                    dropped += 1
                else:
                    kept.append(point)
            self.points[parts[1]] = kept
            return httpx.Response(
                200, json={"result": {"status": "completed", "dropped": dropped}}
            )
        if path.endswith("/points/search"):
            results = [
                {"id": p.get("id"), "score": 0.9, "payload": p.get("payload", {})}
                for p in self.points.get(parts[1], [])
            ]
            return httpx.Response(200, json={"result": results})
        return httpx.Response(404, json={"status": {"error": "unhandled"}})


# Payload fields QdrantHybridSearch matches a document on (see
# QdrantHybridSearch._delete_points_by_document).
_PAYLOAD_ID_FIELDS = ("document_id", "external_id", "document_name")


def _fake_searcher(fake: FakeQdrant):
    """A real QdrantHybridSearch over a fake Qdrant — same code path as prod."""
    from tools.qdrant_tool import QdrantHybridSearch

    searcher = QdrantHybridSearch.__new__(QdrantHybridSearch)
    searcher._base_url = "http://qdrant.test"
    searcher._api_key = ""
    searcher._embed_url = "http://qdrant.test/api/embeddings"
    searcher._embed_model = "fake-embed"
    searcher._http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return searcher


async def _index_points(fake: FakeQdrant, collection_id: str, payloads: List[dict]):
    from tools.qdrant_tool import QdrantHybridSearch

    searcher = _fake_searcher(fake)
    try:
        await searcher._request(
            "PUT",
            f"http://qdrant.test/collections/{collection_id}",
            {"vectors": {"size": 3, "distance": "Cosine"}},
        )
        await searcher._request(
            "PUT",
            f"http://qdrant.test/collections/{collection_id}/points",
            {
                "points": [
                    {"id": idx, "vector": [0.1, 0.2, 0.3], "payload": payload}
                    for idx, payload in enumerate(payloads)
                ]
            },
        )
    finally:
        await searcher._http.aclose()


async def test_delete_document_makes_chunks_and_embeddings_unretrievable():
    fake = FakeQdrant()
    searcher = _fake_searcher(fake)
    try:
        await _index_points(
            fake,
            "doc-42",
            [
                {"document_id": "doc-42", "document_name": "contract-2024",
                 "text": "clause 1 termination"},
                {"document_id": "doc-42", "document_name": "contract-2024",
                 "text": "clause 2 liability"},
            ],
        )
        await _index_points(
            fake,
            "shared",
            [{"document_id": "doc-99", "document_name": "other.txt",
              "text": "unrelated content"}],
        )

        # Before the delete the agent can still retrieve the document's chunks.
        assert len(await searcher.hybrid_search("clause", "doc-42")) == 2

        report = await searcher.delete_document("doc-42", collection_ids=["shared"])

        assert report["collections_deleted"] == ["doc-42"]
        assert report["errors"] == []
        # The very same retrieval call — the one the agents make — now returns
        # nothing: the chunks and their embeddings are gone, not merely hidden.
        assert await searcher.hybrid_search("clause", "doc-42") == []
        # Only this document's points went; the shared collection keeps the rest.
        assert [p["payload"]["document_id"] for p in fake.points["shared"]] == ["doc-99"]
    finally:
        await searcher._http.aclose()


async def test_delete_flow_purges_chunks_cache_and_memory(monkeypatch):
    """End-to-end proof over the real component wiring, faked stores.

    Index a document, let a chat answer it (so a retrieval-cache entry and a
    memory entry exist), then run the delete flow and assert that none of
    chunk / cache / memory can serve the document's content any more.
    """
    from tools import qdrant_tool

    fake = FakeQdrant()
    searcher = _fake_searcher(fake)
    fake_redis = FakeRedis()
    monkeypatch.setattr(qdrant_tool, "_redis_client", fake_redis)

    await _index_points(
        fake,
        "doc-42",
        [
            {"document_id": "doc-42", "document_name": "contract-2024",
             "text": "clause 1 termination"},
            {"document_id": "doc-42", "document_name": "contract-2024",
             "text": "clause 2 liability"},
            {"document_id": "doc-42", "document_name": "contract-2024",
             "text": "clause 3 payment"},
        ],
    )
    # A turn and a long-term fact that quote the document, plus one that does not.
    memory = LongTermMemory()
    await memory.save_turn("alice", "s1", "user", "Summarize contract-2024 for me", "rag")
    await memory.save_turn("alice", "s1", "assistant", "contract-2024 has 1 clause", "rag")
    await memory.save_turn("alice", "s1", "user", "what is the weather today", "rag")
    await memory.extract_and_store(
        "s1", "alice", [{"role": "user", "content": "I want a summary of contract-2024"}]
    )
    graph = GraphMemory()
    await graph._store_mention("e1", "s1", 0, "From contract-2024, section 1")
    await graph._store_mention("e2", "s1", 0, "Unrelated conversation context")

    # The chat path populates the retrieval cache before anything is deleted.
    assert await searcher.hybrid_search("clause", "doc-42", top_k=3)
    cached_key = qdrant_tool._cache_key("clause", "doc-42", 3)
    assert fake_redis.get(cached_key) is not None

    service = DocumentPurgeService(
        vector_store=document_purge.QdrantDocumentStore(searcher),
        cache=document_purge.RagCacheInvalidator(),
        memory=document_purge.LongTermMemoryPurge(memory),
        graph_memory=document_purge.GraphMemoryPurge(graph),
    )
    try:
        result = await service.purge_document(
            "doc-42", user_id="alice", document_name="contract-2024"
        )
    finally:
        await service.aclose()

    assert result.status == "ok", result.to_dict()
    details = {o.component: o.detail for o in result.outcomes}
    assert details["memory"] == {"facts_deleted": 1, "turns_deleted": 2, "backend": "memory"}
    assert details["graph_memory"] == {"mentions_deleted": 1, "backend": "memory"}
    # Chunks + embeddings: gone from the vector store.
    assert fake.collections == set()
    assert await searcher.hybrid_search("clause", "doc-42") == []
    # Retrieval cache: the entry that could still answer from those chunks is gone.
    assert fake_redis.get(cached_key) is None
    assert fake_redis.smembers(qdrant_tool._cache_index_key("doc-42")) == set()
    # Memory: only the entries that reference the document are tombstoned.
    assert [t["content"] for t in await memory.get_history("s1", "alice", limit=50)] == [
        "what is the weather today"
    ]
    assert await memory.retrieve("alice") == []
    assert [m.context_text for m in graph._local_mentions] == [
        "Unrelated conversation context"
    ]


def test_purge_endpoint_rejects_missing_document_id(monkeypatch):
    from fastapi.testclient import TestClient

    import state
    from main import app

    monkeypatch.setattr(state.settings, "app_env", "production")
    monkeypatch.setattr(state.settings, "internal_service_token", "purge-test-secret")
    monkeypatch.setattr(
        document_purge, "build_purge_service", lambda: DocumentPurgeService()
    )

    response = TestClient(app).post(
        "/v1/agent/documents/%20/purge", headers={"X-Internal-Token": "purge-test-secret"}
    )

    assert response.status_code == 400
