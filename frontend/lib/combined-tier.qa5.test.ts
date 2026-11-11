import { describe, expect, it } from "vitest";

import { complementHitRateLabel, slipCardFace } from "@/lib/bet-slip-board";
import { slipFace } from "@/lib/nba-card";
import { formatTierPercent } from "@/lib/player-dd";
import { createBetSlipPick } from "@/test/test-utils";

describe("QA: float-safe floors on the reverse caption and a missing blend", () => {
  it("keeps 0.29, 0.57, 0.58 and 1 − 0.42 on the whole percent, not one below", () => {
    expect(formatTierPercent(0.29)).toBe("29%");
    expect(formatTierPercent(0.57)).toBe("57%");
    expect(formatTierPercent(0.58)).toBe("58%");
    expect(formatTierPercent(1 - 0.42)).toBe("58%");
    expect(formatTierPercent(1 - 0.29)).toBe("71%");
    expect(formatTierPercent(1 - 0.57)).toBe("43%");
    expect(Math.floor(0.29 * 100)).toBe(28);
    expect(Math.floor(0.57 * 100)).toBe(56);
    expect(Math.floor(0.58 * 100)).toBe(57);
  });

  it("floors both sides of the reverse caption, including the float-trap values", () => {
    expect(
      complementHitRateLabel({ direction: "under", probability: 0.29, rate_basis: "complement" }),
    ).toBe("Under hit rate 29% (1 − Over 71%)");
    expect(
      complementHitRateLabel({ direction: "under", probability: 0.57, rate_basis: "complement" }),
    ).toBe("Under hit rate 57% (1 − Over 43%)");
    expect(
      complementHitRateLabel({ direction: "under", probability: 0.58, rate_basis: "complement" }),
    ).toBe("Under hit rate 58% (1 − Over 42%)");
    expect(
      complementHitRateLabel({ direction: "over", probability: 0.42, rate_basis: "complement" }),
    ).toBe("Over hit rate 42% (1 − Under 58%)");
    expect(
      complementHitRateLabel({ direction: "under", probability: 0.6755, rate_basis: "complement" }),
    ).toBe("Under hit rate 67% (1 − Over 32%)");
  });

  it("prints an em dash when a slip leg has no tier and an explicit missing blend", () => {
    expect(slipFace({ probability: 0.72, combined_probability: null, tier: null })).toEqual({
      probabilityText: "—",
      tier: null,
    });
    expect(
      slipCardFace(
        createBetSlipPick({ probability: 0.72, combined_probability: null, tier: null }),
      ).probabilityText,
    ).toBe("—");
    expect(slipFace({ probability: 0.72 }).probabilityText).toBe("72%");
  });
});
