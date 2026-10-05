#!/usr/bin/env python3
"""Live RAG benchmark: evaluates real retrieval and LLM response against live stack.

Runs questions.json (31 items) against a live Spring Boot + Vector DB (Qdrant) stack.
Computes real retrieval metrics (Hit-Rate@K, Recall@K, MRR) from retrieved chunk IDs / sources
rather than synthetic string matches, providing verified production evaluation numbers.

Usage:
    python eval/run_live_benchmark.py --base-url http://localhost:8080/api
"""
import argparse
import json
import os
import pathlib
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_CORPUS = HERE / "fixtures" / "8d_failure_risk_fixture.txt"
DEFAULT_QUESTIONS = HERE / "questions.json"
DEFAULT_OUTPUT = HERE / "results" / "live_benchmark.json"


def get_csrf_token(session: requests.Session, base_url: str) -> Optional[str]:
    try:
        r = session.get(f"{base_url}/csrf", timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("token") or data.get("csrfToken")
    except Exception:
        pass
    return None


def authenticate(session: requests.Session, base_url: str) -> Tuple[str, Dict[str, str]]:
    """Register and login a throwaway benchmark user with clean owner isolation."""
    user = f"livebench_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    email = f"{user}@benchmark.local"
    password = f"BenchTest_{uuid.uuid4().hex[:8]}!"

    csrf = get_csrf_token(session, base_url)
    headers = {"X-XSRF-TOKEN": csrf} if csrf else {}

    reg_resp = session.post(
        f"{base_url}/auth/register",
        headers=headers,
        json={"username": user, "email": email, "password": password},
        timeout=30,
    )
    if reg_resp.status_code not in (200, 201):
        # Continue to login attempt in case user already existed
        pass

    csrf = get_csrf_token(session, base_url)
    if csrf:
        headers["X-XSRF-TOKEN"] = csrf

    login_resp = session.post(
        f"{base_url}/auth/login",
        headers=headers,
        json={"username": user, "password": password},
        timeout=30,
    )

    token = None
    if login_resp.headers.get("content-type", "").startswith("application/json"):
        data = login_resp.json()
        token = data.get("token") or data.get("accessToken")

    # Check for Set-Cookie header if token not in response body
    auth_headers = {}
    if token:
        auth_headers["Authorization"] = f"Bearer {token}"

    return user, auth_headers


def upload_corpus(
    session: requests.Session, base_url: str, auth_headers: Dict[str, str], corpus_path: pathlib.Path
) -> int:
    """Uploads benchmark corpus and waits for ingestion."""
    if not corpus_path.exists():
        raise FileNotFoundError(f"Corpus file not found: {corpus_path}")

    for attempt in range(1, 4):
        csrf = get_csrf_token(session, base_url)
        headers = dict(auth_headers)
        if csrf:
            headers["X-XSRF-TOKEN"] = csrf

        try:
            with open(corpus_path, "rb") as f:
                r = session.post(
                    f"{base_url}/documents/upload",
                    headers=headers,
                    files={"file": (corpus_path.name, f, "text/plain")},
                    timeout=180,
                )
            if r.status_code == 200:
                doc_id = r.json().get("documentId")
                if doc_id:
                    print(f"✅ Ingested corpus document ID: {doc_id}")
                    # Allow indexing settling time
                    time.sleep(3)
                    return int(doc_id)
        except Exception as e:
            print(f"Upload attempt {attempt} failed: {e}", file=sys.stderr)
            time.sleep(2 * attempt)

    raise RuntimeError("Corpus upload failed after retries")


def parse_retrieved_chunks(response_body: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract structured chunk list from backend response."""
    # Backend may return sourceChunks as a list of dicts, or strings, or sources list
    raw_chunks = response_body.get("sourceChunks") or response_body.get("sources") or []
    normalized_chunks = []

    if isinstance(raw_chunks, list):
        for idx, item in enumerate(raw_chunks):
            if isinstance(item, dict):
                normalized_chunks.append({
                    "chunk_id": item.get("chunkId") or item.get("id") or str(idx),
                    "text": item.get("content") or item.get("text") or "",
                    "score": item.get("score", 0.0),
                    "rank": idx + 1,
                })
            elif isinstance(item, str):
                normalized_chunks.append({
                    "chunk_id": str(idx),
                    "text": item,
                    "score": 0.0,
                    "rank": idx + 1,
                })
    elif isinstance(raw_chunks, str) and raw_chunks.strip():
        # Text block with separated chunks
        parts = [p.strip() for p in raw_chunks.split("\n\n") if p.strip()]
        for idx, part in enumerate(parts):
            normalized_chunks.append({
                "chunk_id": str(idx),
                "text": part,
                "score": 0.0,
                "rank": idx + 1,
            })

    return normalized_chunks


def evaluate_retrieval_ranking(
    retrieved_chunks: List[Dict[str, Any]], expected_keywords: List[str], top_k: int = 5
) -> Dict[str, Any]:
    """Calculate Hit@K, Recall@K, and Reciprocal Rank over expected keywords
    matched inside the top-K retrieved chunks.

    Questions carrying no expected keywords have no ground truth, so they are
    reported as ``scored=False`` with ``None`` metrics. They are deliberately
    NOT scored as perfect: doing so would silently inflate every aggregate and
    present unscored questions as retrieval successes.
    """
    if not expected_keywords:
        return {
            "scored": False,
            "hit": False,
            "recall": None,
            "mrr": None,
            "matched_rank": None,
            "keywords_matched": [],
        }

    top_chunks = retrieved_chunks[:top_k]
    matched_rank = None
    keywords_lower = [k.lower() for k in expected_keywords]
    hits_found = set()

    for chunk in top_chunks:
        chunk_text = chunk.get("text", "").lower()
        chunk_hits = [k for k in keywords_lower if k in chunk_text]
        if chunk_hits:
            if matched_rank is None:
                matched_rank = chunk["rank"]
            hits_found.update(chunk_hits)

    recall = len(hits_found) / len(keywords_lower)
    hit = len(hits_found) > 0
    mrr = (1.0 / matched_rank) if matched_rank else 0.0

    return {
        "scored": True,
        "hit": hit,
        "recall": round(recall, 4),
        "mrr": round(mrr, 4),
        "matched_rank": matched_rank,
        "keywords_matched": list(hits_found),
    }


def run_benchmark(
    base_url: str,
    questions_path: pathlib.Path,
    corpus_path: pathlib.Path,
    output_path: pathlib.Path,
    top_k: int = 5,
) -> Dict[str, Any]:
    base_url = base_url.rstrip("/")
    session = requests.Session()

    print(f"Connecting to live backend at: {base_url}")
    user, auth_headers = authenticate(session, base_url)
    print(f"Authenticated as test user: {user}")

    doc_id = upload_corpus(session, base_url, auth_headers, corpus_path)

    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    print(f"Loaded {len(questions)} evaluation questions from {questions_path.name}")

    results = []
    latencies = []
    genuine_responses = 0

    session_id = f"live-bench-{uuid.uuid4().hex[:8]}"

    for i, q in enumerate(questions, 1):
        q_id = q.get("id", i)
        q_text = q.get("question", "")
        expected_keywords = q.get("expected_source_keywords", [])
        expected_answer_contains = q.get("expected_answer_contains", [])

        csrf = get_csrf_token(session, base_url)
        headers = dict(auth_headers)
        if csrf:
            headers["X-XSRF-TOKEN"] = csrf

        t0 = time.time()
        status_code = 0
        response_data = {}
        is_mock = False

        try:
            r = session.post(
                f"{base_url}/chat/ask",
                headers=headers,
                json={
                    "sessionId": session_id,
                    "documentId": doc_id,
                    "message": q_text,
                    "mode": "rag",
                },
                timeout=120,
            )
            status_code = r.status_code
            latency_ms = int((time.time() - t0) * 1000)
            latencies.append(latency_ms)

            if r.headers.get("X-Mock-Backend") or r.headers.get("X-Provider") == "mock-backend":
                is_mock = True

            if r.status_code == 200:
                response_data = r.json()
                if not is_mock and response_data.get("aiResponse"):
                    genuine_responses += 1
        except Exception as e:
            latency_ms = int((time.time() - t0) * 1000)
            print(f"  [Q{q_id}] Request error: {e}", file=sys.stderr)

        retrieved_chunks = parse_retrieved_chunks(response_data)
        retrieval_metrics = evaluate_retrieval_ranking(
            retrieved_chunks, expected_keywords, top_k=top_k
        )

        answer_text = response_data.get("aiResponse") or ""
        answer_hits = [
            k for k in expected_answer_contains if k.lower() in answer_text.lower()
        ]
        # No expected-answer keywords means no ground truth: report None rather
        # than counting "any response text" as a correct answer.
        answer_scored = bool(expected_answer_contains)
        answer_correct = len(answer_hits) > 0 if answer_scored else None

        results.append({
            "id": q_id,
            "question": q_text,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "is_mock": is_mock,
            "scored": retrieval_metrics["scored"],
            "retrieval_hit": retrieval_metrics["hit"],
            "retrieval_recall": retrieval_metrics["recall"],
            "mrr": retrieval_metrics["mrr"],
            "matched_rank": retrieval_metrics["matched_rank"],
            "answer_scored": answer_scored,
            "answer_correct": answer_correct,
            "retrieved_chunks_count": len(retrieved_chunks),
            "confidence": response_data.get("confidence"),
            "rag_strategy": response_data.get("ragStrategy"),
        })

        icon = "✅" if (retrieval_metrics["hit"] and answer_correct) else "⚠️"
        print(f"  [{i}/{len(questions)}] Q{q_id}: {icon} (Hit@{top_k}={retrieval_metrics['hit']}, Recall={retrieval_metrics['recall']}, Latency={latency_ms}ms)")

    total = len(results)
    # Aggregates are computed ONLY over questions that carry ground truth.
    # Mixing unscored questions into the denominator would fabricate signal.
    scored_retrieval = [r for r in results if r["scored"]]
    scored_answers = [r for r in results if r["answer_scored"]]
    hits = sum(1 for r in scored_retrieval if r["retrieval_hit"])
    avg_recall = (
        sum(r["retrieval_recall"] for r in scored_retrieval) / len(scored_retrieval)
        if scored_retrieval else None
    )
    mean_mrr = (
        sum(r["mrr"] for r in scored_retrieval) / len(scored_retrieval)
        if scored_retrieval else None
    )
    correct_answers = sum(1 for r in scored_answers if r["answer_correct"])

    summary = {
        "benchmark_type": "live_stack_evaluation",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target_base_url": base_url,
        "corpus_file": corpus_path.name,
        "total_questions": total,
        "scored_retrieval_questions": len(scored_retrieval),
        "unscored_retrieval_questions": total - len(scored_retrieval),
        "scored_answer_questions": len(scored_answers),
        "top_k": top_k,
        "hit_rate_at_k": (
            round(hits / len(scored_retrieval), 4) if scored_retrieval else None
        ),
        "mean_recall_at_k": round(avg_recall, 4) if avg_recall is not None else None,
        "mean_reciprocal_rank": round(mean_mrr, 4) if mean_mrr is not None else None,
        "answer_correctness": (
            round(correct_answers / len(scored_answers), 4) if scored_answers else None
        ),
        "genuine_llm_responses": genuine_responses,
        "mock_responses": total - genuine_responses if any(r["is_mock"] for r in results) else 0,
        "average_latency_ms": round(sum(latencies) / max(len(latencies), 1)),
        "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
        "results": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n📊 Summary saved to {output_path}")
    print(f"   Scored questions: {summary['scored_retrieval_questions']}/{total} "
          f"(retrieval), {summary['scored_answer_questions']}/{total} (answer)")
    if summary["hit_rate_at_k"] is None:
        print("   ⚠️  No question carried expected source keywords — retrieval "
              "metrics are undefined, not 0%.")
    else:
        print(f"   Hit-Rate@{top_k}: {summary['hit_rate_at_k'] * 100:.1f}%")
        print(f"   Mean Recall@{top_k}: {summary['mean_recall_at_k'] * 100:.1f}%")
        print(f"   MRR: {summary['mean_reciprocal_rank']:.3f}")
    if summary["answer_correctness"] is None:
        print("   ⚠️  No question carried expected answer keywords — "
              "answer_correctness is undefined.")
    else:
        print(f"   Answer correctness: {summary['answer_correctness'] * 100:.1f}%")
    print(f"   Genuine LLM Responses: {genuine_responses}/{total}")
    print(f"   Avg Latency: {summary['average_latency_ms']}ms")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Run Live RAG Retrieval Benchmark")
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", "http://localhost:8080/api"),
                        help="Base API URL including context path")
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS),
                        help="Path to questions.json")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS),
                        help="Path to corpus text file")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help="Path to output results file")
    parser.add_argument("--top-k", type=int, default=5,
                        help="Top-K threshold for retrieval ranking metrics")
    args = parser.parse_args()

    run_benchmark(
        base_url=args.base_url,
        questions_path=pathlib.Path(args.questions),
        corpus_path=pathlib.Path(args.corpus),
        output_path=pathlib.Path(args.output),
        top_k=args.top_k,
    )


if __name__ == "__main__":
    main()
