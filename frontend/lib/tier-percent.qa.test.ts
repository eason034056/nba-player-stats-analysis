import { describe, expect, it } from "vitest";

import { formatSignedPct } from "@/components/agent-widget/presentation";
import { formatPercent, formatTierPercent } from "@/lib/player-dd";
import { dailyPicksResponseSchema, eventsResponseSchema } from "@/lib/schemas";
import { readTier, todayGames } from "@/lib/today-board";
import { formatVig } from "@/lib/utils";
import nbaEventsFixture from "@/test/fixtures/today/nba-events.json";
import nbaPicksFixture from "@/test/fixtures/today/nba-daily-picks.json";

const nbaEvents = eventsResponseSchema.parse(nbaEventsFixture);
const nbaPicks = dailyPicksResponseSchema.parse(nbaPicksFixture);

// Same cutoffs as backend read_tier (daily_analysis.py READ_TIER_CUTOFFS).
const BAND: Record<string, [number, number]> = {
  strong: [70, 100],
  playable: [65, 69],
  lean: [56, 64],
};

const shown = (text: string | null) => Number(text?.replace("%", ""));

describe("formatTierPercent stays inside the tier it sits next to", () => {
  it("never prints the next cutoff for any 4-decimal probability", () => {
    const outside: string[] = [];
    for (let i = 5600; i <= 10000; i += 1) {
      const p = Number((i / 10000).toFixed(4));
      const tier = readTier(p);
      if (!tier || tier.name === "pass") continue;
      const [low, high] = BAND[tier.name];
      const value = shown(formatTierPercent(p));
      if (value < low || value > high) outside.push(`${p} ${tier.label} ${value}%`);
    }
    expect(outside).toEqual([]);
  });

  it("floors every hit rate k/n exactly, despite float error", () => {
    const wrong: string[] = [];
    for (let n = 1; n <= 200; n += 1) {
      for (let k = 0; k <= n; k += 1) {
        const exact = (100 * k - ((100 * k) % n)) / n;
        if (formatTierPercent(k / n) !== `${exact}%`) wrong.push(`${k}/${n}`);
      }
    }
    expect(wrong).toEqual([]);
  });

  it("keeps float-short products on the right whole number", () => {
    expect(0.57 * 100).toBeLessThan(57);
    expect(formatTierPercent(0.57)).toBe("57%");
    expect(formatTierPercent(0.29)).toBe("29%");
    expect(formatTierPercent(0.58)).toBe("58%");
    expect(formatTierPercent(0.7)).toBe("70%");
    expect(formatTierPercent(0.69999)).toBe("69%");
    expect(formatTierPercent(0.64999)).toBe("64%");
    expect(formatTierPercent(0.55999)).toBe("55%");
  });
});

describe("Today game cards use the floor only when a tier is shown", () => {
  it("floors the fallback daily pick when it carries a tier", () => {
    const picks = nbaPicks.picks.map((pick) =>
      pick.player_name === "Bam Adebayo" ? { ...pick, probability: 0.697, tier: "Playable" as const } : pick,
    );
    const [game] = todayGames(nbaEvents.events, picks, "nba", nbaEvents.date);
    expect(game.topSource).toBe("picks");
    expect(game.tier?.name).toBe("playable");
    expect(game.topProbabilityText).toBe("69%");
    expect(game.topProbabilityText).not.toBe("70%");
  });

  it("floors a top_read that borrows a matching pick's tier, and rounds one without a tier", () => {
    const embiid = nbaPicks.picks.find((pick) => pick.player_name === "Joel Embiid");
    expect(embiid).toBeDefined();
    const picks = nbaPicks.picks.map((pick) =>
      pick.player_name === "Joel Embiid" ? { ...pick, probability: 0.697, tier: "Playable" as const } : pick,
    );
    const topRead = {
      player: embiid!.player_name,
      market: "player_points",
      side: embiid!.direction as "over" | "under",
      line: embiid!.threshold,
      probability: 0.697,
    };
    const events = eventsResponseSchema.parse({
      date: nbaEvents.date,
      events: nbaEventsFixture.events.map((event) =>
        event.event_id === embiid!.event_id ? { ...event, top_read: topRead } : event,
      ),
    });
    const matched = todayGames(events.events, picks, "nba", events.date).find(
      (game) => game.topSource === "event",
    );
    expect(matched?.tier?.label).toBe("Playable");
    expect(matched?.topProbabilityText).toBe("69%");

    const unmatchedEvents = eventsResponseSchema.parse({
      date: nbaEvents.date,
      events: nbaEventsFixture.events.map((event) =>
        event.event_id === embiid!.event_id ? { ...event, top_read: { ...topRead, line: 99.5 } } : event,
      ),
    });
    const unmatched = todayGames(unmatchedEvents.events, picks, "nba", unmatchedEvents.date).find(
      (game) => game.topSource === "event",
    );
    expect(unmatched?.tier).toBeNull();
    expect(unmatched?.topProbabilityText).toBe(formatPercent(0.697));
    expect(unmatched?.topProbabilityText).toBe("70%");
  });
});

describe("one-decimal vig and signed edges at the edges", () => {
  it("does not print a negative zero", () => {
    expect(formatSignedPct(-0.0004)).toBe("0.0%");
    expect(formatSignedPct(-0)).toBe("0.0%");
    expect(formatSignedPct(0.0004)).toBe("0.0%");
    expect(formatVig(-0.0004)).toBe("0.0%");
    expect(formatVig(-0)).toBe("0.0%");
  });

  it("rounds x.x5 half away from zero, with the sign", () => {
    expect(formatSignedPct(-0.0005)).toBe("-0.1%");
    expect(formatSignedPct(0.0005)).toBe("+0.1%");
    expect(formatSignedPct(0.0215)).toBe("+2.2%");
    expect(formatSignedPct(-0.0215)).toBe("-2.2%");
    expect(formatVig(0.0455)).toBe("4.6%");
    expect(formatVig(0.0445)).toBe("4.5%");
    expect(formatVig(0.0615)).toBe("6.2%");
    expect(formatVig(0.1005)).toBe("10.1%");
  });

  it("keeps a negative vig negative", () => {
    expect(formatVig(-0.01)).toBe("-1.0%");
    expect(formatVig(-0.0215)).toBe("-2.2%");
  });

  it("prints signed edges as N/A when missing", () => {
    expect(formatSignedPct(null)).toBe("N/A");
    expect(formatSignedPct(Number.NaN)).toBe("N/A");
  });
});
