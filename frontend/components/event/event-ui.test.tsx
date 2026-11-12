import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EventHeader } from "@/components/event/EventHeader";
import { GameFilters } from "@/components/event/GameFilters";
import { GameLogChart } from "@/components/event/GameLogChart";
import { OurRead } from "@/components/event/OurRead";
import { PlayerRail } from "@/components/event/PlayerRail";
import { StatChips } from "@/components/event/StatChips";
import { buildOurRead, buildReadSignals, gameLogChart, lineupChip } from "@/lib/event-page";
import { dailyPicksResponseSchema, playerHistoryResponseSchema } from "@/lib/schemas";
import edgesFixture from "@/test/fixtures/event/nba-history-threshold-edges.json";
import nbaHistoryFixture from "@/test/fixtures/event/nba-history-bam.json";
import nbaPicksFixture from "@/test/fixtures/event/nba-daily-picks.json";
import wnbaPicksFixture from "@/test/fixtures/event/wnba-daily-picks.json";
import { renderWithProviders } from "@/test/test-utils";

const noop = vi.fn();
const bamHistory = playerHistoryResponseSchema.parse(nbaHistoryFixture);
const edgeHistory = playerHistoryResponseSchema.parse(edgesFixture);
const wilsonPick = dailyPicksResponseSchema.parse(wnbaPicksFixture).picks[0];

function logOn(dateFull: string) {
  const game = bamHistory.game_logs.find((row) => row.date_full === dateFull);
  if (!game) throw new Error(`missing game ${dateFull}`);
  return game;
}

describe("EventHeader", () => {
  it("renders the matchup and lineup chips from the payload", () => {
    renderWithProviders(
      <EventHeader
        awayName="Boston Celtics"
        homeName="Miami Heat"
        awayAbbr="BOS"
        homeAbbr="MIA"
        when="Tue, Nov 10 · 7:30 PM"
        chips={[lineupChip("BOS", null), lineupChip("MIA", null)]}
        isLoading={false}
        isError={false}
        errorText={null}
        onBack={noop}
        onRetry={noop}
      />,
    );
    expect(screen.getByRole("heading", { name: /boston celtics @ miami heat/i })).toBeInTheDocument();
    expect(screen.getByText("Tue, Nov 10 · 7:30 PM")).toBeInTheDocument();
    expect(screen.getByText("BOS lineup status unavailable")).toBeInTheDocument();
  });

  it("shows a loading state without a matchup", () => {
    renderWithProviders(
      <EventHeader
        awayName="Boston Celtics"
        homeName="Miami Heat"
        awayAbbr="BOS"
        homeAbbr="MIA"
        when={null}
        chips={[]}
        isLoading
        isError={false}
        errorText={null}
        onBack={noop}
        onRetry={noop}
      />,
    );
    expect(screen.getByText("Loading this game.")).toBeInTheDocument();
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });

  it("shows an error and a retry", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <EventHeader
        awayName=""
        homeName=""
        awayAbbr=""
        homeAbbr=""
        when={null}
        chips={[]}
        isLoading={false}
        isError
        errorText="Events request failed"
        onBack={noop}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByText("Events request failed")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalled();
  });
});

