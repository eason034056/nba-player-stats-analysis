import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/AppShell";
import { renderWithProviders } from "@/test/test-utils";

const navigationMocks = vi.hoisted(() => ({
  usePathname: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => navigationMocks);
vi.mock("@/lib/agent-chat-ui", () => ({
  AGENT_CHAT_UI_ENABLED: true,
}));

const shellPaths = [
  "/",
  "/picks",
  "/betslip",
  "/about",
  "/event/heat-bucks",
  "/wnba",
  "/wnba/picks",
  "/wnba/betslip",
  "/wnba/event/aces-liberty",
  "/wnba/player/A%27ja%20Wilson",
];

describe("AppShell with the agent chat UI on", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    navigationMocks.usePathname.mockReturnValue("/");
  });

  it("keeps an Ask control on every NBA and WNBA route", () => {
    const { rerender } = renderWithProviders(
      <AppShell>
        <p>Board</p>
      </AppShell>,
      { withAgentWidget: true },
    );

    for (const path of shellPaths) {
      navigationMocks.usePathname.mockReturnValue(path);
      rerender(
        <AppShell>
          <p>Board</p>
        </AppShell>,
      );
      expect(screen.getByRole("button", { name: "Ask the agent" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Ask agent" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /ask the board/i })).not.toBeInTheDocument();
    }
  });

  it("opens the betting agent from Ask the agent", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AppShell>
        <p>Board</p>
      </AppShell>,
      { withAgentWidget: true },
    );

    await user.click(screen.getByRole("button", { name: "Ask the agent" }));
    expect(screen.getByRole("button", { name: "Close betting agent" })).toBeInTheDocument();
  });

  it("opens the betting agent from the compact Ask agent control", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AppShell>
        <p>Board</p>
      </AppShell>,
      { withAgentWidget: true },
    );

    await user.click(screen.getByRole("button", { name: "Ask agent" }));
    expect(screen.getByRole("button", { name: "Close betting agent" })).toBeInTheDocument();
  });
});
