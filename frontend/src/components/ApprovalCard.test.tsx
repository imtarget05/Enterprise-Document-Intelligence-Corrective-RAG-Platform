import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ApprovalCard from "./ApprovalCard";

function mockFetchOnce(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("ApprovalCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders pending UI with approve/reject and note input", () => {
    render(<ApprovalCard approvalId="hitl-abc123" token="tok" />);

    expect(screen.getByTestId("approval-card")).toBeDefined();
    expect(screen.getByText("hitl-abc123")).toBeDefined();
    expect(screen.getByTestId("approval-approve")).toBeDefined();
    expect(screen.getByTestId("approval-reject")).toBeDefined();
    expect(screen.getByTestId("approval-note")).toBeDefined();
  });

  it("approve posts approver note and shows receipt", async () => {
    const user = userEvent.setup();
    const onDecided = vi.fn();
    const fetchMock = mockFetchOnce(200, { status: "ok", decision: "approved" });

    render(<ApprovalCard approvalId="hitl-abc123" token="tok" onDecided={onDecided} />);

    await user.type(screen.getByTestId("approval-note"), "looks good");
    await user.click(screen.getByTestId("approval-approve"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/agent/approvals/hitl-abc123/approve");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ note: "looks good" });
    expect(String((init.headers as Record<string, string>).Authorization)).toBe("Bearer tok");

    expect(await screen.findByTestId("approval-receipt")).toBeDefined();
    expect(screen.getByText(/Đã duyệt/)).toBeDefined();
    expect(onDecided).toHaveBeenCalledWith("approved");
  });

  it("reject posts without note and shows rejected receipt", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetchOnce(200, { status: "ok", decision: "rejected" });

    render(<ApprovalCard approvalId="hitl-xyz" token={null} />);

    await user.click(screen.getByTestId("approval-reject"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/agent/approvals/hitl-xyz/reject");
    expect(JSON.parse(String(init.body))).toEqual({});

    expect(await screen.findByTestId("approval-receipt")).toBeDefined();
    expect(screen.getByText(/Đã từ chối/)).toBeDefined();
  });

  it("shows error when the request was already decided (404)", async () => {
    const user = userEvent.setup();
    mockFetchOnce(404, { detail: "Approval request not found or expired" });

    render(<ApprovalCard approvalId="hitl-gone" token="tok" />);

    await user.click(screen.getByTestId("approval-approve"));

    expect(await screen.findByTestId("approval-error")).toBeDefined();
    expect(screen.getByText("Approval request not found or expired")).toBeDefined();
  });
});
