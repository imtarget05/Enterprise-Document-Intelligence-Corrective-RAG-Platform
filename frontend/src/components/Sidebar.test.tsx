import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Document } from "../types";
import Sidebar from "./Sidebar";

const createWrapper = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

afterEach(cleanup);

const mockDocuments: Document[] = [
  {
    id: 1,
    fileName: "doc1.pdf",
    title: "Document One",
    documentNumber: "001",
    fileType: "PDF",
    chunkCount: 10,
    createdAt: "2024-01-01T00:00:00Z",
    sourceType: "USER",
  },
  {
    id: 2,
    fileName: "doc2.docx",
    title: "Document Two",
    documentNumber: "002",
    fileType: "DOCX",
    chunkCount: 5,
    createdAt: "2024-01-02T00:00:00Z",
    sourceType: "USER",
  },
];

function renderSidebar(props: Partial<{
  documents: Document[];
  selectedDoc: Document | null;
  onSelectDoc: (doc: Document | null) => void;
  onNewChat: () => void;
  onUploadClick: () => void;
  isOpen: boolean;
  onClose: () => void;
  activeSessionId: string;
  onSelectSession: (sessionId: string) => void;
  onRenameDoc: (doc: Document) => void;
  onDeleteDoc: (doc: Document) => void;
  onViewVersions: (doc: Document) => void;
  onDeleteBatchDocs?: (ids: number[]) => void;
}> = {}) {
  return render(
    <Sidebar
      documents={props.documents ?? []}
      selectedDoc={props.selectedDoc ?? null}
      onSelectDoc={props.onSelectDoc ?? vi.fn()}
      onNewChat={props.onNewChat ?? vi.fn()}
      onUploadClick={props.onUploadClick ?? vi.fn()}
      isOpen={props.isOpen ?? false}
      onClose={props.onClose ?? vi.fn()}
      activeSessionId={props.activeSessionId ?? "test-session"}
      onSelectSession={props.onSelectSession ?? vi.fn()}
      onRenameDoc={props.onRenameDoc ?? vi.fn()}
      onDeleteDoc={props.onDeleteDoc ?? vi.fn()}
      onViewVersions={props.onViewVersions ?? vi.fn()}
      onDeleteBatchDocs={props.onDeleteBatchDocs}
    />,
    { wrapper: createWrapper() },
  );
}

