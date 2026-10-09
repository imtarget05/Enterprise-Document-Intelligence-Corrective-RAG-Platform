import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useDocumentSearch } from "./useDocumentSearch";

function makeWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useDocumentSearch", () => {
  it("returns an empty array without fetching for a blank query", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ results: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDocumentSearch("   "), { wrapper: makeWrapper() });

    expect(result.current.fetchStatus).toBe("idle");
    expect(result.current.data).toBeUndefined();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fetches search results for a non-empty query", async () => {
    const results = [
      { id: 1, fileName: "a.pdf", title: "Contract A", fileType: "PDF", chunkCount: 3 },
      { id: 2, fileName: "b.pdf", title: null, fileType: "PDF", chunkCount: 1 },
    ];
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ results, total: 2 }), { status: 200, headers: { "Content-Type": "application/json" } })
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDocumentSearch("contract"), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(results);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/documents/search?q=contract");
    expect(url).toContain("limit=20");
    expect(init.credentials).toBe("include");
  });

  it("returns an empty array when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("err", { status: 500 })));

    const { result } = renderHook(() => useDocumentSearch("contract"), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });

  it("returns an empty array when the results key is missing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } }))
    );

    const { result } = renderHook(() => useDocumentSearch("contract"), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });
});
