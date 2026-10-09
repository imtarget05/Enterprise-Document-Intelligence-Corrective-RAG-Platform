import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SearchInput from "./SearchInput";

function renderSearchInput(props: { onSelectDoc: (doc: { id: number; fileName: string; title?: string | null }) => void }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SearchInput onSelectDoc={props.onSelectDoc} />
    </QueryClientProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mockSearch(results: unknown[]) {
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify({ results, total: results.length }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("SearchInput", () => {
  it("debounces the query and renders matching documents", async () => {
    const user = userEvent.setup();
    mockSearch([
      { id: 1, fileName: "contract.pdf", title: "Contract A", fileType: "PDF", chunkCount: 3, documentNumber: "001" },
      { id: 2, fileName: "notes.pdf", title: null, fileType: "PDF", chunkCount: 1 },
    ]);
    const onSelectDoc = vi.fn();
    renderSearchInput({ onSelectDoc });

    await user.type(screen.getByLabelText("Tìm kiếm tài liệu"), "contract");

    await waitFor(() => expect(screen.getByText("📄 Contract A")).toBeInTheDocument());
    expect(screen.getByText("📄 notes.pdf")).toBeInTheDocument();
    expect(screen.getByText("Số: 001 • PDF • 3 chunks")).toBeInTheDocument();
  });

  it("calls onSelectDoc and clears the query when a result is clicked", async () => {
    const user = userEvent.setup();
    mockSearch([{ id: 5, fileName: "a.pdf", title: "Alpha", fileType: "PDF", chunkCount: 2 }]);
    const onSelectDoc = vi.fn();
    renderSearchInput({ onSelectDoc });

    await user.type(screen.getByLabelText("Tìm kiếm tài liệu"), "alpha");
    await waitFor(() => expect(screen.getByText("📄 Alpha")).toBeInTheDocument());

    await user.click(screen.getByText("📄 Alpha"));
    expect(onSelectDoc).toHaveBeenCalledWith({ id: 5, fileName: "a.pdf", title: "Alpha" });
    expect((screen.getByLabelText("Tìm kiếm tài liệu") as HTMLInputElement).value).toBe("");
  });

  it("shows an empty-results message and offers a clear button", async () => {
    const user = userEvent.setup();
    mockSearch([]);
    renderSearchInput({ onSelectDoc: vi.fn() });

    await user.type(screen.getByLabelText("Tìm kiếm tài liệu"), "zzz");
    await waitFor(() => expect(screen.getByText("Không tìm thấy tài liệu")).toBeInTheDocument());

    await user.click(screen.getByLabelText("Xóa tìm kiếm"));
    expect((screen.getByLabelText("Tìm kiếm tài liệu") as HTMLInputElement).value).toBe("");
  });

  it("does not search while the input is blank", async () => {
    const fetchMock = mockSearch([{ id: 1, fileName: "a.pdf", title: "A", fileType: "PDF", chunkCount: 1 }]);
    const user = userEvent.setup();
    renderSearchInput({ onSelectDoc: vi.fn() });

    // Focus without typing: no debounced query, no fetch.
    await user.click(screen.getByLabelText("Tìm kiếm tài liệu"));
    await new Promise((r) => setTimeout(r, 400));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
