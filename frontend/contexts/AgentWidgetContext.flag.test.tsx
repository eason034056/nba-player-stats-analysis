import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AgentWidget } from "@/components/AgentWidget";
import { useAgentWidget } from "@/contexts/AgentWidgetContext";
import { AGENT_CHAT_UI_ENABLED } from "@/lib/agent-chat-ui";
import { renderWithProviders } from "@/test/test-utils";

const apiMocks = vi.hoisted(() => ({
  sendAgentChat: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/picks",
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    sendAgentChat: apiMocks.sendAgentChat,
  };
});

function ChatHarness() {
  const { openWidget, submitAction } = useAgentWidget();
  return (
    <>
      <button type="button" onClick={openWidget}>
        Open chat
      </button>
      <button
        type="button"
        onClick={() => void submitAction({ action: "general", message: "Look at this board" })}
      >
        Send chat
      </button>
    </>
  );
}

describe("agent chat flag", () => {
  it.skipIf(AGENT_CHAT_UI_ENABLED)("does not open the widget or call sendAgentChat when chat UI is off", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <ChatHarness />
        <AgentWidget />
      </>,
      { withAgentWidget: true },
    );

    await user.click(screen.getByRole("button", { name: "Open chat" }));
    await user.click(screen.getByRole("button", { name: "Send chat" }));

    expect(screen.queryByRole("dialog", { name: /betting agent/i })).not.toBeInTheDocument();
    expect(apiMocks.sendAgentChat).not.toHaveBeenCalled();
  });
});
