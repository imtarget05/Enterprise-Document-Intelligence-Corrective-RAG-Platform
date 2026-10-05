import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AuditLogTable from "./AuditLogTable";
import { useAuditLogs } from "../hooks/useAuditLogs";
import type { AuditLog } from "../hooks/useAuditLogs";

vi.mock("../hooks/useAuditLogs", () => ({ useAuditLogs: vi.fn() }));

const useAuditLogsMock = vi.mocked(useAuditLogs);

function baseLog(overrides: Partial<AuditLog> = {}): AuditLog {
  return {
    id: 1,
    username: "alice",
    action: "auth.login",
    resourceType: "user",
    resourceId: "alice",
    ipAddress: "203.0.113.7",
    detail: "success",
    createdAt: "2026-08-26T04:00:00.000Z",
    ...overrides,
  };
}

function mockHook(result: {
  logs?: AuditLog[];
  totalPages?: number;
  totalElements?: number;
  isLoading?: boolean;
  isFetching?: boolean;
  isError?: boolean;
}) {
  const refetch = vi.fn();
  useAuditLogsMock.mockReturnValue({
    data:
      result.isLoading || result.isError
        ? undefined
        : {
            page: 0,
            size: 25,
            totalElements: result.totalElements ?? (result.logs ?? []).length,
            totalPages: result.totalPages ?? 1,
            logs: result.logs ?? [],
          },
    isLoading: result.isLoading ?? false,
    isFetching: result.isFetching ?? false,
    isError: result.isError ?? false,
    refetch,
  } as unknown as ReturnType<typeof useAuditLogs>);
  return refetch;
}

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuditLogTable />
    </QueryClientProvider>
  );
}

/** The action-filter <select> holds <option> labels identical to badge text,
 *  so badge assertions must target the SPAN badge, not any text match. */
function getBadge(action: string): HTMLElement {
  const match = screen
    .getAllByText(action)
    .find((el) => el.tagName === "SPAN");
  if (!match) throw new Error(`badge not found for action ${action}`);
  return match as HTMLElement;
}

function getPageIndicator(): HTMLElement | null {
  return screen
    .getAllByText((_, el) => el?.textContent === "1 / 1" || el?.textContent === "1 / 2")
    .at(0) ?? null;
}

describe("AuditLogTable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(cleanup);

  it("renders log rows with user, action badge, resource and IP", () => {
    mockHook({ logs: [baseLog()] });

    setup();

    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(getBadge("auth.login")).toBeInTheDocument();
    expect(screen.getByText("user:alice")).toBeInTheDocument();
    expect(screen.getByText("203.0.113.7")).toBeInTheDocument();
    // formatted vi-VN date keeps the calendar day regardless of local TZ
    // (04:00 UTC stays on the 26th in UTC±14)
    expect(screen.getByText(/26\/08\/2026/)).toBeInTheDocument();
  });

  it("uses red badge for failed actions", () => {
    mockHook({ logs: [baseLog({ id: 1, action: "auth.login.failed" })] });

    setup();

    expect(getBadge("auth.login.failed").className).toContain("bg-red-50");
  });

  it("uses green badge for successful logins", () => {
    mockHook({ logs: [baseLog({ action: "auth.login" })] });

    setup();

    expect(getBadge("auth.login").className).toContain("bg-google-green/10");
  });

  it("uses blue badge for document actions", () => {
    mockHook({ logs: [baseLog({ action: "doc.upload" })] });

    setup();

    expect(getBadge("doc.upload").className).toContain("bg-google-blue/10");
  });

  it("uses purple badge for chat actions", () => {
    mockHook({ logs: [baseLog({ action: "chat.ask" })] });

    setup();

    expect(getBadge("chat.ask").className).toContain("bg-[#7b1fa2]/10");
  });

  it("falls back to the neutral badge for unknown actions", () => {
    mockHook({ logs: [baseLog({ action: "something.else" })] });

    setup();

    expect(getBadge("something.else").className).toContain("bg-surface-container");
  });

  it("shows a spinner while loading", () => {
    mockHook({ isLoading: true });

    const { container } = setup();

    expect(container.querySelector(".animate-spin")).not.toBeNull();
  });

  it("shows an error state with a working retry button", async () => {
    const refetch = mockHook({ isError: true });
    const user = userEvent.setup();

    setup();

    expect(screen.getByText("Không thể tải nhật ký hoạt động")).toBeInTheDocument();
    await user.click(screen.getByText("Thử lại"));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("shows the empty state when there are no logs", () => {
    mockHook({ logs: [] });

    setup();

    expect(screen.getByText("Không có dữ liệu.")).toBeInTheDocument();
  });

  it("shows a fetching indicator during background refetch", () => {
    mockHook({ logs: [baseLog()], isFetching: true });

    setup();

    expect(screen.getByText("Đang tải...")).toBeInTheDocument();
  });

  it("filters by username and resets to the first page", async () => {
    mockHook({ logs: [baseLog()] });
    const user = userEvent.setup();

    setup();

    await user.type(screen.getByPlaceholderText("Lọc theo username..."), "bob");

    const lastCall = useAuditLogsMock.mock.calls.at(-1)?.[0];
    expect(lastCall).toMatchObject({ username: "bob", page: 0 });
  });

  it("clears both filters with the clear button", async () => {
    mockHook({ logs: [baseLog()] });
    const user = userEvent.setup();

    setup();

    await user.type(screen.getByPlaceholderText("Lọc theo username..."), "bob");
    await user.click(screen.getByText("Xóa bộ lọc"));

    const lastCall = useAuditLogsMock.mock.calls.at(-1)?.[0];
    expect(lastCall).toMatchObject({ page: 0 });
    expect(lastCall?.username).toBeUndefined();
    expect(lastCall?.action).toBeUndefined();
  });

  it("advances pagination and requests the next page", async () => {
    mockHook({ logs: [baseLog()], totalPages: 2, totalElements: 30 });
    const user = userEvent.setup();

    setup();

    expect(getPageIndicator()).not.toBeNull();
    await user.click(screen.getByText("Sau →"));

    const lastCall = useAuditLogsMock.mock.calls.at(-1)?.[0];
    expect(lastCall).toMatchObject({ page: 1 });
  });
});
