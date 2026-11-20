#!/usr/bin/env python3
"""Exercise one local upload, grounded agent answer, and rejected HITL action."""

import argparse
import io
import json
import os
import re
import time
import uuid

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="http://127.0.0.1:18085/api")
    parser.add_argument("--agent", default="http://127.0.0.1:19003/v1")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    internal_token = os.environ.get("INTERNAL_SERVICE_TOKEN")
    if not internal_token:
        parser.error("INTERNAL_SERVICE_TOKEN must be set")
    session = requests.Session()
    username = "agentdemo" + uuid.uuid4().hex[:10]
    session_id = "upload-hitl-" + uuid.uuid4().hex[:10]

    def csrf():
        session.get(args.backend + "/csrf", timeout=15).raise_for_status()
        return {"X-XSRF-TOKEN": session.cookies.get("XSRF-TOKEN", "")}

    def post(path, *, headers=None, **kwargs):
        response = session.post(args.backend + path, headers={**(headers or {}), **csrf()}, timeout=180, **kwargs)
        response.raise_for_status()
        return response.json()

    started = time.perf_counter()
    registration = post("/auth/register", json={"username": username,
        "email": username + "@example.test", "password": "LocalDemoPass123!"})
    auth = {"Authorization": "Bearer " + registration["token"]}
    upload = post("/documents", headers=auth, files={"file": (
        "paris.txt", io.BytesIO(b"The capital of France is Paris. Paris is in France."), "text/plain")})
    document_id = upload["documentId"]
    indexed = post(f"/documents/{document_id}/agent-index", headers=auth)
    answer = post("/chat", headers=auth, json={"sessionId": session_id,
        "documentId": document_id, "message": "What is the capital of France according to my uploaded document?",
        "mode": "agent"})
    if indexed.get("status") != "indexed" or answer.get("answerOrigin") != "agent":
        raise AssertionError("Upload-to-agent path did not complete")
    if "Paris" not in answer.get("aiResponse", ""):
        raise AssertionError("Answer omitted the expected fact")
    if not any(source.get("documentId") == document_id for source in answer.get("sources", [])):
        raise AssertionError("Answer omitted a citation to the uploaded document")

    action = post("/chat", headers=auth, json={"sessionId": session_id,
        "documentId": document_id, "message": "Create a Jira task to review this document.", "mode": "agent"})
    match = re.search(r"Mã phê duyệt:\s*(hitl-[a-f0-9]+)", action.get("aiResponse", ""))
    if not match:
        raise AssertionError("Action did not enter HITL approval: " + action.get("aiResponse", "")[:400])
    approval_id = match.group(1)
    rejected_response = session.post(args.agent + f"/agent/approvals/{approval_id}/reject",
        json={"approver": "local-demo-reviewer", "note": "Controlled rejection drill"},
        headers={"X-Internal-Token": internal_token}, timeout=20)
    rejected_response.raise_for_status()
    rejected = rejected_response.json()
    if rejected.get("decision") != "rejected":
        raise AssertionError("Approval did not reach rejected state")

    result = {"kind": "local_upload_agent_hitl", "session_id": session_id,
        "document_id": document_id, "index": indexed, "answer": {
            "text": answer.get("aiResponse"), "origin": answer.get("answerOrigin"),
            "sources": answer.get("sources")}, "approval": {
            "request_id": approval_id, "decision": rejected["decision"]},
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "environment": "localhost; Ollama qwen2.5:1.5b + nomic-embed-text; Qdrant; PostgreSQL; Redis"}
    with open(args.output, "w", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"document_id": document_id, "answer_origin": result["answer"]["origin"],
                      "approval_decision": rejected["decision"], "evidence": args.output}))


if __name__ == "__main__":
    main()
