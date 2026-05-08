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

  it("renders the SPO-20 12-tile selector with Single/Combo/Binary groups", () => {
    renderWithProviders(
      <MarketSelect value="player_points" onChange={vi.fn()} />,
    );

    // Group sections exist
    expect(screen.getByText("Single Stats")).toBeInTheDocument();
    expect(screen.getByText("Combo")).toBeInTheDocument();
    expect(screen.getByText("Binary")).toBeInTheDocument();

    // 12 tiles in total — pressed state on the selected tile, neutral on the rest
    const allTiles = screen.getAllByRole("button");
    expect(allTiles).toHaveLength(12);

    // 7 Single tiles
    expect(screen.getByTitle("Player points scored")).toBeInTheDocument();
    expect(screen.getByTitle("Player rebounds")).toBeInTheDocument();
    expect(screen.getByTitle("Player assists")).toBeInTheDocument();
    expect(screen.getByTitle("Three-pointers made")).toBeInTheDocument();
    expect(screen.getByTitle("Player steals")).toBeInTheDocument();
    expect(screen.getByTitle("Free throws made")).toBeInTheDocument();
    expect(
      screen.getByTitle("Field goals made (working hypothesis: FGM)"),
    ).toBeInTheDocument();

    // 4 Combo tiles
    expect(screen.getByTitle("Sum of three stats")).toBeInTheDocument();
    expect(screen.getByTitle("Rebounds + Assists")).toBeInTheDocument();
    expect(screen.getByTitle("Points + Rebounds")).toBeInTheDocument();
    expect(screen.getByTitle("Points + Assists")).toBeInTheDocument();

    // 1 Binary tile (DD) — Yes/No, no threshold
    const ddTile = screen.getByTitle(
      "Player records a double-double (Yes/No)",
    );
    expect(ddTile).toBeInTheDocument();
    // DD is in the binary group section
    const binaryGroup = ddTile.closest(
      '[data-market-group="binary"]',
    ) as HTMLElement | null;
    expect(binaryGroup).not.toBeNull();
    expect(within(binaryGroup!).getAllByRole("button")).toHaveLength(1);
  });

  it("flags the DD binary tile as selected via aria-pressed when chosen", () => {
    renderWithProviders(
      <MarketSelect value="player_double_double" onChange={vi.fn()} />,
    );

    const ddTile = screen.getByTitle(
      "Player records a double-double (Yes/No)",
    );
    expect(ddTile).toHaveAttribute("aria-pressed", "true");
    expect(ddTile).toHaveClass("control-tile-active");

    // Other tiles stay neutral
    expect(screen.getByTitle("Player points scored")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
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
