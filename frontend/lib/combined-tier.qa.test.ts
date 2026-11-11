import { describe, expect, it } from "vitest";

import { actionBarPercent, eventPlayerRows } from "@/lib/event-page";
import { boardRate, nbaTierFace, slipFace, tierProbability } from "@/lib/nba-card";
import { buildPickRows, countStrong, matchesConfidence, sortPicks } from "@/lib/picks-board";
import { formatPercent, formatTierPercent } from "@/lib/player-dd";
import { sameSideSlipRead } from "@/lib/bet-slip-board";
import { dailyPickSchema, eventsResponseSchema, propReadSchema } from "@/lib/schemas";
import { todayGames, todayReads } from "@/lib/today-board";
import qa from "@/test/fixtures/spo-121b/qa-review.json";

const boundary = qa.boundary.map((row) => dailyPickSchema.parse(row));
const sameEvent = qa.sameEvent.map((row) => dailyPickSchema.parse(row));
const events = eventsResponseSchema.parse(qa.events);
const tierNoBlend = dailyPickSchema.parse(qa.tierNoBlend);
const wnba = dailyPickSchema.parse(qa.wnba);
const moved = {
  pick: dailyPickSchema.parse(qa.movedLine.pick),
  read: propReadSchema.parse(qa.movedLine.read),
};
const readNoBlend = {
  pick: dailyPickSchema.parse(qa.readNoBlend.pick),
  read: propReadSchema.parse(qa.readNoBlend.read),
};

function railRow(pick: typeof moved.pick, read: typeof moved.read) {
  const rows = eventPlayerRows({
    suggested: [],
    picks: [pick],
    metric: "player_points",
    eventId: pick.event_id,
    selectedName: pick.player_name,
    postedLine: null,
    awayLineup: null,
    homeLineup: null,
    awayAbbr: "MIN",
    homeAbbr: "DEN",
    league: "nba",
    reads: [read],
  });
  return rows.find((row) => row.name === pick.player_name)!;
}

describe("QA: 65% / 70% boundaries on the blend", () => {
  it("keeps exactly 0.65 as Playable and drops 0.6499 even when history is 0.80", () => {
    const [atFloor, justBelow, atStrong] = boundary;
    expect(matchesConfidence(boardRate(atFloor, "nba"), "playable")).toBe(true);
    expect(matchesConfidence(boardRate(justBelow, "nba"), "playable")).toBe(false);
    expect(matchesConfidence(boardRate(justBelow, "nba"), "strong")).toBe(false);
    expect(matchesConfidence(boardRate(atStrong, "nba"), "strong")).toBe(true);
    expect(matchesConfidence(boardRate(atStrong, "nba"), "playable")).toBe(false);
    expect(countStrong(boundary, "nba")).toBe(1);
  });

  it("floors the printed number so the boundary rows read 65% and 64%", () => {
    const rows = buildPickRows(boundary, "nba", "2026-11-10");
    const byName = new Map(rows.map((row) => [row.player, row]));
    expect(byName.get("At Floor")?.probabilityText).toBe("65%");
    expect(byName.get("At Floor")?.tierShort).toBe("Playable");
    expect(byName.get("Just Below")?.probabilityText).toBe("64%");
    expect(byName.get("At Strong")?.probabilityText).toBe("70%");
    expect(rows.map((row) => row.player)).toEqual(["At Strong", "At Floor", "Just Below"]);
  });

  it("floors values that sit one ulp under a whole percent", () => {
    expect(formatTierPercent(0.57)).toBe("57%");
    expect(formatTierPercent(0.29)).toBe("29%");
    expect(formatTierPercent(0.6999)).toBe("69%");
    expect(formatTierPercent(1)).toBe("100%");
    expect(formatTierPercent(0)).toBe("0%");
    expect(formatTierPercent(Number.POSITIVE_INFINITY)).toBe("—");
  });
});

describe("QA: Today game card with several picks on one event", () => {
  it("shows the highest blend, not the highest history, and keeps that pick's player and number together", () => {
    const [game] = todayGames(events.events, sameEvent, "nba", events.date);
    expect(game.topText).toContain("Blend");
    expect(game.topText).not.toContain("History");
    expect(game.topText).toContain("4.5");
    expect(game.topProbabilityText).toBe("72%");
    expect(game.tier?.label).toBe("Strong play");
    const reads = todayReads(sameEvent, "nba", events.date);
    expect(reads[0].probabilityText).toBe("72%");
    expect(reads[0].propText).toContain("4.5");
  });
});

describe("QA: tier present but blend missing", () => {
  it("floors the historical rate beside the tier on every NBA surface", () => {
    expect(tierProbability(tierNoBlend)).toBe(0.697);
    expect(nbaTierFace(tierNoBlend).probabilityText).toBe("69%");
    const [row] = buildPickRows([tierNoBlend], "nba", "2026-11-10");
    expect(row.probabilityText).toBe("69%");
    const slip = slipFace({ ...tierNoBlend, ...sameSideSlipRead(tierNoBlend, "over") });
    expect(slip.probabilityText).toBe("69%");
    expect(actionBarPercent(tierNoBlend, "nba")).toBe("69%");
  });
});

describe("QA: bet slip legs", () => {
  it("a reverse leg copies no tier and keeps one decimal", () => {
    const extra = sameSideSlipRead(tierNoBlend, "under");
    expect(extra).toEqual({});
    const face = slipFace({ probability: 0.303, ...extra });
    expect(face.tier).toBeNull();
    expect(face.probabilityText).toBe(formatPercent(0.303));
  });
});

describe("QA: WNBA regression", () => {
  it("ignores the blend, keeps the historical one-decimal percent and the old bucket", () => {
    const withBlend = { ...wnba, combined_probability: 0.9, tier: "Strong play" as const };
    expect(boardRate(withBlend, "wnba")).toBe(0.697);
    const [row] = buildPickRows([withBlend], "wnba", "2026-11-10");
    expect(row.probabilityText).toBe(formatPercent(0.697));
    expect(row.tierName).toBe("playable");
    const [read] = todayReads([withBlend], "wnba", "2026-11-10");
    expect(read.probabilityText).toBe(formatTierPercent(0.697));
    expect(read.tier?.label).toBe("Strong play");
    expect(actionBarPercent(withBlend, "wnba")).toBeNull();
    expect(sortPicks([withBlend], "wnba")).toHaveLength(1);
  });
});

// These two lock the fix for the game-page rail. They fail at 29e7fd7.
describe("QA: game-page rail keeps one source per row", () => {
  it("does not print the read's side and blend beside the daily pick's line", () => {
    const row = railRow(moved.pick, moved.read);
    const printedLine = row.lineText;
    const printedSide = row.leanText.split(" ")[0];
    if (printedLine === "24.5") {
      expect(printedSide).toBe("O");
      expect(row.leanText).toBe("O 68% Playable");
    } else {
      expect(printedLine).toBe("25.5");
      expect(row.leanText).toBe("U 58% Lean");
    }
  });

  it("does not attach the daily pick's over tier to the read's under side", () => {
    const row = railRow(readNoBlend.pick, readNoBlend.read);
    expect(row.leanText).not.toBe("U 71% Strong play");
  });
});
