"""
Document purge — Phase 2.

Deleting a document must delete every artefact derived from it, not only the
metadata row. A deleted document must never keep serving chunks or answers, so
this module removes, in one call:

  * the vector store points (chunks + embeddings) — Qdrant;
  * the retrieval cache entries that could still answer from those chunks —
    Redis ``rag_cache``;
  * the memory entries that reference the document — long-term facts,
    conversation turns and graph mentions (PostgreSQL, in-memory fallback).

Ownership: the backend owns the document row, the chunks stored in PostgreSQL
and the storage blob; this service (agent) owns the vector store, the retrieval
cache and the memory. Each component is isolated and best-effort: a store that
is down is reported as an error and never blocks the purge of the others, and
every call is reported so the caller (and the tests) can see exactly which
stores were touched.

Component protocol (all optional, all async)::

    async def purge_document(self, document_id, *, user_id="", document_name="",
                             collection_ids=None) -> dict
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from memory.graph_memory import GraphMemory
from memory.long_term import LongTermMemory

logger = logging.getLogger(__name__)

COMPONENT_ORDER = ("vector_store", "cache", "memory", "graph_memory")


@dataclass
class PurgeOutcome:
    """Result of purging one component."""

    component: str
    status: str  # "ok" | "error" | "skipped"
    detail: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component,
            "status": self.status,
            "detail": self.detail,
            "error": self.error,
        }


@dataclass
class PurgeResult:
    """Aggregate report for one document purge."""

    document_id: str
    user_id: str = ""
    status: str = "ok"  # "ok" | "partial" | "failed" | "skipped"
    outcomes: List[PurgeOutcome] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "user_id": self.user_id,
            "status": self.status,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "errors": self.errors,
        }


class QdrantDocumentStore:
    """Vector-store component: drops a document's chunks/embeddings from Qdrant."""

    def __init__(self, search: Any = None):
        self._search = search

    @property
    def _searcher(self) -> Any:
        if self._search is None:
            from tools.qdrant_tool import QdrantHybridSearch

            self._search = QdrantHybridSearch()
        return self._search

    async def purge_document(
        self,
        document_id: str,
        user_id: str = "",
        document_name: str = "",
        collection_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return await self._searcher.delete_document(
            document_id, collection_ids=collection_ids
        )

    async def aclose(self) -> None:
        """Release the Qdrant HTTP connection pool."""
        closer = getattr(self._search, "aclose", None)
        if closer is not None:
            await closer()


class RagCacheInvalidator:
    """Retrieval-cache component: drops cached answers for the document."""

    async def purge_document(
        self,
        document_id: str,
        user_id: str = "",
        document_name: str = "",
        collection_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        from tools import qdrant_tool

        targets = [document_id] + [c for c in (collection_ids or []) if c != document_id]
        removed = sum(qdrant_tool.invalidate_rag_cache(target) for target in targets)
        return {"entries_removed": removed, "targets": targets}


class LongTermMemoryPurge:
    """Memory component: tombstones facts/turns that reference the document."""

    def __init__(self, memory: Any = None):
        self._memory = memory

    @property
    def _store(self) -> Any:
        if self._memory is None:
            self._memory = LongTermMemory()
        return self._memory

    async def purge_document(
        self,
        document_id: str,
        user_id: str = "",
        document_name: str = "",
        collection_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return await self._store.delete_document_memories(
            document_id, user_id=user_id, document_name=document_name
        )


class GraphMemoryPurge:
    """Graph-memory component: tombstones mentions that quote the document."""

    def __init__(self, memory: Any = None):
        self._memory = memory

    @property
    def _store(self) -> Any:
        if self._memory is None:
            self._memory = GraphMemory()
        return self._memory

    async def purge_document(
        self,
        document_id: str,
        user_id: str = "",
        document_name: str = "",
        collection_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return await self._store.delete_document_mentions(
            document_id, document_name=document_name, user_id=user_id
        )


class DocumentPurgeService:
    """Purge every store that holds a copy of a document's content.

    Components are injected so tests can substitute fakes; a component that is
    not configured is reported as "skipped" instead of failing the purge.
    """

    def __init__(
        self,
        vector_store: Any = None,
        cache: Any = None,
        memory: Any = None,
        graph_memory: Any = None,
    ):
        self._components: Dict[str, Any] = {
            "vector_store": vector_store,
            "cache": cache,
            "memory": memory,
            "graph_memory": graph_memory,
        }

    @classmethod
    def with_defaults(
        cls, long_term_memory: Any = None, graph_memory: Any = None
    ) -> "DocumentPurgeService":
        """Wire the real stores; each degrades when its backend is disabled."""
        return cls(
            vector_store=QdrantDocumentStore(),
            cache=RagCacheInvalidator(),
            memory=LongTermMemoryPurge(long_term_memory),
            graph_memory=GraphMemoryPurge(graph_memory),
        )

    async def purge_document(
        self,
        document_id: str,
        user_id: str = "",
        document_name: str = "",
        collection_ids: Optional[List[str]] = None,
    ) -> PurgeResult:
        document_id = str(document_id or "").strip()
        if not document_id:
            return PurgeResult(
                document_id="",
                user_id=user_id,
                status="failed",
                errors=["document_id is required"],
            )

        result = PurgeResult(document_id=document_id, user_id=user_id)
        for name in COMPONENT_ORDER:
            component = self._components.get(name)
            if component is None:
                result.outcomes.append(
                    PurgeOutcome(component=name, status="skipped")
                )
                continue
            try:
                detail = await component.purge_document(
                    document_id,
                    user_id=user_id,
                    document_name=document_name,
                    collection_ids=collection_ids,
                )
            except Exception as exc:  # best-effort: never block the delete
                logger.warning("Document purge failed for %s (%s): %s", document_id, name, exc)
                result.outcomes.append(
                    PurgeOutcome(component=name, status="error", error=str(exc))
                )
                result.errors.append(f"{name}: {exc}")
                continue
            result.outcomes.append(
                PurgeOutcome(
                    component=name,
                    status="ok",
                    detail=detail if isinstance(detail, dict) else {"result": detail},
                )
            )

        executed = [o for o in result.outcomes if o.status != "skipped"]
        if not executed:
            result.status = "skipped"
        elif any(o.status == "error" for o in executed):
            result.status = (
                "failed" if all(o.status == "error" for o in executed) else "partial"
            )
        return result

    async def aclose(self) -> None:
        """Release resources held by the wired components (HTTP connection pools)."""
        for component in self._components.values():
            closer = getattr(component, "aclose", None)
            if closer is None:
                continue
            try:
                await closer()
            except Exception as exc:  # closing must never fail a purge
                logger.debug("Purge component close failed: %s", exc)


def build_purge_service() -> DocumentPurgeService:
    """Service used by the HTTP route; reuses the app singletons when started."""
    import state

    return DocumentPurgeService.with_defaults(
        long_term_memory=state._long_term_memory,
        graph_memory=state._graph_memory,
    )
