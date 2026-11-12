import { screen } from "@testing-library/react";
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
});