describe("Sidebar", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders mobile overlay when isOpen is true", () => {
    renderSidebar({ isOpen: true });
    expect(screen.getByTestId("mobile-overlay")).toBeInTheDocument();
  });

  it("does not render mobile overlay when isOpen is false", () => {
    renderSidebar({ isOpen: false });
    expect(screen.queryByTestId("mobile-overlay")).not.toBeInTheDocument();
  });

  it("calls onClose when mobile overlay is clicked", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderSidebar({ isOpen: true, onClose });

    await user.click(screen.getByTestId("mobile-overlay"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renders new chat button and calls onNewChat + onClose when clicked", async () => {
    const user = userEvent.setup();
    const onNewChat = vi.fn();
    const onClose = vi.fn();
    renderSidebar({ onNewChat, onClose });

    await user.click(screen.getByRole("button", { name: "Cuộc trò chuyện mới" }));
    expect(onNewChat).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renders upload button and calls onUploadClick when clicked", async () => {
    const user = userEvent.setup();
    const onUploadClick = vi.fn();
    renderSidebar({ onUploadClick });

    await user.click(screen.getByRole("button", { name: "Tải lên tài liệu" }));
    expect(onUploadClick).toHaveBeenCalledTimes(1);
  });

  it("shows empty state message when no documents", () => {
    renderSidebar({ documents: [] });
    expect(screen.getByText("Chưa có tài liệu. Tải lên để bắt đầu.")).toBeInTheDocument();
  });

  it("renders document list when documents exist", () => {
    renderSidebar({ documents: mockDocuments });
    // Component shows doc.title || doc.fileName, so titles are displayed
    expect(screen.getByText("Document One")).toBeInTheDocument();
    expect(screen.getByText("Document Two")).toBeInTheDocument();
    expect(screen.getByText(/10 chunks/)).toBeInTheDocument();
    expect(screen.getByText(/5 chunks/)).toBeInTheDocument();
  });

  it("shows document title when available", () => {
    renderSidebar({ documents: mockDocuments });
    expect(screen.getByText("Document One")).toBeInTheDocument();
    expect(screen.getByText("Document Two")).toBeInTheDocument();
  });

  it("shows document number when available", () => {
    renderSidebar({ documents: mockDocuments });
    expect(screen.getByText(/Số: 001/)).toBeInTheDocument();
    expect(screen.getByText(/Số: 002/)).toBeInTheDocument();
  });

  it("highlights selected document", () => {
    const onSelectDoc = vi.fn();
    renderSidebar({ documents: mockDocuments, selectedDoc: mockDocuments[0], onSelectDoc });

    const selectedButton = screen.getByText("Document One").closest('[role="button"]');
    expect(selectedButton).toHaveClass("bg-google-blue/10");
    expect(selectedButton).toHaveClass("text-google-blue");

    const unselectedButton = screen.getByText("Document Two").closest('[role="button"]');
    expect(unselectedButton).not.toHaveClass("bg-google-blue/10");
    expect(unselectedButton).not.toHaveClass("text-google-blue");
  });

  it("calls onSelectDoc and onClose when document is clicked", async () => {
    const user = userEvent.setup();
    const onSelectDoc = vi.fn();
    const onClose = vi.fn();
    renderSidebar({ documents: mockDocuments, onSelectDoc, onClose });

    await user.click(screen.getByText("Document One"));
    expect(onSelectDoc).toHaveBeenCalledWith(mockDocuments[0]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not highlight any document when selectedDoc is null", () => {
    renderSidebar({ documents: mockDocuments, selectedDoc: null });
    const buttons = screen.getAllByRole("button", { name: /Document/ });
    buttons.forEach((btn) => {
      expect(btn).not.toHaveClass("bg-google-blue/10");
      expect(btn).not.toHaveClass("text-google-blue");
    });
  });

  it("renders footer text", () => {
    renderSidebar();
    expect(screen.getByText("Smart Doc \u2022 Enterprise CRAG")).toBeInTheDocument();
  });

  it("applies correct transform classes based on isOpen", () => {
    const { container: closedContainer } = renderSidebar({ isOpen: false });
    const closedSidebar = closedContainer.querySelector("aside");
    expect(closedSidebar).toHaveClass("-translate-x-full");
    expect(closedSidebar).toHaveClass("lg:translate-x-0");

    const { container: openContainer } = renderSidebar({ isOpen: true });
    const openSidebar = openContainer.querySelector("aside");
    expect(openSidebar).toHaveClass("translate-x-0");
  });

  it("toggles multi-select mode and allows selecting all documents", async () => {
    const user = userEvent.setup();
    renderSidebar({ documents: mockDocuments });

    // Click "Chọn nhiều"
    const toggleButton = screen.getByRole("button", { name: "Chọn nhiều" });
    await user.click(toggleButton);

    expect(screen.getByRole("button", { name: "Hủy chọn" })).toBeInTheDocument();
    expect(screen.getByText("Chọn tất cả (2)")).toBeInTheDocument();

    // Click "Chọn tất cả"
    const selectAllCheckbox = screen.getByLabelText("Chọn tất cả tài liệu");
    await user.click(selectAllCheckbox);

    expect(screen.getByText("Đã chọn: 2")).toBeInTheDocument();
    expect(screen.getByText("Xóa 2 tài liệu đã chọn")).toBeInTheDocument();
  });

  it("calls onDeleteBatchDocs when batch delete button is clicked", async () => {
    const user = userEvent.setup();
    const onDeleteBatchDocs = vi.fn();
    renderSidebar({ documents: mockDocuments, onDeleteBatchDocs });

    // Enter multi-select
    await user.click(screen.getByRole("button", { name: "Chọn nhiều" }));
    // Select all
    await user.click(screen.getByLabelText("Chọn tất cả tài liệu"));

    // Click delete batch
    const deleteButton = screen.getByRole("button", { name: /Xóa 2 tài liệu đã chọn/ });
    await user.click(deleteButton);

    expect(onDeleteBatchDocs).toHaveBeenCalledTimes(1);
    expect(onDeleteBatchDocs).toHaveBeenCalledWith([1, 2]);
  });

  it("toggles a document's selection when its row is clicked in multi-select mode", async () => {
    const user = userEvent.setup();
    const onSelectDoc = vi.fn();
    renderSidebar({ documents: mockDocuments, onSelectDoc });

    await user.click(screen.getByRole("button", { name: "Chọn nhiều" }));

    const row = screen.getByText("Document One").closest('[role="button"]')!;
    await user.click(row);
    expect(screen.getByText("Đã chọn: 1")).toBeInTheDocument();
    expect(onSelectDoc).not.toHaveBeenCalled();

    await user.click(row);
    expect(screen.getByText("Đã chọn: 0")).toBeInTheDocument();
  });

  it("toggles selection with the Enter and Space keys on a document row", async () => {
    const user = userEvent.setup();
    renderSidebar({ documents: mockDocuments });

    await user.click(screen.getByRole("button", { name: "Chọn nhiều" }));

    const row = screen.getByText("Document Two").closest('[role="button"]')!;
    row.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByText("Đã chọn: 1")).toBeInTheDocument();

    await user.keyboard(" ");
    expect(screen.getByText("Đã chọn: 0")).toBeInTheDocument();
  });

  it("toggles a document via its checkbox without selecting the document", async () => {
    const user = userEvent.setup();
    const onSelectDoc = vi.fn();
    renderSidebar({ documents: mockDocuments, onSelectDoc });

    await user.click(screen.getByRole("button", { name: "Chọn nhiều" }));

    await user.click(screen.getByLabelText("Chọn tài liệu Document One"));
    expect(screen.getByText("Đã chọn: 1")).toBeInTheDocument();
    expect(onSelectDoc).not.toHaveBeenCalled();
  });

  it("deselects all documents when 'Chọn tất cả' is clicked twice", async () => {
    const user = userEvent.setup();
    renderSidebar({ documents: mockDocuments });

    await user.click(screen.getByRole("button", { name: "Chọn nhiều" }));
    const selectAll = screen.getByLabelText("Chọn tất cả tài liệu");
    await user.click(selectAll);
    expect(screen.getByText("Đã chọn: 2")).toBeInTheDocument();

    await user.click(selectAll);
    expect(screen.getByText("Đã chọn: 0")).toBeInTheDocument();
  });

  it("exits multi-select mode and clears the selection when 'Hủy chọn' is clicked", async () => {
    const user = userEvent.setup();
    renderSidebar({ documents: mockDocuments });

    await user.click(screen.getByRole("button", { name: "Chọn nhiều" }));
    await user.click(screen.getByLabelText("Chọn tất cả tài liệu"));
    expect(screen.getByText("Đã chọn: 2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Hủy chọn" }));
    expect(screen.getByRole("button", { name: "Chọn nhiều" })).toBeInTheDocument();
    expect(screen.queryByText("Đã chọn: 2")).not.toBeInTheDocument();
  });
});