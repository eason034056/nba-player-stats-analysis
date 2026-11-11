import { describe, expect, it } from "vitest";

import { slipCardFace, slipSummary, slipTotals } from "@/lib/bet-slip-board";
import { formatPercent, formatTierPercent } from "@/lib/player-dd";
import { createBetSlipPick } from "@/test/test-utils";

describe("QA: every number on the slip card floors the same way", () => {
  it("floors a stored 0.6755 older-leg pill and totals to 67%, not 68%", () => {
    const leg = createBetSlipPick({ probability: 0.6755 });
    const face = slipCardFace(leg);
    const totals = slipTotals([leg]);
    expect(totals.basis).toBe("stored");
    expect(face.probabilityText).toBe("67%");
    expect(face.tier).toBeNull();
    expect(totals.summary.averageText).toBe("67%");
    expect(totals.summary.allHitText).toBe("67%");
    expect(face.probabilityText).toBe(formatTierPercent(0.6755));
    expect(face.probabilityText).not.toBe(formatPercent(0.6755));
    expect(formatPercent(0.6755)).toBe("68%");
    expect(slipSummary([0.6755]).averageText).toBe("67%");
  });

  it("floors a 0.697 blend with no tier to 69% on the pill and the totals, not 70%", () => {
    const leg = createBetSlipPick({
      probability: 0.5897,
      combined_probability: 0.697,
      tier: null,
    });
    const face = slipCardFace(leg);
    const totals = slipTotals([leg]);
    expect(totals.basis).toBe("blend");
    expect(face.probabilityText).toBe("69%");
    expect(face.tier).toBeNull();
    expect(totals.summary.averageText).toBe("69%");
    expect(totals.summary.allHitText).toBe("69%");
    expect(face.probabilityText).toBe(formatTierPercent(0.697));
    expect(face.probabilityText).not.toBe(formatPercent(0.697));
    expect(formatPercent(0.697)).toBe("70%");
  });
});
