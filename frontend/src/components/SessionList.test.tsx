import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SessionList from "./SessionList";

function renderSessionList(props: { activeSessionId: string; onSelectSession: (id: string) => void }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SessionList activeSessionId={props.activeSessionId} onSelectSession={props.onSelectSession} />
    </QueryClientProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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
});
