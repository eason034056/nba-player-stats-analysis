import { describe, expect, it } from "vitest";

import { sameSideSlipRead, slipCardFace, slipTotals } from "@/lib/bet-slip-board";
import { formatPercent, formatTierPercent } from "@/lib/player-dd";
import { createBetSlipPick } from "@/test/test-utils";

describe("QA: blend slip totals floor the same way the pills do", () => {
  it("prints 69% for a 0.697 blend, not 70%", () => {
    const leg = createBetSlipPick({
      probability: 0.5897,
      ...sameSideSlipRead(
        { direction: "over", tier: "Playable", combined_probability: 0.697 },
        "over",
      ),
    });
    const totals = slipTotals([leg]);
    expect(slipCardFace(leg).probabilityText).toBe("69%");
    expect(totals.basis).toBe("blend");
    expect(totals.summary.averageText).toBe("69%");
    expect(totals.summary.allHitText).toBe("69%");
    expect(totals.summary.averageText).toBe(formatTierPercent(0.697));
    expect(totals.summary.averageText).not.toBe(formatPercent(0.697));
    expect(formatPercent(0.697)).toBe("70%");
  });

  it("floors a 0.6755 blend total to 67%, not 68%", () => {
    const leg = createBetSlipPick({
      probability: 0.5,
      ...sameSideSlipRead(
        { direction: "over", tier: "Playable", combined_probability: 0.6755 },
        "over",
      ),
    });
    const totals = slipTotals([leg]);
    expect(slipCardFace(leg).probabilityText).toBe("67%");
    expect(totals.summary.averageText).toBe("67%");
    expect(totals.summary.allHitText).toBe("67%");
    expect(totals.summary.averageText).not.toBe("68%");
    expect(formatPercent(0.6755)).toBe("68%");
  });
});
