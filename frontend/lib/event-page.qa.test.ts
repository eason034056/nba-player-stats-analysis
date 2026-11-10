import { describe, expect, it } from "vitest";

import {
  buildOurRead,
  buildReadSignals,
  consensusSplit,
  eventWhen,
  gameLogChart,
  historySplit,
} from "@/lib/event-page";
import { formatPercent } from "@/lib/player-dd";
import {
  dailyPicksResponseSchema,
  noVigResponseSchema,
  playerHistoryResponseSchema,
} from "@/lib/schemas";
import { readTier } from "@/lib/today-board";
import edgesFixture from "@/test/fixtures/event/nba-history-threshold-edges.json";
import nbaPicksFixture from "@/test/fixtures/event/nba-daily-picks.json";
import mathFixture from "@/test/fixtures/event/nba-no-vig-math.json";

const edges = playerHistoryResponseSchema.parse(edgesFixture);
const bamPick = dailyPicksResponseSchema.parse(nbaPicksFixture).picks[0];
const math = noVigResponseSchema.parse(mathFixture);

function implied(odds: number): number {
  if (odds < 0) return -odds / (-odds + 100);
  return 100 / (odds + 100);
}

function readFor(probability: number | null) {
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
    pick: probability == null ? null : { ...bamPick, probability },
    consensus: math.consensus ?? null,
    last10: edges.game_logs,
    history: edges,
    projection: null,
  });
}

describe("game clock in America/Chicago", () => {
  it("prints the local civil time, not the UTC clock", () => {
    expect(eventWhen("2026-11-11T00:30:00Z")).toBe("Tue, Nov 10 · 6:30 PM");
    expect(eventWhen("2026-03-17T01:00:00Z")).toBe("Mon, Mar 16 · 8:00 PM");
    expect(eventWhen("2026-11-11T00:30:00Z")).not.toMatch(/Nov 11/);
    expect(eventWhen("2026-11-11T00:30:00Z")).not.toMatch(/12:30/);
  });
});

describe("stored read, once", () => {
  it("keeps the pick probability and buckets it with readTier", () => {
    const model = readFor(0.72);
    expect(model.primary?.probability).toBe(0.72);
    expect(model.tier).toEqual(readTier(0.72));
    expect(model.caption).toContain(formatPercent(0.72));
    expect(model.bar?.overText).toBe(formatPercent(math.consensus?.p_over_fair));
    expect(model.bar?.overText).not.toBe(formatPercent(0.72));
    expect(model.bar).toEqual(consensusSplit(math.consensus, false));
  });

  it("uses the same tier boundaries as readTier", () => {
    expect(readFor(0.7).tier).toEqual(readTier(0.7));
    expect(readFor(0.699).tier?.name).toBe("playable");
    expect(readFor(0.65).tier?.name).toBe("playable");
    expect(readFor(0.649).tier?.name).toBe("lean");
    expect(readFor(0.56).tier?.name).toBe("lean");
    expect(readFor(0.559).tier?.name).toBe("pass");
    expect(readFor(null).tier).toBeNull();
    expect(readFor(Number.NaN).tier).toBeNull();
  });

  it("does not de-vig the stored rate into the other side", () => {
    const model = readFor(0.72);
    expect(model.other?.probability).toBe(edges.p_under);
    expect(model.other?.probability).not.toBeCloseTo(1 - 0.72);
    expect(historySplit(edges)?.underText).toBe(formatPercent(edges.p_under));
  });
});

describe("last-10 hits are strictly above the line", () => {
  it("counts a push as not a hit and keeps the payload dates", () => {
    const model = gameLogChart(edges.game_logs, 18.5);
    expect(model.lineText).toBe("18.5");
    expect(model.bars.map((bar) => [bar.date, bar.value, bar.over])).toEqual([
      ["11/01", 18.49, false],
      ["11/03", 18.5, false],
      ["11/10", 18.51, true],
    ]);
    expect(model.linePct).toBeGreaterThan(0);
    const signal = buildReadSignals({
      binary: false,
      supportsProjection: true,
      line: 18.5,
      consensus: null,
      last10: edges.game_logs,
      history: edges,
      projection: null,
      pick: null,
      market: "player_points",
    }).find((row) => row.key === "last10");
    expect(signal?.value).toBe("1/3");
    expect(signal?.detail).not.toMatch(/supports|neutral|against|easy|tough/i);
  });
});
