import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AgentModeToggle from "./AgentModeToggle";

afterEach(cleanup);

describe("AgentModeToggle", () => {
  it("invokes onToggle(false) for RAG and onToggle(true) for Agent", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(<AgentModeToggle agentMode={true} onToggle={onToggle} />);

    await user.click(screen.getByText("RAG"));
    await user.click(screen.getByText("Agent"));
    expect(onToggle).toHaveBeenNthCalledWith(1, false);
    expect(onToggle).toHaveBeenNthCalledWith(2, true);
  });
});
