import { describe, expect, it } from "vitest";

import { slipSummary } from "@/lib/bet-slip-board";
import { formatPercent, formatTierPercent } from "@/lib/player-dd";
import { dailyPicksResponseSchema } from "@/lib/schemas";
import nbaPicksFixture from "@/test/fixtures/picks/nba-daily-picks.json";

const stored = dailyPicksResponseSchema.parse(nbaPicksFixture).picks.map(
  (pick) => pick.probability,
);

describe("slipSummary", () => {
  it("uses the mean and the product of the stored rates", () => {
    const summary = slipSummary([0.72, 0.5]);
    expect(summary.count).toBe(2);
    expect(summary.averageText).toBe("61%");
    expect(summary.allHitText).toBe("36%");
  });

  it("renders a dash when a stored rate is not finite", () => {
    expect(slipSummary([0.72, Number.NaN])).toEqual({
      count: 2,
      averageText: "—",
      allHitText: "—",
    });
    expect(slipSummary([])).toEqual({
      count: 0,
      averageText: "—",
      allHitText: "—",
    });
    expect(slipSummary([Number.POSITIVE_INFINITY])).toEqual({
      count: 1,
      averageText: "—",
      allHitText: "—",
    });
    expect(slipSummary([Number.NEGATIVE_INFINITY])).toEqual({
      count: 1,
      averageText: "—",
      allHitText: "—",
    });
  });

  it("multiplies the fixture rates for the parlay and drops a removed leg", () => {
    const [bam, embiid, hali] = stored;
    expect(bam).toBe(0.72);
    expect(embiid).toBe(0.702);
    expect(hali).toBe(0.681);

    const full = slipSummary(stored);
    expect(full.count).toBe(3);
    expect(full.averageText).toBe("70%");
    expect(full.allHitText).toBe("34%");

    const afterRemove = slipSummary([bam, embiid]);
    expect(afterRemove).toEqual({
      count: 2,
      averageText: "71%",
      allHitText: "50%",
    });
    expect(slipSummary([bam])).toEqual({
      count: 1,
      averageText: "72%",
      allHitText: "72%",
    });
  });

  it("floors 0, 1, and 0.6755 the same way formatTierPercent does", () => {
    expect(slipSummary([0])).toEqual({
      count: 1,
      averageText: "0%",
      allHitText: "0%",
    });
    expect(slipSummary([1])).toEqual({
      count: 1,
      averageText: "100%",
      allHitText: "100%",
    });
    expect(slipSummary([0.6755]).allHitText).toBe("67%");
    expect(slipSummary([0.6755]).allHitText).toBe(formatTierPercent(0.6755));
    expect(slipSummary([0.6755]).allHitText).not.toBe(formatPercent(0.6755));
  });

  it("does not de-vig stored rates or print American odds", () => {
    // Method page example: both sides -110. Fair price is 50/50.
    // The slip multiplies whatever number was stored. It does not remove vig.
    const implied = 110 / 210;
    const summary = slipSummary([implied, implied]);
    expect(summary.allHitText).toBe("27%");
    expect(summary.averageText).toBe("52%");
    expect(summary.allHitText).not.toBe(formatPercent(0.5 * 0.5));
    expect(`${summary.averageText} ${summary.allHitText}`).not.toMatch(/[+-]\d{2,}/);
  });
});
