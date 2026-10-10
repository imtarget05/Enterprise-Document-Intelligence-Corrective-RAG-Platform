#!/usr/bin/env python3
"""Production smoke test — verifies each boundary of the chat pipeline.

Checks:
  1. GET /api/csrf                (CSRF contract)
  2. JWT authentication           (register + login a throwaway test user)
  3. Document upload              (fixture owned by the test user)
  4. Owner isolation              (unauthenticated access is rejected)
  5. POST /chat/ask               (full chain incl. Spring Security CSRF)
  6. Backend -> Router auth       (X-Internal-Token accepted, no "temporarily unavailable")
  7. LLM response                 (actual assistant answer received)

Credentials are supplied at runtime (never hardcoded):
    python scripts/production_smoke.py --base-url https://<backend>.onrender.com/api

The script creates its own throwaway user and document, so it does not depend
on any pre-existing production state. It never prints secrets or full JWTs.

Exit code: 0 if all critical checks pass, 1 otherwise.
"""
import argparse
import sys
import time

import requests

DEFAULT_BASE_URL = "https://smartdoc-api.blackisland-5a3f0246.southeastasia.azurecontainerapps.io/api"
SMOKE_PASSWORD = "SmokeTest123!"  # throwaway test-user password only


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL':4} | {name} {detail}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Production smoke test")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL,
                    help="Backend API base URL (includes /api context path)")
    ap.add_argument("--mode", choices=("agent", "rag"), default="agent",
                    help="Chat path to test; use rag to isolate retrieval from the agent service")
    ap.add_argument("--browser-origin", default="",
                    help="Check credentialed CORS and JWT cookie for this Pages origin")
    args = ap.parse_args()
    b = args.base_url.rstrip("/")

    results = []
    s = requests.Session()
    if args.browser_origin:
        s.headers["Origin"] = args.browser_origin

    # --- 0. Render free-tier cold starts can outlast a single 60s request.
    health_error = "no response"
    for attempt in range(3):
        try:
            h = s.get(f"{b}/actuator/health", timeout=60)
            if h.status_code == 200 and h.json().get("status") == "UP":
                results.append(check("BACKEND HEALTH  ", True, f"(attempt {attempt + 1})"))
                break
            health_error = f"HTTP {h.status_code}"
        except Exception as exc:
            health_error = str(exc)[:80]
        if attempt == 2:
            check("BACKEND HEALTH  ", False, health_error)
            return 1
        time.sleep(5)

    if args.browser_origin:
        preflight = s.options(f"{b}/auth/login", headers={
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-xsrf-token",
        }, timeout=30)
        cors_ok = (preflight.headers.get("Access-Control-Allow-Origin") == args.browser_origin
                   and preflight.headers.get("Access-Control-Allow-Credentials", "").lower() == "true")
        results.append(check("BROWSER CORS     ", cors_ok,
                             f"(HTTP {preflight.status_code}, origin={preflight.headers.get('Access-Control-Allow-Origin', 'missing')})"))
        if not cors_ok:
            return 1

    # --- 1. CSRF endpoint
    try:
        csrf = s.get(f"{b}/csrf", timeout=60).json()["token"]
        results.append(check("CSRF             ", bool(csrf)))
    except Exception as e:
        check("CSRF             ", False, str(e)[:80])
        return 1

    # --- 2. JWT authentication (throwaway user)
    h = {"X-XSRF-TOKEN": csrf}
    u = f"smoke{int(time.time())}"
    s.post(f"{b}/auth/register", headers=h,
           json={"username": u, "email": f"{u}@test.local",
                 "password": SMOKE_PASSWORD}, timeout=120)
    r = s.post(f"{b}/auth/login", headers=h,
               json={"username": u, "password": SMOKE_PASSWORD}, timeout=120)
    jwt = r.json().get("token") or r.json().get("accessToken")
    cookie_jwt = s.cookies.get("jwt_token")
    # The prod profile suppresses the JSON `token` field and delivers the JWT
    # only via the HttpOnly `jwt_token` cookie (CSRF-protected flow). Fall
    # back to the session cookie so the same script works in both profiles.
    if r.status_code == 200 and (jwt or cookie_jwt):
        auth_detail = f"({r.status_code}, {'cookie' if cookie_jwt else 'bearer'})"
    else:
        auth_detail = f"({r.status_code}, no token in body or cookie)"
    results.append(check("JWT              ",
                         r.status_code == 200 and (jwt or cookie_jwt), auth_detail))
    if not (jwt or cookie_jwt):
        return 1
    if args.browser_origin:
        jwt_headers = [value.lower() for value in r.raw.headers.getlist("Set-Cookie")
                       if value.lower().startswith("jwt_token=")]
        cookie_ok = any("samesite=none" in value and "secure" in value
                        for value in jwt_headers)
        results.append(check("BROWSER COOKIE   ", cookie_ok,
                             "(JWT requires SameSite=None; Secure for cross-site Pages)"))
        if not cookie_ok:
            return 1
    # Cookie auth: the session already carries jwt_token — send no Authorization
    # header. Bearer auth: attach the token from the JSON body.
    ah = {} if cookie_jwt else {"Authorization": f"Bearer {jwt}"}

    def fresh_csrf():
        return s.get(f"{b}/csrf", timeout=60).json()["token"]

    # --- 3. Upload test document owned by the test user
    content = (b"Deployment verification document. The Eiffel Tower is located in "
               b"Paris, France and was completed in 1889. The capital of Japan is Tokyo.")
    r = s.post(f"{b}/documents/upload",
               headers={**ah, "X-XSRF-TOKEN": fresh_csrf()},
               files={"file": ("smoke_doc.txt", content, "text/plain")}, timeout=300)
    doc = r.json().get("documentId") if r.status_code == 200 else None
    results.append(check("DOC UPLOAD       ",
                         r.status_code == 200 and doc is not None, f"(docId={doc})"))

    # --- 4. Owner isolation: unauthenticated document access must be rejected
    # NOTE: allow_redirects=False — unauthenticated requests are redirected
    # (302) to the OAuth2 entry point, which lands on accounts.google.com with
    # 200. Following redirects would make this check a false positive.
    r_anon = requests.Session().get(f"{b}/documents/{doc}", timeout=60,
                                    allow_redirects=False)
    results.append(check("OWNER ISOLATION  ",
                         r_anon.status_code in (301, 302, 303, 307, 308, 401, 403),
                         f"(anon GET -> {r_anon.status_code})"))

    # --- 5-7. Full chain: eval -> backend -> router -> LLM
    t0 = time.time()
    try:
        r = s.post(f"{b}/chat/ask",
                   headers={**ah, "X-XSRF-TOKEN": fresh_csrf(),
                            "Content-Type": "application/json"},
                   json={"sessionId": "smoke-e2e", "documentId": doc,
                         "message": "Where is the Eiffel Tower located?",
                         "mode": args.mode}, timeout=180)
    except requests.RequestException as exc:
        results.append(check("CHAT             ", False,
                             f"({args.mode}, {round(time.time() - t0, 1)}s, {str(exc)[:80]})"))
        return 1
    lat = round(time.time() - t0, 1)
    if r.status_code != 200:
        results.append(check("CHAT             ", False,
                             f"({args.mode}, HTTP {r.status_code}, {lat}s, body={r.text[:120]!r})"))
        results.append(False)
        return 1
    response = r.json()
    ans = response.get("aiResponse", "")
    strategy = response.get("ragStrategy", "")
    unavailable = "temporarily unavailable" in ans.lower()
    results.append(check("CHAT             ", not unavailable, f"({lat}s, strategy={strategy})"))
    if unavailable:
        results.append(check("ROUTER AUTH      ", False,
                             'router rejected backend ("temporarily unavailable")'))
        results.append(check("LLM RESPONSE     ", False))
        return 1
    results.append(check("ROUTER AUTH      ", True))
    results.append(check("LLM RESPONSE     ", True))
    if args.mode == "agent":
        results.append(check("AGENT PATH       ", strategy == "agentic",
                             f"(strategy={strategy}; fallback RAG is not agent success)"))
    print(f"   answer[:160]: {ans[:160].replace(chr(10), ' ')}")

    overall = all(results)
    print(f"\nOVERALL           {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
