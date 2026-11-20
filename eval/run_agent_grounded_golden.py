#!/usr/bin/env python3
"""Run a small, real localhost retrieval and agent golden set."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import statistics
import sys
import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))


def tokens(value):
    return set(re.findall(r"[a-z0-9]+", value.lower())) - {
        "the", "is", "a", "of", "in", "what", "when", "where", "how", "was"
    }


def rank_of(rows, gold):
    return next((index for index, row in enumerate(rows, 1) if row == gold), None)


def metrics(ranks, k=5):
    return {"recall_at_5": round(sum(rank is not None and rank <= k for rank in ranks) / len(ranks), 4),
            "mrr": round(sum(1 / rank if rank else 0 for rank in ranks) / len(ranks), 4)}


def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * quantile + 0.5))
    return round(ordered[index], 1)


async def retrieve(queries, collection_id):
    from tools.qdrant_tool import QdrantHybridSearch

    search = QdrantHybridSearch()
    try:
        output = []
        for query in queries:
            started = time.perf_counter()
            found = await search.hybrid_search(query, collection_id, top_k=5)
            output.append({"rows": found, "latency_ms": round((time.perf_counter() - started) * 1000, 1)})
        return output
    finally:
        await search.aclose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "eval/agent_grounded_golden.json"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--agent", default="http://127.0.0.1:19003/v1")
    parser.add_argument("--qdrant", default="http://127.0.0.1:6333")
    parser.add_argument("--ollama", default="http://127.0.0.1:11434")
    args = parser.parse_args()
    token = os.environ.get("INTERNAL_SERVICE_TOKEN")
    if not token:
        parser.error("INTERNAL_SERVICE_TOKEN must be set")
    dataset_bytes = Path(args.dataset).read_bytes()
    dataset = json.loads(dataset_bytes)
    corpus = [(doc["document"], index, chunk)
              for doc in dataset["corpus"] for index, chunk in enumerate(doc["chunks"])]
    collection_id = "golden_" + uuid.uuid4().hex[:12]
    session_id = "golden-" + uuid.uuid4().hex[:12]
    headers = {"X-Internal-Token": token}
    points = []
    for point_id, (document, chunk_index, chunk) in enumerate(corpus, 1):
        embedding_response = requests.post(args.ollama + "/api/embeddings", json={
            "model": "nomic-embed-text", "prompt": chunk}, timeout=60)
        embedding_response.raise_for_status()
        vector = embedding_response.json()["embedding"]
        points.append({"id": point_id, "vector": vector, "payload": {
            "text": chunk, "document_name": document, "chunk_index": chunk_index,
            "source_type": "document"}})
    create = requests.put(args.qdrant + "/collections/" + collection_id, json={
        "vectors": {"size": len(points[0]["vector"]), "distance": "Cosine"}}, timeout=30)
    create.raise_for_status()
    try:
        upsert = requests.put(args.qdrant + "/collections/" + collection_id + "/points",
                              json={"points": points}, timeout=60)
        upsert.raise_for_status()
        retrieval_raw = asyncio.run(retrieve(
            [case["question"] for case in dataset["retrieval_cases"]], collection_id))
        retrieval_cases = []
        hybrid_ranks = []
        lexical_ranks = []
        for case, observed in zip(dataset["retrieval_cases"], retrieval_raw):
            gold = (case["gold_document"], case["gold_chunk"])
            hybrid = [(row["document_name"], row["chunk_index"]) for row in observed["rows"]]
            baseline = sorted(corpus, key=lambda item: (
                -len(tokens(case["question"]) & tokens(item[2])), item[0], item[1]))
            lexical = [(doc, index) for doc, index, _ in baseline]
            hybrid_rank, lexical_rank = rank_of(hybrid, gold), rank_of(lexical, gold)
            hybrid_ranks.append(hybrid_rank)
            lexical_ranks.append(lexical_rank)
            retrieval_cases.append({"id": case["id"], "gold_document": gold[0], "gold_chunk": gold[1],
                "hybrid_rank": hybrid_rank, "lexical_rank": lexical_rank,
                "hybrid_top5": hybrid, "lexical_top5": lexical[:5],
                "latency_ms": observed["latency_ms"]})

        agent_cases = []
        approval_id = None
        for case in dataset["agent_cases"]:
            selected = [collection_id]
            if case["type"] == "tool_error":
                selected = [str(int(time.time() * 1_000_000))]
                absent = requests.get(args.qdrant + "/collections/" + selected[0], timeout=15)
                if absent.status_code != 404:
                    raise RuntimeError("Tool-error collection unexpectedly exists")
            started = time.perf_counter()
            response = requests.post(args.agent + "/agent/invoke", json={
                "query": case["question"], "session_id": session_id + "-" + case["id"],
                "user_id": "local-golden-owner", "document_ids": selected,
                "use_web_search": False}, headers=headers, timeout=180)
            latency = round((time.perf_counter() - started) * 1000, 1)
            body = response.json()
            answer = body.get("answer", "")
            sources = body.get("sources", [])
            kind = case["type"]
            if kind == "answer":
                passed = (response.status_code == 200 and body.get("agent_type") == "rag"
                    and all(text.lower() in answer.lower() for text in case["expected_answer_contains"])
                    and any(source.get("document_name") == case["gold_document"]
                            and case["gold_chunk"] == next((idx for doc, idx, chunk in corpus
                                if doc == source.get("document_name") and chunk.startswith(source.get("chunk_text", ""))), -1)
                            for source in sources))
            elif kind == "no_answer":
                passed = response.status_code == 200 and bool(re.search(
                    r"not (?:contain|found|provided)|could not find|no (?:reliable )?evidence", answer.lower()))
            elif kind == "prompt_injection":
                passed = response.status_code in (400, 403, 422)
            elif kind == "tool_error":
                passed = response.status_code == 200 and body.get("answer_origin") == "abstention" and not sources
            else:
                approval_id = body.get("hitl_approval_id")
                passed = response.status_code == 200 and body.get("hitl_pending") is True and bool(approval_id)
            agent_cases.append({"id": case["id"], "type": kind, "http_status": response.status_code,
                "passed": passed, "latency_ms": latency, "answer": answer,
                "answer_origin": body.get("answer_origin"), "agent_type": body.get("agent_type"),
                "sources": sources, "hitl_pending": body.get("hitl_pending"),
                "cost_usd": body.get("cost_usd")})
        if approval_id:
            rejection = requests.post(args.agent + f"/agent/approvals/{approval_id}/reject",
                json={"approver": "golden-reviewer", "note": "controlled golden evaluation"},
                headers=headers, timeout=20)
            rejection.raise_for_status()
            agent_cases[-1]["approval_decision"] = rejection.json().get("decision")
            agent_cases[-1]["passed"] &= rejection.json().get("decision") == "rejected"

        latencies = [case["latency_ms"] for case in agent_cases]
        report = {"dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
            "model": "qwen2.5:1.5b", "embedding_model": "nomic-embed-text",
            "scope": "localhost synthetic corpus; shared Qdrant collection; real Ollama and LangGraph agent",
            "session_id": session_id, "collection_id": collection_id,
            "corpus": corpus, "retrieval_cases": retrieval_cases, "agent_cases": agent_cases,
            "metrics": {"retrieval_hybrid": metrics(hybrid_ranks),
                "retrieval_lexical_baseline": metrics(lexical_ranks),
                "answer_quality_exact_fact_and_source": sum(c["passed"] for c in agent_cases if c["type"] == "answer") / 3,
                "tool_call_accuracy": int(agent_cases[-1]["agent_type"] == "action" and agent_cases[-1]["hitl_pending"] is True),
                "task_completion": round(sum(c["passed"] for c in agent_cases) / len(agent_cases), 4),
                "abstention_cases_passed": sum(c["passed"] for c in agent_cases if c["type"] in ("no_answer", "tool_error")),
                "abstention_cases_total": 2,
                "p50_agent_latency_ms": percentile(latencies, 0.5),
                "p95_agent_latency_ms": percentile(latencies, 0.95),
                "metered_api_cost_usd": sum(c["cost_usd"] or 0 for c in agent_cases)}}
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(report["metrics"], ensure_ascii=False))
    finally:
        requests.delete(args.qdrant + "/collections/" + collection_id, timeout=20)


if __name__ == "__main__":
    main()
