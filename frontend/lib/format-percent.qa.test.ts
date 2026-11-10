import { describe, expect, it } from "vitest";

import { formatPct, formatSignedPct } from "@/components/agent-widget/presentation";
import { formatPercent } from "@/lib/player-dd";
import { dailyPicksResponseSchema, eventsResponseSchema } from "@/lib/schemas";
import { tierFromApi, todayGames, todayReads } from "@/lib/today-board";
import { formatProbability, formatVig } from "@/lib/utils";
import nbaEventsFixture from "@/test/fixtures/today/nba-events.json";
import nbaPicksFixture from "@/test/fixtures/today/nba-daily-picks.json";
import wnbaEventsFixture from "@/test/fixtures/today/wnba-events.json";
import wnbaPicksFixture from "@/test/fixtures/today/wnba-daily-picks.json";

/**
 * Whole-percent display edge cases (SPO-120a).
 * A missing or non-finite value is an em dash. A real zero is 0%.
 */
describe("formatPercent edge cases", () => {
  it.each([
    [null, "—"],
    [undefined, "—"],
    [Number.NaN, "—"],
    [Number.POSITIVE_INFINITY, "—"],
    [Number.NEGATIVE_INFINITY, "—"],
  ])("renders %s as an em dash", (value, expected) => {
    expect(formatPercent(value as number | null | undefined)).toBe(expected);
  });

  it("does not coerce a numeric string", () => {
    expect(formatPercent("0.5" as unknown as number)).toBe("—");
  });

  it.each([
    [0, "0%"],
    [-0, "0%"],
    [0.0049, "0%"],
    [0.005, "1%"],
    [0.125, "13%"],
    [0.5, "50%"],
    [0.6755, "68%"],
    [0.6949, "69%"],
    [0.695, "70%"],
    [0.9949, "99%"],
    [0.995, "100%"],
    [1, "100%"],
  ])("rounds %s half away from zero to %s", (value, expected) => {
    expect(formatPercent(value)).toBe(expected);
  });

  it("never prints a negative zero", () => {
    expect(formatPercent(-0.004)).toBe("0%");
    expect(formatPercent(-0.0049)).toBe("0%");
    expect(formatPercent(-0.005)).toBe("-1%");
    expect(formatPercent(-0.03)).toBe("-3%");
  });

  it("scales a fraction once and does not clamp out-of-range input", () => {
    expect(formatPercent(0.72)).toBe("72%");
    expect(formatPercent(1.5)).toBe("150%");
  });
});

describe("formatVig and formatProbability", () => {
  it("prints a dash for missing or non-finite vig", () => {
    expect(formatVig(Number.NaN)).toBe("—");
    expect(formatVig(Number.POSITIVE_INFINITY)).toBe("—");
  });

  it("matches formatPercent for missing and real values", () => {
    expect(formatProbability(null)).toBe("—");
    expect(formatProbability(undefined)).toBe("—");
    expect(formatProbability(0)).toBe("0%");
    expect(formatProbability(0.5238)).toBe("52%");
    expect(formatProbability(0.6755)).toBe(formatPercent(0.6755));
  });
});

describe("agent widget percent helpers", () => {
  it("keeps N/A for missing and non-finite values", () => {
    for (const value of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
      expect(formatPct(value as number | null | undefined)).toBe("N/A");
      expect(formatSignedPct(value as number | null | undefined)).toBe("N/A");
    }
  });
});

describe("Today keeps the backend tier next to the whole percent", () => {
  const nbaPicks = dailyPicksResponseSchema.parse(nbaPicksFixture);
  const wnbaPicks = dailyPicksResponseSchema.parse(wnbaPicksFixture);

  it("prints every fixture tier exactly as the API sent it, NBA and WNBA", () => {
    for (const [picks, league] of [
      [nbaPicks, "nba"],
      [wnbaPicks, "wnba"],
    ] as const) {
      const reads = todayReads(picks.picks, league, picks.date, picks.picks.length);
      for (const read of reads) {
        const source = picks.picks.find((pick) => read.key.startsWith(`${pick.event_id}-${pick.player_name}-`));
        expect(source).toBeDefined();
        expect(read.tier).toEqual(tierFromApi(source?.tier));
        expect(read.probabilityText).toBe(formatPercent(source?.probability));
        expect(read.href.startsWith(league === "wnba" ? "/wnba/" : "/")).toBe(true);
      }
    }
  });

  it("builds WNBA game cards from the WNBA fixtures without an ET clock", () => {
    const events = eventsResponseSchema.parse(wnbaEventsFixture);
    const games = todayGames(events.events, wnbaPicks.picks, "wnba", events.date);
    expect(games.length).toBe(events.events.length);
    for (const game of games) {
      expect(game.href.startsWith("/wnba/")).toBe(true);
      expect(game.topSource).not.toBe("event");
    }
  });

  it("parses the NBA events fixture without inventing top_read or lineup_status", () => {
    const events = eventsResponseSchema.parse(nbaEventsFixture);
    for (const event of events.events) {
      expect(event.top_read ?? null).toBeNull();
      expect(event.lineup_status ?? null).toBeNull();
    }
  });
});
