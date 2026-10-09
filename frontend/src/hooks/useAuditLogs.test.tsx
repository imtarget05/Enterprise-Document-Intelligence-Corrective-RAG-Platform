import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useAuditLogs } from "./useAuditLogs";

function makeWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

const payload = {
  page: 0,
  size: 50,
  totalElements: 0,
  totalPages: 0,
  logs: [
    {
      id: 1,
      username: "admin",
      action: "LOGIN",
      resourceType: "SESSION",
      resourceId: "s1",
      ipAddress: "127.0.0.1",
      detail: "ok",
      createdAt: "2024-01-01T00:00:00Z",
    },
  ],
};

function mockAuditLogFetch() {
  return vi.fn(async () =>
    new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } })
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useAuditLogs", () => {
  it("fetches audit logs with default page and size", async () => {
    const fetchMock = mockAuditLogFetch();
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useAuditLogs(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(payload);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/admin/audit-logs?");
    expect(url).toContain("page=0");
    expect(url).toContain("size=50");
  });

  it("includes optional filters in the query string", async () => {
    const fetchMock = mockAuditLogFetch();
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(
      () => useAuditLogs({ page: 2, size: 10, username: "admin", action: "LOGIN", from: "2024-01-01" }),
      { wrapper: makeWrapper() }
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("page=2");
    expect(url).toContain("size=10");
    expect(url).toContain("username=admin");
    expect(url).toContain("action=LOGIN");
    expect(url).toContain("from=2024-01-01");
  });

  it("throws when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("denied", { status: 403 })));

    const { result } = renderHook(() => useAuditLogs(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Failed to fetch audit logs");
  });
});
