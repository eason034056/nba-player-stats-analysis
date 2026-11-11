import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EventActionBar } from "@/components/event/EventActionBar";
import {
  buildOurRead,
  mobileOtherCopy,
  nbaOtherSideProbability,
  webOtherCopy,
} from "@/lib/event-page";
import { formatPercent, formatTierPercent } from "@/lib/player-dd";
import {
  dailyPicksResponseSchema,
  playerHistoryResponseSchema,
  type DailyPick,
  type PlayerHistoryResponse,
} from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";
import nbaPicksFixture from "@/test/fixtures/event/nba-daily-picks.json";
import nbaHistoryFixture from "@/test/fixtures/event/nba-history-bam.json";

const bamPick = dailyPicksResponseSchema.parse(nbaPicksFixture).picks[0];
const bamHistory = playerHistoryResponseSchema.parse(nbaHistoryFixture);

function pick(overrides: Partial<DailyPick> = {}): DailyPick {
  return { ...bamPick, ...overrides };
}

function nbaRead(p: DailyPick | null, history: PlayerHistoryResponse | null = null) {
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
    pick: p,
    consensus: null,
    last10: [],
    history,
    projection: null,
    league: "nba",
  });
}

describe("nbaOtherSideProbability", () => {
  it("stores 1 - combined_probability and ignores the historical field", () => {
    expect(nbaOtherSideProbability(0.673, 0.41)).toEqual({
      probability: 1 - 0.673,
      source: "model",
    });
    expect(nbaOtherSideProbability(0, 0.41)).toEqual({ probability: 1, source: "model" });
    expect(nbaOtherSideProbability(1, 0.41)).toEqual({ probability: 0, source: "model" });
  });

  it("clamps a complement outside [0, 1]", () => {
    expect(nbaOtherSideProbability(1.4, 0.2)).toEqual({ probability: 0, source: "model" });
    expect(nbaOtherSideProbability(-0.2, 0.2)).toEqual({ probability: 1, source: "model" });
  });

  it("falls back to the historical field when combined is null or not finite", () => {
    expect(nbaOtherSideProbability(null, 0.41)).toEqual({ probability: 0.41, source: "history" });
    expect(nbaOtherSideProbability(undefined, 0.41)).toEqual({ probability: 0.41, source: "history" });
    expect(nbaOtherSideProbability(Number.NaN, 0.41)).toEqual({ probability: 0.41, source: "history" });
    expect(nbaOtherSideProbability(Number.POSITIVE_INFINITY, -0.2)).toEqual({
      probability: 0,
      source: "history",
    });
    expect(nbaOtherSideProbability(null, null)).toBeNull();
    expect(nbaOtherSideProbability(undefined, Number.NaN)).toBeNull();
  });

  it("prints the complement as a whole percent, half away from zero", () => {
    const decided = nbaOtherSideProbability(0.675, 0.2);
    expect(formatPercent(decided?.probability)).toBe("33%");
    expect(formatTierPercent(decided?.probability)).toBe("32%");

    const model = nbaRead(pick({ combined_probability: 0.675, p_under: 0.2, tier: "Strong play" }));
    expect(model.other).not.toBeNull();
    expect(model.other?.tier).toBeNull();
    expect(model.tier?.label).toBe("Strong play");
    expect(webOtherCopy(model.other!, false, "nba")).toBe("Under instead (33%)");
    expect(webOtherCopy(model.other!, true, "nba")).toBe("✓ Under in slip");
    expect(mobileOtherCopy(model.other!)).toBe("Under 33%");
    expect(model.bar?.underText).toBe("33%");
  });

  it("keeps the history rate and the History label when combined is null", () => {
    const model = nbaRead(pick({ probability: 0.72, combined_probability: null, p_under: null }), bamHistory);
    expect(model.other?.probability).toBe(bamHistory.p_under);
    expect(model.other?.combined_probability).toBeNull();
    expect(model.other?.probability).not.toBeCloseTo(1 - 0.72, 4);
    expect(webOtherCopy(model.other!, false, "nba")).toBe(
      `Under instead (${formatPercent(bamHistory.p_under)})`,
    );

    renderWithProviders(
      <EventActionBar
        league="nba"
        model={model}
        primaryInSlip={false}
        otherInSlip={false}
        onAddPrimary={() => {}}
        onAddOther={() => {}}
        onAsk={() => {}}
      />,
    );
    const history = screen.getByRole("button", { name: /History/ });
    expect(history).toHaveTextContent(`Under ${formatPercent(bamHistory.p_under)}`);
    expect(history).not.toHaveTextContent("28%");
  });
});
