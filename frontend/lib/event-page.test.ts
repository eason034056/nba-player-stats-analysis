import { describe, expect, it } from "vitest";

import {
  buildOurRead,
  buildReadSignals,
  consensusSplit,
  eventClock,
  eventLineupChips,
  eventPlayerRows,
  eventWhen,
  gameLogChart,
  joinMeta,
  lineupChip,
  postedLine,
} from "@/lib/event-page";
import {
  dailyPicksResponseSchema,
  noVigResponseSchema,
  playerHistoryResponseSchema,
  teamLineupSchema,
  type DailyPick,
} from "@/lib/schemas";
import nbaPicksFixture from "@/test/fixtures/event/nba-daily-picks.json";
import nbaHistoryFixture from "@/test/fixtures/event/nba-history-bam.json";
import confirmedLineupFixture from "@/test/fixtures/event/nba-lineup-confirmed.json";
import mixedLineupFixture from "@/test/fixtures/event/nba-lineup-mixed.json";
import nbaNoVigFixture from "@/test/fixtures/event/nba-no-vig-bam.json";
import syntheticNoVigFixture from "@/test/fixtures/event/nba-no-vig-synthetic.json";

const bamPick = dailyPicksResponseSchema.parse(nbaPicksFixture).picks[0];
const bamHistory = playerHistoryResponseSchema.parse(nbaHistoryFixture);
const confirmedLineup = teamLineupSchema.parse(confirmedLineupFixture);
const mixedLineup = teamLineupSchema.parse(mixedLineupFixture);
const bamNoVig = noVigResponseSchema.parse(nbaNoVigFixture);
const bamConsensus = bamNoVig.consensus ?? null;
const syntheticNoVig = noVigResponseSchema.parse(syntheticNoVigFixture);

function logOn(dateFull: string) {
  const game = bamHistory.game_logs.find((row) => row.date_full === dateFull);
  if (!game) throw new Error(`missing game ${dateFull}`);
  return game;
}

function pick(overrides: Partial<DailyPick> = {}): DailyPick {
  return { ...bamPick, ...overrides };
}

describe("lineup chips", () => {
  it("says confirmed only when every source snapshot says confirmed", () => {
    expect(lineupChip("MIA", confirmedLineup).label).toBe("MIA lineup confirmed");
  });

  it("keeps the consensus word when sources disagree", () => {
    const chip = lineupChip("MIA", mixedLineup);
    expect(chip.tone).toBe("projected");
    expect(chip.label).toBe("MIA lineup projected");
  });

  it("does not invent confirmed when the lineup is missing", () => {
    expect(lineupChip("NYL", null)).toEqual({
      abbr: "NYL",
      tone: "missing",
      label: "NYL lineup status unavailable",
    });
  });
});

describe("read signals", () => {
  const base = {
    binary: false,
    supportsProjection: true,
    line: 18.5,
    consensus: bamConsensus,
    last10: [logOn("2026-11-08"), logOn("2026-11-03")],
    history: bamHistory,
    projection: null,
    pick: pick(),
    market: "player_points",
  };

  it("shows raw rates and the stored rank without a verdict", () => {
    const signals = buildReadSignals(base);
    const text = signals.map((signal) => `${signal.label} ${signal.detail} ${signal.value}`).join(" ");
    expect(signals.find((signal) => signal.key === "market")?.value).toBe("54%");
    expect(signals.find((signal) => signal.key === "last10")?.value).toBe("1/2");
    expect(signals.find((signal) => signal.key === "history")?.value).toBe("62%");
    expect(signals.find((signal) => signal.key === "projection")?.value).toBe("20.4");
    expect(signals.find((signal) => signal.key === "defense")?.value).toBe("#9");
    expect(text).not.toMatch(/supports|neutral|against/i);
  });

  it("leaves market, last-10, history, projection, and defense empty when the fields are missing", () => {
    const signals = buildReadSignals({
      ...base,
      line: null,
      consensus: null,
      last10: [],
      history: null,
      pick: null,
    });
    for (const signal of signals) {
      expect(signal.value).toBeNull();
      expect(signal.meter).toBeNull();
    }
    expect(signals.find((signal) => signal.key === "defense")?.detail).toMatch(/not on this response/);
    expect(signals.find((signal) => signal.key === "market")?.detail).toMatch(/not on this response/);
  });

  it("says WNBA has no projection instead of a stand-in number", () => {
    const projection = buildReadSignals({
      ...base,
      supportsProjection: false,
      pick: pick({ projected_value: null, opponent_rank: null, opponent_position_rank: null }),
    }).find((signal) => signal.key === "projection");
    expect(projection?.value).toBeNull();
    expect(projection?.detail).toBe("Projection is not available for WNBA.");
  });
});

