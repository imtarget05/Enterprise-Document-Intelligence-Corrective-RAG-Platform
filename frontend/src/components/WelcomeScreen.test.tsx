import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WelcomeScreen from "./WelcomeScreen";

afterEach(() => cleanup());

describe("WelcomeScreen", () => {
  it("renders the heading and upload call-to-action", () => {
    render(<WelcomeScreen onUploadClick={vi.fn()} />);
    expect(screen.getByText("Chào mừng đến với Smart Document")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Tải lên tài liệu đầu tiên/ })).toBeInTheDocument();
  });

  it("lists the four suggested prompts", () => {
    render(<WelcomeScreen onUploadClick={vi.fn()} />);
    expect(screen.getByText("Tóm tắt tài liệu này")).toBeInTheDocument();
    expect(screen.getByText("Điều khoản pháp lý quan trọng")).toBeInTheDocument();
    expect(screen.getByText("So sánh các điều khoản")).toBeInTheDocument();
    expect(screen.getByText("Trích xuất các điểm chính")).toBeInTheDocument();
  });

  it("calls onSelectPrompt with the prompt text when provided", async () => {
    const user = userEvent.setup();
    const onSelectPrompt = vi.fn();
    render(<WelcomeScreen onUploadClick={vi.fn()} onSelectPrompt={onSelectPrompt} />);

    await user.click(screen.getByText("Tóm tắt tài liệu này"));
    expect(onSelectPrompt).toHaveBeenCalledWith("Tóm tắt tài liệu này");
  });

  it("falls back to onUploadClick when onSelectPrompt is not provided", async () => {
    const user = userEvent.setup();
    const onUploadClick = vi.fn();
    render(<WelcomeScreen onUploadClick={onUploadClick} />);

    await user.click(screen.getByText("So sánh các điều khoản"));
    expect(onUploadClick).toHaveBeenCalledTimes(1);
  });
});
