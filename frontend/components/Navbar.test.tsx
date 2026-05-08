import type { ReactNode } from "react";
import { waitFor, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Navbar } from "@/components/Navbar";
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

describe("Navbar", () => {
  beforeEach(() => {
    clearBetSlip();
    navigationMocks.usePathname.mockReturnValue("/picks");
  });

  it("highlights the active route and shows the bet slip count", async () => {
    seedBetSlip([
      createBetSlipPick(),
      createBetSlipPick({
        id: "LeBron James-points",
        player_name: "LeBron James",
      }),
    ]);

    renderWithProviders(<Navbar />);

    const dailyPicksLink = screen.getByRole("link", { name: /daily picks/i });
    expect(dailyPicksLink).toHaveAttribute("aria-current", "page");

    await waitFor(() => {
      expect(screen.getByText("2")).toBeInTheDocument();
    });
  });

  it("toggles a mobile navigation menu", async () => {
    const user = userEvent.setup();

    renderWithProviders(<Navbar />);

    const menuButton = screen.getByRole("button", {
      name: /open navigation menu/i,
    });

    expect(menuButton).toHaveAttribute("aria-expanded", "false");

    await user.click(menuButton);

    expect(menuButton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("dialog", { name: /mobile navigation/i })).toBeInTheDocument();
  });
});