describe("player rows and lines", () => {
  it("prints a lean only for a stored pick", () => {
    const rows = eventPlayerRows({
      suggested: ["Bam Adebayo", "Tyler Herro"],
      picks: [pick()],
      metric: "player_points",
      eventId: "evt-mia-bos",
      selectedName: "Tyler Herro",
      postedLine: 16.5,
      awayLineup: null,
      homeLineup: mixedLineup,
      awayAbbr: "BOS",
      homeAbbr: "MIA",
      league: "nba",
    });
    const bam = rows.find((row) => row.name === "Bam Adebayo");
    const herro = rows.find((row) => row.name === "Tyler Herro");
    expect(bam?.leanText).toBe("O 72%");
    expect(bam?.lineText).toBe("18.5");
    expect(herro?.leanText).toBe("No read");
    expect(herro?.lineText).toBe("16.5");
    expect(rows.map((row) => row.leanText).join(" ")).not.toMatch(/80%|51%/);
  });

  it("ignores a synthetic double-double line", () => {
    expect(postedLine(syntheticNoVig.results)).toBeNull();
    expect(postedLine(bamNoVig.results)).toBe(18.5);
  });
});

describe("game log chart", () => {
  it("draws oldest to newest and marks the posted line", () => {
    const model = gameLogChart(
      [logOn("2026-11-10"), logOn("2026-11-01")],
      18.5,
    );
    expect(model.empty).toBe(false);
    expect(model.bars.map((bar) => bar.dateFull)).toEqual(["2026-11-01", "2026-11-10"]);
    expect(model.bars[0]?.over).toBe(false);
    expect(model.bars[1]?.over).toBe(true);
    expect(model.lineText).toBe("18.5");
    expect(model.linePct).not.toBeNull();
  });

  it("stays empty when the log is empty", () => {
    expect(gameLogChart([], 18.5).empty).toBe(true);
    expect(gameLogChart([], 18.5).bars).toEqual([]);
  });
});

