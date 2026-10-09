import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useRenameDocument, useDeleteDocument, useDeleteDocumentsBatch } from "./useDocumentMutations";

function makeWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { wrapper, invalidateQueries };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useRenameDocument", () => {
  it("PUTs the new title and invalidates the documents queries on success", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ id: 1, title: "New" }), { status: 200, headers: { "Content-Type": "application/json" } })
    );
    vi.stubGlobal("fetch", fetchMock);
    const { wrapper, invalidateQueries } = makeWrapper();

    const { result } = renderHook(() => useRenameDocument(), { wrapper });

    act(() => {
      result.current.mutate({ id: 1, payload: { title: "New" } });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/documents/1");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ title: "New" });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["documents"] });
  });

  it("throws the server error text when the rename fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Tên tài liệu đã tồn tại", { status: 409 })));
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useRenameDocument(), { wrapper });

    act(() => {
      result.current.mutate({ id: 1, payload: { title: "Dup" } });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Tên tài liệu đã tồn tại");
  });
});

describe("useDeleteDocument", () => {
  it("DELETEs the document and invalidates the documents queries on success", async () => {
    const fetchMock = vi.fn(async () => new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const { wrapper, invalidateQueries } = makeWrapper();

    const { result } = renderHook(() => useDeleteDocument(), { wrapper });

    act(() => {
      result.current.mutate(9);
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/documents/9");
    expect(init.method).toBe("DELETE");
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["documents"] });
  });

  it("throws the server error text when the delete fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Không có quyền xóa", { status: 403 })));
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useDeleteDocument(), { wrapper });

    act(() => {
      result.current.mutate(9);
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Không có quyền xóa");
  });
});

describe("useDeleteDocumentsBatch", () => {
  it("POSTs the id list to the batch endpoint and invalidates on success", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ deleted: 2 }), { status: 200, headers: { "Content-Type": "application/json" } })
    );
    vi.stubGlobal("fetch", fetchMock);
    const { wrapper, invalidateQueries } = makeWrapper();

    const { result } = renderHook(() => useDeleteDocumentsBatch(), { wrapper });

    act(() => {
      result.current.mutate([1, 2]);
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/documents/batch");
    expect(init.method).toBe("DELETE");
    expect(JSON.parse(init.body as string)).toEqual([1, 2]);
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["documents"] });
  });

  it("throws the server error text when the batch delete fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Xóa hàng loạt thất bại", { status: 500 })));
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useDeleteDocumentsBatch(), { wrapper });

    act(() => {
      result.current.mutate([1, 2]);
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Xóa hàng loạt thất bại");
  });
});
