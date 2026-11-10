import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useChatSessions, relativeTime, saveLocalSession, deleteLocalSession } from "./useChatSessions";

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

describe("saveLocalSession", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("shifts in a new session with defaults when the id is unknown", () => {
    saveLocalSession({ sessionId: "local-1" });

    const saved = JSON.parse(localStorage.getItem("smartdoc_sessions") ?? "[]");
    expect(saved).toHaveLength(1);
    expect(saved[0]).toMatchObject({
      sessionId: "local-1",
      lastMessage: "Cuộc trò chuyện mới",
      messageCount: 1,
      createdAt: saved[0].updatedAt,
    });
  });

  it("updates an existing session in place and refreshes updatedAt", () => {
    const before = new Date(Date.now() - 60_000).toISOString();
    localStorage.setItem(
      "smartdoc_sessions",
      JSON.stringify([
        { sessionId: "s1", lastMessage: "older message", messageCount: 1, createdAt: before, updatedAt: before },
        { sessionId: "s2", lastMessage: "keep me", messageCount: 3, createdAt: before, updatedAt: before },
      ]),
    );

    saveLocalSession({ sessionId: "s1", lastMessage: "newer message", messageCount: 2 });

    const saved = JSON.parse(localStorage.getItem("smartdoc_sessions") ?? "[]");
    expect(saved).toHaveLength(2);
    const updated = saved.find((s: { sessionId: string }) => s.sessionId === "s1");
    expect(updated.lastMessage).toBe("newer message");
    expect(updated.messageCount).toBe(2);
    expect(updated.updatedAt).not.toBe(before);
    expect(saved.find((s: { sessionId: string }) => s.sessionId === "s2").lastMessage).toBe("keep me");
  });
});

describe("deleteLocalSession", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("records the id in smartdoc_deleted_sessions and drops it from smartdoc_sessions", () => {
    const now = new Date().toISOString();
    localStorage.setItem(
      "smartdoc_sessions",
      JSON.stringify([
        { sessionId: "s1", lastMessage: "a", messageCount: 1, createdAt: now, updatedAt: now },
        { sessionId: "s2", lastMessage: "b", messageCount: 1, createdAt: now, updatedAt: now },
      ]),
    );

    deleteLocalSession("s1");

    expect(JSON.parse(localStorage.getItem("smartdoc_deleted_sessions") ?? "[]")).toEqual(["s1"]);
    const list = JSON.parse(localStorage.getItem("smartdoc_sessions") ?? "[]");
    expect(list.map((s: { sessionId: string }) => s.sessionId)).toEqual(["s2"]);
  });

  it("does not duplicate an id already tracked in smartdoc_deleted_sessions", () => {
    localStorage.setItem("smartdoc_deleted_sessions", JSON.stringify(["s1"]));

    deleteLocalSession("s1");

    expect(JSON.parse(localStorage.getItem("smartdoc_deleted_sessions") ?? "[]")).toEqual(["s1"]);
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
