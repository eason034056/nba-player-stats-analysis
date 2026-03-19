import { useState } from "react";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DatePicker } from "@/components/DatePicker";
import { MarketSelect } from "@/components/MarketSelect";
import { PlayerInput } from "@/components/PlayerInput";
import { renderWithProviders } from "@/test/test-utils";

const apiMocks = vi.hoisted(() => ({
  getPlayerSuggestions: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  getPlayerSuggestions: apiMocks.getPlayerSuggestions,
}));

const mockGetPlayerSuggestions = vi.mocked(apiMocks.getPlayerSuggestions);

const ControlledPlayerInput = ({
  initialValue = "",
}: {
  initialValue?: string;
}) => {
  const [value, setValue] = useState(initialValue);

  return (
    <PlayerInput
      eventId="evt-1"
      market="player_points"
      value={value}
      onChange={setValue}
    />
  );
};

describe("control readability refresh", () => {
  beforeEach(() => {
    mockGetPlayerSuggestions.mockImplementation(async (_eventId, query = "") => {
      const normalized = query.toLowerCase();

      if (!normalized) {
        return {
          players: ["Cam Spencer", "Nick Richards", "Matas Buzelis"],
        };
      }

      if (normalized.includes("nick")) {
        return {
          players: ["Nick Richards"],
        };
      }

      return {
        players: [],
      };
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the home date control in compact English format with an active today segment", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-16T12:00:00"));

    renderWithProviders(
      <DatePicker value="2026-03-16" onChange={vi.fn()} />,
    );

    expect(screen.getByText("Mar 16 · Mon")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Today" }),
    ).toHaveClass("control-segment-active");
    expect(
      screen.getByRole("button", { name: "Tomorrow" }),
    ).toHaveClass("control-segment");
  });

  it("uses explicit active and neutral tile styles for stat selection", () => {
    renderWithProviders(
      <MarketSelect value="player_points" onChange={vi.fn()} />,
    );

    expect(screen.getByTitle("Player points scored")).toHaveClass(
      "control-tile-active",
    );
    expect(screen.getByTitle("Player assists")).toHaveClass("control-tile");
  });

  it("shows the console dropdown and selected player chip with readable state classes", async () => {
    const user = userEvent.setup();

    renderWithProviders(<ControlledPlayerInput initialValue="Nick Richards" />);

    const selectedChip = await screen.findByRole("button", {
      name: "Nick Richards",
    });
    expect(selectedChip).toHaveClass("control-chip-active");

    const input = screen.getByPlaceholderText(
      "Enter player name, e.g., Stephen Curry",
    );

    await user.clear(input);
    await user.type(input, "Nick");

    const dropdown = await screen.findByRole("list");
    expect(dropdown).toHaveClass("control-popover");

    const option = within(dropdown).getByText("Nick Richards");
    expect(option.closest("li")).toHaveClass("control-option");
  });
});