describe("StatChips", () => {
  it("offers the prototype stats and the other markets the API supports", () => {
    renderWithProviders(<StatChips value="player_points" onChange={noop} />);
    for (const label of ["PTS", "REB", "AST", "3PM", "PRA", "STL", "FTM", "FGM", "DD"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "PTS" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("PlayerRail", () => {
  const rows = [
    {
      name: "Bam Adebayo",
      team: "MIA",
      position: null,
      lineText: "18.5",
      leanText: "O 72.0%",
      hasLean: true,
      probability: 0.72,
      tier: null,
      injury: null,
    },
    {
      name: "Tyler Herro",
      team: "MIA",
      position: null,
      lineText: "—",
      leanText: "No read",
      hasLean: false,
      probability: null,
      tier: null,
      injury: null,
    },
  ];

  it("renders stored leans and leaves the rest unlabeled", () => {
    renderWithProviders(
      <PlayerRail
        rows={rows}
        selected="Bam Adebayo"
        onSelect={noop}
        isLoading={false}
        isError={false}
        errorText={null}
        onRetry={noop}
      />,
    );
    expect(screen.getByText("O 72.0%")).toBeInTheDocument();
    expect(screen.getByText("No read")).toBeInTheDocument();
    expect(screen.queryByText("History")).not.toBeInTheDocument();
    expect(screen.queryByText("Jalen Brunson")).not.toBeInTheDocument();
  });

  it("does not label an NBA lean History, because that number is the blend", () => {
    renderWithProviders(
      <PlayerRail
        league="nba"
        rows={rows}
        selected="Bam Adebayo"
        onSelect={noop}
        isLoading={false}
        isError={false}
        errorText={null}
        onRetry={noop}
      />,
    );
    const bam = screen.getByRole("button", { name: /O 72\.0%/ });
    expect(bam).toHaveTextContent("O 72.0%");
    expect(bam).not.toHaveTextContent("History");
    const herro = screen.getByRole("button", { name: /Tyler Herro/ });
    expect(herro).toHaveTextContent("No read");
    expect(herro).not.toHaveTextContent("History");
  });

  it("shows loading, empty, and error states", () => {
    const { rerender } = renderWithProviders(
      <PlayerRail rows={[]} selected="" onSelect={noop} isLoading isError={false} errorText={null} onRetry={noop} />,
    );
    expect(screen.getByText("Loading players.")).toBeInTheDocument();
    rerender(
      <PlayerRail rows={[]} selected="" onSelect={noop} isLoading={false} isError={false} errorText={null} onRetry={noop} />,
    );
    expect(screen.getByText("No players are posted for this stat.")).toBeInTheDocument();
    rerender(
      <PlayerRail
        rows={[]}
        selected=""
        onSelect={noop}
        isLoading={false}
        isError
        errorText="Suggest failed"
        onRetry={noop}
      />,
    );
    expect(screen.getByText("Suggest failed")).toBeInTheDocument();
  });
});

describe("OurRead", () => {
  const model = buildOurRead({
    player: "A'ja Wilson",
    marketName: "Points",
    market: "player_points",
    binary: false,
    eventId: "wnba-1",
    homeTeam: "Las Vegas Aces",
    awayTeam: "New York Liberty",
    commenceTime: "2026-11-11T00:00:00Z",
    team: "LVA",
    position: null,
    line: wilsonPick.threshold,
    pick: wilsonPick,
    consensus: null,
    last10: [],
    history: null,
    league: "wnba",
  });

  it("renders a WNBA read with the projection gap and no verdict", () => {
    renderWithProviders(
      <OurRead
        model={model}
        isLoading={false}
        isError={false}
        errorText={null}
        primaryInSlip={false}
        otherInSlip={false}
        onAddPrimary={noop}
        onAddOther={noop}
        onAsk={noop}
      />,
    );
    expect(screen.getByText(/A'ja Wilson/)).toBeInTheDocument();
    expect(screen.getByText(/Projection is not available for WNBA/)).toBeInTheDocument();
    expect(screen.queryByText(/supports|neutral|against/i)).not.toBeInTheDocument();
    expect(screen.getByText("Playable")).toBeInTheDocument();
    expect(screen.queryByText("Strong play")).not.toBeInTheDocument();
  });

  it("shows loading and error states", () => {
    const { rerender } = renderWithProviders(
      <OurRead
        model={model}
        isLoading
        isError={false}
        errorText={null}
        primaryInSlip={false}
        otherInSlip={false}
        onAddPrimary={noop}
        onAddOther={noop}
        onAsk={noop}
      />,
    );
    expect(screen.getByText("Loading this read.")).toBeInTheDocument();
    expect(screen.queryByText("A'ja Wilson")).not.toBeInTheDocument();
    rerender(
      <OurRead
        model={model}
        isLoading={false}
        isError
        errorText="Odds request failed"
        primaryInSlip={false}
        otherInSlip={false}
        onAddPrimary={noop}
        onAddOther={noop}
        onAsk={noop}
      />,
    );
    expect(screen.getByText("Odds request failed")).toBeInTheDocument();
  });

  it("asks the agent", async () => {
    const onAsk = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <OurRead
        model={model}
        isLoading={false}
        isError={false}
        errorText={null}
        primaryInSlip={false}
        otherInSlip={false}
        onAddPrimary={noop}
        onAddOther={noop}
        onAsk={onAsk}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Ask the agent" }));
    expect(onAsk).toHaveBeenCalled();
    expect(buildReadSignals({
      binary: false,
      line: null,
      consensus: null,
      last10: [],
      history: null,
      pick: null,
      market: "player_points",
    }).every((signal) => signal.value === null)).toBe(true);
  });

  it("hides an NBA projection signal when its value is null", () => {
    const bam = dailyPicksResponseSchema.parse(nbaPicksFixture).picks[0];
    const pick = {
      ...bam,
      has_projection: false,
      projected_value: null,
      projected_minutes: null,
      edge: null,
      injury_status: null,
      lineup_confirmed: null,
      signals: bam.signals?.map((signal) =>
        signal.key === "projection" ? { ...signal, value: null, verdict: null } : signal,
      ),
    };
    const hidden = buildOurRead({
      player: "Bam Adebayo",
      marketName: "Points",
      market: "player_points",
      binary: false,
      eventId: "evt-mia-bos",
      homeTeam: "Miami Heat",
      awayTeam: "Boston Celtics",
      commenceTime: "2026-11-11T00:30:00Z",
      team: "MIA",
      position: "C",
      line: 18.5,
      pick,
      consensus: null,
      last10: [],
      history: null,
      league: "nba",
    });
    renderWithProviders(
      <OurRead
        model={hidden}
        isLoading={false}
        isError={false}
        errorText={null}
        primaryInSlip={false}
        otherInSlip={false}
        onAddPrimary={noop}
        onAddOther={noop}
        onAsk={noop}
        league="nba"
      />,
    );
    expect(screen.getByText("Market price")).toBeInTheDocument();
    expect(screen.queryByTestId("signal-projection")).not.toBeInTheDocument();
    expect(screen.queryByText("Projection")).not.toBeInTheDocument();
    expect(screen.queryByText("Projected value is not on this response.")).not.toBeInTheDocument();
    expect(screen.getByTestId("our-read").textContent ?? "").not.toMatch(/Proj |Edge |NaN/);
  });
});

describe("GameLogChart", () => {
  it("renders bars for fixture games", () => {
    const model = gameLogChart([logOn("2026-11-10"), logOn("2026-11-09")], 18.5);
    renderWithProviders(
      <GameLogChart
        model={model}
        note="Points · 2 games"
        selectedKey={null}
        onSelect={noop}
        isLoading={false}
        isError={false}
        errorText={null}
        emptyMessage={null}
      />,
    );
    expect(screen.getByText("Points · 2 games")).toBeInTheDocument();
    expect(screen.getAllByText("24").length).toBeGreaterThan(0);
    expect(screen.getAllByText("16").length).toBeGreaterThan(0);
    expect(screen.getAllByText("18.5").length).toBeGreaterThan(0);
  });

  it("shows loading, error, and empty copy", () => {
    const { rerender } = renderWithProviders(
      <GameLogChart
        model={null}
        note="Points"
        selectedKey={null}
        onSelect={noop}
        isLoading
        isError={false}
        errorText={null}
        emptyMessage={null}
      />,
    );
    expect(screen.getByText("Loading the game log.")).toBeInTheDocument();
    rerender(
      <GameLogChart
        model={null}
        note="Points"
        selectedKey={null}
        onSelect={noop}
        isLoading={false}
        isError
        errorText="History failed"
        emptyMessage={null}
      />,
    );
    expect(screen.getByText("History failed")).toBeInTheDocument();
    rerender(
      <GameLogChart
        model={gameLogChart([], null)}
        note="Points"
        selectedKey={null}
        onSelect={noop}
        isLoading={false}
        isError={false}
        errorText={null}
        emptyMessage="No games match these filters."
      />,
    );
    expect(screen.getByText("No games match these filters.")).toBeInTheDocument();
  });

  it("labels a value on the line as a push", () => {
    const model = gameLogChart(edgeHistory.game_logs, 18.5);
    const push = model.bars.find((bar) => bar.value === 18.5);
    renderWithProviders(
      <GameLogChart
        model={model}
        note="Points · 3 games"
        selectedKey={push?.key ?? null}
        onSelect={noop}
        isLoading={false}
        isError={false}
        errorText={null}
        emptyMessage={null}
      />,
    );
    expect(screen.getByText("Push")).toBeInTheDocument();
    expect(screen.getAllByText(/Minutes not on this row/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "11/03 BOS 18.5" })).toBeInTheDocument();
  });
});

describe("GameFilters", () => {
  it("disables venue because home and away are not on the game log", () => {
    renderWithProviders(
      <GameFilters
        range={10}
        onRange={noop}
        lineText="18.5"
        lineChanged={false}
        lineDisabled={false}
        onMinus={noop}
        onPlus={noop}
        onResetLine={noop}
        role="all"
        onRole={noop}
        opponent=""
        opponents={["BOS"]}
        onOpponent={noop}
        teammates={["Tyler Herro"]}
        selectedMates={[]}
        onToggleMate={noop}
        mateMode="all"
        onMateMode={noop}
        gameCount={10}
      />,
    );
    expect(screen.getByRole("button", { name: "Home" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Away" })).toBeDisabled();
    expect(screen.getByText("Home and away are not on the game log.")).toBeInTheDocument();
    expect(screen.getByText("10 games")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "BOS" })).toBeInTheDocument();
  });
});
