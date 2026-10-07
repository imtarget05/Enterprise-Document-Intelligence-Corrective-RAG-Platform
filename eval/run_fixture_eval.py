#!/usr/bin/env python3
"""Reproducible fixture benchmark.

End-to-end regression workflow:
  1. Register/login a throwaway evaluation user (owner isolation respected)
  2. Upload eval/fixtures/8d_failure_risk_fixture.txt as that user
  3. Run eval/eval.py against the owned document ID

Usage:
    python eval/run_fixture_eval.py \
        --base-url https://smartdoc-backend-2hhz.onrender.com/api \
        [--questions eval/agent_questions.json]

Credentials are created at runtime — no secrets are stored or printed.
Exit code: 0 only if the evaluation reports zero errors.
"""
import argparse
import importlib.util
import json
import os
import pathlib
import sys
import time

import requests

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "8d_failure_risk_fixture.txt"


def load_eval_module():
    spec = importlib.util.spec_from_file_location("fixture_eval", HERE / "eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the fixture benchmark")
    ap.add_argument("--base-url", required=True,
                    help="Backend API base URL (includes /api context path)")
    ap.add_argument("--questions",
                    default=str(HERE / "agent_questions.json"))
    ap.add_argument("--output", default=str(HERE / "results" / "fixture_eval.json"))
    args = ap.parse_args()
    b = args.base_url.rstrip("/")

    s = requests.Session()

    def csrf():
        return s.get(f"{b}/csrf", timeout=60).json()["token"]

    # 1. Throwaway evaluation user
    u = f"fixtbench{int(time.time())}"
    h = {"X-XSRF-TOKEN": csrf()}
    s.post(f"{b}/auth/register", headers=h,
           json={"username": u, "email": f"{u}@test.local",
                 "password": "FixtureBench123!"}, timeout=120)
    r = s.post(f"{b}/auth/login", headers=h,
               json={"username": u, "password": "FixtureBench123!"}, timeout=120)
    jwt = r.json().get("token") or r.json().get("accessToken")
    if not jwt:
        print("FATAL: login failed", file=sys.stderr)
        return 1

    # 2. Upload fixture (owned by the evaluation user). CI races Render
    # redeploys, so tolerate transient 5xx/timeouts with a short backoff.
    doc = None
    for attempt in range(1, 4):
        try:
            r = s.post(f"{b}/documents/upload",
                       headers={"Authorization": f"Bearer {jwt}",
                                "X-XSRF-TOKEN": csrf()},
                       files={"file": (FIXTURE.name, FIXTURE.read_bytes(), "text/plain")},
                       timeout=300)
            doc = r.json().get("documentId") if r.status_code == 200 else None
        except requests.RequestException as exc:
            print(f"upload attempt {attempt} failed: {exc}", file=sys.stderr)
        if doc is not None:
            break
        time.sleep(15 * attempt)
    if doc is None:
        print("FATAL: fixture upload failed after retries", file=sys.stderr)
        return 1
    print(f"✅ Fixture uploaded: documentId={doc} (user={u})")

    # 3. Run the standard evaluator against the owned document
    eval_mod = load_eval_module()
    ns = argparse.Namespace(base_url=b, token=jwt, document_id=int(doc),
                            questions=args.questions, output=args.output,
                            mlflow=False, mlflow_uri="http://mlflow:5000")
    summary = eval_mod.run_evaluation(ns)
    errors = summary.get("error_count", 0)
    provider_errors = summary.get("provider_errors", 0)
    # run_evaluation() returns the summary; persist full per-question details
    out = {"summary": summary, "details": summary.get("details", [])}
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    clean = errors == 0 and provider_errors == 0
    print(f"\nFIXTURE BENCHMARK: {'PASS' if clean else 'FAIL'} "
          f"(errors={errors}, provider_errors={provider_errors}, results -> {args.output})")
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
