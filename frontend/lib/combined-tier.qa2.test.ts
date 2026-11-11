import { describe, expect, it } from "vitest";

import { sameSideSlipRead, slipTotals } from "@/lib/bet-slip-board";
import { eventPlayerRows } from "@/lib/event-page";
import { formatPercent, formatTierPercent } from "@/lib/player-dd";
import { dailyPickSchema } from "@/lib/schemas";
import { createBetSlipPick } from "@/test/test-utils";
import qa from "@/test/fixtures/spo-121b/qa-review.json";

const wnba = dailyPickSchema.parse(qa.wnba);
const validPick = dailyPickSchema.parse(qa.movedLine.pick);

describe("QA: slip totals use the side-correct blend on under legs", () => {
  it("averages each same-side under blend, not the historical rate or 1 minus the blend", () => {
    const under = createBetSlipPick({
      id: "under-points",
      player_name: "Under Player",
      direction: "under",
      probability: 0.55,
      ...sameSideSlipRead(
        { direction: "under", tier: "Strong play", combined_probability: 0.71 },
        "under",
      ),
    });
    const over = createBetSlipPick({
      direction: "over",
      probability: 0.59,
      ...sameSideSlipRead(
        { direction: "over", tier: "Playable", combined_probability: 0.66 },
        "over",
      ),
    });
    const totals = slipTotals([under, over]);
    expect(totals.basis).toBe("blend");
    expect(totals.averageLabel).toBe("avg. blend");
    expect(totals.allHitLabel).toBe("all hit");
    expect(totals.summary.averageText).toBe(formatTierPercent((0.71 + 0.66) / 2));
    expect(totals.summary.allHitText).toBe(formatTierPercent(0.71 * 0.66));
    expect(totals.summary.averageText).not.toBe(formatPercent((0.55 + 0.59) / 2));
    expect(totals.summary.averageText).not.toBe(formatPercent((1 - 0.71 + 0.66) / 2));
  });

  it("labels a mixed slip History and uses the historical rate on the under leg too", () => {
    const under = createBetSlipPick({
      id: "under-points",
      player_name: "Under Player",
      direction: "under",
      probability: 0.55,
      ...sameSideSlipRead(
        { direction: "under", tier: "Strong play", combined_probability: 0.71 },
        "under",
      ),
    });
    const plain = createBetSlipPick({
      id: "plain-points",
      player_name: "Plain Player",
      direction: "over",
      probability: 0.4,
    });
    const mixed = slipTotals([under, plain]);
    expect(mixed.basis).toBe("history");
    expect(mixed.averageLabel).toBe("History");
    expect(mixed.allHitLabel).toBe("History");
    expect(mixed.summary.averageText).toBe(formatTierPercent((0.55 + 0.4) / 2));
    expect(mixed.summary.averageText).not.toBe(formatPercent((0.71 + 0.4) / 2));
  });
});

describe("QA: WNBA game page ignores NBA reads status", () => {
  it("keeps the historical lean and never prints Loading or Unavailable", () => {
    const rows = eventPlayerRows({
      suggested: ["Bench Player"],
      picks: [wnba],
      metric: "player_points",
      eventId: wnba.event_id,
      selectedName: wnba.player_name,
      postedLine: null,
      awayLineup: null,
      homeLineup: null,
      awayAbbr: "NYL",
      homeAbbr: "LVA",
      league: "wnba",
      reads: [
        {
          player: wnba.player_name,
          market: "player_points",
          line: 99.5,
          side: "under",
          combined_probability: 0.9,
          tier: "Strong play",
        },
      ],
      readsStatus: "loading",
    });
    const posted = rows.find((row) => row.name === wnba.player_name);
    const bench = rows.find((row) => row.name === "Bench Player");
    expect(posted?.lineText).toBe("12.5");
    expect(posted?.leanText).toBe(`O ${formatPercent(0.697)}`);
    expect(posted?.leanText).not.toContain("Loading");
    expect(bench?.leanText).toBe("No read");

    const failed = eventPlayerRows({
      suggested: ["Bench Player"],
      picks: [],
      metric: "player_points",
      eventId: wnba.event_id,
      selectedName: "",
      postedLine: null,
      awayLineup: null,
      homeLineup: null,
      awayAbbr: "NYL",
      homeAbbr: "LVA",
      league: "wnba",
      readsStatus: "error",
    }).find((row) => row.name === "Bench Player");
    expect(failed?.leanText).toBe("No read");
    expect(failed?.leanText).not.toContain("Unavailable");
  });
});

describe("QA: catch(null) only softens new optional fields", () => {
  it("keeps a valid tier and blend, and still rejects a bad required probability", () => {
    expect(validPick.tier).toBe("Playable");
    expect(validPick.combined_probability).toBe(0.68);
    expect(validPick.probability).toBe(0.66);
    expect(() => dailyPickSchema.parse({ ...qa.movedLine.pick, probability: "bad" })).toThrow();
  });
});
