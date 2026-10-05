import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import DocumentMenu from "./DocumentMenu";
import type { Document } from "../types";

function baseDoc(): Document {
  return {
    id: 7,
    fileName: "contract.pdf",
    title: "contract.pdf",
    createdAt: "2026-08-26T04:00:00.000Z",
  } as Document;
}

function setup(callbacks: { onRename?: () => void; onDelete?: () => void; onViewHistory?: () => void } = {}) {
  const onRename = callbacks.onRename ?? vi.fn();
  const onDelete = callbacks.onDelete ?? vi.fn();
  const onViewHistory = callbacks.onViewHistory ?? vi.fn();
  render(
    <DocumentMenu document={baseDoc()} onRename={onRename} onDelete={onDelete} onViewHistory={onViewHistory} />
  );
  return { onRename, onDelete, onViewHistory };
}

describe("DocumentMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(cleanup);

  it("starts closed and opens on toggle click", async () => {
    const user = userEvent.setup();

    setup();

    expect(screen.queryByText("Đổi tên")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Tùy chọn" }));
    expect(screen.getByText("Đổi tên")).toBeInTheDocument();
  });

  it("dispatches rename and closes the menu", async () => {
    const user = userEvent.setup();
    const { onRename } = setup();

    await user.click(screen.getByRole("button", { name: "Tùy chọn" }));
    await user.click(screen.getByText("Đổi tên"));

    expect(onRename).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Lịch sử")).toBeNull();
  });

  it("dispatches view-history", async () => {
    const user = userEvent.setup();
    const { onViewHistory } = setup();

    await user.click(screen.getByRole("button", { name: "Tùy chọn" }));
    await user.click(screen.getByText("Lịch sử"));

    expect(onViewHistory).toHaveBeenCalledTimes(1);
  });

  it("dispatches delete", async () => {
    const user = userEvent.setup();
    const { onDelete } = setup();

    await user.click(screen.getByRole("button", { name: "Tùy chọn" }));
    await user.click(screen.getByText("Xóa"));

    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("closes when clicking outside the menu", async () => {
    const user = userEvent.setup();

    render(
      <div>
        <button type="button">outside</button>
        <DocumentMenu document={baseDoc()} onRename={vi.fn()} onDelete={vi.fn()} onViewHistory={vi.fn()} />
      </div>
    );

    await user.click(screen.getByRole("button", { name: "Tùy chọn" }));
    expect(screen.getByText("Đổi tên")).toBeInTheDocument();
    await user.click(screen.getByText("outside"));
    expect(screen.queryByText("Đổi tên")).toBeNull();
  });
});
