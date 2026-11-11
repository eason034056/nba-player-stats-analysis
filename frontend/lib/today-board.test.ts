import { describe, expect, it } from "vitest";

import { tierFromBackend } from "@/lib/nba-card";
import { formatPercent, formatTierPercent } from "@/lib/player-dd";
import {
  dailyPicksResponseSchema,
  eventsResponseSchema,
  type DailyPick,
} from "@/lib/schemas";
import {
  boardClock,
  directionLabel,
  etWallClock,
  eventTipClock,
  marketShort,
  propText,
  readTier,
  slateEyebrow,
  todayGames,
  todayReads,
} from "@/lib/today-board";
import nbaEventsFixture from "@/test/fixtures/today/nba-events.json";
import nbaPicksFixture from "@/test/fixtures/today/nba-daily-picks.json";
import nbaPicksPartialFixture from "@/test/fixtures/today/nba-daily-picks-partial.json";
import nbaPicksMissingDirectionFixture from "@/test/fixtures/today/nba-daily-picks-missing-direction.json";
import wnbaEventsFixture from "@/test/fixtures/today/wnba-events.json";
import wnbaPicksFixture from "@/test/fixtures/today/wnba-daily-picks.json";
import { brokenTopRead, giannisTopRead } from "@/test/fixtures/today/top-read";

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
  it("shows an em dash when the NBA pick has no blend and no tier", () => {
    const [stored] = nbaPicks.picks;
    const [card] = todayReads(
      [{ ...stored, tier: null, combined_probability: null }],
      "nba",
      nbaPicks.date,
    );
    expect(card.probabilityText).toBe("—");
    expect(card.tier).toBeNull();
    expect(card.probabilityText).not.toBe(formatPercent(0.724));
  });

  it("uses the backend tier and the blend, and does not recompute a tier", () => {
    const [bam] = todayReads(nbaPicks.picks, "nba", nbaPicks.date);
    expect(bam.probabilityText).toBe(formatTierPercent(0.724));
    expect(bam.probabilityText).toBe("72%");
    expect(bam.probabilityText).not.toBe("72.4%");
    expect(bam.probabilityText).not.toBe("7240%");
    expect(bam.tier).toEqual(tierFromBackend("Strong play"));

    const [stored] = nbaPicks.picks;
    const highButPlayable = todayReads(
      [{ ...stored, probability: 0.91, combined_probability: 0.91, tier: "Playable" }],
      "nba",
      nbaPicks.date,
    );
    expect(highButPlayable[0].probabilityText).toBe("91%");
    expect(highButPlayable[0].tier).toEqual({ name: "playable", label: "Playable" });
    expect(highButPlayable[0].tier?.name).not.toBe("strong");

    const highWithoutTier = todayReads(
      [{ ...stored, probability: 0.91, combined_probability: null, tier: null }],
      "nba",
      nbaPicks.date,
    );
    expect(highWithoutTier[0].tier).toBeNull();
    expect(highWithoutTier[0].probabilityText).toBe("—");

    const justUnderStrong = todayReads(
      [{ ...stored, probability: 0.697, combined_probability: 0.697, tier: "Playable" }],
      "nba",
      nbaPicks.date,
    );
    expect(justUnderStrong[0].tier?.label).toBe("Playable");
    expect(justUnderStrong[0].probabilityText).toBe("69%");
    expect(justUnderStrong[0].probabilityText).toBe(formatTierPercent(0.697));
    expect(justUnderStrong[0].probabilityText).not.toBe(formatPercent(0.697));

    const sameRateWithoutTier = todayReads(
      [{ ...stored, probability: 0.697, combined_probability: null, tier: null }],
      "nba",
      nbaPicks.date,
    );
    expect(sameRateWithoutTier[0].tier).toBeNull();
    expect(sameRateWithoutTier[0].probabilityText).toBe("—");

    expect(tierFromBackend(null)).toBeNull();
    expect(tierFromBackend(undefined)).toBeNull();
    expect(tierFromBackend("Pass")).toBeNull();
  });

  it("buckets WNBA display tiers on the stored probability", () => {
    expect(readTier(0.7)?.name).toBe("strong");
    expect(readTier(0.699)?.name).toBe("playable");
    expect(readTier(0.65)?.name).toBe("playable");
    expect(readTier(0.649)?.name).toBe("lean");
    expect(readTier(0.56)?.name).toBe("lean");
    expect(readTier(0.559)?.name).toBe("pass");
    expect(readTier(null)).toBeNull();
    expect(readTier(undefined)).toBeNull();
  });

  it("formats a half-away probability the same way formatPercent does", () => {
    const stewart = todayReads(wnbaPicks.picks, "wnba", wnbaPicks.date).find(
      (read) => read.player === "Breanna Stewart",
    );
    expect(stewart?.tier?.label).toBe("Playable");
    expect(stewart?.probabilityText).toBe("67%");
    expect(stewart?.probabilityText).toBe(formatTierPercent(0.6755));
    expect(stewart?.probabilityText).not.toBe(formatPercent(0.6755));
    expect(stewart?.probabilityText).not.toBe("67.6%");
  });

  it("keeps a null probability as an em dash and does not throw", () => {
    const picks = nbaPicksPartialFixture.picks as unknown as DailyPick[];
    const [card] = todayReads(picks, "nba", "2026-11-10");
    expect(card.probabilityText).toBe("—");
    expect(card.tier).toBeNull();
    expect(card.probabilityText).not.toMatch(/NaN|undefined/);
    expect(card.matchup).toBe("MIA @ MIL");
    expect(propText(picks[0])).toBe("Over 10.5 REB");
  });

  it("dashes a missing direction instead of printing null or undefined", () => {
    expect(directionLabel(null)).toBe("—");
    expect(directionLabel(undefined)).toBe("—");
    expect(directionLabel("null")).toBe("—");
    expect(directionLabel("undefined")).toBe("—");
    const picks = nbaPicksMissingDirectionFixture.picks as unknown as DailyPick[];
    expect(propText(picks[0])).toBe("— 10.5 REB");
    expect(propText(picks[0])).not.toMatch(/undefined|\bnull\b/);
    const [card] = todayReads(picks, "nba", "2026-11-10");
    expect(card.propText).toBe("— 10.5 REB");
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
    expect(games[0].topSource).toBe("picks");
    expect(games[0].time).toBe("7:00 PM");
    expect(games[2].topSource).toBe("none");
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
    expect(games[0].topSource).toBe("picks");
  });
});

