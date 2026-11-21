import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAgentWidget } from "@/contexts/AgentWidgetContext";
import { renderWithProviders } from "@/test/test-utils";

const chatFlag = vi.hoisted(() => ({ enabled: false }));

const apiMocks = vi.hoisted(() => ({
  sendAgentChat: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/picks",
}));

vi.mock("@/lib/agent-chat-ui", () => ({
  get AGENT_CHAT_UI_ENABLED() {
    return chatFlag.enabled;
  },
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    sendAgentChat: apiMocks.sendAgentChat,
  };
});

const chatResponse = {
  thread: "thread-1",
  action: "general" as const,
  status: "ok" as const,
  reply: "Checked the board.",
  verdict: null,
  slip_review: null,
  quick_actions: [],
};

function GuardHarness() {
  const { isOpen, isPending, messages, retryLastRequest, submitAction } = useAgentWidget();
  return (
    <>
      <button
        type="button"
        onClick={() => void submitAction({ action: "general", message: "Look at this board" })}
      >
        Send chat
      </button>
      <button type="button" onClick={() => void retryLastRequest()}>
        Retry chat
      </button>
      <p data-testid="chat-open">{isOpen ? "open" : "closed"}</p>
      <p data-testid="chat-pending">{isPending ? "pending" : "idle"}</p>
      <p data-testid="chat-messages">{messages.length}</p>
    </>
  );
}

function storedThreadId(): string {
  const raw = window.sessionStorage.getItem("agent_widget_state");
  if (!raw) return "";
  const stored = JSON.parse(raw) as { threadId?: string };
  return stored.threadId ?? "";
}

describe("agent chat guards", () => {
  beforeEach(() => {
    chatFlag.enabled = false;
    window.sessionStorage.clear();
    apiMocks.sendAgentChat.mockReset();
    apiMocks.sendAgentChat.mockResolvedValue(chatResponse);
  });

  it("submitAction returns without calling sendAgentChat when the flag is off", async () => {
    const user = userEvent.setup();
    renderWithProviders(<GuardHarness />);

    await user.click(screen.getByRole("button", { name: "Send chat" }));

    expect(apiMocks.sendAgentChat).not.toHaveBeenCalled();
    expect(screen.getByTestId("chat-open")).toHaveTextContent("closed");
    expect(screen.getByTestId("chat-pending")).toHaveTextContent("idle");
    expect(screen.getByTestId("chat-messages")).toHaveTextContent("0");
    await waitFor(() => {
      expect(storedThreadId()).toBe("");
    });
  });

  it("runRequest returns without calling sendAgentChat when the flag is off", async () => {
    const user = userEvent.setup();
    chatFlag.enabled = true;
    renderWithProviders(<GuardHarness />);

    await user.click(screen.getByRole("button", { name: "Send chat" }));
    await waitFor(() => {
      expect(apiMocks.sendAgentChat).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId("chat-messages")).not.toHaveTextContent("0");
    const messagesAfterSend = screen.getByTestId("chat-messages").textContent;

    chatFlag.enabled = false;
    apiMocks.sendAgentChat.mockClear();

    await user.click(screen.getByRole("button", { name: "Retry chat" }));

    expect(apiMocks.sendAgentChat).not.toHaveBeenCalled();
    expect(screen.getByTestId("chat-pending")).toHaveTextContent("idle");
    expect(screen.getByTestId("chat-messages")).toHaveTextContent(messagesAfterSend ?? "");
  });
});
