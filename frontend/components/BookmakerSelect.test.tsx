import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { BookmakerSelect } from "@/components/BookmakerSelect";
import { BOOKMAKERS } from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";

describe("BookmakerSelect", () => {
  it("collapses to one line on mobile and leaves the picker open at md", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(<BookmakerSelect value={[]} onChange={onChange} />);

    const toggle = screen.getByTestId("bookmaker-mobile-toggle");
    expect(toggle.className).toContain("md:hidden");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveTextContent(`Bookmakers · All ${BOOKMAKERS.length} bookmakers`);

    const picker = screen.getByTestId("bookmaker-picker");
    expect(picker.className).toContain("max-md:hidden");
    expect(picker.className).not.toMatch(/(?:^|\s)hidden(?:\s|$)/);
    expect(screen.getByText("Featured Platforms")).toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(picker.className).not.toContain("max-md:hidden");

    await user.click(screen.getByRole("button", { name: "DraftKings" }));
    expect(onChange).toHaveBeenCalled();
  });

  it("lists featured books in BALLDONTLIE order and sends ballybet", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(<BookmakerSelect value={[]} onChange={onChange} />);

    const featured = screen.getByRole("heading", { name: "Featured Platforms" }).nextElementSibling;
    expect(featured).not.toBeNull();
    expect(
      within(featured as HTMLElement)
        .getAllByRole("button")
        .map((button) => button.textContent?.trim()),
    ).toEqual(["DraftKings", "FanDuel", "BetMGM", "Caesars", "BetRivers", "Fanatics"]);
    expect(screen.queryByRole("button", { name: "ESPN Bet" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Bet365" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /other bookmakers \(4\)/i }));
    const others = screen.getByRole("button", { name: /other bookmakers \(4\)/i }).nextElementSibling;
    expect(others).not.toBeNull();
    expect(
      within(others as HTMLElement)
        .getAllByRole("button")
        .map((button) => button.textContent?.trim()),
    ).toEqual(["BetPARX", "Bally Bet", "Betway", "Rebet"]);

    await user.click(screen.getByRole("button", { name: "Bally Bet" }));
    expect(onChange).toHaveBeenCalledWith(
      BOOKMAKERS.map((book) => book.key).filter((key) => key !== "ballybet"),
    );
    expect(BOOKMAKERS.map((book) => book.key)).not.toContain("bally_bet");
  });
});
