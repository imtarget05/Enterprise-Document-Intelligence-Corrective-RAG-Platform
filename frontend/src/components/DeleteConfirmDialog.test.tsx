import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DeleteConfirmDialog from "./DeleteConfirmDialog";

afterEach(() => cleanup());

describe("DeleteConfirmDialog", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <DeleteConfirmDialog open={false} documentName="doc.pdf" onClose={vi.fn()} onConfirm={vi.fn()} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the document name and confirm/cancel actions when open", async () => {
    render(<DeleteConfirmDialog open documentName="contract.pdf" onClose={vi.fn()} onConfirm={vi.fn()} />);
    expect(screen.getByText("Xóa tài liệu?")).toBeInTheDocument();
    expect(screen.getByText("contract.pdf")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hủy" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Xóa" })).toBeInTheDocument();
  });

  it("calls onClose when the backdrop is clicked but not from inside the dialog", () => {
    const onClose = vi.fn();
    const onConfirm = vi.fn();
    const { container } = render(
      <DeleteConfirmDialog open documentName="doc.pdf" onClose={onClose} onConfirm={onConfirm} />
    );

    // Click the dimmed overlay itself, outside the dialog card.
    const overlay = container.querySelector(".fixed.inset-0")!;
    fireEvent.click(overlay);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("calls onConfirm when the confirm button is clicked", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<DeleteConfirmDialog open documentName="doc.pdf" onClose={vi.fn()} onConfirm={onConfirm} />);

    await user.click(screen.getByRole("button", { name: "Xóa" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("shows a deleting state that disables both buttons", async () => {
    render(
      <DeleteConfirmDialog open documentName="doc.pdf" onClose={vi.fn()} onConfirm={vi.fn()} loading />
    );
    expect(screen.getByRole("button", { name: "Đang xóa..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Hủy" })).toBeDisabled();
  });
});
