import { describe, expect, it } from "vitest";

import { formatPercent } from "@/lib/player-dd";
import {
  dailyPicksResponseSchema,
  eventsResponseSchema,
  type DailyPick,
} from "@/lib/schemas";
import {
  boardClock,
  propText,
  readTier,
  slateEyebrow,
  todayGames,
  todayReads,
} from "@/lib/today-board";
import nbaEventsFixture from "@/test/fixtures/today/nba-events.json";
import nbaPicksFixture from "@/test/fixtures/today/nba-daily-picks.json";
import nbaPicksPartialFixture from "@/test/fixtures/today/nba-daily-picks-partial.json";
import wnbaEventsFixture from "@/test/fixtures/today/wnba-events.json";
import wnbaPicksFixture from "@/test/fixtures/today/wnba-daily-picks.json";

const nbaEvents = eventsResponseSchema.parse(nbaEventsFixture);
const nbaPicks = dailyPicksResponseSchema.parse(nbaPicksFixture);
const wnbaEvents = eventsResponseSchema.parse(wnbaEventsFixture);
const wnbaPicks = dailyPicksResponseSchema.parse(wnbaPicksFixture);

describe("today board dates", () => {
  it("reads a YYYY-MM-DD slate as a civil date, not a UTC midnight", () => {
    expect(slateEyebrow("2026-11-10", 3)).toBe("TUE · NOV 10 · 3 GAMES");
    expect(slateEyebrow("2026-11-10", 1)).toBe("TUE · NOV 10 · 1 GAME");
    expect(slateEyebrow("not-a-date", 2)).toBe("not-a-date");
  });

  it("prints the commence instant in local time and drops an empty clock", () => {
    expect(boardClock("2026-11-11T01:00:00Z")).toBe("7:00 PM");
    expect(boardClock("2026-11-11T01:00:00Z")).not.toBe("1:00 AM");
    expect(boardClock("")).toBeNull();
    expect(boardClock("not-a-time")).toBeNull();
  });
});

describe("today board numbers", () => {
  it("shows the stored probability, not a second vig pass", () => {
    const [bam] = todayReads(nbaPicks.picks, "nba", nbaPicks.date);
    expect(bam.probabilityText).toBe(formatPercent(0.724));
    expect(bam.probabilityText).toBe("72.4%");
    expect(bam.probabilityText).not.toBe("7240.0%");
    expect(bam.tier).toEqual({ name: "strong", label: "Strong play" });
  });

  it("buckets the display tiers on the stored probability", () => {
    expect(readTier(0.7).name).toBe("strong");
    expect(readTier(0.699).name).toBe("playable");
    expect(readTier(0.65).name).toBe("playable");
    expect(readTier(0.649).name).toBe("lean");
    expect(readTier(0.56).name).toBe("lean");
    expect(readTier(0.559).name).toBe("pass");
  });

  it("formats a half-away probability the same way formatPercent does", () => {
    const stewart = todayReads(wnbaPicks.picks, "wnba", wnbaPicks.date).find(
      (read) => read.player === "Breanna Stewart",
    );
    expect(stewart?.probabilityText).toBe("67.6%");
    expect(stewart?.probabilityText).toBe(formatPercent(0.6755));
    expect(stewart?.probabilityText).not.toBe("67.5%");
  });

  it("keeps a null probability as an em dash and does not throw", () => {
    const picks = nbaPicksPartialFixture.picks as unknown as DailyPick[];
    const [card] = todayReads(picks, "nba", "2026-11-10");
    expect(card.probabilityText).toBe("—");
    expect(card.probabilityText).not.toMatch(/NaN|undefined/);
    expect(card.matchup).toBe("MIA @ MIL");
    expect(propText(picks[0])).toBe("Over 10.5 REB");
  });
});

describe("today board leagues", () => {
  it("uses NBA abbreviations for an NBA slate", () => {
    const games = todayGames(nbaEvents.events, nbaPicks.picks, "nba", nbaEvents.date);
    expect(games.map((game) => `${game.awayAbbr} @ ${game.homeAbbr}`)).toEqual([
      "MIA @ MIL",
      "PHI @ BKN",
      "ORL @ CHA",
    ]);
    expect(games.map((game) => game.awayName)).toEqual(["Heat", "76ers", "Magic"]);
    expect(games[2].topText).toBeNull();
    expect(games[2].topProbabilityText).toBeNull();
  });

  it("uses WNBA abbreviations and does not borrow NBA codes", () => {
    const games = todayGames(wnbaEvents.events, wnbaPicks.picks, "wnba", wnbaEvents.date);
    expect(games.map((game) => `${game.awayAbbr} @ ${game.homeAbbr}`)).toEqual([
      "LVA @ NYL",
      "SEA @ MIN",
    ]);
    expect(games.map((game) => `${game.awayAbbr} @ ${game.homeAbbr}`).join(" ")).not.toMatch(
      /LAL|NYK|GSW|SAS/,
    );
    expect(games[0].href.startsWith("/wnba/event/")).toBe(true);
    expect(games[1].awayName).toBe("Storm");
    expect(games[1].homeName).toBe("Lynx");
  });
});
