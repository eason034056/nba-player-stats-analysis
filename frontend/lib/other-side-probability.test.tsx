import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EventActionBar } from "@/components/event/EventActionBar";
import { OurRead } from "@/components/event/OurRead";
import { slipCardFace } from "@/lib/bet-slip-board";
import {
  buildOurRead,
  mobileOtherCopy,
  nbaOtherSideProbability,
  webOtherCopy,
} from "@/lib/event-page";
import { formatTierPercent } from "@/lib/player-dd";
import {
  dailyPicksResponseSchema,
  playerHistoryResponseSchema,
  type DailyPick,
  type PlayerHistoryResponse,
} from "@/lib/schemas";
import { createBetSlipPick, renderWithProviders } from "@/test/test-utils";
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

  it("prints the complement with the same floor on the button, the bar, and the slip card", () => {
    const cases = [
      { combined: 0.675, text: "32%" },
      { combined: 0.673, text: "32%" },
      { combined: 0.7, text: "30%" },
    ];
    for (const { combined, text } of cases) {
      const model = nbaRead(pick({ combined_probability: combined, p_under: 0.2, tier: "Strong play" }));
      expect(model.other?.tier).toBeNull();
      expect(model.tier?.label).toBe("Strong play");
      expect(formatTierPercent(model.other?.probability)).toBe(text);
      expect(webOtherCopy(model.other!, false, "nba")).toBe(`Under instead (${text})`);
      expect(webOtherCopy(model.other!, true, "nba")).toBe("✓ Under in slip");
      expect(mobileOtherCopy(model.other!)).toBe(`Under ${text}`);
      expect(model.bar?.underText).toBe(text);
      expect(
        slipCardFace(
          createBetSlipPick({
            direction: "under",
            probability: model.other!.probability,
            combined_probability: model.other!.combined_probability,
            tier: null,
          }),
        ).probabilityText,
      ).toBe(text);
    }
  });

  it("matches the exact-decimal floor for every combined value 0.000-1.000", () => {
    for (let k = 0; k <= 1000; k += 1) {
      const model = nbaRead(pick({ combined_probability: k / 1000, p_under: 0.2, tier: "Playable" }));
      const text = `${Math.floor((1000 - k) / 10)}%`;
      expect(model.bar?.underText).toBe(text);
      expect(webOtherCopy(model.other!, false, "nba")).toBe(`Under instead (${text})`);
      expect(mobileOtherCopy(model.other!)).toBe(`Under ${text}`);
      expect(
        slipCardFace(
          createBetSlipPick({
            direction: "under",
            probability: model.other!.probability,
            combined_probability: model.other!.combined_probability,
            tier: null,
          }),
        ).probabilityText,
      ).toBe(text);
    }
  });

  it("the web buttons carry no History heading when the other side is 1 - combined", () => {
    const model = nbaRead(pick({ combined_probability: 0.673, p_under: 0.41, tier: "Lean" }));
    renderWithProviders(
      <OurRead
        league="nba"
        model={model}
        isLoading={false}
        isError={false}
        errorText={null}
        primaryInSlip={false}
        otherInSlip={false}
        onAddPrimary={() => {}}
        onAddOther={() => {}}
        onAsk={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Under instead (32%)" })).toBeInTheDocument();
    expect(screen.queryByText("History")).not.toBeInTheDocument();
  });

  it("keeps the history rate and the History label when combined is null", () => {
    const model = nbaRead(pick({ probability: 0.72, combined_probability: null, p_under: null }), bamHistory);
    const text = formatTierPercent(bamHistory.p_under);
    expect(model.other?.probability).toBe(bamHistory.p_under);
    expect(model.other?.combined_probability).toBeNull();
    expect(model.other?.probability).not.toBeCloseTo(1 - 0.72, 4);
    expect(webOtherCopy(model.other!, false, "nba")).toBe(`Under instead (${text})`);

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
          onAddPrimary={() => {}}
          onAddOther={() => {}}
          onAsk={() => {}}
        />
        <EventActionBar
          league="nba"
          model={model}
          primaryInSlip={false}
          otherInSlip={false}
          onAddPrimary={() => {}}
          onAddOther={() => {}}
          onAsk={() => {}}
        />
      </>,
    );
    expect(screen.getAllByText("History").length).toBeGreaterThan(0);
    const history = screen.getByRole("button", { name: /History/ });
    expect(history).toHaveTextContent(`Under ${text}`);
    expect(history).not.toHaveTextContent("28%");
  });
});
