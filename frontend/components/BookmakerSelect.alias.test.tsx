import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { BookmakerSelect } from "@/components/BookmakerSelect";
import { renderWithProviders } from "@/test/test-utils";

describe("BookmakerSelect stored alias", () => {
  it("shows a saved bally_bet as selected and reports ballybet", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(<BookmakerSelect value={["bally_bet"]} onChange={onChange} />);

    expect(screen.getByTestId("bookmaker-mobile-toggle")).toHaveTextContent("1 of 10 bookmakers");

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith(["ballybet"]);
    });

    await user.click(screen.getByRole("button", { name: /other bookmakers \(4\)/i }));
    const bally = screen.getByRole("button", { name: "Bally Bet" });
    expect(bally.className.split(/\s+/)).toContain("control-chip-active");
  });
});
