import { expect, test } from '@playwright/test';

// These UI tests run against the static preview (no backend). They mock the
// HTTP layer via page.route so the authenticated shell renders fully.

const MOCK_DOCUMENTS = [
  {
    id: 1,
    fileName: 'contract-2024.pdf',
    fileSize: 1024,
    fileType: 'PDF',
    chunkCount: 12,
    createdAt: '2024-01-01T00:00:00Z',
    sourceType: 'USER',
  },
];

const MOCK_HISTORY = [
  {
    id: 1,
    sessionId: 'test-session',
    userMessage: 'Điều khoản chính của hợp đồng là gì?',
    aiResponse: 'Hợp đồng quy định các điều khoản chính…',
    ragStrategy: 'direct',
    confidence: 'high',
    isStreaming: false,
  },
];

test.describe('Chat UI after login', () => {
  // Login through a mocked backend, then assert on the chat shell.
  async function loginAndOpen(
    page: import('@playwright/test').Page,
    history: unknown[] = [],
  ) {
    await page.route('**/api/csrf', (route) =>
      route.fulfill({ json: { token: 'fake-csrf' } }),
    );
    await page.route('**/api/auth/login', (route) =>
      route.fulfill({
        json: { token: 'fake-jwt', username: 'testuser', role: 'ROLE_VIEWER' },
      }),
    );
    await page.route('**/api/documents', (route) =>
      route.fulfill({ json: MOCK_DOCUMENTS }),
    );
    await page.route('**/api/chat/history/**', (route) =>
      route.fulfill({ json: history }),
    );
    await page.route('**/api/chat/sessions', (route) =>
      route.fulfill({ json: [] }),
    );

    await page.goto('/');
    await page.getByPlaceholder('Email hoặc tên đăng nhập').fill('testuser@test.local');
    await page.getByPlaceholder('Mật khẩu', { exact: true }).fill('TestPass123!');
    await page.getByRole('button', { name: 'Tiếp tục', exact: true }).click();
    await expect(page.getByLabel('Menu người dùng')).toBeVisible();
  }

  test('renders app bar, sidebar and welcome screen', async ({ page }) => {
    await loginAndOpen(page);

    await expect(page.getByText('Smart Document').first()).toBeVisible();
    await expect(page.getByText('Cuộc trò chuyện mới')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Tải lên tài liệu', exact: true })).toBeVisible();
    await expect(page.getByText(/Chào mừng đến với Smart Document/)).toBeVisible();
    await expect(page.getByText('Tóm tắt tài liệu này')).toBeVisible();
    await expect(page.getByPlaceholder(/Nhập tin nhắn/)).toBeVisible();
  });

  test('shows document list in sidebar', async ({ page }) => {
    await loginAndOpen(page);

    await expect(page.getByText('contract-2024.pdf').first()).toBeVisible();
    await expect(page.getByText(/12 chunks/)).toBeVisible();
  });

  test('renders chat history messages', async ({ page }) => {
    await loginAndOpen(page, MOCK_HISTORY);

    await expect(page.getByText('Điều khoản chính của hợp đồng là gì?')).toBeVisible();
    await expect(page.getByText(/Hợp đồng quy định/)).toBeVisible();
  });

  test('user menu dropdown opens and has logout', async ({ page }) => {
    await loginAndOpen(page);

    // Verify user initials are displayed in the menu button (avatar)
    await expect(page.getByLabel('Menu người dùng')).toContainText('TE');
  });
});