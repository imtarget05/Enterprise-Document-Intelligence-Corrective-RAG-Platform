# Security gate review — 2026-11-13

## Verified facts

- Runtime CI run `43249675096`: backend, frontend, agent, chaos, contracts,
  graders, frontend E2E and Docker build passed. Production canary was skipped.
- Gitleaks failed on six historical fingerprints. TruffleHog scanned 26,240
  chunks / 230,713,110 bytes and returned 61 unverified results, zero verified.
  **Unverified does not mean safe or revoked.** These counts are scanner
  results, not a count of distinct live credentials.
- Gitleaks against `origin/main..HEAD` at release commit `b200e3f` scanned
  14 commits / 150,384 bytes with no leaks found. The added P0 commit alone
  also scanned clean. This does not erase findings in common history.
- The complete CPU agent suite, including the new production-readiness tests,
  passed 356 tests with one skip. See the local verification command below.

## Historical Gitleaks findings (values deliberately omitted)

| Commit | Location | Review |
|---|---|---|
| `554736d` | `frontend/functions/api/[[path]].ts:151` | Literal Google API key. Revocation has not been independently confirmed; treat as exposed. |
| `7171d55` | `scripts/_secret_leak_test.py:3` | Historical leak-test credential pattern; review provenance before any baseline exception. |
| `7171d55` | `scripts/_secret_leak_test.py:4` | Historical leak-test credential pattern; review provenance before any baseline exception. |
| `e5c5c4c` | `deploy/terraform/main.tf:75` | `password_secret_name` is a secret reference/name, not a password value. |
| `06bab797` | `.github/workflows/load-test.yml:85` | Encoded CI test JWT signing value; not evidence of a production key. |
| `9d03bad` | `.github/workflows/ci.yml:54` | Encoded CI test JWT signing value; not evidence of a production key. |

No scanner was disabled, no finding baseline/allowlist was added, and history
was not rewritten. Historical credential remediation still needs confirmed
rotation/revocation. Removing a current-source literal does not revoke it or
remove it from Git objects. Rewriting shared history would require an explicit
migration and coordination plan, rather than an automatic force-push.

## CI correction

Previously a TruffleHog failure caused all subsequent Trivy setup/scan steps
to be skipped. The final gate then failed on `TRIVY_RC unset`, without ever
checking dependency vulnerabilities. Trivy setup and scanning now use
`if: always()` so independent dependency evidence is still produced. The
TruffleHog failure remains blocking and the existing Trivy fail-closed gate
is unchanged. Missing scanner, scan errors, incomplete coverage or findings
still fail the job.

## Current Azure deployment limitation

The discovered `smartdoc-api` app in `rg-portfolio-prod` points at
`mcr.microsoft.com/k8se/quickstart:latest`, port 80. Its `/api/actuator/health`
returns HTTP 404. It is a placeholder deployment, not a working EDI backend;
its existence cannot satisfy the production canary requirement. The Render
account check did not find EDI services. No production app was overwritten.

## Reproduce safely

```sh
gitleaks git --redact=100 --log-opts 'origin/main..HEAD'
# Run the complete agent suite with test credentials and no model downloads:
APP_ENV=test REDIS_URL= HITL_STORE_BACKEND=memory HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 python -m pytest agent/tests -q
```

Keep raw credential values out of reports, workflow output and committed files.
