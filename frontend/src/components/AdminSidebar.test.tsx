import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminSidebar from "./AdminSidebar";

/**
 * AdminSidebar filters tabs by role (canAdmin=false hides admin-only tabs,
 * i.e. an ENGINEER must see only the approvals queue) and exposes the
 * window.__appView bridge that returns to the chat view.
 */

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete (window as unknown as { __appView?: unknown }).__appView;
});

function renderSidebar(props: { activeTab: string; canAdmin?: boolean }) {
  const onTabChange = vi.fn();
  render(
    <AdminSidebar activeTab={props.activeTab} onTabChange={onTabChange} canAdmin={props.canAdmin} />,
  );
  return { onTabChange };
}

describe("AdminSidebar", () => {
  it("shows all tabs for admins", () => {
    renderSidebar({ activeTab: "overview", canAdmin: true });
    expect(screen.getByText("Tổng quan")).toBeInTheDocument();
    expect(screen.getByText("Phê duyệt")).toBeInTheDocument();
    expect(screen.getByText("Audit Logs")).toBeInTheDocument();
  });

  it("hides admin-only tabs for non-admins (only approvals remains)", () => {
    renderSidebar({ activeTab: "approvals", canAdmin: false });
    expect(screen.getByText("Phê duyệt")).toBeInTheDocument();
    expect(screen.queryByText("Tổng quan")).not.toBeInTheDocument();
    expect(screen.queryByText("Audit Logs")).not.toBeInTheDocument();
  });

  it("calls onTabChange with the clicked tab id", async () => {
    const user = userEvent.setup();
    const { onTabChange } = renderSidebar({ activeTab: "overview", canAdmin: true });

    await user.click(screen.getByText("Audit Logs"));
    expect(onTabChange).toHaveBeenCalledWith("audit");
  });

  it("returns to the chat view through the __appView bridge", async () => {
    const user = userEvent.setup();
    const bridgeSpy = vi.fn();
    (window as unknown as { __appView?: ["chat" | "admin", (v: "chat" | "admin") => void] }).__appView = [
      "admin",
      bridgeSpy,
    ];

    renderSidebar({ activeTab: "overview", canAdmin: true });
    await user.click(screen.getByText("Quay lại Trò chuyện"));
    expect(bridgeSpy).toHaveBeenCalledWith("chat");
  });
});
