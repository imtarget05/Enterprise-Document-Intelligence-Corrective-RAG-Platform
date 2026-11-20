"""
Shared connector ingestion pipeline.

Flow:
  external source -> raw text -> chunks -> embeddings -> Qdrant collection.
"""

import hashlib
import logging
import re
from typing import Any, Dict, Iterable, List

import httpx

from settings import settings

logger = logging.getLogger(__name__)


RawConnectorDocument = Dict[str, Any]


def _safe_collection_part(value: str, max_len: int = 48) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_").lower()
    return (safe or "item")[:max_len]


class ConnectorIngestionPipeline:
    """Chunk, embed, and index raw connector documents into Qdrant."""

    def __init__(self) -> None:
        self._qdrant_url = f"http://{settings.qdrant_host}:{settings.qdrant_port}"
        if settings.local_ollama_url:
            self._embed_url = f"{settings.local_ollama_url.rstrip('/')}/api/embeddings"
            self._embed_model = settings.local_ollama_embed_model
        else:
            self._embed_url = f"{settings.llm_base_url.rstrip('/')}/api/embeddings"
            self._embed_model = settings.llm_embedding_model

    async def index_backend_document(
        self, document_id: str, user_id: str, title: str, chunks: List[str]
    ) -> Dict[str, Any]:
        """Index owner-checked Spring chunks under the numeric document ID."""
        if not document_id.isdecimal() or not user_id or not chunks:
            raise ValueError("document_id, user_id and nonempty chunks are required")
        if len(chunks) > 200 or any(not c.strip() or len(c) > 12_000 for c in chunks):
            raise ValueError("chunks exceed the local indexing limits")
        async with httpx.AsyncClient(timeout=60) as client:
            vectors = await self._embed_chunks(client, chunks)
            if len(vectors) != len(chunks):
                raise RuntimeError("embedding count does not match chunk count")
            headers = self._qdrant_headers()
            # Reindexing a replaced document removes stale trailing points.
            existing = await client.get(f"{self._qdrant_url}/collections/{document_id}", headers=headers)
            if existing.status_code == 200:
                deleted = await client.delete(f"{self._qdrant_url}/collections/{document_id}", headers=headers)
                deleted.raise_for_status()
            elif existing.status_code != 404:
                existing.raise_for_status()
            await self._create_collection(client, document_id, len(vectors[0]))
            await self._upsert_chunks(client, document_id, chunks, vectors, user_id,
                                      "spring_upload", document_id, title, {})
        return {"status": "indexed", "document_id": document_id, "chunk_count": len(chunks)}

    async def ingest_documents(
        self,
        user_id: str,
        documents: Iterable[RawConnectorDocument],
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=60) as client:
            for doc in documents:
                results.append(await self._ingest_one(client, user_id, doc))
        return results

    async def _ingest_one(
        self,
        client: httpx.AsyncClient,
        user_id: str,
        doc: RawConnectorDocument,
    ) -> Dict[str, Any]:
        source = str(doc.get("source") or "connector")
        external_id = str(
            doc.get("external_id") or doc.get("id") or doc.get("title") or "item"
        )
        title = str(doc.get("title") or doc.get("document_name") or external_id)
        text = self._normalize_text(str(doc.get("text") or ""))
        metadata = dict(doc.get("metadata") or {})

        base_result = {
            "source": source,
            "external_id": external_id,
            "document_name": title,
            "text_length": len(text),
            "chunk_count": 0,
            "collection_id": None,
            "status": "skipped",
        }

        if not text:
            base_result["reason"] = "empty_text"
            return base_result

        chunks = self._chunk_text(
            text,
            chunk_size=getattr(settings, "connector_chunk_size", 1200),
            overlap=getattr(settings, "connector_chunk_overlap", 180),
        )
        if not chunks:
            base_result["reason"] = "no_chunks"
            return base_result

        try:
            embeddings = await self._embed_chunks(client, chunks)
            if len(embeddings) != len(chunks):
                raise RuntimeError("embedding count does not match chunk count")

            collection_id = self._collection_id(user_id, source, external_id)
            await self._create_collection(client, collection_id, len(embeddings[0]))
            await self._upsert_chunks(
                client=client,
                collection_id=collection_id,
                chunks=chunks,
                embeddings=embeddings,
                user_id=user_id,
                source=source,
                external_id=external_id,
                title=title,
                metadata=metadata,
            )
        except Exception as exc:
            logger.exception(
                "Connector ingestion failed for %s:%s", source, external_id
            )
            base_result["status"] = "failed"
            base_result["reason"] = str(exc)
            return base_result

        base_result.update(
            {
                "status": "indexed",
                "chunk_count": len(chunks),
                "collection_id": collection_id,
            }
        )
        logger.info(
            "Indexed connector document source=%s external_id=%s collection=%s chunks=%d",
            source,
            external_id,
            collection_id,
            len(chunks),
        )
        return base_result

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 1200, overlap: int = 180) -> List[str]:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        overlap = max(0, min(overlap, chunk_size // 2))

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        chunks: List[str] = []
        current = ""

        for paragraph in paragraphs or [text]:
            if len(paragraph) > chunk_size:
                if current:
                    chunks.append(current.strip())
                    current = ""
                start = 0
                while start < len(paragraph):
                    piece = paragraph[start : start + chunk_size].strip()
                    if piece:
                        chunks.append(piece)
                    if start + chunk_size >= len(paragraph):
                        break
                    start += chunk_size - overlap
                continue

            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                chunks.append(current.strip())
                tail = current[-overlap:].strip() if overlap and current else ""
                current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph

        if current:
            chunks.append(current.strip())

        return [chunk for chunk in chunks if chunk]

    async def _embed_chunks(
        self, client: httpx.AsyncClient, chunks: List[str]
    ) -> List[List[float]]:
        embeddings: List[List[float]] = []
        for chunk in chunks:
            resp = await client.post(
                self._embed_url,
                json={"model": self._embed_model, "prompt": chunk},
            )
            resp.raise_for_status()
            vector = resp.json().get("embedding") or []
            if not vector:
                raise RuntimeError("empty embedding returned")
            embeddings.append([float(v) for v in vector])
        return embeddings

    async def _create_collection(
        self,
        client: httpx.AsyncClient,
        collection_id: str,
        vector_size: int,
    ) -> None:
        headers = self._qdrant_headers()
        payload = {"vectors": {"size": vector_size, "distance": "Cosine"}}
        resp = await client.put(
            f"{self._qdrant_url}/collections/{collection_id}",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()

    async def _upsert_chunks(
        self,
        client: httpx.AsyncClient,
        collection_id: str,
        chunks: List[str],
        embeddings: List[List[float]],
        user_id: str,
        source: str,
        external_id: str,
        title: str,
        metadata: Dict[str, Any],
    ) -> None:
        points = []
        for idx, (chunk, vector) in enumerate(zip(chunks, embeddings)):
            payload = {
                "text": chunk,
                "chunk_index": idx,
                "document_name": title,
                "source_type": "document" if source == "spring_upload" else "connector",
                "source": source,
                "user_id": user_id,
                "external_id": external_id,
                "metadata": metadata,
            }
            points.append({"id": idx, "vector": vector, "payload": payload})

        headers = self._qdrant_headers()
        batch_size = 64
        for start in range(0, len(points), batch_size):
            resp = await client.put(
                f"{self._qdrant_url}/collections/{collection_id}/points",
                json={"points": points[start : start + batch_size]},
                headers=headers,
            )
            resp.raise_for_status()

    @staticmethod
    def _collection_id(user_id: str, source: str, external_id: str) -> str:
        digest = hashlib.sha1(
            f"{user_id}:{source}:{external_id}".encode("utf-8")
        ).hexdigest()[:12]
        return f"conn_{_safe_collection_part(source, 24)}_{digest}"

    @staticmethod
    def _qdrant_headers() -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if settings.qdrant_api_key:
            headers["api-key"] = settings.qdrant_api_key
        return headers
