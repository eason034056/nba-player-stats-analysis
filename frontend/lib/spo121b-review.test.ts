import { describe, expect, it } from "vitest";

import { slipTotals } from "@/lib/bet-slip-board";
import { buildOurRead, eventPlayerRows, nbaReadsStatus, nbaRequestNote } from "@/lib/event-page";
import { formatTierPercent } from "@/lib/player-dd";
import {
  dailyPickSchema,
  playerHistoryResponseSchema,
  propReadSchema,
} from "@/lib/schemas";
import { createBetSlipPick } from "@/test/test-utils";
import qa from "@/test/fixtures/spo-121b/qa-review.json";
import historyFixture from "@/test/fixtures/event/nba-history-bam.json";

const movedPick = dailyPickSchema.parse(qa.movedLine.pick);
const movedRead = propReadSchema.parse(qa.movedLine.read);

function rail(picks: typeof movedPick[], reads: typeof movedRead[], status?: "loading" | "error" | "ready") {
  return eventPlayerRows({
    suggested: ["Posted Only"],
    picks,
    metric: "player_points",
    eventId: "evt-min-den",
    selectedName: "",
    postedLine: null,
    awayLineup: null,
    homeLineup: null,
    awayAbbr: "MIN",
    homeAbbr: "DEN",
    league: "nba",
    reads,
    readsStatus: status,
  });
}

describe("review: one source per rail row", () => {
  it("uses the daily pick for the line and the lean, matching the Our read headline", () => {
    const row = rail([movedPick], [movedRead]).find((item) => item.name === "Moved Line");
    const model = buildOurRead({
      player: movedPick.player_name,
      marketName: "Points",
      market: "player_points",
      binary: false,
      supportsProjection: true,
      eventId: movedPick.event_id,
      homeTeam: movedPick.home_team,
      awayTeam: movedPick.away_team,
      commenceTime: movedPick.commence_time,
      team: "MIN",
      position: null,
      line: movedRead.line,
      pick: movedPick,
      consensus: null,
      last10: [],
      history: null,
      projection: null,
      league: "nba",
      read: movedRead,
    });
    expect(row?.lineText).toBe("24.5");
    expect(row?.leanText).toBe("O 68% Playable");
    expect(model.headlineLead).toBe("Over 24.5");
    expect(model.tier?.label).toBe("Playable");
  });

  it("uses the reads entry when that player has no daily pick", () => {
    const row = rail([], [movedRead]).find((item) => item.name === "Moved Line");
    const model = buildOurRead({
      player: movedRead.player,
      marketName: "Points",
      market: "player_points",
      binary: false,
      supportsProjection: true,
      eventId: "evt-min-den",
      homeTeam: "Denver Nuggets",
      awayTeam: "Minnesota Timberwolves",
      commenceTime: "2026-11-11T02:00:00Z",
      team: null,
      position: null,
      line: null,
      pick: null,
      consensus: null,
      last10: [],
      history: null,
      projection: null,
      league: "nba",
      read: movedRead,
    });
    expect(row?.lineText).toBe("25.5");
    expect(row?.leanText).toBe("U 58% Lean");
    expect(model.headlineLead).toBe("Under 25.5");
    expect(model.tier?.label).toBe("Lean");
  });
});

describe("review: reads loading and failure", () => {
  it("does not print No read while the request is loading or has failed", () => {
    const loading = rail([], [], "loading").find((item) => item.name === "Posted Only");
    const failed = rail([], [], "error").find((item) => item.name === "Posted Only");
    const ready = rail([], [], "ready").find((item) => item.name === "Posted Only");
    expect(loading?.leanText).toBe("Loading");
    expect(failed?.leanText).toBe("Unavailable");
    expect(ready?.leanText).toBe("No read");
    expect(nbaReadsStatus(true, false)).toBe("loading");
    expect(nbaReadsStatus(false, true)).toBe("error");
    expect(nbaRequestNote("reads", "loading")).toBe("Loading reads.");
    expect(nbaRequestNote("reads", "error")).toBe("Reads failed.");
    expect(nbaRequestNote("props", "error")).toBe("Props failed.");
    expect(nbaRequestNote("reads", "ready")).toBeNull();
  });
});

describe("review: slip totals", () => {
  it("averages the blend for same-side legs and labels a mixed slip History", () => {
    const blend = createBetSlipPick({
      probability: 0.59,
      combined_probability: 0.66,
      tier: "Playable",
      direction: "over",
    });
    const other = createBetSlipPick({
      id: "other-points",
      player_name: "Other Player",
      probability: 0.5,
      combined_probability: 0.5,
      tier: "Lean",
      direction: "over",
    });
    const blended = slipTotals([blend, other]);
    expect(blended.basis).toBe("blend");
    expect(blended.averageLabel).toBe("avg. blend");
    expect(blended.summary.averageText).toBe(formatTierPercent((0.66 + 0.5) / 2));
    expect(blended.summary.allHitText).toBe(formatTierPercent(0.66 * 0.5));

    const plain = createBetSlipPick({
      id: "plain-points",
      player_name: "Plain Player",
      probability: 0.4,
      direction: "over",
    });
    const mixed = slipTotals([blend, plain]);
    expect(mixed.basis).toBe("history");
    expect(mixed.averageLabel).toBe("History");
    expect(mixed.allHitLabel).toBe("History");
    expect(mixed.summary.averageText).toBe(formatTierPercent((0.59 + 0.4) / 2));
    expect(slipTotals([plain]).averageLabel).toBe("avg. probability");
  });
});

describe("review: a bad new field does not drop the payload", () => {
  it("turns an invalid tier, blend, and season mean into null", () => {
    const pick = dailyPickSchema.parse({
      ...qa.movedLine.pick,
      tier: "Not a tier",
      combined_probability: 1.4,
      p_over: -1,
      signals: "bad",
      season_mean: "nope",
    });
    expect(pick.player_name).toBe("Moved Line");
    expect(pick.tier).toBeNull();
    expect(pick.combined_probability).toBeNull();
    expect(pick.p_over).toBeNull();
    expect(pick.signals).toBeNull();
    expect(pick.season_mean).toBeNull();

    const read = propReadSchema.parse({
      ...qa.movedLine.read,
      combined_probability: 4,
      tier: "Pass",
    });
    expect(read.player).toBe("Moved Line");
    expect(read.line).toBe(25.5);
    expect(read.combined_probability).toBeNull();
    expect(read.tier).toBeNull();

    const history = playerHistoryResponseSchema.parse({
      ...historyFixture,
      season_mean: "nope",
    });
    expect(history.n_games).toBe(historyFixture.n_games);
    expect(history.season_mean).toBeNull();
  });
});
