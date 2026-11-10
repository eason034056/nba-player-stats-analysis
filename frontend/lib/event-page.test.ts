import { describe, expect, it } from "vitest";

import {
  buildOurRead,
  buildReadSignals,
  consensusSplit,
  eventPlayerRows,
  eventWhen,
  gameLogChart,
  lineupChip,
  postedLine,
} from "@/lib/event-page";
import type { DailyPick, GameLog, PlayerHistoryResponse, TeamLineup } from "@/lib/schemas";

function lineup(
  status: TeamLineup["status"],
  snapshots: Array<{ source: string; status: string }>,
): TeamLineup {
  return {
    date: "2026-11-10",
    team: "MIA",
    opponent: "BOS",
    home_or_away: "HOME",
    status,
    starters: ["Bam Adebayo"],
    bench_candidates: ["Kevin Love"],
    sources: snapshots.map((item) => item.source),
    source_disagreement: false,
    confidence: "high",
    updated_at: "2026-11-10T18:00:00Z",
    source_snapshots: Object.fromEntries(
      snapshots.map((item) => [
        item.source,
        {
          team: "MIA",
          opponent: "BOS",
          home_or_away: "HOME",
          status: item.status,
          starters: ["Bam Adebayo"],
          bench_candidates: [],
        },
      ]),
    ),
  };
}

function game(date: string, value: number, opponent: string): GameLog {
  return {
    date: date.slice(5).replace("-", "/"),
    date_full: date,
    opponent,
    value,
    is_over: value > 18.5,
    team: "MIA",
    minutes: 34,
    is_starter: true,
    game_type: "regular_season",
    season: "2025-2026",
  };
}

function pick(overrides: Partial<DailyPick> = {}): DailyPick {
  return {
    player_name: "Bam Adebayo",
    player_team: "Heat",
    player_team_code: "MIA",
    event_id: "evt-mia",
    home_team: "Miami Heat",
    away_team: "Boston Celtics",
    commence_time: "2026-11-11T00:00:00Z",
    metric: "points",
    threshold: 18.5,
    direction: "over",
    probability: 0.72,
    n_games: 40,
    bookmakers_count: 4,
    all_lines: [18.5],
    has_projection: true,
    projected_value: 20.4,
    projected_minutes: 34,
    edge: 1.9,
    opponent_rank: 22,
    opponent_position_rank: 9,
    injury_status: null,
    lineup_confirmed: null,
    ...overrides,
  };
}

function history(overrides: Partial<PlayerHistoryResponse> = {}): PlayerHistoryResponse {
  return {
    player: "Bam Adebayo",
    metric: "points",
    threshold: 18.5,
    n_games: 40,
    p_over: 0.62,
    p_under: 0.35,
    equal_count: 1,
    mean: 19.4,
    std: 4,
    histogram: [],
    game_logs: [],
    opponents: ["BOS"],
    teammates: ["Tyler Herro"],
    message: null,
    ...overrides,
  };
}

describe("lineup chips", () => {
  it("says confirmed only when every source snapshot says confirmed", () => {
    expect(lineupChip("MIA", lineup("projected", [
      { source: "rotowire", status: "confirmed" },
      { source: "rotogrinders", status: "confirmed" },
    ])).label).toBe("MIA lineup confirmed");
  });

  it("keeps the consensus word when sources disagree", () => {
    const chip = lineupChip("MIA", lineup("projected", [
      { source: "rotowire", status: "confirmed" },
      { source: "rotogrinders", status: "expected" },
    ]));
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
    consensus: { p_over_fair: 0.54, p_under_fair: 0.46 },
    last10: [game("2026-11-01", 22, "BOS"), game("2026-11-03", 14, "PHI")],
    history: history(),
    projection: null,
    pick: pick(),
    market: "player_points",
  };

  it("shows raw rates and the stored rank without a verdict", () => {
    const signals = buildReadSignals(base);
    const text = signals.map((signal) => `${signal.label} ${signal.detail} ${signal.value}`).join(" ");
    expect(signals.find((signal) => signal.key === "market")?.value).toBe("54.0%");
    expect(signals.find((signal) => signal.key === "last10")?.value).toBe("1/2");
    expect(signals.find((signal) => signal.key === "history")?.value).toBe("62.0%");
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
      eventId: "evt-mia",
      selectedName: "Tyler Herro",
      postedLine: 16.5,
      awayLineup: null,
      homeLineup: lineup("projected", []),
      awayAbbr: "BOS",
      homeAbbr: "MIA",
      league: "nba",
    });
    const bam = rows.find((row) => row.name === "Bam Adebayo");
    const herro = rows.find((row) => row.name === "Tyler Herro");
    expect(bam?.leanText).toBe("O 72.0%");
    expect(bam?.lineText).toBe("18.5");
    expect(herro?.leanText).toBe("No read");
    expect(herro?.lineText).toBe("16.5");
    expect(rows.map((row) => row.leanText).join(" ")).not.toMatch(/80%|51%/);
  });

  it("ignores a synthetic double-double line", () => {
    expect(postedLine([
      { line: 0.5, line_is_synthetic: true, market_kind: "binary" },
    ])).toBeNull();
    expect(postedLine([
      { line: 18.5, market_kind: "over_under" },
      { line: 18.5, market_kind: "over_under" },
      { line: 19.5, market_kind: "over_under" },
    ])).toBe(18.5);
  });
});

describe("game log chart", () => {
  it("draws oldest to newest and marks the posted line", () => {
    const model = gameLogChart(
      [game("2026-11-08", 24, "BOS"), game("2026-11-01", 12, "PHI")],
      18.5,
    );
    expect(model.empty).toBe(false);
    expect(model.bars.map((bar) => bar.dateFull)).toEqual(["2026-11-01", "2026-11-08"]);
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
      commenceTime: "2026-11-11T00:00:00Z",
      team: "MIA",
      position: "C",
      line: 18.5,
      pick: pick(),
      consensus: { p_over_fair: 0.54, p_under_fair: 0.46 },
      last10: [],
      history: null,
      projection: null,
    });
    expect(model.tier?.label).toBe("Strong play");
    expect(model.headlineLead).toBe("Over 18.5");
    expect(model.caption).toMatch(/Historical hit rate 72.0%/);
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
      commenceTime: "2026-11-11T00:00:00Z",
      team: "MIA",
      position: null,
      line: 18.5,
      pick: pick(),
      consensus: null,
      last10: [],
      history: history(),
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
      commenceTime: "2026-11-11T00:00:00Z",
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
});
