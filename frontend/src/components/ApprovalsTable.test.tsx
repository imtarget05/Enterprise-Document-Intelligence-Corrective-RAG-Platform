import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ApprovalsTable from "./ApprovalsTable";

const QUEUE = {
  status: "ok",
  count: 2,
  pending: [
    {
      request_id: "hitl-aaa",
      query: "Send report by email",
      session_id: "s1",
      user_id: "alice",
      agent_plan: "1. compose email\n2. send via SMTP",
      document_ids: [],
      status: "pending",
      approver: null,
      note: null,
      created_at: 1725000000,
    },
    {
      request_id: "hitl-bbb",
      query: "Create Jira ticket",
      session_id: "s2",
      user_id: "bob",
      agent_plan: "",
      document_ids: [],
      status: "pending",
      approver: null,
      note: null,
      created_at: 1725000100,
    },
  ],
};

function renderTable(fetchImpl: (url: string, init?: RequestInit) => unknown) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.stubGlobal("fetch", vi.fn(fetchImpl));
  render(
    <QueryClientProvider client={client}>
      <ApprovalsTable token="tok" />
    </QueryClientProvider>,
  );
}

describe("ApprovalsTable", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders pending rows and detail with plan", async () => {
    renderTable(async (url: string) => {
      if (String(url).endsWith("/agent/approvals")) {
        return { ok: true, status: 200, json: () => Promise.resolve(QUEUE) };
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    expect(await screen.findByTestId("approval-row-hitl-aaa")).toBeDefined();
    // Query text appears both in the row and the auto-selected detail panel
    expect(screen.getAllByText("Send report by email").length).toBeGreaterThanOrEqual(1);

    // Detail auto-selects the first row and shows the agent plan
    expect(await screen.findByTestId("approval-detail")).toBeDefined();
    expect(screen.getByText(/compose email/)).toBeDefined();
  });

  it("approve posts note and shows success receipt", async () => {
    const user = userEvent.setup();
    const calls: Array<[string, RequestInit?]> = [];
    renderTable(async (url: string, init?: RequestInit) => {
      calls.push([url, init]);
      if (String(url).endsWith("/agent/approvals")) {
        return { ok: true, status: 200, json: () => Promise.resolve(QUEUE) };
      }
      if (String(url).endsWith("/hitl-aaa/approve")) {
        return {
          ok: true,
          status: 200,
          json: () => Promise.resolve({ status: "ok", decision: "approved", approver: "boss" }),
        };
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    expect(await screen.findByTestId("approval-row-hitl-aaa")).toBeDefined();
    await user.type(screen.getByTestId("queue-note"), "go ahead");
    await user.click(screen.getByTestId("queue-approve"));

    await waitFor(() => expect(screen.getByTestId("queue-success")).toBeDefined());
    const post = calls.find(([u]) => String(u).endsWith("/hitl-aaa/approve"));
    expect(post).toBeDefined();
    expect(JSON.parse(String(post![1]?.body))).toEqual({ note: "go ahead" });
    expect(String((post![1]?.headers as Record<string, string>).Authorization)).toBe("Bearer tok");
  });

  it("shows empty-state when nothing is pending", async () => {
    renderTable(async () => ({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ status: "ok", pending: [], count: 0 }),
    }));

    expect(await screen.findByText(/Không có yêu cầu nào đang chờ/)).toBeDefined();
  });

  it("shows permission hint on 403", async () => {
    renderTable(async () => ({
      ok: false,
      status: 403,
      json: () => Promise.resolve({ error: "Forbidden" }),
    }));

    expect(await screen.findByText(/cần quyền ADMIN hoặc ENGINEER/)).toBeDefined();
  });
});
