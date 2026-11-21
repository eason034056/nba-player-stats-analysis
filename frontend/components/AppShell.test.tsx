import type { ReactNode } from "react";
import { screen, waitFor, within } from "@testing-library/react";
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

const RETIRED_SLIP_KEY = "wnba_betslip_picks";

describe("AppShell", () => {
  beforeEach(() => {
    clearBetSlip();
    window.localStorage.removeItem(RETIRED_SLIP_KEY);
    window.sessionStorage.clear();
    navigationMocks.usePathname.mockReturnValue("/");
  });

  it("highlights Today and shows the bet slip count", async () => {
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
    expect(screen.queryByRole("group", { name: "League" })).not.toBeInTheDocument();

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

  it("drops a retired slip key so it cannot be parsed", async () => {
    window.localStorage.setItem(RETIRED_SLIP_KEY, "{not-json");
    renderWithProviders(
      <AppShell>
        <p>Board</p>
      </AppShell>,
    );

    await waitFor(() => {
      expect(window.localStorage.getItem(RETIRED_SLIP_KEY)).toBeNull();
    });
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
  });

  const shellPaths = ["/", "/picks", "/betslip", "/about", "/event/heat-bucks"];

  function renderShellPaths() {
    const { rerender } = renderWithProviders(
      <AppShell>
        <p>Board</p>
      </AppShell>,
      { withAgentWidget: true },
    );
    return (path: string) => {
      navigationMocks.usePathname.mockReturnValue(path);
      rerender(
        <AppShell>
          <p>Board</p>
        </AppShell>,
      );
    };
  }

  it("renders no Ask controls when chat UI is off", () => {
    const showPath = renderShellPaths();
    for (const path of shellPaths) {
      showPath(path);
      expect(screen.queryByRole("button", { name: "Ask the agent" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Ask agent" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^ask$/i })).not.toBeInTheDocument();
    }
  });

  it("highlights Method on the method page", () => {
    navigationMocks.usePathname.mockReturnValue("/about");
    renderWithProviders(
      <AppShell>
        <p>Method</p>
      </AppShell>,
    );

    const primary = screen.getByRole("navigation", { name: "Primary" });
    expect(within(primary).getByRole("link", { name: "Method" })).toHaveAttribute("aria-current", "page");
    expect(within(primary).getByRole("link", { name: "Method" })).toHaveAttribute("href", "/about");
    expect(within(primary).getByRole("link", { name: "Today" })).toHaveAttribute("href", "/");
  });

  it("highlights Today on an event page", () => {
    navigationMocks.usePathname.mockReturnValue("/event/heat-bucks");
    renderWithProviders(
      <AppShell>
        <p>Event</p>
      </AppShell>,
    );

    const primary = screen.getByRole("navigation", { name: "Primary" });
    expect(within(primary).getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page");
    expect(within(primary).getByRole("link", { name: "Today" })).toHaveAttribute("href", "/");
    expect(within(primary).getByRole("link", { name: "Picks" })).toHaveAttribute("href", "/picks");
    expect(within(primary).getByRole("link", { name: /bet slip/i })).toHaveAttribute("href", "/betslip");
  });

  it("does not light a tab for a path outside the four sections", () => {
    navigationMocks.usePathname.mockReturnValue("/player/Stephen%20Curry");
    renderWithProviders(
      <AppShell>
        <p>Player</p>
      </AppShell>,
    );

    const primary = screen.getByRole("navigation", { name: "Primary" });
    expect(within(primary).getByRole("link", { name: "Today" })).not.toHaveAttribute("aria-current", "page");
    expect(within(primary).getByRole("link", { name: "Today" })).toHaveAttribute("href", "/");
    expect(within(primary).getByRole("link", { name: "Picks" })).toHaveAttribute("href", "/picks");
    expect(within(primary).getByRole("link", { name: /bet slip/i })).toHaveAttribute("href", "/betslip");
  });

  it("spans the web header and leaves the research disclaimer on Method only", () => {
    renderWithProviders(
      <AppShell>
        <p>Board</p>
      </AppShell>,
    );

    const bar = screen.getByTestId("web-header");
    expect(bar.className).toContain("w-full");
    expect(bar.className).toContain("px-8");
    expect(bar.className).not.toContain("max-w-");
    expect(screen.queryByRole("contentinfo")).not.toBeInTheDocument();
    expect(screen.queryByText(/not betting advice/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/for research/i)).not.toBeInTheDocument();
  });

  it("highlights Bet Slip on the slip page", () => {
    navigationMocks.usePathname.mockReturnValue("/betslip");
    renderWithProviders(
      <AppShell>
        <p>Slip</p>
      </AppShell>,
    );

    const primary = screen.getByRole("navigation", { name: "Primary" });
    expect(within(primary).getByRole("link", { name: /bet slip/i })).toHaveAttribute("aria-current", "page");
    expect(within(primary).getByRole("link", { name: /bet slip/i })).toHaveAttribute("href", "/betslip");
  });
});
