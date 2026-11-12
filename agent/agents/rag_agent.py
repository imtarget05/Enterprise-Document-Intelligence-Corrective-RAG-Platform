"""
RAG Agent - Phase 1 enhanced RAG pipeline.

Improvements over the basic Java implementation:
  1. Hybrid search:  semantic (Qdrant cosine) + BM25 keyword scoring -> RRF fusion
  2. Cross-encoder reranking:  re-score top-k with a prompted LLM judge
     NOTE (issue #17): The LLM-based reranker adds 10-20s latency. For production,
     replace with a dedicated reranker model (e.g., bge-reranker-v2-m3, jina-reranker-v2).
     Set RERANKER_MODEL env var to use a local reranker when available.
  3. Multi-doc reasoning:      synthesise answer across several documents
  4. Citation tracking:        every answer carries structured source citations
  5. Corrective CRAG loop:     query reformulation + parallel re-retrieval on low confidence
     NOTE (issue #18): CONFIDENCE_THRESHOLD is now configurable via CRAG_CONFIDENCE_THRESHOLD
     env var. Default 0.6 is empirical; benchmark with A/B testing before production tuning.
"""

import asyncio
import logging
import os
import re
from typing import Dict, List, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from llm_factory import LLMFactory
from graph.state import AgentState
from memory.short_term import ShortTermMemory
from memory.long_term import LongTermMemory
from memory.context_summarizer import ContextSummarizer
from memory.context_trim import cap_chunks, trim_messages
from memory.language_handler import detect_language, get_language_instruction
from settings import settings
from tools.qdrant_tool import QdrantHybridSearch
from prompts import render_prompt, PromptNotFoundError

logger = logging.getLogger(__name__)

CRAG_CONFIDENCE_THRESHOLD = float(os.getenv("CRAG_CONFIDENCE_THRESHOLD", "0.6"))
TOP_K = 5
LTM_EXTRACT_INTERVAL = 5

RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

MAX_REFORMULATIONS = int(os.getenv("CRAG_MAX_REFORMULATIONS", "2"))


