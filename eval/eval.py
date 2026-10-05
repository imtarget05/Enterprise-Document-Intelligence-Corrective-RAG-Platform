#!/usr/bin/env python3
"""
Smart Document Chatbot — RAG Evaluation Pipeline

Evaluates the RAG system against a versioned question set and produces
structured metrics: retrieval accuracy, answer correctness,
hallucination rate, latency, and token estimates.

Usage:
    python eval.py --base-url http://localhost:8080/api \
                   --token <jwt> \
                   --document-id 1 \
                   --questions eval/questions.json \
                   --output eval/results/eval_results.json
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests

# Optional MLflow import — graceful fallback if not installed
try:
    import mlflow

    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False

# Optional sentence-transformers for semantic similarity metric
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np

    EMBEDDING_MODEL_AVAILABLE = True
except ImportError:
    EMBEDDING_MODEL_AVAILABLE = False

# Optional LLM judge for faithfulness/relevance scoring
try:
    from llm_judge import LLMJudge, JudgeScore

    LLM_JUDGE_AVAILABLE = True
except ImportError:
    LLM_JUDGE_AVAILABLE = False


def load_questions(path: str) -> list[dict]:
    if not os.path.exists(path):
        fallback = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.path.basename(path))
        if os.path.exists(fallback):
            path = fallback
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_csrf_token(base_url: str, session: requests.Session) -> Optional[str]:
    """Fetch a CSRF token from the backend (if the endpoint is available).

    The Spring Boot backend enables CSRF protection on mutating endpoints,
    so POST requests must carry the X-XSRF-TOKEN header plus the XSRF-TOKEN
    cookie issued by {base_url}/csrf. Returns None when CSRF is disabled or the
    endpoint is unreachable.
    """
    try:
        resp = session.get(f"{base_url}/csrf", timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("token")
    except (requests.exceptions.RequestException, ValueError):
        pass
    return None


def ask_question(
    base_url: str,
    token: str,
    session_id: str,
    document_id: int,
    question: str,
    session: Optional[requests.Session] = None,
    csrf_token: Optional[str] = None,
) -> dict[str, Any]:
    """Send a synchronous /chat/ask request and capture response + latency."""
    http = session or requests
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if csrf_token:
        headers["X-XSRF-TOKEN"] = csrf_token
    payload = {
        "sessionId": session_id,
        "documentId": document_id,
        "message": question,
    }

    start = time.time()
    last_error = None
    # Rate-limit aware retry: Cloudflare Workers AI free tier throttles bursts,
    # so 429/5xx responses are retried with exponential backoff (Blueprint #48
    # fast CI evaluation must not report false failures from transient 429s).
    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        try:
            resp = http.post(
                f"{base_url}/chat/ask", json=payload, headers=headers, timeout=120
            )

            if resp.status_code in (429, 502, 503, 504) and attempt < max_attempts:
                backoff = min(2 ** attempt * 2, 30)
                print(f"    [retry {attempt}] HTTP {resp.status_code} — backing off {backoff}s")
                time.sleep(backoff)
                continue

            latency_ms = round((time.time() - start) * 1000)

            if resp.status_code != 200:
                return {
                    "status": "error",
                    "http_status": resp.status_code,
                    "latency_ms": latency_ms,
                    "answer": "",
                    "source_chunks": "",
                    "confidence": None,
                    "confidence_score": None,
                }

            data = resp.json()
            is_mock = (
                resp.headers.get("X-Mock-Backend") == "true"
                or resp.headers.get("X-Provider") == "mock-backend"
                or data.get("is_mock") is True
                or "8081" in base_url
                or "mock" in str(data.get("model", "")).lower()
            )
            return {
                "status": "success",
                "latency_ms": latency_ms,
                "answer": data.get("aiResponse", ""),
                "source_chunks": data.get("sourceChunks", ""),
                "confidence": data.get("confidence"),
                "confidence_score": data.get("confidenceScore"),
                "rag_strategy": data.get("ragStrategy"),
                "model": data.get("model"),
                "is_mock": is_mock,
            }
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < max_attempts:
                backoff = min(2 ** attempt * 2, 30)
                print(f"    [retry {attempt}] request error: {e} — backing off {backoff}s")
                time.sleep(backoff)
                continue
    return {
        "status": "error",
        "error": str(last_error),
        "latency_ms": round((time.time() - start) * 1000),
        "answer": "",
        "source_chunks": "",
        "confidence": None,
        "confidence_score": None,
    }

# ---------------------------------------------------------------------------
# Grading Contract v2 helpers (Decision 10)
#
# Deterministic concept coverage — NOT semantic LLM judging.
# Normalization is a small rule-based layer: lowercase, whitespace collapse,
# and simple plural singularization. No external dependencies, no stemmers,
# no embeddings. Both answers and surface forms are normalized identically so
# "differences" in an answer matches the surface form "difference".
# ---------------------------------------------------------------------------

_IRREGULAR_PLURALS = {
    "analyses": "analysis",
    "criteria": "criterion",
    "data": "data",
}

# Known provider/LLM failure contracts. When a match is found, the evaluator
# must NOT treat the response as a genuine LLM answer, regardless of HTTP status
# (the backend returns HTTP 200 and places the message in `aiResponse`).
_PROVIDER_ERROR_MARKERS = (
    "temporarily unavailable",           # backend MessageHandler LLM-router error path
    "language model is temporarily",     # explicit variant
    "cloudflare_error",                  # llm-router provider error passthrough
    "http status error",                 # router httpx HTTPStatusError leak
)


def is_provider_error(result: dict) -> bool:
    """Return True when a response matches a known provider failure contract.

    This is deliberately narrow: only established backend/router failure strings
    are recognized, so a genuine answer that merely mentions words such as
    "unavailable", "error", or "failed" is NOT mislabelled as a provider error.
    """
    answer = normalize_text(result.get("answer") or "")
    return any(marker in answer for marker in _PROVIDER_ERROR_MARKERS)


def normalize_text(text: str) -> str:
    """Deterministic text normalization for lexical grading.

    - lowercase
    - collapse whitespace
    - strip punctuation from token edges (keep intra-word hyphens/apostrophes)
    - simple plural singularization (risks→risk, causes→cause, ies→y, ...)
    """
    import re as _re

    if not text:
        return ""
    lowered = text.lower()
    # collapse any whitespace runs to single spaces
    lowered = _re.sub(r"\s+", " ", lowered)
    tokens = []
    for tok in lowered.split(" "):
        tok = tok.strip(".,;:!?()[]{}\"'—–")
        if not tok:
            continue
        # possessives: "document's" -> "document"
        if tok.endswith("'s"):
            tok = tok[:-2]
        if tok in _IRREGULAR_PLURALS:
            tok = _IRREGULAR_PLURALS[tok]
        elif len(tok) > 3 and tok.endswith("ies"):
            tok = tok[:-3] + "y"          # similarities → similarity
        elif len(tok) > 4 and tok.endswith(
            ("sses", "shes", "ches", "xes", "zes")
        ):
            tok = tok[:-2]                # addresses → address
        elif len(tok) > 3 and tok.endswith("s") and not tok.endswith(
            ("ss", "us", "is")
        ):
            tok = tok[:-1]               # risks → risk, causes → cause
        tokens.append(tok)
    return " ".join(tokens)


# ---------------------------------------------------------------------------
# Semantic similarity metric (issue #20)
# ---------------------------------------------------------------------------

_EMBEDDING_MODEL = None


def _get_embedding_model():
    """Lazy-load the shared embedding model for semantic similarity scoring."""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None and EMBEDDING_MODEL_AVAILABLE:
        model_name = os.getenv("EVAL_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        _EMBEDDING_MODEL = SentenceTransformer(model_name)
    return _EMBEDDING_MODEL


def _cosine_similarity(a, b) -> float:
    """Compute cosine similarity between two vectors."""
    if not EMBEDDING_MODEL_AVAILABLE:
        return 0.0
    a = np.array(a)
    b = np.array(b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(np.dot(a, b) / norm)


def compute_semantic_retrieval_score(query: str, source_chunks: str) -> float:
    """
    Compute semantic similarity between the query and retrieved source chunks.

    Returns the max cosine similarity between the query embedding and each
    chunk embedding. Falls back to 0.0 when sentence-transformers is not
    installed or source_chunks is empty.
    """
    if not EMBEDDING_MODEL_AVAILABLE or not source_chunks:
        return 0.0

    model = _get_embedding_model()
    if model is None:
        return 0.0

    # Split source chunks on the delimiter used by the backend
    chunks = [c.strip() for c in source_chunks.split("\n---\n") if c.strip()]
    if not chunks:
        # Fallback: treat the whole string as one chunk
        chunks = [source_chunks.strip()]

    try:
        query_embedding = model.encode(query, convert_to_numpy=True)
        chunk_embeddings = model.encode(chunks, convert_to_numpy=True)
        scores = [_cosine_similarity(query_embedding, ce) for ce in chunk_embeddings]
        return max(scores) if scores else 0.0
    except Exception:
        return 0.0


def load_concepts_overrides(path: Optional[str] = None) -> dict[str, dict]:
    """Load optional per-question structured concepts from a side file.

    The side file keeps question definitions (agent_questions.json) separate
    from grading hints. Returns {question_id: {"expected_concepts": [...]}}.
    """
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "concepts_overrides.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def grade_concepts(answer: str, concepts: list[dict]) -> dict[str, Any]:
    """Grade an answer against required concepts using normalized matching.

    A concept is covered when at least one of its approved surface forms is
    found in the normalized answer. ALL concepts must be covered for the
    answer to be correct (AND logic — this is what protects against false
    positives such as keyword-only answers with unrelated content).
    """
    norm_answer = normalize_text(answer)
    details = []
    covered = 0
    for concept in concepts:
        name = concept.get("concept", "<unnamed>")
        forms = [normalize_text(f) for f in concept.get("forms", [])]
        matched = [f for f in forms if f and f in norm_answer]
        is_covered = len(matched) > 0
        if is_covered:
            covered += 1
        details.append(
            {
                "concept": name,
                "covered": is_covered,
                "matched_forms": matched,
            }
        )
    return {
        "concepts_expected": len(concepts),
        "concepts_covered": covered,
        "concept_details": details,
        "answer_correct": len(concepts) > 0 and covered == len(concepts),
    }


def resolve_concepts(question: dict, overrides: dict[str, dict]) -> Optional[list[dict]]:
    """Return structured concepts for a question, or None for legacy grading.

    Priority: inline `expected_concepts` on the question > side-file override
    keyed by question id. Absence of both selects the legacy keyword path.
    """
    inline = question.get("expected_concepts")
    if isinstance(inline, list) and inline:
        return inline
    override = overrides.get(question.get("id")) or {}
    ov_concepts = override.get("expected_concepts")
    if isinstance(ov_concepts, list) and ov_concepts:
        return ov_concepts
    return None


def evaluate_answer(result: dict, question: dict, overrides: Optional[dict[str, dict]] = None) -> dict[str, Any]:
    """Score a single answer.

    Grading Contract v2:
    - structured concepts present  → deterministic concept coverage (AND logic)
    - legacy keywords only         → original expected_answer_contains behavior
    """
    overrides = overrides if overrides is not None else {}
    provider_error = is_provider_error(result)
    answer = result["answer"].lower()
    sources = (result.get("source_chunks") or "").lower()

    concepts = resolve_concepts(question, overrides) if not provider_error else None
    keywords_found = []
    concept_payload: dict[str, Any] = {}

    if concepts is not None:
        graded = grade_concepts(result["answer"], concepts)
        answer_correct = graded.pop("answer_correct")
        concept_payload = graded
        concept_payload["grading_mode"] = "structured_concepts"
    elif provider_error:
        # Provider/LLM failure: do NOT grade answer correctness. The response is
        # excluded from answer-correctness/retrieval denominators in run_evaluation.
        answer_correct = None
    else:
        # Legacy path: at least one expected keyword found (unchanged behavior)
        expected_keywords = [k.lower() for k in question["expected_answer_contains"]]
        keywords_found = [k for k in expected_keywords if k in answer]
        answer_correct = len(keywords_found) > 0

    # Evidence support: retrieval returned usable evidence for this answer.
    # Distinct from retrieval_accurate (keyword hits) — this only checks that
    # real evidence existed and the strategy was not no_evidence.
    evidence_supported = bool(sources) and result.get("rag_strategy") != "no_evidence"

    # Retrieval accuracy: expected source keywords found in sourceChunks
    source_keywords = [k.lower() for k in question["expected_source_keywords"]]
    source_hits = [k for k in source_keywords if k in sources]
    retrieval_accurate = len(source_hits) > 0 if sources else False

    # Hallucination heuristic: answer is confident but retrieval has no sources
    is_hallucination = (
        not provider_error
        and not retrieval_accurate
        and answer_correct
        and "không tìm thấy" not in answer
        and result.get("confidence") != "low"
    )

    # Semantic similarity: how semantically close the query is to retrieved chunks
    semantic_score = compute_semantic_retrieval_score(
        question.get("question", ""), result.get("source_chunks") or ""
    )

    evaluation = {
        "question_id": question["id"],
        "difficulty": question.get("difficulty"),
        "answer_correct": answer_correct,
        "provider_error": provider_error,
        "keywords_found": keywords_found,
        "evidence_supported": evidence_supported,
        "retrieval_accurate": retrieval_accurate,
        "source_hits": source_hits,
        "semantic_retrieval_score": round(semantic_score, 4),
        "is_hallucination": is_hallucination,
        "latency_ms": result["latency_ms"],
        "confidence": result.get("confidence"),
        "confidence_score": result.get("confidence_score"),
        "rag_strategy": result.get("rag_strategy"),
        "status": result["status"],
        "is_mock": result.get("is_mock", False),
    }
    if concept_payload:
        evaluation.update(concept_payload)
    return evaluation


def run_evaluation(args: argparse.Namespace) -> dict[str, Any]:
    questions = load_questions(args.questions)
    overrides = load_concepts_overrides()
    session_id = f"eval-{int(time.time())}"

    print(f"🔬 Running evaluation: {len(questions)} questions")
    print(f"   Target: {args.base_url}")
    print(f"   Document ID: {args.document_id}")
    print(f"   Session: {session_id}")
    print()

    # Use a persistent requests.Session so the backend's session cookie
    # (set during CSRF exchange) is reused across all ask requests.
    session = requests.Session()

    csrf_token: Optional[str] = get_csrf_token(args.base_url, session)
    if csrf_token:
        print(f"   ✅ CSRF token acquired")
    else:
        print(f"   ⚠️  No CSRF token (POST may fail if CSRF is enforced)")
    print()

    # Start MLflow run if available
    mlflow_run = None
    if args.mlflow and MLFLOW_AVAILABLE:
        try:
            mlflow.set_tracking_uri(args.mlflow_uri)
            mlflow.set_experiment("rag-evaluation")
            mlflow_run = mlflow.start_run(run_name=f"eval-{session_id}")
            mlflow.log_params(
                {
                    "base_url": args.base_url,
                    "document_id": args.document_id,
                    "total_questions": len(questions),
                    "session_id": session_id,
                    "csrf_enabled": csrf_token is not None,
                }
            )
        except Exception as e:
            print(f"  ⚠️  MLflow unavailable: {e}")
            mlflow_run = None


    # Initialize LLM judge if requested
    llm_judge = None
    _llm_judge_enabled = getattr(args, 'llm_judge', False)
    _llm_judge_url = getattr(args, 'llm_judge_url', None)
    _llm_judge_model = getattr(args, 'llm_judge_model', None)
    if _llm_judge_enabled and LLM_JUDGE_AVAILABLE:
        try:
            llm_judge = LLMJudge(base_url=_llm_judge_url, model=_llm_judge_model)
            print("   + LLM judge enabled")
        except Exception as e:
            print(f"   ! LLM judge initialization failed: {e}")
            llm_judge = None
    elif _llm_judge_enabled and not LLM_JUDGE_AVAILABLE:
        print("   ! LLM judge requested but llm_judge module not available")
    print()
    details = []
    for i, q in enumerate(questions, 1):
        print(f"  [{i}/{len(questions)}] {q['question'][:60]}...", end=" ", flush=True)
        # Spring Security rotates the CSRF token on every authenticated POST,
        # so a fresh token must be fetched before each request.
        csrf_token = get_csrf_token(args.base_url, session)
        result = ask_question(
            args.base_url,
            args.token,
            session_id,
            args.document_id,
            q["question"],
            session=session,
            csrf_token=csrf_token,
        )
        evaluation = evaluate_answer(result, q, overrides)
        details.append(evaluation)


        # LLM judge evaluation
        if llm_judge and result.get("status") == "success" and not evaluation.get("provider_error"):
            try:
                judge_result = llm_judge.evaluate_all(
                    question=q.get("question", ""),
                    answer=result.get("answer", ""),
                    context=result.get("source_chunks", ""),
                    expected_concepts=[
                        c.get("concept", "")
                        for c in question.get("expected_concepts", [])
                    ] or None,
                )
                evaluation["llm_judge"] = judge_result.to_dict()
                evaluation["llm_judge_score"] = judge_result.average_score
            except Exception as e:
                evaluation["llm_judge_error"] = str(e)

        status_icon = "⚠️" if evaluation.get("provider_error") else ("✅" if evaluation["answer_correct"] else "❌")
        print(f"{status_icon} ({result['latency_ms']}ms)")

        # Log per-question metrics to MLflow
        if mlflow_run:
            try:
                mlflow.log_metrics(
                    {
                        f"q{i}_latency_ms": evaluation["latency_ms"],
                        f"q{i}_correct": 1.0 if evaluation["answer_correct"] else 0.0,
                        f"q{i}_retrieval": 1.0
                        if evaluation["retrieval_accurate"]
                        else 0.0,
                    },
                    step=i,
                )
            except Exception:
                pass

    # Aggregate metrics
    total = len(details)
    provider_errors = [d for d in details if d.get("provider_error")]
    # Genuine LLM responses: HTTP/application success that is NOT a provider error.
    successful = [
        d for d in details if d["status"] == "success" and not d.get("provider_error")
    ]
    correct = [d for d in successful if d["answer_correct"]]
    retrieval_accurate = [d for d in successful if d["retrieval_accurate"]]
    hallucinations = [d for d in successful if d["is_hallucination"]]
    latencies = [d["latency_ms"] for d in successful]
    # True application/HTTP errors (excludes provider errors, which are counted separately).
    error_count = total - len(successful) - len(provider_errors)

    # Aggregate semantic retrieval scores
    semantic_scores = [d["semantic_retrieval_score"] for d in successful if "semantic_retrieval_score" in d]
    avg_semantic_score = round(sum(semantic_scores) / max(len(semantic_scores), 1), 4)


    # Aggregate LLM judge scores
    llm_judge_scores = [
        d["llm_judge_score"]
        for d in details
        if d.get("llm_judge_score") is not None
    ]
    avg_llm_judge_score = round(sum(llm_judge_scores) / max(len(llm_judge_scores), 1), 4) if llm_judge_scores else None

    faithfulness_scores = [
        d.get("llm_judge", {}).get("faithfulness", {}).get("score")
        for d in details
        if d.get("llm_judge") and d["llm_judge"].get("faithfulness")
    ]
    avg_faithfulness = round(sum(faithfulness_scores) / max(len(faithfulness_scores), 1), 4) if faithfulness_scores else None

    relevance_scores = [
        d.get("llm_judge", {}).get("relevance", {}).get("score")
        for d in details
        if d.get("llm_judge") and d["llm_judge"].get("relevance")
    ]
    avg_relevance = round(sum(relevance_scores) / max(len(relevance_scores), 1), 4) if relevance_scores else None

    is_mock_run = any(d.get("is_mock") for d in details) or "8081" in args.base_url or "mock" in args.base_url
    genuine_responses = 0 if is_mock_run else len(
        [d for d in details if d.get("status") == "success" and not d.get("provider_error")]
    )
    mock_responses = len(successful) if is_mock_run else 0

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "test_type": "fixture_grader_smoke_test" if is_mock_run else "live_llm_benchmark",
        "is_mock_run": is_mock_run,
        "base_url": args.base_url,
        "document_id": args.document_id,
        "total_questions": total,
        "successful_requests": len(successful),
        "retrieval_accuracy": round(
            len(retrieval_accurate) / max(len(successful), 1), 4
        ),
        "semantic_retrieval_score": avg_semantic_score,
        "answer_correctness": round(len(correct) / max(len(successful), 1), 4),
        "hallucination_cases": len(hallucinations),
        "hallucination_rate": round(len(hallucinations) / max(len(successful), 1), 4),
        "average_latency_ms": round(sum(latencies) / max(len(latencies), 1)),
        "p95_latency_ms": round(
            sorted(latencies)[int(len(latencies) * 0.95) - 1] if latencies else 0
        ),
        "min_latency_ms": min(latencies) if latencies else 0,
        "max_latency_ms": max(latencies) if latencies else 0,
        "error_count": error_count,
        "provider_errors": len(provider_errors),
        "provider_error_rate": round(len(provider_errors) / max(total, 1), 4),
        "genuine_llm_responses": genuine_responses,
        "mock_responses": mock_responses,

        "llm_judge_enabled": llm_judge is not None,
        "llm_judge_avg_score": avg_llm_judge_score,
        "llm_judge_avg_faithfulness": avg_faithfulness,
        "llm_judge_avg_relevance": avg_relevance,

        "details": details,
    }

    # Log aggregate metrics to MLflow
    if mlflow_run:
        try:
            mlflow.log_metrics(
                {
                    "retrieval_accuracy": summary["retrieval_accuracy"],
                    "answer_correctness": summary["answer_correctness"],
                    "hallucination_rate": summary["hallucination_rate"],
                    "avg_latency_ms": summary["average_latency_ms"],
                    "p95_latency_ms": summary["p95_latency_ms"],
                    "total_questions": total,
                    "error_count": summary["error_count"],
                    "provider_errors": summary["provider_errors"],
                }
            )
            mlflow.end_run(status="FINISHED")
        except Exception:
            try:
                mlflow.end_run(status="FAILED")
            except Exception:
                pass

    return summary


def validate_questions_only(path: str) -> int:
    """Validate the question set structure without hitting a live backend.

    Used by CI so the eval workflow stays green without a deployed API.
    Returns number of questions validated.
    """
    questions = load_questions(path)
    errors = []
    for i, q in enumerate(questions, start=1):
        if not q.get("question"):
            errors.append(f"q{i}: missing 'question'")
        if not (q.get("expected_answer") or q.get("golden_answer") or q.get("expected_answer_contains")):
            errors.append(f"q{i}: missing expected answer field")
        expected = q.get("expected_answer_contains") or q.get("expected_source_keywords")
        if expected is not None and not isinstance(expected, list):
            errors.append(f"q{i}: expected fields must be lists")
        for field in ("difficulty", "tags"):
            if field in q and not isinstance(q[field], (str, list)):
                errors.append(f"q{i}: invalid '{field}' type")
    if errors:
        raise SystemExit(f"Question set invalid:\n  " + "\n  ".join(errors))
    print(f"[validate-questions] OK: {len(questions)} questions valid in {path}")
    return len(questions)


def main():
    parser = argparse.ArgumentParser(description="RAG Evaluation Pipeline")
    parser.add_argument(
        "--base-url", default="http://localhost:8080/api", help="Backend API base URL"
    )
    parser.add_argument(
        "--token",
        default=None,
        help="JWT auth token (required for live evaluation, not for --validate-only)",
    )
    parser.add_argument(
        "--document-id",
        type=int,
        default=None,
        help="Document ID to evaluate against",
    )
    parser.add_argument(
        "--questions", default="eval/questions.json", help="Path to questions JSON file"
    )
    parser.add_argument(
        "--output",
        default="eval/results/eval_results.json",
        help="Path to write evaluation results",
    )
    parser.add_argument(
        "--mlflow", action="store_true", help="Log results to MLflow tracking server"
    )
    parser.add_argument(
        "--mlflow-uri", default="http://mlflow:5000", help="MLflow tracking server URI"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate question set structure (CI-safe, no backend needed)",
    )
    parser.add_argument(
        "--llm-judge",
        action="store_true",
        help="Enable LLM-judge evaluation (faithfulness + relevance scores)",
    )
    parser.add_argument(
        "--llm-judge-url",
        default=None,
        help="LLM judge base URL (defaults to LLM_JUDGE_BASE_URL or LLM_BASE_URL)",
    )
    parser.add_argument(
        "--llm-judge-model",
        default=None,
        help="LLM judge model name (defaults to LLM_JUDGE_MODEL or LLM_CHAT_MODEL)",
    )

    args = parser.parse_args()

    if args.validate_only or args.token is None or args.document_id is None:
        validate_questions_only(args.questions)
        return

    summary = run_evaluation(args)

    # Print summary
    print()
    print("=" * 60)
    print("📊 EVALUATION RESULTS")
    print("=" * 60)
    print(f"  Total Questions:      {summary['total_questions']}")
    print(f"  Retrieval Accuracy:   {summary['retrieval_accuracy']:.2%}")
    print(f"  Semantic Retr. Score: {summary['semantic_retrieval_score']:.4f}")
    print(f"  Answer Correctness:   {summary['answer_correctness']:.2%}")
    print(f"  Hallucination Cases:  {summary['hallucination_cases']}")
    print(f"  Hallucination Rate:   {summary['hallucination_rate']:.2%}")
    print(f"  Avg Latency:          {summary['average_latency_ms']}ms")
    print(f"  P95 Latency:          {summary['p95_latency_ms']}ms")
    print(f"  Errors:               {summary['error_count']}")

    if summary.get("llm_judge_enabled"):
        print()
        print("  LLM Judge Metrics:")
        if summary.get("llm_judge_avg_faithfulness") is not None:
            print(f"     Faithfulness:  {summary['llm_judge_avg_faithfulness']:.4f}")
        if summary.get("llm_judge_avg_relevance") is not None:
            print(f"     Relevance:     {summary['llm_judge_avg_relevance']:.4f}")
        if summary.get("llm_judge_avg_score") is not None:
            print(f"     Overall Score: {summary['llm_judge_avg_score']:.4f}")

    print("=" * 60)

    # Save results
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Results saved to: {args.output}")


if __name__ == "__main__":
    main()
