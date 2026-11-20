#!/usr/bin/env python3
"""Verify a missing selected Qdrant collection cannot produce an uncited answer."""

import argparse
import json
import os
import time
import uuid

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="http://127.0.0.1:19003/v1")
    parser.add_argument("--qdrant", default="http://127.0.0.1:6333")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    token = os.environ.get("INTERNAL_SERVICE_TOKEN")
    if not token:
        parser.error("INTERNAL_SERVICE_TOKEN must be set")

    document_id = str(int(time.time() * 1_000_000))
    collection = requests.get(f"{args.qdrant}/collections/{document_id}", timeout=15)
    if collection.status_code != 404:
        raise RuntimeError(f"Expected a missing collection, got HTTP {collection.status_code}")
    session_id = "retrieval-failure-" + uuid.uuid4().hex[:10]
    started = time.perf_counter()
    response = requests.post(args.agent + "/agent/invoke", json={
        "query": "According to the selected document, what is the capital of France?",
        "session_id": session_id, "user_id": "local-failure-drill",
        "document_ids": [document_id], "intent_override": "rag", "use_web_search": False,
    }, headers={"X-Internal-Token": token}, timeout=180)
    response.raise_for_status()
    result = response.json()
    answer = result.get("answer", "")
    passed = ("Paris" not in answer and "selected documents" in answer
              and result.get("answer_origin") == "abstention"
              and not result.get("sources"))
    evidence = {"kind": "missing_selected_collection", "session_id": session_id,
                "document_id": document_id, "qdrant_collection_http_status": collection.status_code,
                "agent_http_status": response.status_code, "agent_answer": answer,
                "answer_origin": result.get("answer_origin"),
                "agent_sources": result.get("sources"), "agent_type": result.get("agent_type"),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "passed": passed, "environment": "localhost; Ollama qwen2.5:1.5b; Qdrant"}
    with open(args.output, "w", encoding="utf-8") as output:
        json.dump(evidence, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"passed": passed, "evidence": args.output}))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
