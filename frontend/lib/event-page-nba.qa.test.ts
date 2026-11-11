import { describe, expect, it } from "vitest";

import { MARKETS } from "@/components/MarketSelect";
import {
  buildOurRead,
  eventClock,
  eventLineupChips,
  eventPlayerRows,
  eventWhen,
  joinMeta,
  percentBesideTier,
  readMarketName,
} from "@/lib/event-page";
import {
  dailyPicksResponseSchema,
  dailyPickSchema,
  playerHistoryResponseSchema,
  teamLineupSchema,
  type DailyPick,
  type PlayerHistoryResponse,
} from "@/lib/schemas";
import { tierFromBackend } from "@/lib/nba-card";
import nbaPicksFixture from "@/test/fixtures/event/nba-daily-picks.json";
import nbaEventsFixture from "@/test/fixtures/event/nba-events.json";
import nbaHistoryFixture from "@/test/fixtures/event/nba-history-bam.json";
import confirmedLineupFixture from "@/test/fixtures/event/nba-lineup-confirmed.json";

const bamPick = dailyPicksResponseSchema.parse(nbaPicksFixture).picks[0];
const bamHistory = playerHistoryResponseSchema.parse(nbaHistoryFixture);
const confirmedLineup = teamLineupSchema.parse(confirmedLineupFixture);
const nbaEvent = nbaEventsFixture.events[0];

function pick(overrides: Partial<DailyPick> = {}): DailyPick {
  return { ...bamPick, ...overrides };
}

function nbaRead(p: DailyPick | null, history: PlayerHistoryResponse | null = null, line = 18.5) {
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
    line,
    pick: p,
    consensus: null,
    last10: [],
    history,
    projection: null,
    league: "nba",
  });
}

describe("QA: Bet Slip other side on the NBA read", () => {
  // The other side stores 1 − combined_probability when the blend is finite.
  // That is the same complement the model bar draws. A missing blend keeps
  // the historical opposite field, then the history rate. No tier is derived.
  it("stores 1 - combined, not the history rate, when the blend is finite", () => {
    const model = nbaRead(pick({ probability: 0.59, tier: "Lean", combined_probability: 0.673 }), bamHistory);
    expect(model.other?.direction).toBe("under");
    expect(model.other?.probability).toBeCloseTo(1 - 0.673, 12);
    expect(model.other?.combined_probability).toBeCloseTo(1 - 0.673, 12);
    expect(model.other?.probability).not.toBe(bamHistory.p_under);
    expect(model.other?.tier).toBeNull();
    expect(model.primary?.probability).toBe(0.59);
    expect(model.primary?.tier).toBe("Lean");
    expect(model.other?.threshold).toBe(18.5);
  });

  it("prefers 1 - combined over the pick field and over history", () => {
    const model = nbaRead(
      pick({ probability: 0.59, tier: "Lean", p_under: 0.41, combined_probability: 0.673 }),
      bamHistory,
    );
    expect(model.other?.probability).toBeCloseTo(1 - 0.673, 12);
    expect(model.other?.probability).not.toBe(0.41);
    expect(model.other?.probability).not.toBe(bamHistory.p_under);
    expect(model.other?.tier).toBeNull();
  });

  it("flips an under pick onto 1 - combined, not p_over or history", () => {
    const fromHistory = nbaRead(pick({ direction: "under", combined_probability: 0.61 }), bamHistory);
    expect(fromHistory.primary?.direction).toBe("under");
    expect(fromHistory.other?.direction).toBe("over");
    expect(fromHistory.other?.probability).toBeCloseTo(0.39, 12);
    expect(fromHistory.other?.probability).not.toBe(bamHistory.p_over);

    const fromPick = nbaRead(
      pick({ direction: "under", probability: 0.62, p_over: 0.38, combined_probability: 0.61 }),
      bamHistory,
    );
    expect(fromPick.other?.probability).toBeCloseTo(0.39, 12);
    expect(fromPick.other?.probability).not.toBe(0.38);
    expect(fromPick.other?.tier).toBeNull();
  });

  it("builds the other side from combined alone and clamps the complement into [0, 1]", () => {
    expect(nbaRead(pick({ combined_probability: 0.673 })).other?.probability).toBeCloseTo(1 - 0.673, 12);
    expect(nbaRead(pick({ combined_probability: 1.4, p_under: 0.2 })).other?.probability).toBe(0);
    expect(nbaRead(pick({ combined_probability: -0.2, p_under: 0.2 })).other?.probability).toBe(1);
  });

  it("clamps the historical field only when combined is null", () => {
    expect(nbaRead(pick({ combined_probability: null, p_under: 1.4 })).other?.probability).toBe(1);
    expect(nbaRead(pick({ combined_probability: null, p_under: -0.2 })).other?.probability).toBe(0);
    expect(nbaRead(pick({ combined_probability: null, p_under: 1.4 })).other?.combined_probability).toBeNull();
  });

  it("falls back to the strict history rate, never 1 - probability, when combined is null", () => {
    const model = nbaRead(pick({ probability: 0.72, combined_probability: null }), bamHistory);
    expect(model.other?.probability).toBe(bamHistory.p_under);
    expect(model.other?.n_games).toBe(bamHistory.n_games);
    expect(model.other?.combined_probability).toBeNull();
    expect(model.other?.probability).not.toBeCloseTo(1 - 0.72, 4);
  });

  it("has no other side when history is at a different line and combined is null", () => {
    const model = nbaRead(pick({ threshold: 19.5, combined_probability: null }), bamHistory, 19.5);
    expect(model.other).toBeNull();
  });
});

