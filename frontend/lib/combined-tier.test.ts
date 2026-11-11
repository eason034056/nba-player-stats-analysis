import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { actionBarPercent, buildOurRead, buildReadSignals, eventPlayerRows, slipButtonLabel } from "@/lib/event-page";
import { boardRate, slipFace, tierProbability } from "@/lib/nba-card";
import { buildPickRows, matchesConfidence } from "@/lib/picks-board";
import { formatPercent, formatTierPercent } from "@/lib/player-dd";
import {
  dailyPickSchema,
  playerHistoryResponseSchema,
  propReadSchema,
  type DailyPick,
} from "@/lib/schemas";
import { todayReads } from "@/lib/today-board";
import combinedFixture from "@/test/fixtures/spo-121b/combined-tier.json";
import nbaHistoryFixture from "@/test/fixtures/event/nba-history-bam.json";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const alexander = dailyPickSchema.parse(combinedFixture.alexanderWalker);
const thybulle = dailyPickSchema.parse(combinedFixture.thybulle);
const nullCombined = dailyPickSchema.parse(combinedFixture.nullCombined);
const nullCombined72 = dailyPickSchema.parse(combinedFixture.nullCombined72);
const sameCard = dailyPickSchema.parse(combinedFixture.sameCard);
const contradiction = dailyPickSchema.parse(combinedFixture.contradiction);
const postedRead = propReadSchema.parse(combinedFixture.postedRead);
const besideTier = dailyPickSchema.parse(combinedFixture.besideTier);

function source(path: string): string {
  return readFileSync(resolve(frontendRoot, path), "utf8");
}

describe("formatTierPercent", () => {
  it("floors the fixture cutoffs and keeps a missing rate as an em dash", () => {
    for (const row of combinedFixture.formatTierPercent) {
      expect(formatTierPercent(row.input)).toBe(row.text);
    }
    expect(formatTierPercent(Number.NaN)).toBe("—");
    expect(formatPercent(0.697)).toBe("70%");
  });
});

