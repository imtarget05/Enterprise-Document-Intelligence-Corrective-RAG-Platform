import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SessionList from "./SessionList";

function renderSessionList(props: {
  activeSessionId: string;
  onSelectSession: (id: string) => void;
  onResetSession?: () => void;
}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SessionList
        activeSessionId={props.activeSessionId}
        onSelectSession={props.onSelectSession}
        onResetSession={props.onResetSession}
      />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

function mockSessions(body: unknown, status = 200) {
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("SessionList", () => {
  it("shows a loading placeholder while sessions load", () => {
    mockSessions({ sessions: [] });
    renderSessionList({ activeSessionId: "s1", onSelectSession: vi.fn() });
    expect(screen.getByText("Đang tải...")).toBeInTheDocument();
  });

  it("renders nothing when there are no sessions", async () => {
    mockSessions({ sessions: [] });
    const { container } = renderSessionList({ activeSessionId: "s1", onSelectSession: vi.fn() });
    await screen.findByText("Đang tải...");
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("lists sessions with relative time and calls onSelectSession", async () => {
    const onSelectSession = vi.fn();
    const now = new Date().toISOString();
    mockSessions({
      sessions: [
        { sessionId: "s1", lastMessage: "hello", messageCount: 2, createdAt: now, updatedAt: now },
        { sessionId: "s2", lastMessage: "", messageCount: 7, createdAt: now, updatedAt: now },
      ],
    });
    renderSessionList({ activeSessionId: "s2", onSelectSession });

    const item = await screen.findByText("🕐 hello");
    expect(screen.getByText("🕐 Cuộc trò chuyện")).toBeInTheDocument();
    expect(screen.getByText("Vừa xong • 2 tin nhắn")).toBeInTheDocument();

    await userEvent.click(item);
    expect(onSelectSession).toHaveBeenCalledWith("s1");
  });

  it("deletes a single session: DELETE endpoint, local tracking, refetch and reset when active", async () => {
    const now = new Date().toISOString();
    const fetchMock = mockSessions({
      sessions: [
        { sessionId: "s1", lastMessage: "hello", messageCount: 2, createdAt: now, updatedAt: now },
        { sessionId: "s2", lastMessage: "keep", messageCount: 1, createdAt: now, updatedAt: now },
      ],
    });
    localStorage.setItem(
      "smartdoc_sessions",
      JSON.stringify([
        { sessionId: "s1", lastMessage: "hello", messageCount: 2, createdAt: now, updatedAt: now },
      ]),
    );
    const onResetSession = vi.fn();
    renderSessionList({ activeSessionId: "s1", onSelectSession: vi.fn(), onResetSession });

    // Scope to the row of s1 ("hello") — there is one delete button per session.
    const row = (await screen.findByText("🕐 hello")).closest('[role="button"]')!;
    await userEvent.click(within(row).getByLabelText("Xóa cuộc trò chuyện"));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/chat/history/s1"))).toBe(true),
    );
    const [, deleteInit] = fetchMock.mock.calls.find(([u]) => String(u).includes("/chat/history/s1"))!;
    expect(deleteInit.method).toBe("DELETE");
    expect(JSON.parse(localStorage.getItem("smartdoc_deleted_sessions") ?? "[]")).toEqual(["s1"]);
    expect(JSON.parse(localStorage.getItem("smartdoc_sessions") ?? "[]")).toEqual([]);
    expect(onResetSession).toHaveBeenCalledTimes(1);
  });

  it("does not reset the chat when a non-active session is deleted", async () => {
    const now = new Date().toISOString();
    mockSessions({
      sessions: [
        { sessionId: "s1", lastMessage: "hello", messageCount: 2, createdAt: now, updatedAt: now },
        { sessionId: "s2", lastMessage: "other", messageCount: 1, createdAt: now, updatedAt: now },
      ],
    });
    const onResetSession = vi.fn();
    renderSessionList({ activeSessionId: "s2", onSelectSession: vi.fn(), onResetSession });

    const row = (await screen.findByText("🕐 hello")).closest('[role="button"]')!;
    await userEvent.click(within(row).getByLabelText("Xóa cuộc trò chuyện"));
    await waitFor(() =>
      expect(JSON.parse(localStorage.getItem("smartdoc_deleted_sessions") ?? "[]")).toEqual(["s1"]),
    );
    expect(onResetSession).not.toHaveBeenCalled();
  });

  it("clears all sessions after the confirm dialog is accepted", async () => {
    const now = new Date().toISOString();
    const fetchMock = mockSessions({
      sessions: [
        { sessionId: "s1", lastMessage: "hello", messageCount: 2, createdAt: now, updatedAt: now },
        { sessionId: "s2", lastMessage: "world", messageCount: 7, createdAt: now, updatedAt: now },
      ],
    });
    localStorage.setItem(
      "smartdoc_sessions",
      JSON.stringify([
        { sessionId: "s1", lastMessage: "hello", messageCount: 2, createdAt: now, updatedAt: now },
        { sessionId: "s2", lastMessage: "world", messageCount: 7, createdAt: now, updatedAt: now },
      ]),
    );
    localStorage.setItem("smartdoc_deleted_sessions", JSON.stringify(["gone"]));
    const onResetSession = vi.fn();
    vi.stubGlobal("confirm", vi.fn(() => true));
    renderSessionList({ activeSessionId: "s1", onSelectSession: vi.fn(), onResetSession });

    await userEvent.click(await screen.findByText("Xóa tất cả"));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/chat/history"))).toBe(true));
    const [clearUrl, clearInit] = fetchMock.mock.calls.find(([u]) => String(u).includes("/chat/history"))!;
    expect(String(clearUrl)).toContain("/chat/history");
    expect(clearInit.method).toBe("DELETE");
    expect(JSON.parse(localStorage.getItem("smartdoc_deleted_sessions") ?? "[]")).toEqual([
      "gone",
      "s1",
      "s2",
      "session-default-01",
    ]);
    expect(localStorage.getItem("smartdoc_sessions")).toBeNull();
    expect(onResetSession).toHaveBeenCalledTimes(1);
  });

  it("does nothing when the clear-all confirm dialog is declined", async () => {
    const now = new Date().toISOString();
    const fetchMock = mockSessions({
      sessions: [
        { sessionId: "s1", lastMessage: "hello", messageCount: 2, createdAt: now, updatedAt: now },
      ],
    });
    localStorage.setItem(
      "smartdoc_sessions",
      JSON.stringify([
        { sessionId: "s1", lastMessage: "hello", messageCount: 2, createdAt: now, updatedAt: now },
      ]),
    );
    const confirmSpy = vi.fn(() => false);
    vi.stubGlobal("confirm", confirmSpy);
    renderSessionList({ activeSessionId: "s1", onSelectSession: vi.fn() });

    await userEvent.click(await screen.findByText("Xóa tất cả"));
    expect(confirmSpy).toHaveBeenCalledWith("Bạn có chắc muốn xóa toàn bộ lịch sử các cuộc trò chuyện?");
    expect(fetchMock.mock.calls.every(([u]) => String(u).includes("/chat/sessions"))).toBe(true);
    expect(JSON.parse(localStorage.getItem("smartdoc_deleted_sessions") ?? "[]")).toEqual([]);
    expect(localStorage.getItem("smartdoc_sessions")).not.toBeNull();
  });
});