describe("our read", () => {
  it("uses the stored hit rate and does not invent the other side", () => {
    const model = buildOurRead({
      player: "Bam Adebayo",
      marketName: "Points",
      market: "player_points",
      binary: false,
      supportsProjection: true,
      eventId: "evt-mia",
      homeTeam: "Miami Heat",
      awayTeam: "Boston Celtics",
      commenceTime: "2026-11-11T00:30:00Z",
      team: "MIA",
      position: "C",
      line: 18.5,
      pick: pick(),
      consensus: bamConsensus,
      last10: [],
      history: null,
      projection: null,
    });
    expect(model.tier?.label).toBe("Strong play");
    expect(model.headlineLead).toBe("Over 18.5");
    expect(model.caption).toMatch(/Historical hit rate 72%/);
    expect(model.primary?.probability).toBe(0.72);
    expect(model.other).toBeNull();
    expect(model.bar?.sourceLabel).toBe("No-vig consensus");
    expect(consensusSplit(null, false)).toBeNull();
  });

  it("adds the other side from the history rate, not from one minus the pick", () => {
    const model = buildOurRead({
      player: "Bam Adebayo",
      marketName: "Points",
      market: "player_points",
      binary: false,
      supportsProjection: true,
      eventId: "evt-mia",
      homeTeam: "Miami Heat",
      awayTeam: "Boston Celtics",
      commenceTime: "2026-11-11T00:30:00Z",
      team: "MIA",
      position: null,
      line: 18.5,
      pick: pick(),
      consensus: null,
      last10: [],
      history: bamHistory,
      projection: null,
    });
    expect(model.other?.direction).toBe("under");
    expect(model.other?.probability).toBe(0.35);
    expect(model.other?.probability).not.toBeCloseTo(0.28);
    expect(model.bar?.sourceLabel).toBe("Hit rate");
  });

  it("hides the tier when there is no stored pick", () => {
    const model = buildOurRead({
      player: "Tyrese Haliburton",
      marketName: "Assists",
      market: "player_assists",
      binary: false,
      supportsProjection: true,
      eventId: "evt-mia",
      homeTeam: "Miami Heat",
      awayTeam: "Boston Celtics",
      commenceTime: "2026-11-11T00:30:00Z",
      team: null,
      position: null,
      line: null,
      pick: null,
      consensus: null,
      last10: [],
      history: null,
      projection: null,
    });
    expect(model.tier).toBeNull();
    expect(model.headlineLead).toBe("No posted line");
    expect(model.primary).toBeNull();
  });
});

describe("clock", () => {
  it("does not print a timezone the payload does not carry", () => {
    const label = eventWhen("2026-11-11T00:30:00Z");
    expect(label).toBeTruthy();
    expect(label).not.toMatch(/ET|UTC|PT/);
  });

  it("returns null for a blank time", () => {
    expect(eventWhen(null)).toBeNull();
    expect(eventWhen("not-a-date")).toBeNull();
  });

  it("prints the ET face and appends ET only when display_tz is ET", () => {
    const clock = eventClock(
      {
        commence_time: "2026-11-11T00:30:00Z",
        commence_time_et: "2026-11-10T19:30:00-05:00",
        display_tz: "ET",
      },
      "nba",
    );
    expect(clock.web).toBe("Tue, Nov 10 · 7:30 PM ET");
    expect(clock.mobile).toBe("7:30 PM ET");
    const unlabeled = eventClock(
      {
        commence_time: "2026-11-11T00:30:00Z",
        commence_time_et: "2026-11-10T19:30:00-05:00",
        display_tz: null,
      },
      "nba",
    );
    expect(unlabeled.web).toBe("Tue, Nov 10 · 7:30 PM");
    expect(unlabeled.web).not.toMatch(/ET/);
  });
});

