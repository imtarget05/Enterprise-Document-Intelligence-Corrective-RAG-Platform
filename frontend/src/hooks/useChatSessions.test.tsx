import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useChatSessions, relativeTime } from "./useChatSessions";

function makeWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("relativeTime", () => {
  it("returns 'Vừa xong' for timestamps less than a minute old", () => {
    expect(relativeTime(new Date(Date.now() - 5_000).toISOString())).toBe("Vừa xong");
  });

  it("returns minutes for timestamps under an hour old", () => {
    expect(relativeTime(new Date(Date.now() - 5 * 60_000).toISOString())).toBe("5 phút trước");
  });

  it("returns hours for timestamps under a day old", () => {
    expect(relativeTime(new Date(Date.now() - 3 * 3_600_000).toISOString())).toBe("3 giờ trước");
  });

  it("returns days for timestamps under a week old", () => {
    expect(relativeTime(new Date(Date.now() - 2 * 86_400_000).toISOString())).toBe("2 ngày trước");
  });

  it("falls back to a locale date string for older timestamps", () => {
    const old = new Date(Date.now() - 30 * 86_400_000).toISOString();
    expect(relativeTime(old)).toBe(new Date(old).toLocaleDateString("vi-VN"));
  });
});

describe("useChatSessions", () => {
  it("fetches sessions and returns them on success", async () => {
    const sessions = [
      { sessionId: "s1", lastMessage: "hello", messageCount: 2, createdAt: "2024-01-01T00:00:00Z", updatedAt: new Date().toISOString() },
      { sessionId: "s2", lastMessage: "world", messageCount: 5, createdAt: "2024-01-02T00:00:00Z", updatedAt: new Date().toISOString() },
    ];
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ sessions }), { status: 200, headers: { "Content-Type": "application/json" } })
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChatSessions(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(sessions);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/chat/sessions");
    expect(init.credentials).toBe("include");
  });

  it("returns an empty array when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500 })));

    const { result } = renderHook(() => useChatSessions(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });

  it("returns an empty array when the sessions key is missing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } }))
    );

    const { result } = renderHook(() => useChatSessions(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });
});
