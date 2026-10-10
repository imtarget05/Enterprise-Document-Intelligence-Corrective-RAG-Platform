import { expect, test } from '@playwright/test';

const apiUrl = process.env.E2E_API_URL;
const pagesUrl = process.env.E2E_BASE_URL;

test('Pages browser keeps the cross-site auth cookie', async ({ page }) => {
  test.skip(!apiUrl || !pagesUrl, 'Live Pages and API URLs are required');
  test.setTimeout(180_000);

  await page.goto(pagesUrl!);
  const result = await page.evaluate(async (api) => {
    const credentials: RequestCredentials = 'include';
    const csrfResponse = await fetch(`${api}/csrf`, { credentials });
    if (!csrfResponse.ok) return { step: 'csrf', status: csrfResponse.status };
    const csrf = (await csrfResponse.json()) as { token: string };
    const headers = { 'Content-Type': 'application/json', 'X-XSRF-TOKEN': csrf.token };
    const name = `browser-smoke-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
    const password = 'BrowserSmoke123!';

    const registration = await fetch(`${api}/auth/register`, {
      method: 'POST', credentials, headers,
      body: JSON.stringify({ username: name, email: `${name}@test.local`, password }),
    });
    if (!registration.ok) return { step: 'register', status: registration.status, detail: (await registration.text()).slice(0, 300) };

    const login = await fetch(`${api}/auth/login`, {
      method: 'POST', credentials, headers,
      body: JSON.stringify({ username: name, password }),
    });
    if (!login.ok) return { step: 'login', status: login.status, detail: (await login.text()).slice(0, 300) };

    const me = await fetch(`${api}/auth/me`, { credentials });
    return { step: 'me', status: me.status };
  }, apiUrl!);

  expect(result, JSON.stringify(result)).toEqual({ step: 'me', status: 200 });
});