describe("NBA read uses the backend tier", () => {
  const base = {
    player: "Bam Adebayo",
    marketName: "Points",
    market: "player_points",
    binary: false,
    supportsProjection: true,
    eventId: "evt-mia-bos",
    homeTeam: "Miami Heat",
    awayTeam: "Boston Celtics",
    commenceTime: "2026-11-11T00:30:00Z",
    team: "MIA" as string | null,
    position: "C" as string | null,
    line: 18.5 as number | null,
    consensus: null,
    last10: [],
    history: null,
    projection: null,
    league: "nba" as const,
  };

  it("keeps Playable at 0.91 and stays blank when the tier field is null", () => {
    const playable = buildOurRead({
      ...base,
      pick: pick({ probability: 0.91, tier: "Playable", signals: null, combined_probability: null }),
    });
    expect(playable.tier).toEqual({ name: "playable", label: "Playable" });
    const blank = buildOurRead({
      ...base,
      pick: pick({ probability: 0.91, tier: null, signals: null, combined_probability: null }),
    });
    expect(blank.tier).toBeNull();
    expect(blank.tier).not.toEqual({ name: "strong", label: "Strong play" });
  });

  it("floors the percent beside the tier at 0.56, 0.65, and 0.70", () => {
    const cases: Array<[number, string, string]> = [
      [0.7, "Strong play", "70%"],
      [0.699, "Playable", "69%"],
      [0.697, "Playable", "69%"],
      [0.65, "Playable", "65%"],
      [0.649, "Lean", "64%"],
      [0.56, "Lean", "56%"],
      [0.559, "Lean", "55%"],
    ];
    for (const [probability, tier, text] of cases) {
      const rows = eventPlayerRows({
        suggested: [],
        picks: [pick({ probability, tier, signals: null, combined_probability: probability })],
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
      expect(rows[0]?.leanText).toBe(`O ${text}`);
      const model = buildOurRead({
        ...base,
        pick: pick({
          probability,
          tier,
          combined_probability: probability,
          signals: null,
        }),
      });
      expect(model.bar?.overText).toBe(text);
      expect(model.leanProbability).toBe(probability);
      expect(model.primary?.probability).toBe(probability);
    }
  });

  it("keeps half-away rounding when the pick has no tier", () => {
    const rows = eventPlayerRows({
      suggested: [],
      picks: [pick({ probability: 0.699, tier: null, signals: null })],
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
    expect(rows[0]?.tier).toBeNull();
    expect(rows[0]?.leanText).toBe("O 70%");
  });

  it("does not flip an under signal into an over sentence", () => {
    const model = buildOurRead({
      ...base,
      pick: pick({
        direction: "under",
        probability: 0.697,
        tier: "Playable",
        combined_probability: 0.697,
        signals: [
          { key: "last10", label: "Last 10 games", value: "7/10", verdict: "supports" },
          { key: "market", label: "Market price", value: "54.0%", verdict: "neutral" },
        ],
      }),
    });
    expect(model.caption).toBe("1 of 2 signals support the under.");
    expect(model.signals[0]?.detail).toBe("Went under 18.5 in 7 of 10");
    expect(model.signals[1]?.value).toBe("54.0%");
    expect(model.bar?.underText).toBe("69%");
    expect(model.bar?.overText).toBe("30%");
    expect(model.other?.probability).toBeCloseTo(0.303);
    expect(model.primary?.probability).toBe(0.697);
  });

  it("says there is no stored read and does not invent signal rows", () => {
    const model = buildOurRead({ ...base, pick: null, line: null });
    expect(model.caption).toBe("No stored read for this player.");
    expect(model.signals).toEqual([]);
    expect(model.tier).toBeNull();
    expect(model.bar).toBeNull();
  });

  it("joins position and team only when both exist", () => {
    expect(joinMeta("C", "NYK", " · ")).toBe("C · NYK");
    expect(joinMeta("C", null, " · ")).toBe("C");
    expect(joinMeta(null, "NYK", ", ")).toBe("NYK");
    expect(joinMeta("  ", "  ", " · ")).toBeNull();
    const model = buildOurRead({ ...base, team: null, position: "C", pick: null });
    expect(model.meta).toBe("C");
  });

  it("reads NBA lineup chips from the event and ignores a confirmed snapshot", () => {
    const chips = eventLineupChips({
      league: "nba",
      awayAbbr: "BOS",
      homeAbbr: "MIA",
      status: null,
      awayLineup: confirmedLineup,
      homeLineup: confirmedLineup,
    });
    expect(chips.map((chip) => chip.label)).toEqual([
      "BOS lineup status unavailable",
      "MIA lineup status unavailable",
    ]);
    const posted = eventLineupChips({
      league: "nba",
      awayAbbr: "BOS",
      homeAbbr: "MIA",
      status: { away: "confirmed", home: "projected" },
      awayLineup: null,
      homeLineup: null,
    });
    expect(posted.map((chip) => chip.label)).toEqual(["BOS lineup confirmed", "MIA lineup projected"]);
  });
});
