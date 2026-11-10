import type { ReactNode } from "react";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/AppShell";
import {
  clearBetSlip,
  createBetSlipPick,
  renderWithProviders,
  seedBetSlip,
} from "@/test/test-utils";

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
    children: ReactNode;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => navigationMocks);

function seedWnbaSlip(count: number) {
  const picks = Array.from({ length: count }, (_, index) =>
    createBetSlipPick({
      id: `aja-${index}`,
      player_name: `Player ${index}`,
    }),
  );
  window.localStorage.setItem("wnba_betslip_picks", JSON.stringify(picks));
}

describe("AppShell", () => {
  beforeEach(() => {
    clearBetSlip();
    window.localStorage.removeItem("wnba_betslip_picks");
    window.sessionStorage.clear();
    navigationMocks.usePathname.mockReturnValue("/");
  });

  it("highlights Today and shows the NBA bet slip count", async () => {
    seedBetSlip([createBetSlipPick(), createBetSlipPick({ id: "bam", player_name: "Bam Adebayo" })]);
    renderWithProviders(
      <AppShell>
        <p>Board</p>
      </AppShell>,
    );

    const primary = screen.getByRole("navigation", { name: "Primary" });
    expect(within(primary).getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page");
    expect(within(primary).getByRole("link", { name: "Today" })).toHaveAttribute("href", "/");
    expect(within(primary).getByRole("link", { name: "Picks" })).toHaveAttribute("href", "/picks");
    expect(within(primary).getByRole("link", { name: "Method" })).toHaveAttribute("href", "/about");
    expect(within(primary).getByRole("link", { name: /bet slip/i })).toHaveAttribute("href", "/betslip");

    await waitFor(() => {
      expect(within(primary).getByText("2")).toBeInTheDocument();
    });
  });

  it("renders mobile tabs for the same four sections", () => {
    navigationMocks.usePathname.mockReturnValue("/picks");
    renderWithProviders(
      <AppShell>
        <p>Board</p>
      </AppShell>,
    );

    const mobile = screen.getByRole("navigation", { name: "Mobile" });
    expect(within(mobile).getByRole("link", { name: "Picks" })).toHaveAttribute("aria-current", "page");
    expect(within(mobile).getByRole("link", { name: "Today" })).toHaveAttribute("href", "/");
    expect(within(mobile).getByRole("link", { name: "Bet Slip" })).toHaveAttribute("href", "/betslip");
    expect(within(mobile).getByRole("link", { name: "Method" })).toHaveAttribute("href", "/about");
  });

  it("routes the league switch between NBA and WNBA sections", () => {
    const { rerender } = renderWithProviders(
      <AppShell>
        <p>Board</p>
      </AppShell>,
    );

    for (const group of screen.getAllByRole("group", { name: "League" })) {
      expect(within(group).getByRole("link", { name: "NBA" })).toHaveAttribute("aria-current", "true");
      expect(within(group).getByRole("link", { name: "WNBA" })).toHaveAttribute("href", "/wnba");
    }

    navigationMocks.usePathname.mockReturnValue("/wnba/picks");
    rerender(
      <AppShell>
        <p>Board</p>
      </AppShell>,
    );

    const primary = screen.getByRole("navigation", { name: "Primary" });
    expect(within(primary).getByRole("link", { name: "Picks" })).toHaveAttribute("href", "/wnba/picks");
    expect(within(primary).getByRole("link", { name: "Today" })).toHaveAttribute("href", "/wnba");
    expect(within(primary).getByRole("link", { name: /bet slip/i })).toHaveAttribute("href", "/wnba/betslip");
    for (const group of screen.getAllByRole("group", { name: "League" })) {
      expect(within(group).getByRole("link", { name: "WNBA" })).toHaveAttribute("aria-current", "true");
      expect(within(group).getByRole("link", { name: "NBA" })).toHaveAttribute("href", "/picks");
    }
  });

  it("uses the WNBA slip count on a WNBA route", async () => {
    seedBetSlip([createBetSlipPick()]);
    seedWnbaSlip(2);
    navigationMocks.usePathname.mockReturnValue("/wnba");
    renderWithProviders(
      <AppShell>
        <p>Board</p>
      </AppShell>,
    );

    const primary = screen.getByRole("navigation", { name: "Primary" });
    await waitFor(() => {
      expect(within(primary).getByText("2")).toBeInTheDocument();
    });
    expect(within(primary).queryByText("1")).not.toBeInTheDocument();
  });

  it("keeps an Ask control on every NBA and WNBA route", () => {
    const paths = [
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
    const { rerender } = renderWithProviders(
      <AppShell>
        <p>Board</p>
      </AppShell>,
      { withAgentWidget: true },
    );

    for (const path of paths) {
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

  it("keeps Method as one page and sends the league switch to Today", () => {
    navigationMocks.usePathname.mockReturnValue("/about");
    renderWithProviders(
      <AppShell>
        <p>Method</p>
      </AppShell>,
    );

    const primary = screen.getByRole("navigation", { name: "Primary" });
    expect(within(primary).getByRole("link", { name: "Method" })).toHaveAttribute("aria-current", "page");
    expect(within(primary).getByRole("link", { name: "Method" })).toHaveAttribute("href", "/about");
    for (const group of screen.getAllByRole("group", { name: "League" })) {
      expect(within(group).getByRole("link", { name: "NBA" })).toHaveAttribute("href", "/");
      expect(within(group).getByRole("link", { name: "WNBA" })).toHaveAttribute("href", "/wnba");
    }
  });

  it("highlights Today on an event page and switches to the other league's Today", () => {
    navigationMocks.usePathname.mockReturnValue("/event/heat-bucks");
    const { rerender } = renderWithProviders(
      <AppShell>
        <p>Event</p>
      </AppShell>,
    );

    const primary = screen.getByRole("navigation", { name: "Primary" });
    expect(within(primary).getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page");
    for (const group of screen.getAllByRole("group", { name: "League" })) {
      expect(within(group).getByRole("link", { name: "WNBA" })).toHaveAttribute("href", "/wnba");
      expect(within(group).getByRole("link", { name: "NBA" })).toHaveAttribute("aria-current", "true");
    }

    navigationMocks.usePathname.mockReturnValue("/wnba/event/aces-liberty");
    rerender(
      <AppShell>
        <p>Event</p>
      </AppShell>,
    );
    expect(within(primary).getByRole("link", { name: "Today" })).toHaveAttribute("href", "/wnba");
    for (const group of screen.getAllByRole("group", { name: "League" })) {
      expect(within(group).getByRole("link", { name: "NBA" })).toHaveAttribute("href", "/");
      expect(within(group).getByRole("link", { name: "WNBA" })).toHaveAttribute("aria-current", "true");
    }
  });

  it("sends a WNBA player page to NBA Today and keeps the WNBA section links", () => {
    navigationMocks.usePathname.mockReturnValue("/wnba/player/A%27ja%20Wilson");
    renderWithProviders(
      <AppShell>
        <p>Player</p>
      </AppShell>,
    );

    const primary = screen.getByRole("navigation", { name: "Primary" });
    expect(within(primary).getByRole("link", { name: "Today" })).not.toHaveAttribute("aria-current", "page");
    expect(within(primary).getByRole("link", { name: "Today" })).toHaveAttribute("href", "/wnba");
    expect(within(primary).getByRole("link", { name: "Picks" })).toHaveAttribute("href", "/wnba/picks");
    expect(within(primary).getByRole("link", { name: /bet slip/i })).toHaveAttribute("href", "/wnba/betslip");
    for (const group of screen.getAllByRole("group", { name: "League" })) {
      expect(within(group).getByRole("link", { name: "NBA" })).toHaveAttribute("href", "/");
      expect(within(group).getByRole("link", { name: "WNBA" })).toHaveAttribute("aria-current", "true");
    }
  });

  it("keeps Bet Slip when the league switch flips", () => {
    navigationMocks.usePathname.mockReturnValue("/betslip");
    renderWithProviders(
      <AppShell>
        <p>Slip</p>
      </AppShell>,
    );

    const primary = screen.getByRole("navigation", { name: "Primary" });
    expect(within(primary).getByRole("link", { name: /bet slip/i })).toHaveAttribute("aria-current", "page");
    for (const group of screen.getAllByRole("group", { name: "League" })) {
      expect(within(group).getByRole("link", { name: "WNBA" })).toHaveAttribute("href", "/wnba/betslip");
    }
  });
});