describe("QA: NBA model bar", () => {
  it("floors only the lean side when a tier is shown (over)", () => {
    const bar = nbaRead(pick({ tier: "Playable", combined_probability: 0.697 })).bar;
    expect(bar?.sourceLabel).toBe("Model");
    expect(bar?.overText).toBe("69%");
    expect(bar?.underText).toBe("30%");
    expect(bar?.overWidth).toBeCloseTo(69.7, 6);
  });

  it("floors the under side for an under pick and keeps the bar width as the over share", () => {
    const bar = nbaRead(pick({ direction: "under", tier: "Playable", combined_probability: 0.697 })).bar;
    expect(bar?.underText).toBe("69%");
    expect(bar?.overText).toBe("30%");
    expect(bar?.overWidth).toBeCloseTo(30.3, 6);
  });

  it("floors the lean side when there is no tier, like nbaTierFace", () => {
    const bar = nbaRead(pick({ tier: null, combined_probability: 0.6951 })).bar;
    expect(bar?.overText).toBe("69%");
    expect(bar?.underText).toBe("30%");
  });

  it("draws no bar when combined is null", () => {
    expect(nbaRead(pick({ combined_probability: null })).bar).toBeNull();
  });
});

describe("QA: stored signal meters", () => {
  it("parses percent and k/10 values and leaves ranks and unjudged rows without a meter", () => {
    const model = nbaRead(
      pick({
        signals: [
          { key: "market", label: "Market price", value: "54.0%", verdict: "neutral" },
          { key: "last10", label: "Last 10 games", value: "7/10", verdict: "supports" },
          { key: "history", label: "All-game hit rate", value: "72.0%", verdict: null },
          { key: "defense", label: "Opponent defense", value: "#9", verdict: "neutral" },
        ],
      }),
    );
    const byKey = Object.fromEntries(model.signals.map((s) => [s.key, s]));
    expect(byKey.market.meter).toBeCloseTo(0.54, 10);
    expect(byKey.last10.meter).toBeCloseTo(0.7, 10);
    expect(byKey.history.meter).toBeNull();
    expect(byKey.history.verdict).toBeNull();
    expect(byKey.defense.meter).toBeNull();
    expect(model.caption).toContain("1 of 4 signals support the over.");
  });

  it("does not name an opponent when the pick's team is blank", () => {
    const model = nbaRead(
      pick({
        player_team: "",
        player_team_code: "",
        signals: [{ key: "defense", label: "Opponent defense", value: "#9", verdict: "neutral" }],
      }),
    );
    const detail = model.signals[0].detail;
    expect(detail).toMatch(/^Rank #9/);
    expect(detail).not.toMatch(/MIA|BOS/);
  });
});

describe("QA: blank team never falls back to the home team", () => {
  it("leaves team null for a pick with no team that is on neither lineup", () => {
    const rows = eventPlayerRows({
      suggested: [],
      picks: [pick({ player_name: "Nobody Listed", player_team: "", player_team_code: "", position: null })],
      metric: "player_points",
      eventId: "evt-mia-bos",
      selectedName: "Nobody Listed",
      postedLine: 18.5,
      awayLineup: null,
      homeLineup: confirmedLineup,
      awayAbbr: "BOS",
      homeAbbr: "MIA",
      league: "nba",
    });
    expect(rows[0].team).toBeNull();
    expect(joinMeta(rows[0].position, rows[0].team, " · ")).toBeNull();
  });

  it("keeps the WNBA rail without a backend tier and with half-away rounding", () => {
    const rows = eventPlayerRows({
      suggested: [],
      picks: [pick({ probability: 0.697, tier: "Playable" })],
      metric: "player_points",
      eventId: "evt-mia-bos",
      selectedName: "",
      postedLine: null,
      awayLineup: null,
      homeLineup: null,
      awayAbbr: "BOS",
      homeAbbr: "MIA",
      league: "wnba",
    });
    expect(rows[0].tier).toBeNull();
    expect(rows[0].leanText).toBe("O 70%");
  });

  it("floors the NBA rail percent beside the backend tier", () => {
    const rows = eventPlayerRows({
      suggested: [],
      picks: [pick({ probability: 0.697, tier: "Playable" })],
      metric: "player_points",
      eventId: "evt-mia-bos",
      selectedName: "",
      postedLine: null,
      awayLineup: null,
      homeLineup: null,
      awayAbbr: "BOS",
      homeAbbr: "MIA",
      league: "nba",
    });
    expect(rows[0].tier?.label).toBe("Playable");
    expect(rows[0].leanText).toBe("O 69% Playable");
  });

  it("trims whitespace-only position and team", () => {
    expect(joinMeta("  ", "  ", " · ")).toBeNull();
    expect(joinMeta(" C ", "", ", ")).toBe("C");
    expect(joinMeta(null, " MIA ", ", ")).toBe("MIA");
  });
});

describe("QA: percentBesideTier", () => {
  const playable = tierFromBackend("Playable");
  it("floors with a tier and rounds half-away without one", () => {
    expect(percentBesideTier(0.6999, playable)).toBe("69%");
    expect(percentBesideTier(0.65, playable)).toBe("65%");
    expect(percentBesideTier(0.6951, null)).toBe("70%");
    expect(percentBesideTier(undefined, playable)).toBe("—");
    expect(percentBesideTier(Number.NaN, null)).toBe("—");
  });
});

describe("QA: DailyPick schema tolerates new and broken fields", () => {
  it("keeps the pick when tier, signals, or combined are malformed", () => {
    const parsed = dailyPickSchema.parse({
      ...nbaPicksFixture.picks[0],
      tier: "Pass",
      signals: "broken",
      combined_probability: "0.7",
    });
    expect(parsed.tier).toBe("Pass");
    expect(tierFromBackend(parsed.tier)).toBeNull();
    expect(parsed.signals).toBeNull();
    expect(parsed.combined_probability).toBeNull();
  });

  it("drops an unknown verdict to null instead of failing the signal", () => {
    const parsed = dailyPickSchema.parse({
      ...nbaPicksFixture.picks[0],
      signals: [{ key: "market", label: "Market price", value: "54.0%", verdict: "maybe" }],
    });
    expect(parsed.signals?.[0].verdict).toBeNull();
  });

  it("parses an older payload with none of the new fields", () => {
    const { tier: _t, signals: _s, position: _p, ...older } = nbaPicksFixture.picks[0];
    const parsed = dailyPickSchema.parse(older);
    expect(parsed.tier ?? null).toBeNull();
    expect(parsed.signals ?? null).toBeNull();
    expect(parsed.combined_probability ?? null).toBeNull();
  });
});

describe("QA: NBA clock and lineup chips stay league-scoped", () => {
  it("does not append ET for another zone label, and WNBA ignores the ET face", () => {
    const pt = eventClock({ ...nbaEvent, display_tz: "PT" }, "nba");
    expect(pt.web).toBe(eventWhen(nbaEvent.commence_time));
    expect(pt.web).not.toMatch(/ET$/);
    expect(eventClock(nbaEvent, "wnba").web).toBe(eventWhen(nbaEvent.commence_time));
    expect(eventClock(nbaEvent, "nba").web).toBe("Tue, Nov 10 · 7:30 PM ET");
    expect(eventClock(null, "nba")).toEqual({ web: null, mobile: null });
  });

  it("falls back for an impossible ET date", () => {
    const bad = eventClock({ ...nbaEvent, commence_time_et: "2026-02-30T19:30:00-05:00" }, "nba");
    expect(bad.web).toBe(eventWhen(nbaEvent.commence_time));
  });

  it("WNBA chips come from the lineup snapshot even when a status is passed", () => {
    const chips = eventLineupChips({
      league: "wnba",
      awayAbbr: "NYL",
      homeAbbr: "LVA",
      status: { away: "confirmed", home: "confirmed" },
      awayLineup: null,
      homeLineup: null,
    });
    expect(chips.map((chip) => chip.tone)).not.toContain("confirmed");
  });

  it("NBA chips say unavailable when lineup_status is missing", () => {
    const chips = eventLineupChips({
      league: "nba",
      awayAbbr: "",
      homeAbbr: "MIA",
      status: null,
      awayLineup: confirmedLineup,
      homeLineup: confirmedLineup,
    });
    expect(chips.map((chip) => chip.tone)).toEqual(["missing", "missing"]);
    expect(chips[0].label).toBe("Team lineup status unavailable");
  });
});

describe("QA: all twelve market chips have a read headline", () => {
  it("names every market key without falling back to the display label", () => {
    expect(MARKETS).toHaveLength(12);
    for (const market of MARKETS) {
      expect(readMarketName(market.key, "FALLBACK")).not.toBe("fallback");
    }
    expect(readMarketName("player_blocks", " Blocks ")).toBe("blocks");
  });
});