class RagAgent:
    def __init__(self):
        self._llm = LLMFactory.get_reasoning_model(temperature=settings.llm_temperature)
        self._search = QdrantHybridSearch()
        self._memory = ShortTermMemory()
        self._long_term_memory = LongTermMemory(llm_router=self._llm)
        self._summarizer = ContextSummarizer(llm_router=self._llm)
        self._turn_counters: dict = {}
        self._reranker = self._init_reranker()

    def _resolve_config(self, state: AgentState) -> dict:
        """Resolve A/B variant config from state, falling back to defaults."""
        ab_config = state.get("ab_config", {})
        return {
            "top_k": ab_config.get("top_k", TOP_K),
            "confidence_threshold": ab_config.get(
                "confidence_threshold", CRAG_CONFIDENCE_THRESHOLD
            ),
            "hybrid": state.get("hybrid_search_enabled", True),
            "rrf_k": ab_config.get("rrf_k", 60),
            "max_reformulations": ab_config.get("max_reformulations", MAX_REFORMULATIONS),
        }

    def _get_top_k(self, state: AgentState) -> int:
        return self._resolve_config(state)["top_k"]

    def _get_confidence_threshold(self, state: AgentState) -> float:
        return self._resolve_config(state)["confidence_threshold"]

    def _init_reranker(self):
        """Initialize a dedicated reranker model if configured (issue #17)."""
        if not RERANKER_MODEL:
            return None
        try:
            from sentence_transformers import CrossEncoder

            reranker = CrossEncoder(RERANKER_MODEL)
            logger.info("Dedicated reranker loaded: %s", RERANKER_MODEL)
            return reranker
        except ImportError:
            logger.warning(
                "RERANKER_MODEL set to '%s' but sentence-transformers not installed. "
                "Falling back to LLM-based reranking. Install with: pip install sentence-transformers",
                RERANKER_MODEL,
            )
        except Exception as exc:
            logger.warning(
                "Failed to load reranker model '%s': %s. Falling back to LLM reranking.",
                RERANKER_MODEL,
                exc,
            )
        return None

    async def run(self, state: AgentState) -> AgentState:
        query = state["query"]
        document_ids = state.get("document_ids") or []
        session_id = state["session_id"]
        user_id = state.get("user_id", session_id)
        cfg = self._resolve_config(state)
        hybrid = cfg["hybrid"]
        variant_id = state.get("ab_config", {}).get("variant_id", "none")

        logger.info(
            "RAG Agent: query=%s docs=%s hybrid=%s variant=%s top_k=%s rrf_k=%s",
            query[:80],
            document_ids,
            hybrid,
            variant_id,
            cfg["top_k"],
            cfg["rrf_k"],
        )

        detected_lang, lang_instruction = (
            detect_language(query),
            get_language_instruction(detect_language(query)),
        )
        state["detected_language"] = detected_lang
        state["language_instruction"] = lang_instruction
        logger.info("Detected language: %s", detected_lang)

        await self._long_term_memory.ensure_table()
        long_term_facts = await self._long_term_memory.retrieve(user_id)
        ltm_context = ""
        if long_term_facts:
            ltm_parts = [
                f"- {f.fact_text} (importance: {f.importance:.1f})"
                for f in long_term_facts
            ]
            ltm_context = "\n".join(ltm_parts)
            logger.info(
                "Loaded %d long-term facts for user %s", len(long_term_facts), user_id
            )

        recent_history = trim_messages(self._memory.get_recent(session_id, turns=10))
        # WP2: dùng đúng return của compress (list of {role, content}) —
        # bản compressed này là history đã sát, không phình prompt.
        compressed_history = await self._summarizer.compress(session_id, recent_history)
        context_summary = self._summarizer.get_summary(session_id)
        state["context_summary"] = context_summary

        chunks, max_score = await self._retrieve(query, document_ids, hybrid, cfg)
        state["confidence_score"] = max_score

        if max_score < cfg["confidence_threshold"]:
            logger.info(
                "Low confidence %.2f < %.2f - starting CRAG loop",
                max_score,
                cfg["confidence_threshold"],
            )
            chunks, max_score = await self._crag_loop(query, document_ids, hybrid, cfg, cfg["max_reformulations"])
            state["confidence_score"] = max_score

        if chunks:
            chunks = await self._rerank(query, chunks)
            # WP2: cap top_k=5 × 1200 chars trước khi vào prompt/state.
            chunks = cap_chunks(chunks, top_k=cfg.get("top_k", TOP_K))

        if chunks and max_score >= cfg["confidence_threshold"]:
            answer = await self._generate_answer(
                query,
                chunks,
                session_id,
                state.get("long_term_history", []),
                lang_instruction,
                ltm_context,
                context_summary,
            )
        elif state.get("use_web_search"):
            answer = await self._web_search_fallback(query)
            chunks = []
        else:
            answer = await self._deep_reasoning_fallback(query)
            chunks = []

        sources = [
            {
                "document_name": c.get("document_name", "unknown"),
                "chunk_text": c.get("text", "")[:300],
                "score": round(c.get("score", 0.0), 4),
                "source_type": c.get("source_type", "document"),
            }
            for c in chunks[: cfg["top_k"]]
        ]

        self._memory.add(session_id, "user", query)
        self._memory.add(session_id, "assistant", answer)

        self._turn_counters[session_id] = self._turn_counters.get(session_id, 0) + 1
        if self._turn_counters[session_id] % LTM_EXTRACT_INTERVAL == 0:
            full_history = self._memory.get_recent(
                session_id, turns=LTM_EXTRACT_INTERVAL
            )
            await self._long_term_memory.extract_and_store(
                session_id, user_id, full_history
            )

        state["final_answer"] = answer
        state["sources"] = sources
        state["retrieved_chunks"] = chunks
        state["agent_type"] = "rag"
        return state

    async def _retrieve(
        self, query: str, document_ids: List[str], hybrid: bool, cfg: dict = None
    ) -> Tuple[List[Dict], float]:
        if not document_ids:
            return [], 0.0
        top_k = (cfg or {}).get("top_k", TOP_K)
        rrf_k = (cfg or {}).get("rrf_k", 60)

        tasks = [
            self._search.hybrid_search(
                query, doc_id, top_k=top_k, use_bm25=hybrid, rrf_k=rrf_k
            )
            for doc_id in document_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_chunks: List[Dict] = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Retrieval task failed: %s", r)
                continue
            all_chunks.extend(r)

        seen: Dict[str, Dict] = {}
        for c in all_chunks:
            key = c.get("text", "").strip()[:200]
            if key not in seen or seen[key]["score"] < c["score"]:
                seen[key] = c
        deduped = sorted(seen.values(), key=lambda x: x["score"], reverse=True)

        max_score = deduped[0]["score"] if deduped else 0.0
        return deduped, max_score

    async def _crag_loop(
        self, query: str, document_ids: List[str], hybrid: bool, cfg: dict = None,
        max_reformulations: int = 2
    ) -> Tuple[List[Dict], float]:
        """Iteratively reformulate and re-retrieve until confidence is high enough."""
        merged: Dict[str, Dict] = {}
        best_score = 0.0
        current_query = query

        for iteration in range(max_reformulations + 1):
            variants = []
            if iteration > 0:
                variants = await self._reformulate_query(current_query)
                if not variants:
                    logger.info("CRAG loop: no more reformulations produced at iteration %d", iteration)
                    break
                all_queries = [current_query] + variants
                logger.info("CRAG loop iteration %d: reformulated into %d variants", iteration, len(variants))
            else:
                all_queries = [current_query]

            tasks = [self._retrieve(q, document_ids, hybrid, cfg) for q in all_queries]
            all_results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in all_results:
                if isinstance(res, Exception):
                    continue
                chunks, score = res
                if score > best_score:
                    best_score = score
                for c in chunks:
                    key = c.get("text", "").strip()[:200]
                    if key not in merged or merged[key]["score"] < c["score"]:
                        merged[key] = c

            confidence_threshold = (cfg or {}).get("confidence_threshold", CRAG_CONFIDENCE_THRESHOLD)
            if best_score >= confidence_threshold:
                logger.info("CRAG loop: confidence %.2f >= threshold %.2f at iteration %d — stopping",
                            best_score, confidence_threshold, iteration)
                break

            if iteration < max_reformulations:
                current_query = variants[0] if variants else current_query

        final = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        logger.info("CRAG loop completed: %d iterations used, best score %.2f", iteration + 1, best_score)
        return final, best_score

    async def _reformulate_query(self, query: str) -> List[str]:
        try:
            prompt = render_prompt("query_reformulation", query=query)
            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            lines = [
                line.strip()
                for line in response.content.strip().split("\n")
                if line.strip()
            ]
            return lines[:2]
        except PromptNotFoundError:
            logger.warning("query_reformulation prompt not found, using fallback")
            prompt = (
                f"Rewrite the following question into 2 alternative phrasings to improve document retrieval. "
                f"Output ONLY the two alternatives, one per line, no numbering.\n\nQuestion: {query}"
            )
            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            lines = [
                line.strip()
                for line in response.content.strip().split("\n")
                if line.strip()
            ]
            return lines[:2]
        except Exception as exc:
            logger.warning("Query reformulation failed: %s", exc)
            return []

    async def _rerank(self, query: str, chunks: List[Dict]) -> List[Dict]:
        if len(chunks) <= 2:
            return chunks

        if self._reranker is not None:
            return await self._rerank_dedicated(query, chunks)

        return await self._rerank_llm(query, chunks)

    async def _rerank_dedicated(self, query: str, chunks: List[Dict]) -> List[Dict]:
        """Use a dedicated CrossEncoder model for fast reranking (issue #17)."""
        try:
            limit = TOP_K * 2
            pairs = [(query, c.get("text", "")[:500]) for c in chunks[:limit]]
            # Run blocking CPU inference in thread pool
            scores = await asyncio.to_thread(self._reranker.predict, pairs)
            rescored = []
            for i, score in enumerate(scores):
                chunk = dict(chunks[i])
                chunk["rerank_score"] = float(score)
                chunk["score"] = (chunk["score"] + float(score)) / 2
                rescored.append(chunk)
            # keep remaining chunks unscored
            if len(chunks) > limit:
                rescored.extend(chunks[limit:])
            return sorted(rescored, key=lambda x: x["score"], reverse=True)
        except Exception as exc:
            logger.warning(
                "Dedicated reranker failed (%s), falling back to LLM reranking.", exc
            )
            return await self._rerank_llm(query, chunks)

    async def _rerank_llm(self, query: str, chunks: List[Dict]) -> List[Dict]:
        """LLM-based relevance judge (slow fallback, issue #17)."""
        system = (
            "You are a relevance judge. Given a query and a passage, output a relevance score "
            "from 0.0 to 1.0 (no other text). Be strict."
        )
        tasks = []
        for c in chunks[: TOP_K * 2]:
            text = c.get("text", "")[:500]
            user_msg = f"Query: {query}\nPassage: {text}\nScore:"
            tasks.append(
                self._llm.ainvoke(
                    [SystemMessage(content=system), HumanMessage(content=user_msg)]
                )
            )

        responses = await asyncio.gather(*tasks, return_exceptions=True)
        rescored = []
        for i, resp in enumerate(responses):
            chunk = chunks[i]
            if isinstance(resp, Exception):
                logger.warning("Rerank scoring failed for chunk %d: %s", i, resp)
                rescored.append(chunk)
                continue
            try:
                score = float(re.search(r"[\d.]+", resp.content).group())
                chunk = dict(chunk)
                chunk["rerank_score"] = score
                chunk["score"] = (chunk["score"] + score) / 2
            except (AttributeError, ValueError, TypeError) as exc:
                logger.debug("Rerank score parse failed for chunk %d: %s", i, exc)
            rescored.append(chunk)

        return sorted(rescored, key=lambda x: x["score"], reverse=True)

    async def _generate_answer(
        self,
        query: str,
        chunks: List[Dict],
        session_id: str,
        long_term_history: List[Dict],
        lang_instruction: str = "",
        ltm_context: str = "",
        context_summary: str = "",
    ) -> str:
        history = self._memory.get_recent(session_id, turns=3)
        if not history and long_term_history:
            history = [
                {"role": item.get("role", ""), "content": item.get("content", "")}
                for item in long_term_history[-6:]
            ]
        context_parts = []
        for c in chunks[:TOP_K]:
            doc = c.get("document_name", "document")
            text = c.get("text", "")
            context_parts.append(f"[{doc}]\n{text}")
        context = "\n\n---\n\n".join(context_parts)

        history_text = ""
        if history:
            history_text = "\n".join(
                f"{m['role'].capitalize()}: {m['content']}" for m in history
            )
            history_text = f"\n\n[Conversation history]\n{history_text}\n"

        extra_parts = []
        if lang_instruction:
            extra_parts.append(f"[Language Instruction]\n{lang_instruction}")
        if ltm_context:
            extra_parts.append(f"[Remembered Facts about User]\n{ltm_context}")
        if context_summary:
            extra_parts.append(f"[Session Summary]\n{context_summary}")
        extra_context = "\n\n".join(extra_parts)
        extra_section = f"\n\n{extra_context}\n" if extra_context else ""

        try:
            prompt = render_prompt(
                "rag_answer",
                query=query,
                context=context,
                history_text=history_text,
                extra_section=extra_section,
            )
        except PromptNotFoundError:
            logger.warning("rag_answer prompt not found, using fallback")
            prompt = (
                f"You are a helpful document assistant. Answer the user's question based ONLY on the "
                f"provided context. Include citations in the format [document_name].{history_text}"
                f"{extra_section}\n"
                f"[Context]\n{context}\n\n[Question]\n{query}\n\n[Answer]"
            )

        response = await self._llm.ainvoke([HumanMessage(content=prompt)])
        return response.content.strip()

    async def _web_search_fallback(self, query: str) -> str:
        from tools.web_search_tool import TavilySearch

        results = await TavilySearch().search(query, max_results=3)
        if not results:
            return await self._deep_reasoning_fallback(query)
        context = "\n\n".join(r["content"] for r in results)
        prompt = f"Based on the following web search results, answer the question.\n\nResults:\n{context}\n\nQuestion: {query}\n\nAnswer:"
        response = await self._llm.ainvoke([HumanMessage(content=prompt)])
        return "[Web Search]\n\n" + response.content.strip()

    async def _deep_reasoning_fallback(self, query: str) -> str:
        prompt = (
            f"The retrieved documents don't contain enough relevant information. "
            f"Use your internal knowledge to answer as accurately as possible.\n\nQuestion: {query}\n\nAnswer:"
        )
        response = await self._llm.ainvoke([HumanMessage(content=prompt)])
        return (
            "[Deep Reasoning - low document confidence]\n\n" + response.content.strip()
        )