describe("NBA combined tier", () => {
  it("renders Alexander-Walker from the backend tier and the floored blend", () => {
    const [today] = todayReads([alexander], "nba", "2026-11-10");
    const [row] = buildPickRows([alexander], "nba", "2026-11-10");
    const model = ourRead(alexander);

    expect(today.probabilityText).toBe("67%");
    expect(today.tier).toEqual({ name: "playable", label: "Playable" });
    expect(row.probabilityText).toBe("67%");
    expect(row.tierShort).toBe("Playable");
    expect(model.tier?.label).toBe("Playable");
    expect(model.caption).toContain("Combined probability 67%");
    expect(model.caption).toContain(formatPercent(0.5897));
    expect(`${today.probabilityText} ${today.tier?.label}`).not.toBe("59% Lean");
    expect(`${row.probabilityText} ${row.tierShort}`).not.toBe("59% Lean");
  });

  it("shows 66% Playable beside the tier, never the 0.59 historical percent", () => {
    expect(tierProbability(besideTier)).toBe(0.66);
    const [today] = todayReads([besideTier], "nba", "2026-11-10");
    const [row] = buildPickRows([besideTier], "nba", "2026-11-10");
    const slip = slipFace(besideTier);
    const rows = eventPlayerRows({
      suggested: [],
      picks: [besideTier],
      metric: "player_points",
      eventId: besideTier.event_id,
      selectedName: besideTier.player_name,
      postedLine: null,
      awayLineup: null,
      homeLineup: null,
      awayAbbr: "MIN",
      homeAbbr: "DEN",
      league: "nba",
    });
    const action = slipButtonLabel(
      {
        player_name: besideTier.player_name,
        player_team: besideTier.player_team,
        event_id: besideTier.event_id,
        home_team: besideTier.home_team,
        away_team: besideTier.away_team,
        commence_time: besideTier.commence_time,
        metric: besideTier.metric,
        threshold: besideTier.threshold,
        direction: besideTier.direction,
        probability: besideTier.probability,
        n_games: besideTier.n_games,
        tier: besideTier.tier,
        combined_probability: besideTier.combined_probability,
      },
      false,
    );
    const faces = [
      `${today.probabilityText} ${today.tier?.label}`,
      `${row.probabilityText} ${row.tierShort}`,
      `${slip.probabilityText} ${slip.tier?.label}`,
      rows[0]?.leanText,
    ];
    for (const face of faces) {
      expect(face).toContain("66% Playable");
      expect(face).not.toContain("59% Playable");
    }
    expect(action).toContain("66%");
    expect(action).not.toContain("59%");
    expect(actionBarPercent(besideTier, "nba")).toBe("66%");
    expect(actionBarPercent(besideTier, "wnba")).toBeNull();
  });

  it("keeps Thybulle when the blend is 0.73 and the historical rate is 0.40", () => {
    expect(boardRate(thybulle, "nba")).toBe(0.73);
    expect(matchesConfidence(boardRate(thybulle, "nba"), "strong")).toBe(true);
    expect(matchesConfidence(boardRate(thybulle, "nba"), "all")).toBe(true);
    expect(matchesConfidence(thybulle.probability, "strong")).toBe(false);
    const [row] = buildPickRows([thybulle], "nba", "2026-11-10");
    expect(row.probabilityText).toBe("73%");
    expect(row.tierShort).toBe("Strong play");
    const rows = eventPlayerRows({
      suggested: [],
      picks: [],
      metric: "player_rebounds",
      eventId: "evt-por-sac",
      selectedName: "",
      postedLine: null,
      awayLineup: null,
      homeLineup: null,
      awayAbbr: "POR",
      homeAbbr: "SAC",
      league: "nba",
      reads: [postedRead],
    });
    expect(rows.map((row) => row.name)).toContain("Matisse Thybulle");
    expect(rows[0]?.leanText).toBe("U 73% Strong play");
  });

  it("falls back to the historical rate and does not invent a tier when the blend is null", () => {
    expect(boardRate(nullCombined, "nba")).toBe(0.8);
    expect(boardRate(nullCombined72, "nba")).toBe(0.72);
    expect(matchesConfidence(boardRate(nullCombined72, "nba"), "strong")).toBe(true);
    for (const pick of [nullCombined, nullCombined72]) {
      const [today] = todayReads([pick], "nba", "2026-11-10");
      const [row] = buildPickRows([pick], "nba", "2026-11-10");
      expect(today.probabilityText).toBe("—");
      expect(today.tier).toBeNull();
      expect(row.probabilityText).toBe("—");
      expect(row.tierShort).toBeNull();
      expect(ourRead(pick).tier).toBeNull();
      expect(ourRead(pick).caption).toContain("Combined probability —");
      expect(ourRead(pick).caption).toContain(formatPercent(pick.probability));
    }
  });

  it("shows Lean for a 0.99 historical rate when the backend tier is Lean", () => {
    const [today] = todayReads([contradiction], "nba", "2026-11-10");
    const [row] = buildPickRows([contradiction], "nba", "2026-11-10");
    const model = ourRead(contradiction);
    const slip = slipFace({
      probability: contradiction.probability,
      combined_probability: contradiction.combined_probability,
      tier: contradiction.tier,
    });

    expect(today.tier?.label).toBe("Lean");
    expect(today.probabilityText).toBe("58%");
    expect(row.tierShort).toBe("Lean");
    expect(row.probabilityText).toBe("58%");
    expect(model.tier?.label).toBe("Lean");
    expect(slip).toEqual({
      probabilityText: "58%",
      tier: { name: "lean", label: "Lean" },
    });
    expect(today.tier?.name).not.toBe("strong");
    expect(row.tierName).not.toBe("strong");
    expect(model.tier?.name).not.toBe("strong");
    expect(slip.tier?.name).not.toBe("strong");
  });

  it("keeps a saved slip that has no blend on the one-decimal historical percent", () => {
    expect(slipFace({ probability: 0.72 })).toEqual({
      probabilityText: "72%",
      tier: null,
    });
  });

  it("mentions season_mean only when the history payload has a finite one", () => {
    const history = playerHistoryResponseSchema.parse(nbaHistoryFixture);
    const withMean = buildReadSignals({
      binary: false,
      supportsProjection: true,
      line: 18.5,
      consensus: null,
      last10: [],
      history: { ...history, season_mean: 20.4 },
      projection: null,
      pick: null,
      market: "player_points",
    }).find((signal) => signal.key === "history");
    const withoutMean = buildReadSignals({
      binary: false,
      supportsProjection: true,
      line: 18.5,
      consensus: null,
      last10: [],
      history,
      projection: null,
      pick: null,
      market: "player_points",
    }).find((signal) => signal.key === "history");
    expect(withMean?.detail).toContain("Season mean 20.4.");
    expect(withoutMean?.detail).not.toContain("Season mean");
  });

  it("turns a combined probability outside 0 to 1 into null and keeps the row", () => {
    const read = propReadSchema.safeParse({ ...combinedFixture.postedRead, combined_probability: 1.01 });
    const pick = dailyPickSchema.safeParse({ ...combinedFixture.sameCard, combined_probability: -0.01 });
    expect(read.success).toBe(true);
    expect(pick.success).toBe(true);
    if (read.success) {
      expect(read.data.combined_probability).toBeNull();
      expect(read.data.line).toBe(combinedFixture.postedRead.line);
    }
    if (pick.success) {
      expect(pick.data.combined_probability).toBeNull();
      expect(pick.data.player_name).toBe(combinedFixture.sameCard.player_name);
    }
  });

  it("does not call readTier from the NBA card or the bet slip", () => {
    expect(source("lib/nba-card.ts")).not.toMatch(/readTier/);
    expect(source("components/betslip/BetSlipScreen.tsx")).not.toMatch(/readTier/);
    expect(source("lib/today-board.ts")).toMatch(
      /if \(league === "nba"\) return tierFromBackend\(pick\.tier\)/,
    );
    expect(source("lib/picks-board.ts")).toMatch(/league === "nba" \? nbaTierFace\(pick\) : null/);
    expect(source("lib/event-page.ts")).toMatch(/if \(args\.league === "nba"\)/);
    expect(source("components/agent-widget/presentation.ts")).toMatch(/toFixed\(1\)/);
  });
});

function ourRead(pick: DailyPick) {
  return buildOurRead({
    player: pick.player_name,
    marketName: "Points",
    market: "player_points",
    binary: false,
    supportsProjection: true,
    eventId: pick.event_id,
    homeTeam: pick.home_team,
    awayTeam: pick.away_team,
    commenceTime: pick.commence_time,
    team: pick.player_team_code,
    position: pick.position ?? null,
    line: pick.threshold,
    pick,
    consensus: null,
    last10: [],
    history: null,
    projection: null,
    league: "nba",
  });
}
