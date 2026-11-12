import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { activeFilterCount, RangeControl, type FilterState } from "@/components/event/GameFilters";
import { NbaGameLog } from "@/components/event/NbaGameLog";
import { gameLogChart, gameLogTiles } from "@/lib/event-page";

const noop = () => {};

function filterState(overrides: Partial<FilterState> = {}): FilterState {
  return {
    range: 10,
    onRange: noop,
    lineText: "18.5",
    lineChanged: false,
    lineDisabled: false,
    onMinus: noop,
    onPlus: noop,
    onResetLine: noop,
    role: "all",
    onRole: noop,
    opponent: "",
    opponents: ["BOS", "PHI"],
    onOpponent: noop,
    teammates: ["Tyler Herro"],
    selectedMates: [],
    onToggleMate: noop,
    mateMode: "all",
    onMateMode: noop,
    ...overrides,
  };
}

const logs = [
  { date: "11/01", date_full: "2026-11-01", opponent: "PHI", value: 22, minutes: 34, is_starter: true },
  { date: "11/03", date_full: "2026-11-03", opponent: "BOS", value: 14, minutes: 31, is_starter: true },
];

function renderLog(props: Partial<Parameters<typeof NbaGameLog>[0]> = {}) {
  return render(
    <NbaGameLog
      filters={filterState()}
      note="Points · 2 games"
      tiles={gameLogTiles({ n_games: 2, p_over: 0.5, p_under: 0.5, mean: 18 }, 18.5)}
      chart={{
        model: gameLogChart(logs as never, 18.5),
        selectedKey: null,
        onSelect: noop,
        isLoading: false,
        isError: false,
        errorText: null,
        emptyMessage: null,
      }}
      activeFilters={0}
      onOpenFilters={noop}
      onReset={null}
      {...props}
    />,
  );
}

describe("RangeControl", () => {
  it("offers L5, L10, L20, and All on NBA and keeps the WNBA labels", () => {
    const { unmount } = render(<RangeControl league="nba" value={5} onChange={noop} />);
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["L5", "L10", "L20", "All"]);
    expect(screen.getByRole("button", { name: "L5" })).toHaveAttribute("aria-pressed", "true");
    unmount();

    render(<RangeControl league="wnba" value={10} onChange={noop} />);
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["Last 10", "Last 20", "All"]);
  });

  it("sends 5 when L5 is picked", async () => {
    const onChange = vi.fn();
    render(<RangeControl league="nba" value={10} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "L5" }));
    expect(onChange).toHaveBeenCalledWith(5);
  });
});

describe("NbaGameLog", () => {
  it("puts the filters above the stat tiles and the tiles above the chart", () => {
    renderLog();

    const card = screen.getByTestId("game-log");
    const filters = within(card).getByTestId("game-filters");
    const tile = within(card).getByTestId("log-tile-over");
    const chart = within(card).getByTestId("game-log-chart");
    expect(filters.compareDocumentPosition(tile) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(tile.compareDocumentPosition(chart) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(card).getByRole("heading", { name: "Game log" })).toBeInTheDocument();
    expect(within(card).getByText("Points · 2 games")).toBeInTheDocument();
    expect(within(chart).queryByRole("heading", { name: "Game log" })).not.toBeInTheDocument();
  });

  it("prints each tile with its count or its gap to the line", () => {
    renderLog();

    expect(screen.getByTestId("log-tile-over")).toHaveTextContent("Over 18.550%1 of 2 games");
    expect(screen.getByTestId("log-tile-average")).toHaveTextContent("Average18.0-0.5 vs line");
    expect(screen.getByTestId("log-tile-games")).toHaveTextContent("Games2");
  });

  it("counts active sheet filters on the mobile button and offers a reset", async () => {
    const onOpenFilters = vi.fn();
    const onReset = vi.fn();
    renderLog({ activeFilters: 2, onOpenFilters, onReset });

    await userEvent.click(screen.getByRole("button", { name: "Filters · 2" }));
    expect(onOpenFilters).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(onReset).toHaveBeenCalled();
  });

  it("hides the reset link when nothing is filtered", () => {
    renderLog();
    expect(screen.getByRole("button", { name: "Filters" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reset filters" })).not.toBeInTheDocument();
  });
});

describe("activeFilterCount", () => {
  it("counts role, opponent, and a teammate split, and ignores teammates with mode All", () => {
    expect(activeFilterCount(filterState())).toBe(0);
    expect(activeFilterCount(filterState({ role: "bench", opponent: "BOS" }))).toBe(2);
    expect(activeFilterCount(filterState({ selectedMates: ["Tyler Herro"] }))).toBe(0);
    expect(activeFilterCount(filterState({ selectedMates: ["Tyler Herro"], mateMode: "without" }))).toBe(1);
  });
});
