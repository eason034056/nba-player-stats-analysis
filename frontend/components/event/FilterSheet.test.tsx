import { useState } from "react";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FilterSheet } from "@/components/event/FilterSheet";
import { renderWithProviders } from "@/test/test-utils";

function Harness({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Filters
      </button>
      <FilterSheet
        open={open}
        onClose={() => {
          onClose();
          setOpen(false);
        }}
      >
        <button type="button">Raise line</button>
        <button type="button">Lower line</button>
      </FilterSheet>
    </>
  );
}

describe("FilterSheet", () => {
  it("is a modal dialog, moves focus inside, and returns focus on Escape", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness onClose={vi.fn()} />);
    const trigger = screen.getByRole("button", { name: "Filters" });
    await user.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "Filter games" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("button", { name: "Raise line" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("does not move focus when the parent passes a new onClose", async () => {
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(<Harness onClose={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Filters" }));
    const lower = screen.getByRole("button", { name: "Lower line" });
    lower.focus();
    expect(lower).toHaveFocus();

    rerender(<Harness onClose={vi.fn()} />);
    expect(lower).toHaveFocus();
    expect(screen.getByRole("button", { name: "Raise line" })).not.toHaveFocus();
  });

  it("traps Tab and Shift+Tab inside the sheet", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness onClose={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Filters" }));
    const raise = screen.getByRole("button", { name: "Raise line" });
    const lower = screen.getByRole("button", { name: "Lower line" });
    expect(raise).toHaveFocus();

    await user.tab();
    expect(lower).toHaveFocus();
    await user.tab();
    expect(raise).toHaveFocus();
    await user.tab({ shift: true });
    expect(lower).toHaveFocus();
  });
});
