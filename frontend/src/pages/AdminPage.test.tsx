import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AdminPage from "./AdminPage";
import * as AuthContextModule from "../context/AuthContext";

describe("AdminPage", () => {
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

  it("renders overview when user is admin", async () => {
    vi.spyOn(AuthContextModule, "useAuth").mockReturnValue({
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
  });
});