describe("today board event fields", () => {
  const heat = {
    event_id: "heat-bucks",
    sport_key: "basketball_nba",
    home_team: "Milwaukee Bucks",
    away_team: "Miami Heat",
    commence_time: "2026-11-11T01:00:00Z",
  };

  it("reads the ET wall clock and ignores the machine zone", () => {
    expect(etWallClock("2026-11-10T20:00:00-05:00")).toBe("8:00 PM");
    expect(etWallClock("2026-11-11T00:10:00-05:00")).toBe("12:10 AM");
    expect(etWallClock("2026-07-14T20:00:00-04:00")).toBe("8:00 PM");
    expect(etWallClock("2026-11-11T01:00:00Z")).toBeNull();
    expect(etWallClock("")).toBeNull();
    expect(etWallClock("not-a-time")).toBeNull();
    expect(eventTipClock({
      ...heat,
      commence_time_et: "2026-11-10T20:00:00-05:00",
      display_tz: "ET",
    })).toBe("8:00 PM");
    expect(eventTipClock({
      ...heat,
      commence_time_et: "2026-11-10T20:00:00-05:00",
      display_tz: "ET",
    })).not.toBe("7:00 PM");
    expect(eventTipClock({
      ...heat,
      commence_time_et: "2026-11-10T20:00:00-05:00",
      display_tz: "CT",
    })).toBe("7:00 PM");
    expect(eventTipClock(heat)).toBe("7:00 PM");
  });

  it("prints that ET clock on a read joined by event id", () => {
    const events = eventsResponseSchema.parse({
      date: "2026-11-10",
      events: [{
        ...heat,
        commence_time_et: "2026-11-10T20:00:00-05:00",
        display_tz: "ET",
        lineup_status: { home: "confirmed", away: "projected" },
      }],
    });
    expect(events.events[0].lineup_status).toEqual({
      home: "confirmed",
      away: "projected",
    });
    const [bam] = todayReads(nbaPicks.picks, "nba", "2026-11-10", 3, events.events);
    expect(bam.matchup).toBe("MIA @ MIL · 8:00 PM");
    expect(bam.probabilityText).toBe("72%");
  });

  it("keeps a published NBA pick ahead of top_read, and prints top_read with no percent when no pick exists", () => {
    expect(marketShort("player_points")).toBe("PTS");
    expect(marketShort("player_rebounds")).toBe("REB");
    expect(marketShort("player_threes")).toBe("3PM");
    const events = eventsResponseSchema.parse({
      date: nbaEvents.date,
      events: nbaEventsFixture.events.map((event, index) =>
        index === 0
          ? {
              ...event,
              commence_time_et: "2026-11-10T20:00:00-05:00",
              display_tz: "ET",
              top_read: giannisTopRead,
            }
          : event,
      ),
    });
    const games = todayGames(events.events, nbaPicks.picks, "nba", events.date);
    expect(games[0].topSource).toBe("picks");
    expect(games[0].topText).toBe("Adebayo Over 10.5 REB");
    expect(games[0].topProbabilityText).toBe("72%");
    expect(games[0].tier).toEqual({ name: "strong", label: "Strong play" });
    expect(games[0].time).toBe("8:00 PM");
    expect(games[0].href).toContain("player=Bam");
    expect(games[1].topSource).toBe("picks");
    expect(games[1].topText).toBe("Embiid Over 29.5 PTS");

    const onlyRead = todayGames(
      [
        {
          ...events.events[0],
          event_id: "no-pick",
          top_read: giannisTopRead,
        },
      ],
      [],
      "nba",
      events.date,
    );
    expect(onlyRead[0].topSource).toBe("event");
    expect(onlyRead[0].topText).toBe("Antetokounmpo Under 31.5 PTS");
    expect(onlyRead[0].topProbabilityText).toBeNull();
    expect(onlyRead[0].tier).toBeNull();
    expect(onlyRead[0].href).toContain("player=Giannis");
    expect(onlyRead[0].href).toContain("market=player_points");
    expect(onlyRead[0].href).toContain("threshold=31.5");
  });

  it("drops a top_read that does not match the contract and uses the client pick", () => {
    const events = eventsResponseSchema.parse({
      date: "2026-11-10",
      events: [{
        ...heat,
        top_read: brokenTopRead,
      }],
    });
    expect(events.events[0].top_read).toBeNull();
    const [game] = todayGames(events.events, nbaPicks.picks, "nba", "2026-11-10");
    expect(game.topSource).toBe("picks");
    expect(game.topText).toBe("Adebayo Over 10.5 REB");
    expect(game.topProbabilityText).toBe("72%");
    expect(game.tier).toEqual({ name: "strong", label: "Strong play" });
  });
});
