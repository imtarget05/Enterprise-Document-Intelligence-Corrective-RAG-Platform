import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import VersionHistory from "./VersionHistory";
import { useDocumentVersions } from "../hooks/useDocumentVersions";
import type { DocumentVersion } from "../hooks/useDocumentVersions";

vi.mock("../hooks/useDocumentVersions", () => ({ useDocumentVersions: vi.fn() }));

const useDocumentVersionsMock = vi.mocked(useDocumentVersions);

function version(overrides: Partial<DocumentVersion> = {}): DocumentVersion {
  return {
    versionNumber: 1,
    fileName: "contract.pdf",
    createdAt: "2026-08-26T04:00:00.000Z",
    ...overrides,
  };
}

function setup(props: { documentId?: number | null; versions?: DocumentVersion[]; isLoading?: boolean; onClose?: () => void }) {
  useDocumentVersionsMock.mockReturnValue({
    data: props.isLoading ? undefined : (props.versions ?? []),
    isLoading: props.isLoading ?? false,
  } as unknown as ReturnType<typeof useDocumentVersions>);

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onClose = props.onClose ?? vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <VersionHistory documentId={props.documentId ?? 42} documentName="contract.pdf" onClose={onClose} />
    </QueryClientProvider>
  );
  return onClose;
}

describe("VersionHistory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(cleanup);

  it("renders the document name and a version entry", () => {
    setup({ versions: [version()] });

    expect(screen.getByText("contract.pdf")).toBeInTheDocument();
    expect(screen.getByText(/Phiên bản 1/)).toBeInTheDocument();
  });

  it("marks the newest entry as current and shows restore only on older ones", () => {
    setup({ versions: [version({ versionNumber: 2 }), version({ versionNumber: 1 })] });

    expect(screen.getAllByText("Hiện tại")).toHaveLength(1);
    expect(screen.getAllByText("Khôi phục")).toHaveLength(1);
    expect(screen.getByText(/Phiên bản 2/)).toBeInTheDocument();
  });

  it("renders formatted file size when present", () => {
    setup({
      versions: [
        version({ fileSize: 2048 }),
        version({ versionNumber: 0, fileSize: 512, createdAt: "2026-08-26T03:00:00.000Z" }),
      ],
    });

    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
    expect(screen.getByText("512 B")).toBeInTheDocument();
  });

  it("renders the change description when present", () => {
    setup({ versions: [version({ changeDescription: "fixed clause 4" })] });

    expect(screen.getByText("fixed clause 4")).toBeInTheDocument();
  });

  it("shows a loading state", () => {
    setup({ isLoading: true });

    expect(screen.getByText("Đang tải...")).toBeInTheDocument();
  });

  it("shows the empty state when there is no history", () => {
    setup({ versions: [] });

    expect(screen.getByText("Chưa có lịch sử phiên bản.")).toBeInTheDocument();
  });

  it("calls onClose from both the close button and the backdrop", async () => {
    const onClose = setup({ versions: [version()] });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Đóng" }));
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.click(screen.getByTestId("version-history").firstElementChild!);
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
