import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useDocumentVersions } from "./useDocumentVersions";

function makeWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useDocumentVersions", () => {
  it("fetches versions for a document id", async () => {
    const versions = [
      { versionNumber: 2, fileName: "doc.pdf", createdAt: "2024-01-02T00:00:00Z" },
      { versionNumber: 1, fileName: "doc.pdf", createdAt: "2024-01-01T00:00:00Z" },
    ];
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ versions }), { status: 200, headers: { "Content-Type": "application/json" } })
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDocumentVersions(42), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(versions);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/documents/42/versions");
    expect(init.credentials).toBe("include");
  });

  it("returns an empty array when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 404 })));

    const { result } = renderHook(() => useDocumentVersions(7), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });

  it("does not fetch while documentId is null", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ versions: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDocumentVersions(null), { wrapper: makeWrapper() });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.fetchStatus).toBe("idle");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
