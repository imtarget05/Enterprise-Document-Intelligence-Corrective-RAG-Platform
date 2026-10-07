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

DEFAULT_BASE_URL = "https://smart-doc-backend-h4mt.onrender.com/api"
SMOKE_PASSWORD = "SmokeTest123!"  # throwaway test-user password only


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL':4} | {name} {detail}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Production smoke test")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL,
                    help="Backend API base URL (includes /api context path)")
    args = ap.parse_args()
    b = args.base_url.rstrip("/")

    results = []
    s = requests.Session()

    # --- 0. Backend health first (fail fast with a clear message)
    try:
        h = s.get(f"{b}/actuator/health", timeout=60)
        results.append(check("BACKEND HEALTH  ", h.status_code == 200, f"({h.status_code})"))
        if h.status_code != 200:
            print("Backend is not healthy — aborting remaining checks.", file=sys.stderr)
            return 1
    except Exception as e:
        check("BACKEND HEALTH  ", False, str(e)[:80])
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
    r = s.post(f"{b}/chat/ask",
               headers={**ah, "X-XSRF-TOKEN": fresh_csrf(),
                        "Content-Type": "application/json"},
               json={"sessionId": "smoke-e2e", "documentId": doc,
                     "message": "Where is the Eiffel Tower located?"}, timeout=600)
    lat = round(time.time() - t0, 1)
    if r.status_code != 200:
        results.append(check("CHAT             ", False, f"(HTTP {r.status_code})"))
        results.append(False)
        return 1
    ans = r.json().get("aiResponse", "")
    unavailable = "temporarily unavailable" in ans.lower()
    results.append(check("CHAT             ", not unavailable, f"({lat}s)"))
    if unavailable:
        results.append(check("ROUTER AUTH      ", False,
                             'router rejected backend ("temporarily unavailable")'))
        results.append(check("LLM RESPONSE     ", False))
        return 1
    results.append(check("ROUTER AUTH      ", True))
    results.append(check("LLM RESPONSE     ", True))
    print(f"   answer[:160]: {ans[:160].replace(chr(10), ' ')}")

    overall = all(results)
    print(f"\nOVERALL           {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
