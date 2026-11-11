import { describe, expect, it } from "vitest";

import {
  buildOurRead,
  buildReadSignals,
  consensusSplit,
  eventPlayerRows,
  eventTeammates,
  eventWhen,
  gameLogChart,
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

  it("labels a player from the lineup and drops a club that is not in the game", () => {
    const phi = teamLineupSchema.parse({
      date: "2026-11-10",
      team: "PHI",
      status: "projected",
      confidence: "medium",
      starters: ["Tyrese Maxey"],
      bench_candidates: ["Anfernee Simons"],
    });
    const bos = teamLineupSchema.parse({
      date: "2026-11-10",
      team: "BOS",
      status: "projected",
      confidence: "medium",
      starters: ["Jaylen Brown", "Jayson Tatum"],
      bench_candidates: [],
    });
    const rows = eventPlayerRows({
      suggested: ["Anfernee Simons", "Jaylen Brown"],
      picks: [
        pick({
          player_name: "Anfernee Simons",
          player_team: "Bulls",
          player_team_code: "CHI",
          event_id: "bos-phi",
          home_team: "Philadelphia 76ers",
          away_team: "Boston Celtics",
        }),
        pick({
          player_name: "Jaylen Brown",
          player_team: "Celtics",
          player_team_code: "BOS",
          event_id: "bos-phi",
          home_team: "Philadelphia 76ers",
          away_team: "Boston Celtics",
        }),
      ],
      metric: "player_points",
      eventId: "bos-phi",
      selectedName: "Anfernee Simons",
      postedLine: 9.5,
      awayLineup: bos,
      homeLineup: phi,
      awayAbbr: "BOS",
      homeAbbr: "PHI",
      league: "nba",
    });
    expect(rows.find((row) => row.name === "Anfernee Simons")?.team).toBe("PHI");
    expect(rows.find((row) => row.name === "Jaylen Brown")?.team).toBe("BOS");
    const unlabeled = eventPlayerRows({
      suggested: ["Anfernee Simons"],
      picks: [
        pick({
          player_name: "Anfernee Simons",
          player_team: "Bulls",
          player_team_code: "CHI",
          event_id: "bos-phi",
        }),
      ],
      metric: "player_points",
      eventId: "bos-phi",
      selectedName: "",
      postedLine: null,
      awayLineup: null,
      homeLineup: null,
      awayAbbr: "BOS",
      homeAbbr: "PHI",
      league: "nba",
    });
    expect(unlabeled.find((row) => row.name === "Anfernee Simons")?.team).toBeNull();
  });

  it("folds initials and accents into one teammate", () => {
    const phi = teamLineupSchema.parse({
      date: "2026-11-10",
      team: "PHI",
      status: "projected",
      confidence: "medium",
      starters: ["Tyrese Maxey", "VJ Edgecombe", "Nikola Jokic"],
      bench_candidates: [],
    });
    expect(
      eventTeammates({
        player: "Tyrese Maxey",
        awayLineup: null,
        homeLineup: phi,
        historyTeammates: ["V.J. Edgecombe", "VJ Edgecombe", "Nikola Jokić", "Nikola Jokic"],
      }),
    ).toEqual(["V.J. Edgecombe", "Nikola Jokić"]);
  });

  it("joins spaced initials and treats a hyphen as a space", () => {
    const bos = teamLineupSchema.parse({
      date: "2026-11-10",
      team: "BOS",
      status: "projected",
      confidence: "medium",
      starters: ["Derrick White", "A.J. Green", "AJ Green", "Shai Gilgeous Alexander"],
      bench_candidates: ["Shai Alexander"],
    });
    expect(
      eventTeammates({
        player: "Derrick White",
        awayLineup: bos,
        homeLineup: null,
        historyTeammates: ["A. J. Green", "Shai Gilgeous-Alexander", "Shai Alexander"],
      }),
    ).toEqual(["A. J. Green", "Shai Gilgeous-Alexander", "Shai Alexander"]);
  });

  it("keeps a teammate who is out and appends lineup names", () => {
    const phi = teamLineupSchema.parse({
      date: "2026-11-10",
      team: "PHI",
      status: "projected",
      confidence: "medium",
      starters: ["Tyrese Maxey", "Paul George"],
      bench_candidates: ["Anfernee Simons"],
    });
    expect(
      eventTeammates({
        player: "Anfernee Simons",
        awayLineup: null,
        homeLineup: phi,
        historyTeammates: ["Joel Embiid", "Tyrese Maxey", "Anfernee Simons"],
      }),
    ).toEqual(["Joel Embiid", "Tyrese Maxey", "Paul George"]);
    expect(
      eventTeammates({
        player: "Anfernee Simons",
        awayLineup: null,
        homeLineup: phi,
        historyTeammates: [],
      }),
    ).toEqual(["Tyrese Maxey", "Paul George"]);
    expect(
      eventTeammates({
        player: "Anfernee Simons",
        awayLineup: null,
        homeLineup: null,
        historyTeammates: ["Derrick White"],
      }),
    ).toEqual(["Derrick White"]);
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
});
