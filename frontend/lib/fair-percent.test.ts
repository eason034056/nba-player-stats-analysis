import { describe, expect, it } from "vitest";

import { fairNoValue, fairYesValue, noImpliedText, noPriceText } from "@/lib/no-vig-display";
import { formatPercent, roundHalfAwayFromZero } from "@/lib/player-dd";
import type { BookmakerResult } from "@/lib/schemas";

/**
 * Shared half-away rounding. ResultsTable fair cells and the DD tile both
 * call formatPercent, so these cases are the agreement oracle.
 * Number#toFixed(1) on 0.6755 * 100 is "67.5" because the product is
 * 67.549999999999997. Half-away must print 67.6%.
 */
describe("roundHalfAwayFromZero", () => {
  it.each([
    [1.005, 2, 1.01],
    [-1.005, 2, -1.01],
    [10.055, 2, 10.06],
    [0, 2, 0],
    [1, 2, 1],
    [-1, 2, -1],
    [0.5, 0, 1],
    [-0.5, 0, -1],
    [67.55, 1, 67.6],
    [67.44, 1, 67.4],
    [67.45, 1, 67.5],
    [99.95, 1, 100],
    [0, 1, 0],
    [1, 1, 1],
  ])("rounds %s to %s digits as %s", (value, digits, expected) => {
    expect(roundHalfAwayFromZero(value, digits)).toBe(expected);
  });
});

describe("formatPercent", () => {
  it.each([
    [0.6755, "67.6%"],
    [0.6745, "67.5%"],
    [0.1005, "10.1%"],
    [0.1004, "10.0%"],
    [0.1006, "10.1%"],
    [0.1245, "12.5%"],
    [0.1255, "12.6%"],
    [0.005, "0.5%"],
    [0.0055, "0.6%"],
    [0.0145, "1.5%"],
    [0.015, "1.5%"],
    [0.3245, "32.5%"],
    [0.3255, "32.6%"],
    [0.995, "99.5%"],
    [0.9995, "100.0%"],
    [0, "0.0%"],
    [1, "100.0%"],
    [1.005, "100.5%"],
    [-0.6755, "-67.6%"],
    [-0.6745, "-67.5%"],
    [-1.005, "-100.5%"],
  ])("formats %s as %s", (probability, expected) => {
    expect(formatPercent(probability)).toBe(expected);
  });

  it("leaves a null fair value to the caller instead of printing a percent", () => {
    const row = {
      bookmaker: "fanduel",
      line: 0.5,
      vig: 0.045,
      p_over_fair: null,
      p_under_fair: null,
      yes_fair_prob: null,
      no_fair_prob: null,
      under_odds: null,
      no_price: null,
      p_under_imp: null,
      p_no_imp: null,
      yes_price: -240,
      uses_prior: true,
      line_is_synthetic: true,
      market_kind: "binary",
    } as unknown as BookmakerResult;

    expect(fairYesValue(row)).toBeNull();
    expect(fairNoValue(row)).toBeNull();
    expect(noPriceText(row, true)).toBe("—");
    expect(noImpliedText(row, true)).toBe("—");
    expect(noPriceText(row, true)).not.toContain("-240");
    expect(noPriceText(row, true)).not.toContain("-110");
    expect(noPriceText(row, true)).not.toContain("NaN");
  });
});
