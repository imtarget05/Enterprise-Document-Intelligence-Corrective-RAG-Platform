import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useApprovalsQueue, useApprovalDetail, useDecideApproval } from "./useApprovals";

function makeWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, mutations: { retry: false } } } });
  const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { wrapper, invalidateQueries };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useApprovalsQueue", () => {
  it("fetches the queue with the bearer token", async () => {
    const queue = { requests: [{ id: "r1", status: "PENDING" }], total: 1 };
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify(queue), { status: 200, headers: { "Content-Type": "application/json" } })
    );
    vi.stubGlobal("fetch", fetchMock);
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useApprovalsQueue("tok-123", true), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(queue);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/agent/approvals");
    expect(init.headers.Authorization).toBe("Bearer tok-123");
  });

  it("omits the Authorization header when token is null", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ requests: [], total: 0 }), { status: 200, headers: { "Content-Type": "application/json" } })
    );
    vi.stubGlobal("fetch", fetchMock);
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useApprovalsQueue(null, true), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers.Authorization).toBeUndefined();
  });

  it("surfaces the server error message on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ error: "approvals unavailable" }), { status: 503, headers: { "Content-Type": "application/json" } })
      )
    );
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useApprovalsQueue("tok", true), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("approvals unavailable");
    expect(result.current.error?.status).toBe(503);
  });

  it("falls back to the generic message when the error body is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Service Unavailable", { status: 503 })));
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useApprovalsQueue("tok", true), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toContain("Failed to fetch approvals");
  });
});

describe("useApprovalDetail", () => {
  it("does not fetch while requestId is null", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useApprovalDetail("tok", null), { wrapper });

    expect(result.current.fetchStatus).toBe("idle");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fetches a single approval detail", async () => {
    const detail = { status: "PENDING", request: { id: "r1" } };
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify(detail), { status: 200, headers: { "Content-Type": "application/json" } })
    );
    vi.stubGlobal("fetch", fetchMock);
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useApprovalDetail("tok", "r1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(detail);
    expect(fetchMock.mock.calls[0][0]).toContain("/agent/approvals/r1");
  });
});

describe("useDecideApproval", () => {
  it("approves a request with a note and invalidates approvals on settle", async () => {
    const outcome = { status: "APPROVED", decision: "approve", request_id: "r1" };
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify(outcome), { status: 200, headers: { "Content-Type": "application/json" } })
    );
    vi.stubGlobal("fetch", fetchMock);
    const { wrapper, invalidateQueries } = makeWrapper();

    const { result } = renderHook(() => useDecideApproval("tok"), { wrapper });

    act(() => {
      result.current.mutate({ requestId: "r1", decision: "approve", note: "looks good" });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/agent/approvals/r1/approve");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ note: "looks good" });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["approvals"] });
  });

  it("rejects a request without a note sending an empty object", async () => {
    const outcome = { status: "REJECTED", decision: "reject", request_id: "r2" };
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify(outcome), { status: 200, headers: { "Content-Type": "application/json" } })
    );
    vi.stubGlobal("fetch", fetchMock);
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useDecideApproval("tok"), { wrapper });

    act(() => {
      result.current.mutate({ requestId: "r2", decision: "reject" });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/agent/approvals/r2/reject");
    expect(JSON.parse(init.body as string)).toEqual({});
  });

  it("surfaces the server error message when the decision fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: "request already handled" }), { status: 409, headers: { "Content-Type": "application/json" } })
      )
    );
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useDecideApproval("tok"), { wrapper });

    act(() => {
      result.current.mutate({ requestId: "r1", decision: "approve" });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("request already handled");
  });
});
