import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EventActionBar } from "@/components/event/EventActionBar";
import { OurRead } from "@/components/event/OurRead";
import { PlayerRail } from "@/components/event/PlayerRail";
import { buildOurRead, eventPlayerRows } from "@/lib/event-page";
import { dailyPicksResponseSchema, type DailyPick } from "@/lib/schemas";
import nbaPicksFixture from "@/test/fixtures/event/nba-daily-picks.json";
import { renderWithProviders } from "@/test/test-utils";

const bam = dailyPicksResponseSchema.parse(nbaPicksFixture).picks[0];
const noop = vi.fn();

const CUTOFFS: Array<{ probability: number; tier: string; text: string }> = [
  { probability: 0.7, tier: "Strong play", text: "70%" },
  { probability: 0.699, tier: "Playable", text: "69%" },
  { probability: 0.697, tier: "Playable", text: "69%" },
  { probability: 0.65, tier: "Playable", text: "65%" },
  { probability: 0.649, tier: "Lean", text: "64%" },
  { probability: 0.56, tier: "Lean", text: "56%" },
  { probability: 0.559, tier: "Lean", text: "55%" },
];

function pickAt(probability: number, tier: string): DailyPick {
  return {
    ...bam,
    probability,
    tier,
    combined_probability: probability,
    signals: null,
  };
}

function modelAt(probability: number, tier: string) {
  return buildOurRead({
    player: "Bam Adebayo",
    marketName: "Points",
    market: "player_points",
    binary: false,
    supportsProjection: true,
    eventId: "evt-mia-bos",
    homeTeam: "Miami Heat",
    awayTeam: "Boston Celtics",
    commenceTime: "2026-11-11T00:30:00Z",
    team: "MIA",
    position: "C",
    line: 18.5,
    pick: pickAt(probability, tier),
    consensus: null,
    last10: [],
    history: null,
    projection: null,
    league: "nba",
  });
}

describe("tier percent on the game page", () => {
  it.each(CUTOFFS)(
    "floors $probability beside $tier to $text on the rail, the read, and the action bar",
    ({ probability, tier, text }) => {
      const rows = eventPlayerRows({
        suggested: [],
        picks: [pickAt(probability, tier)],
        metric: "player_points",
        eventId: "evt-mia-bos",
        selectedName: "Bam Adebayo",
        postedLine: 18.5,
        awayLineup: null,
        homeLineup: null,
        awayAbbr: "BOS",
        homeAbbr: "MIA",
        league: "nba",
      });
      const model = modelAt(probability, tier);
      renderWithProviders(
        <>
          <PlayerRail
            league="nba"
            rows={rows}
            selected="Bam Adebayo"
            onSelect={noop}
            isLoading={false}
            isError={false}
            errorText={null}
            onRetry={noop}
          />
          <OurRead
            league="nba"
            model={model}
            isLoading={false}
            isError={false}
            errorText={null}
            primaryInSlip={false}
            otherInSlip={false}
            onAddPrimary={noop}
            onAddOther={noop}
            onAsk={noop}
          />
          <EventActionBar
            league="nba"
            model={model}
            primaryInSlip={false}
            otherInSlip={false}
            onAddPrimary={noop}
            onAddOther={noop}
            onAsk={noop}
          />
        </>,
      );

      expect(screen.getByText(`O ${text} ${tier}`)).toBeInTheDocument();
      expect(screen.getByText(tier)).toBeInTheDocument();
      expect(screen.getByTestId("read-bar")).toHaveTextContent(`Over ${text}`);
      expect(screen.getByTestId("event-action-bar")).toHaveTextContent(text);
      expect(screen.getByTestId("event-action-bar")).toHaveTextContent("Add Adebayo O 18.5");
    },
  );

  it("prints an em dash when the tiered probability is null", () => {
    const rows = eventPlayerRows({
      suggested: [],
      picks: [pickAt(Number.NaN, "Lean")],
      metric: "player_points",
      eventId: "evt-mia-bos",
      selectedName: "Bam Adebayo",
      postedLine: 18.5,
      awayLineup: null,
      homeLineup: null,
      awayAbbr: "BOS",
      homeAbbr: "MIA",
      league: "nba",
    });
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
    expect(screen.getByText("O — Lean")).toBeInTheDocument();
    expect(screen.queryByText("O 0%")).not.toBeInTheDocument();
  });

  it("labels history and model when combined_probability is not the pick rate", () => {
    const model = buildOurRead({
      player: "Bam Adebayo",
      marketName: "Points",
      market: "player_points",
      binary: false,
      supportsProjection: true,
      eventId: "evt-mia-bos",
      homeTeam: "Miami Heat",
      awayTeam: "Boston Celtics",
      commenceTime: "2026-11-11T00:30:00Z",
      team: "MIA",
      position: "C",
      line: 18.5,
      pick: {
        ...bam,
        probability: 0.59,
        tier: "Lean",
        p_under: 0.41,
        combined_probability: 0.673,
        signals: null,
      },
      consensus: null,
      last10: [],
      history: null,
      projection: null,
      league: "nba",
    });
    renderWithProviders(
      <>
        <OurRead
          league="nba"
          model={model}
          isLoading={false}
          isError={false}
          errorText={null}
          primaryInSlip={false}
          otherInSlip={false}
          onAddPrimary={noop}
          onAddOther={noop}
          onAsk={noop}
        />
        <EventActionBar
          league="nba"
          model={model}
          primaryInSlip={false}
          otherInSlip={false}
          onAddPrimary={noop}
          onAddOther={noop}
          onAsk={noop}
        />
      </>,
    );

    expect(screen.getByTestId("read-bar")).toHaveTextContent("Model");
    expect(screen.getByTestId("read-bar")).toHaveTextContent("Over 67%");
    expect(screen.getByTestId("read-bar")).toHaveTextContent("Under 32%");
    expect(screen.queryByText("History")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Under instead (32%)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Under instead (41%)" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add Adebayo O 18\.5/ })).toHaveTextContent("67%");
    expect(screen.getByRole("button", { name: /Add Adebayo O 18\.5/ })).not.toHaveTextContent("History");
    expect(screen.getByRole("button", { name: "Under 32%" })).toBeInTheDocument();
    expect(screen.getByTestId("event-action-bar")).not.toHaveTextContent("History");
    expect(screen.getByTestId("event-action-bar")).not.toHaveTextContent("59%");
    expect(screen.getByTestId("event-action-bar")).not.toHaveTextContent("Under 41%");
  });
});
