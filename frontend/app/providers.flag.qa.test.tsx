import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Providers } from "@/app/providers";
import { AGENT_CHAT_UI_ENABLED } from "@/lib/agent-chat-ui";

const apiMocks = vi.hoisted(() => ({ sendAgentChat: vi.fn() }));

vi.mock("next/navigation", () => ({ usePathname: () => "/picks" }));
vi.mock("@tanstack/react-query-devtools", () => ({ ReactQueryDevtools: () => null }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, sendAgentChat: apiMocks.sendAgentChat };
});

describe("Providers with the agent chat UI off", () => {
  beforeEach(() => {
    sessionStorage.clear();
    apiMocks.sendAgentChat.mockReset();
  });

  it.skipIf(AGENT_CHAT_UI_ENABLED)(
    "shows no chat widget even when a saved session left it open",
    () => {
      // A visitor who had the widget open before this release still has
      // isOpen=true in sessionStorage. The widget must stay hidden.
      sessionStorage.setItem(
        "agent_widget_state",
        JSON.stringify({ isOpen: true, messages: [], threadId: "t1", viewMode: "panel" }),
      );

      render(
        <Providers>
          <p>Board</p>
        </Providers>,
      );

      expect(screen.getByText("Board")).toBeInTheDocument();
      expect(screen.queryByRole("dialog", { name: /betting agent/i })).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/betting agent/i)).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/message betting agent/i)).not.toBeInTheDocument();
      expect(apiMocks.sendAgentChat).not.toHaveBeenCalled();
    },
  );
});
