import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AdminPage from "./AdminPage";
import * as AuthContextModule from "../context/AuthContext";

describe("AdminPage", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  it("renders access denied when user is not admin", () => {
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      token: "tok",
      username: "user",
      role: "ROLE_USER",
      login: vi.fn(),
      logout: vi.fn(),
      isAuthenticated: true,
      isAdmin: false,
      isEngineer: false,
      isViewer: false,
      isInitializing: false,
    });

    render(
      <QueryClientProvider client={queryClient}>
        <AdminPage />
      </QueryClientProvider>
    );

    expect(screen.getByText("Bạn không có quyền truy cập trang quản trị.")).toBeInTheDocument();
  });

  it("renders overview when user is admin", async () => {    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      token: "tok",
      username: "admin_user",
      role: "ROLE_ADMIN",
      login: vi.fn(),
      logout: vi.fn(),
      isAuthenticated: true,
      isAdmin: true,
      isEngineer: false,
      isViewer: false,
      isInitializing: false,
    });

    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <AdminPage />
      </QueryClientProvider>
    );

    expect(screen.getByText("Tổng quan hệ thống Smart Document AI")).toBeInTheDocument();
    expect(screen.getByText("Văn bản pháp luật & quy chế")).toBeInTheDocument();
    expect(screen.getAllByText("admin_user").length).toBeGreaterThanOrEqual(1);

    // Switch to audit tab
    const auditTabBtn = screen.getByRole("button", { name: /Audit Logs/i });
    await user.click(auditTabBtn);

    expect(screen.getByText(/Nhật ký kiểm toán|Audit Trail|Audit Logs/i)).toBeInTheDocument();

    // Approvals tab is available to admins too
    expect(screen.getByRole("button", { name: /Phê duyệt/i })).toBeDefined();
  });

  it("engineer lands on approvals queue without admin tabs", async () => {
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
      token: "tok",
      username: "eng_user",
      role: "ROLE_ENGINEER",
      login: vi.fn(),
      logout: vi.fn(),
      isAuthenticated: true,
      isAdmin: false,
      isEngineer: true,
      isViewer: false,
      isInitializing: false,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ status: "ok", pending: [], count: 0 }),
      }),
    );
    try {
      render(
        <QueryClientProvider client={queryClient}>
          <AdminPage />
        </QueryClientProvider>
      );

      expect(await screen.findByText("Phê duyệt hành động (HITL)")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Tổng quan/i })).toBeNull();
      expect(screen.queryByRole("button", { name: /Audit Logs/i })).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
