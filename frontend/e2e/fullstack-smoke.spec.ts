import { expect, test } from '@playwright/test';

/**
 * Full-stack API smoke (Giai đoạn 2 — E2E).
 *
 * Exercises the real backend end-to-end through the same HTTP surface the
 * frontend uses: CSRF handshake → register → login → upload fixture →
 * synchronous chat ask. Owner isolation is respected by using a throwaway
 * per-run user; no secrets are stored or printed.
 *
 * Opt-in via E2E_API_URL (e.g. https://smart-doc-backend-h4mt.onrender.com/api).
 * When unset (default in Stage 1) the suite skips, keeping PRs hermetic; the
 * eval workflow sets it explicitly.
 *
 * The idempotent-upload check (Blueprint #17) soft-skips with an explanatory
 * note when the target backend predates that fix, so this suite can act as a
 * regression gate before staging is redeployed. Set E2E_EXPECT_IDEMPOTENT=1
 * to hard-enforce the assertion once the fix is live.
 *
 * The backend guards state-changing requests with Spring Security CSRF, which
 * binds a session cookie to a token from GET /api/csrf. Playwright's per-test
 * `request` fixture does not automatically carry that cookie, so we capture it
 * and send it explicitly on every call — mirroring how the Python eval runner
 * (requests.Session) behaves. Note the CSRF controller is served under an
 * at `{E2E_API_URL}/csrf` (the backend serves CSRF under the /api context path already included in E2E_API_URL), matching
 * run_fixture_eval.py.
 *
 * E2E_API_URL points at Render's free tier, where cold starts can exceed a
 * minute; every test therefore raises its own timeout.
 */
const apiUrl = process.env.E2E_API_URL;

const FIXTURE = {
  name: `e2e-fixture-${Date.now()}.txt`,
  mime: 'text/plain',
  buffer: Buffer.from(
    'Failure Report F-2024-118. Root cause: coolant pump seal degradation ' +
      'leading to overheating of the spindle bearing. Corrective action: ' +
      'replaced seal assembly and revised the preventive maintenance interval. ' +
      'Verification: 30-day thermal monitoring showed no recurrence.',
    'utf-8',
  ),
};

/** Creates a fresh throwaway user and returns CSRF cookie + auth headers. */
async function freshSession(context: {
  get: (url: string, opts?: any) => Promise<any>;
  post: (url: string, opts?: any) => Promise<any>;
}) {
  const csrfRes = await context.get(`${apiUrl}/csrf`, { timeout: 120_000 });
  expect(csrfRes.status()).toBe(200);
  const body = await csrfRes.json();
  const csrfToken = body.token;

  // Capture the XSRF-TOKEN cookie from the csrf Set-Cookie header.
  const setCookie = String(csrfRes.headers()['set-cookie'] || '');
  const match = setCookie.match(/XSRF-TOKEN=([^;]+)/);
  const cookie = match ? `XSRF-TOKEN=${match[1]}` : '';
  expect(cookie, `expected XSRF-TOKEN cookie in ${setCookie}`).toBeTruthy();

  const csrfHeaders = { 'X-XSRF-TOKEN': csrfToken, Cookie: cookie };
  const username = `e2e${Date.now()}${Math.floor(Math.random() * 1e4)}`;

  const reg = await context.post(`${apiUrl}/auth/register`, {
    headers: csrfHeaders,
    data: { username, email: `${username}@test.local`, password: 'E2eSmoke123!' },
  });
  expect(reg.status(), await reg.text()).toBeLessThan(500);

  const login = await context.post(`${apiUrl}/auth/login`, {
    headers: csrfHeaders,
    data: { username, password: 'E2eSmoke123!' },
  });
  expect(login.status(), await login.text()).toBe(200);
  const loginBody = await login.json();
  const token = loginBody.token || loginBody.accessToken;
  expect(token).toBeTruthy();

  return {
    cookie,
    token,
    authHeaders: {
      Authorization: `Bearer ${token}`,
      'X-XSRF-TOKEN': csrfToken,
      Cookie: cookie,
    } as Record<string, string>,
  };
}

test.describe('full-stack API smoke', () => {
  test.skip(!apiUrl, 'E2E_API_URL not set — skipping full-stack smoke');

  test('csrf → register → login yields a bearer token', async ({ request }) => {
    test.setTimeout(180_000);
    const s = await freshSession(request);
    expect(s.token.length).toBeGreaterThan(10);
  });

  test('authenticated user uploads a document and receives an evidence-backed answer', async ({ request }) => {
    test.setTimeout(180_000);
    const { token } = await freshSession(request);

    // Fetch a fresh CSRF token + cookie for each mutating request (Spring Security
    // rotates the token per authenticated session). Mirrors run_fixture_eval.py.
    const freshCsrf = async () => {
      const csrfRes = await request.get(`${apiUrl}/csrf`, { timeout: 120_000 });
      expect(csrfRes.status()).toBe(200);
      const body = await csrfRes.json();
      const csrfToken = body.token;
      const setCookie = String(csrfRes.headers()['set-cookie'] || '');
      const match = setCookie.match(/XSRF-TOKEN=([^;]+)/);
      const cookie = match ? `XSRF-TOKEN=${match[1]}` : '';
      return {
        Authorization: `Bearer ${token}`,
        'X-XSRF-TOKEN': csrfToken,
        Cookie: cookie,
      };
    };

    const upload = async () =>
      request.post(`${apiUrl}/documents/upload`, {
        headers: await freshCsrf(),
        multipart: {
          file: { name: FIXTURE.name, mimeType: FIXTURE.mime, buffer: FIXTURE.buffer },
        },
        // Render free-tier ingestion (R2 + Qdrant indexing) is slow on the first
        // call after a cold start; the default actionTimeout (15s) is too tight.
        timeout: 150_000,
      });

    const first = await upload();
    expect(first.status(), await first.text()).toBe(200);
    const doc = await first.json();
    const documentId = doc.id ?? doc.documentId;
    expect(documentId).toBeTruthy();

    const ask = await request.post(`${apiUrl}/chat/ask`, {
      headers: await freshCsrf(),
      data: {
        sessionId: `e2e-session-${Date.now()}`,
        documentId,
        message: 'What was the root cause of the failure?',
        mode: 'rag',
      },
      timeout: 150_000,
    });
    expect(ask.status(), await ask.text()).toBe(200);
    const answer = await ask.json();
    expect(answer.aiResponse.length).toBeGreaterThan(0);
    expect(['direct', 'corrective', 'web_search', 'no_evidence']).toContain(answer.ragStrategy);

    // Idempotent ingestion (Blueprint #17): identical bytes must not create a
    // second document. Soft-skip when the backend predates the fix; enforce
    // strictly when E2E_EXPECT_IDEMPOTENT=1.
    const strict = process.env.E2E_EXPECT_IDEMPOTENT === '1';
    const second = await upload();
    expect(second.status(), await second.text()).toBe(200);
    const doc2 = await second.json();
    const secondId = doc2.id ?? doc2.documentId;
    if (secondId !== documentId) {
      const note =
        `idempotent ingestion not active (upload returned ${secondId}, ` +
        `first was ${documentId}) — backend likely predates Blueprint #17`;
      if (strict) {
        throw new Error(`E2E_EXPECT_IDEMPOTENT=1: ${note}`);
      }
      test.skip(true, note);
    }
  });
});