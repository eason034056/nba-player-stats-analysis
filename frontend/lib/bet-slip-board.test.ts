import { describe, expect, it } from "vitest";

import { slipSummary } from "@/lib/bet-slip-board";

describe("slipSummary", () => {
  it("uses the mean and the product of the stored rates", () => {
    const summary = slipSummary([0.72, 0.5]);
    expect(summary.count).toBe(2);
    expect(summary.averageText).toBe("61.0%");
    expect(summary.allHitText).toBe("36.0%");
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
  });
});
