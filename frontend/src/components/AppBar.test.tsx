import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../context/AuthContext";
import AppBar from "./AppBar";

/**
 * AppBar carries real behavior:
 *  - pending HITL count badge (approvalsData.pending?.length)
 *  - username initials
 *  - view switching (prop callback + window.__appView bridge)
 *  - RBAC role switcher (calls login() with ROLE_ADMIN / ROLE_USER)
 *  - logout callback
 */

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

type View = "chat" | "admin";

async function renderAppBar(overrides: Partial<Parameters<typeof AppBar>[0]> = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/auth/me")) {
      return jsonResponse({ username: "Nguyen Van A", role: "ROLE_USER" });
    }
    if (url.includes("/agent/approvals")) {
      return jsonResponse({
        pending: [{ request_id: "r1" }, { request_id: "r2" }],
        count: 2,
      });
    }
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);

  const bridgeSpy = vi.fn();
  (window as unknown as { __appView?: [View, (v: View) => void] }).__appView = [
    "chat",
    bridgeSpy,
  ];

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <AppBar
          onMenuClick={overrides.onMenuClick ?? vi.fn()}
          username={overrides.username ?? "Nguyen Van A"}
          onLogout={overrides.onLogout ?? vi.fn()}
          currentView={overrides.currentView ?? "chat"}
          onViewChange={overrides.onViewChange}
        />
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { fetchMock, bridgeSpy };
}

beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete (window as unknown as { __appView?: unknown }).__appView;
});

describe("AppBar", () => {
  it("shows pending HITL count as a badge on the admin switcher", async () => {
    // Only enabled when a token exists; seed one before mounting.
    sessionStorage.setItem("smartdoc_jwt", "test-token");
    const { fetchMock } = await renderAppBar();
    // Wait for the approvals query to resolve and the badge to render.
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/agent/approvals"),
        expect.anything(),
      );
    });
    await waitFor(() => {
      expect(screen.getByText("2")).toBeInTheDocument();
    });
  });

  it("renders user initials from the username", async () => {
    await renderAppBar({ username: "Nguyen Van A" });
    expect(screen.getByRole("button", { name: "Menu người dùng" })).toHaveTextContent("NG");
  });

  it("switches to chat view via callback and __appView bridge from the dropdown", async () => {
    const user = userEvent.setup();
    const onViewChange = vi.fn();
    const { bridgeSpy } = await renderAppBar({ currentView: "admin", onViewChange });

    // From the admin view the dropdown entry reads "Mở Chatbot RAG".
    await user.click(screen.getByText(/Mở Chatbot RAG/));
    expect(onViewChange).toHaveBeenCalledWith("chat");
    expect(bridgeSpy).toHaveBeenCalledWith("chat");
  });

  it("switches to admin view via callback and __appView bridge from the switcher", async () => {
    const user = userEvent.setup();
    const onViewChange = vi.fn();
    const { bridgeSpy } = await renderAppBar({ currentView: "chat", onViewChange });

    await user.click(screen.getByText("🛡️"));
    expect(onViewChange).toHaveBeenCalledWith("admin");
    expect(bridgeSpy).toHaveBeenCalledWith("admin");
  });

  it("promotes the user to ROLE_ADMIN through the RBAC switcher", async () => {
    sessionStorage.setItem("smartdoc_jwt", "test-token");
    const user = userEvent.setup();
    await renderAppBar({});

    await waitFor(() => expect(screen.getByText("ROLE_USER")).toBeInTheDocument());
    await user.click(screen.getByText("👑 Admin"));
    await waitFor(() => expect(screen.getByText("ROLE_ADMIN")).toBeInTheDocument());
    // login() re-persisted the current token; role badge flipped to ROLE_ADMIN.
    expect(sessionStorage.getItem("smartdoc_jwt")).toBe("test-token");
  });

  it("demotes back to ROLE_USER and hops to chat view", async () => {
    sessionStorage.setItem("smartdoc_jwt", "test-token");
    const user = userEvent.setup();
    const { bridgeSpy } = await renderAppBar({});

    await waitFor(() => expect(screen.getByText("ROLE_USER")).toBeInTheDocument());
    await user.click(screen.getByText("👑 Admin"));
    await waitFor(() => expect(screen.getByText("ROLE_ADMIN")).toBeInTheDocument());

    await user.click(screen.getByText("👤 User"));
    await waitFor(() => {
      expect(screen.getByText("ROLE_USER")).toBeInTheDocument();
    });
    await waitFor(() => expect(bridgeSpy).toHaveBeenCalledWith("chat"));
  });

  it("annotates admin menu with 'Toàn quyền' when role is ROLE_ADMIN", async () => {
    const user = userEvent.setup();
    await renderAppBar({});

    await waitFor(() => expect(screen.getByText("ROLE_USER")).toBeInTheDocument());
    await user.click(screen.getByText("👑 Admin"));
    await waitFor(() => expect(screen.getByText("Toàn quyền")).toBeInTheDocument());
  });

  it("notifies onLogout when the dropdown logout entry is clicked", async () => {
    const user = userEvent.setup();
    const onLogout = vi.fn();
    await renderAppBar({ onLogout });

    await user.click(screen.getByText("Đăng xuất"));
    expect(onLogout).toHaveBeenCalledTimes(1);
  });
});
