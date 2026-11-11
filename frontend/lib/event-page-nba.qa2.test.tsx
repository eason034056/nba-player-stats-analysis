import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EventActionBar } from "@/components/event/EventActionBar";
import { PlayerRail } from "@/components/event/PlayerRail";
import { buildOurRead, eventPlayerRows } from "@/lib/event-page";
import { nbaTierFace } from "@/lib/nba-card";
import { dailyPicksResponseSchema, dailyPickSchema, type DailyPick } from "@/lib/schemas";
import nbaPicksFixture from "@/test/fixtures/event/nba-daily-picks.json";
import { renderWithProviders } from "@/test/test-utils";

const bam = dailyPicksResponseSchema.parse(nbaPicksFixture).picks[0];
const noop = vi.fn();

function pick(overrides: Partial<DailyPick> = {}): DailyPick {
  return { ...bam, ...overrides };
}

function read(p: DailyPick) {
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
    history: null,
    projection: null,
    league: "nba",
  });
}

function rail(p: DailyPick) {
  return eventPlayerRows({
    suggested: [],
    picks: [p],
    metric: "player_points",
    eventId: "evt-mia-bos",
    selectedName: "Bam Adebayo",
    postedLine: 18.5,
    awayLineup: null,
    homeLineup: null,
    awayAbbr: "BOS",
    homeAbbr: "MIA",
    league: "nba",
  })[0];
}

describe("QA: one blend, one number on the NBA read card", () => {
  // nbaTierFace floors a blend with no tier, so the rail and the caption floor it.
  // The Model bar prints the same blend on the same card and must agree.
  it.each([
    [0.6755, "67%"],
    [0.6951, "69%"],
    [0.57, "57%"],
    [0.58, "58%"],
  ])("floors a no-tier blend %s to %s on the rail, the caption, and the Model bar", (combined, text) => {
    const p = pick({ tier: null, combined_probability: combined, probability: 0.72 });
    const row = rail(p);
    const model = read(p);
    expect(row.leanText).toBe(`O ${text}`);
    expect(model.caption).toContain(`Combined probability ${text}.`);
    expect(model.bar?.sourceLabel).toBe("Model");
    expect(model.bar?.overText).toBe(text);
  });

  it("keeps a Pass blend under the Lean cutoff on the Model bar", () => {
    const p = dailyPickSchema.parse({ ...nbaPicksFixture.picks[0], tier: "Pass", combined_probability: 0.5551 });
    expect(p.tier).toBe("Pass");
    const model = read(p);
    expect(model.tier).toBeNull();
    expect(rail(p).leanText).toBe("O 55%");
    expect(model.caption).toContain("Combined probability 55%.");
    expect(model.bar?.overText).toBe("55%");
    expect(model.bar?.overText).not.toBe("56%");
  });

  it("floors the under lean side with no tier and keeps the bar width as the over share", () => {
    const model = read(pick({ direction: "under", tier: null, combined_probability: 0.6755 }));
    expect(model.bar?.underText).toBe("67%");
    expect(model.bar?.overWidth).toBeCloseTo(32.45, 6);
  });
});

describe("QA: caption, rail, and action bar keep the two sources apart", () => {
  it("prints the whole caption with the floored blend and the labelled historical rate", () => {
    const model = read(pick({ tier: "Playable", combined_probability: 0.697, probability: 0.72 }));
    expect(model.caption).toBe(
      "Combined probability 69%. Historical hit rate 72% over 40 games. 3 of 5 signals support the over.",
    );
  });

  it("does not derive a tier from the blend or from a Pass string", () => {
    expect(read(pick({ tier: null, combined_probability: 0.99 })).tier).toBeNull();
    expect(rail(pick({ tier: null, combined_probability: 0.99 })).tier).toBeNull();
    expect(read(pick({ tier: "Pass", combined_probability: 0.99 })).tier).toBeNull();
    expect(rail(pick({ tier: "Pass", combined_probability: 0.99 })).leanText).toBe("O 99%");
    expect(nbaTierFace({ tier: "Pass", combined_probability: 0.697 })).toEqual({ probabilityText: "69%", tier: null });
  });

  it("puts the blend on the rail and the primary button, and History only on the other side", () => {
    const p = pick({ probability: 0.59, tier: "Lean", p_under: 0.41, combined_probability: 0.673 });
    const row = rail(p);
    expect(row.leanText).toBe("O 67% Lean");
    expect(row.leanText).not.toContain("59");
    const model = read(p);
    renderWithProviders(
      <>
        <PlayerRail
          league="nba"
          rows={[row]}
          selected="Bam Adebayo"
          onSelect={noop}
          isLoading={false}
          isError={false}
          errorText={null}
          onRetry={noop}
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
    expect(screen.getByTestId("player-row-Bam Adebayo")).not.toHaveTextContent("History");
    const history = screen.getAllByRole("button", { name: /History/ });
    expect(history).toHaveLength(1);
    expect(history[0]).toHaveTextContent("Under 41%");
    expect(history[0]).not.toHaveTextContent("67%");
  });
});
