# Contributing — Enterprise RAG

Conventions: ECC (TDD, immutability, 80%+ coverage, conventional commits, security review, code review).

## Branch & commit
- Create branch from `main`: `feat/<scope>`, `fix/<scope>`, `refactor/<scope>`, `docs/<scope>`, `test/<scope>`, `chore/<scope>`, `ci/<scope>`.
- Commit message: `type(scope): summary` + optional body + `Signed-off-by: Name <email>`.
- No direct push to `main` — PR required, reviewed, CI green.

## TDD workflow
1. Write a failing test (RED).
2. Implement the smallest change to pass (GREEN).
3. Refactor (IMPROVE), keep coverage ≥ 80% (lines/branches/functions).
4. Run `mvn verify` (backend), `npm run test:coverage` (frontend), `python -m pytest` (agent/eval).

## Immutability
- Do not mutate input models; return a new copy.
- Java: use records / immutable DTOs. Python: return new dict/list, avoid in-place ops on inputs.
- JavaScript/TS: spread / immutable helpers, no `push`/`splice` on inputs.

## Security
- No hardcoded secrets. Use env vars / secret manager; `.env.example` only contains `REPLACE_WITH_*` placeholders.
- Validate input at API boundary (Spring validation, Pydantic/Zod schema).
- Run `scripts/check_no_secrets.py` before commit; CI runs TruffleHog + gitleaks + Trivy.

## Code review
- Every PR needs ≥ 1 approval (`ecc:code-reviewer`).
- Auth / payment / user data changes additionally need `ecc:security-reviewer`.
- No merge with CI red or open security findings.

## File size
- Source file < 800 lines; split module if exceeded.

## Error handling
- Never swallow exceptions silently. Log detailed context server-side; return safe, generic messages to the client.

## Repo-specific commands
- Backend: `cd backend && mvn clean verify -B`
- Frontend: `cd frontend && npm run test:coverage && npm run build`
- Agent: `cd agent && python -m pytest tests/ -q`
- Eval: `python -m pytest eval/tests/test_grader.py -q`
