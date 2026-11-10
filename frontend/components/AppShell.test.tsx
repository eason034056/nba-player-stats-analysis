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
});
