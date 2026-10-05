import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import RenameDialog from "./RenameDialog";

function setup(props: {
  open?: boolean;
  currentTitle?: string | null;
  currentNumber?: string | null;
  loading?: boolean;
  onClose?: () => void;
  onSave?: (data: { title: string; documentNumber: string }) => void;
} = {}) {
  const onClose = props.onClose ?? vi.fn();
  const onSave = props.onSave ?? vi.fn();
  render(
    <RenameDialog
      open={props.open ?? true}
      currentTitle={props.currentTitle ?? "Old title"}
      currentNumber={props.currentNumber ?? "HDLD-2024-001"}
      onClose={onClose}
      onSave={onSave}
      loading={props.loading}
    />
  );
  return { onClose, onSave };
}

describe("RenameDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(cleanup);

  it("renders nothing when closed", () => {
    setup({ open: false });

    expect(screen.queryByText("Đổi tên tài liệu")).toBeNull();
  });

  it("prefills title and number from current values", () => {
    setup();

    expect(screen.getByLabelText("Tiêu đề tài liệu")).toHaveValue("Old title");
    expect(screen.getByLabelText("Số văn bản")).toHaveValue("HDLD-2024-001");
  });

  it("shows a live character counter as the title is edited", async () => {
    const user = userEvent.setup();

    setup({ currentTitle: "" });

    await user.type(screen.getByLabelText("Tiêu đề tài liệu"), "hello");
    expect(screen.getByText("5/200")).toBeInTheDocument();
  });

  it("saves trimmed values", async () => {
    const user = userEvent.setup();
    const { onSave } = setup({ currentTitle: "  draft  ", currentNumber: "  N-9  " });

    await user.click(screen.getByText("Lưu"));

    expect(onSave).toHaveBeenCalledWith({ title: "draft", documentNumber: "N-9" });
  });

  it("disables save when the title is blank", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();

    setup({ currentTitle: "", onSave });

    const saveBtn = screen.getByText("Lưu");
    expect(saveBtn).toBeDisabled();
    await user.clear(screen.getByLabelText("Tiêu đề tài liệu"));
    expect(saveBtn).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("closes via cancel and via the backdrop", async () => {
    const user = userEvent.setup();
    const { onClose } = setup();

    await user.click(screen.getByText("Hủy"));
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.click(screen.getByText("Đổi tên tài liệu").parentElement!.parentElement!);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("shows a loading state that blocks save", () => {
    setup({ loading: true });

    expect(screen.getByText("Đang lưu...")).toBeInTheDocument();
    expect(screen.getByText("Hủy")).toBeDisabled();
  });
});
