import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OurRead } from "@/components/event/OurRead";
import { EventActionBar } from "@/components/event/EventActionBar";
import { slipCardFace } from "@/lib/bet-slip-board";
import { buildOurRead, mobileOtherCopy, webOtherCopy } from "@/lib/event-page";
import {
  dailyPicksResponseSchema,
  playerHistoryResponseSchema,
  type DailyPick,
  type PlayerHistoryResponse,
} from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";
import nbaPicksFixture from "@/test/fixtures/event/nba-daily-picks.json";
import nbaHistoryFixture from "@/test/fixtures/event/nba-history-bam.json";

// Eason's rule: every NBA percent on a card that carries a tier, and every
// percent on the Bet Slip, rounds down. The other-side button prints the
// number the slip will store, so it must print what the slip pill prints.

const bamPick = dailyPicksResponseSchema.parse(nbaPicksFixture).picks[0];
const bamHistory = playerHistoryResponseSchema.parse(nbaHistoryFixture);
const noop = () => {};

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

/** The slip pill for the leg the other-side button would add. */
function pillFor(other: NonNullable<ReturnType<typeof nbaRead>["other"]>) {
  // addSeed stores the seed as the slip pick unchanged.
  return slipCardFace(other as Parameters<typeof slipCardFace>[0]).probabilityText;
}

/** Exact decimal expectation: floor((1000 - k) / 10) for combined = k / 1000. */
function flooredComplement(thousandths: number): string {
  return `${Math.floor((1000 - thousandths) / 10)}%`;
}

describe("QA: other-side button and slip pill show the same floored number", () => {
  it.each([
    [675, "32%"],
    [673, "32%"],
    [700, "30%"],
    [500, "50%"],
    [420, "58%"],
    [580, "42%"],
    [130, "87%"],
    [70, "93%"],
    [710, "29%"],
  ])("combined %i/1000 prints %s on the web button, mobile button and pill", (k, expected) => {
    const model = nbaRead(pick({ combined_probability: k / 1000, tier: "Strong play" }));
    const other = model.other!;
    expect(other).not.toBeNull();
    expect(pillFor(other)).toBe(expected);
    expect(webOtherCopy(other, false, "nba")).toBe(`Under instead (${expected})`);
    expect(mobileOtherCopy(other)).toBe(`Under ${expected}`);
    // Item 11 asks the button to match the bar, so the bar's under side too.
    expect(model.bar?.underText).toBe(expected);
  });

  it("matches the exact-decimal floor for every combined value 0.000-1.000", () => {
    const pillMiss: string[] = [];
    const buttonMiss: string[] = [];
    for (let k = 0; k <= 1000; k += 1) {
      const other = nbaRead(pick({ combined_probability: k / 1000 })).other!;
      const expected = flooredComplement(k);
      if (pillFor(other) !== expected) pillMiss.push(`${k / 1000}:${pillFor(other)}`);
      if (mobileOtherCopy(other) !== `Under ${expected}`) buttonMiss.push(`${k / 1000}:${mobileOtherCopy(other)}`);
    }
    expect(pillMiss).toEqual([]);
    expect(buttonMiss).toEqual([]);
  });
});

describe("QA: fallback uses the other side's own probability", () => {
  it("an over pick with no blend stores p_under, not 1 - probability or p_over", () => {
    const other = nbaRead(
      pick({ direction: "over", probability: 0.72, combined_probability: null, p_over: 0.7, p_under: 0.31 }),
    ).other!;
    expect(other.direction).toBe("under");
    expect(other.probability).toBe(0.31);
    expect(other.tier).toBeNull();
  });

  it("with no blend and no pick field, uses /history for the other side at the pick's line", () => {
    const over = nbaRead(pick({ direction: "over", combined_probability: null, p_over: null, p_under: null }), bamHistory)
      .other!;
    expect(over.direction).toBe("under");
    expect(over.probability).toBe(bamHistory.p_under);

    const under = nbaRead(pick({ direction: "under", combined_probability: null, p_over: null, p_under: null }), bamHistory)
      .other!;
    expect(under.direction).toBe("over");
    expect(under.probability).toBe(bamHistory.p_over);
  });

  it("an under pick with a blend stores 1 - combined on the over side", () => {
    const other = nbaRead(pick({ direction: "under", combined_probability: 0.61, p_over: 0.2 })).other!;
    expect(other.direction).toBe("over");
    expect(other.probability).toBeCloseTo(0.39, 12);
    expect(other.tier).toBeNull();
  });
});

describe("QA: History label only beside a historical rate", () => {
  function renderRead(model: ReturnType<typeof nbaRead>) {
    return renderWithProviders(
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
      />,
    );
  }

  it("the web buttons carry no History heading when the other side is 1 - combined", () => {
    renderRead(nbaRead(pick({ combined_probability: 0.675, tier: "Strong play" })));
    const other = screen.getByRole("button", { name: /instead/ });
    const group = other.parentElement!;
    expect(within(group).queryByText(/^History$/i)).not.toBeInTheDocument();
  });

  it("the web buttons keep the History heading when the other side is the history rate", () => {
    renderRead(nbaRead(pick({ combined_probability: null, p_under: 0.31 })));
    const other = screen.getByRole("button", { name: /instead/ });
    expect(within(other.parentElement!).getByText(/^History$/i)).toBeInTheDocument();
  });

  it("the mobile button is labeled History only for the history rate", () => {
    const { unmount } = render(
      <EventActionBar
        league="nba"
        model={nbaRead(pick({ combined_probability: 0.675, tier: "Strong play" }))}
        primaryInSlip={false}
        otherInSlip={false}
        onAddPrimary={noop}
        onAddOther={noop}
        onAsk={noop}
      />,
    );
    expect(screen.queryByText(/^History$/i)).not.toBeInTheDocument();
    unmount();
    render(
      <EventActionBar
        league="nba"
        model={nbaRead(pick({ combined_probability: null, p_under: 0.31 }))}
        primaryInSlip={false}
        otherInSlip={false}
        onAddPrimary={noop}
        onAddOther={noop}
        onAsk={noop}
      />,
    );
    expect(screen.getByText(/^History$/i)).toBeInTheDocument();
  });
});
