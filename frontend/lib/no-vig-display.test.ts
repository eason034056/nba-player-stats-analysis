import { describe, expect, it } from "vitest";

import {
  lineText,
  noImpliedText,
  noPriceText,
  usesSingleLegPrior,
} from "@/lib/no-vig-display";
import { noVigResponseSchema } from "@/lib/schemas";
import legacyBody from "@/test/fixtures/props-no-vig/player-double-double.json";
import oneSidedBody from "@/test/fixtures/props-no-vig/player-double-double-one-sided.json";

const SINGLE_LEG_DIVISOR = 1.045;

function impliedAmerican(odds: number): number {
  if (odds < 0) return Math.abs(odds) / (Math.abs(odds) + 100);
  return 100 / (odds + 100);
}

function round4(value: number): number {
  return Math.round(value * 10000) / 10000;
}

function twoSided(overOdds: number, underOdds: number) {
  const pOver = impliedAmerican(overOdds);
  const pUnder = impliedAmerican(underOdds);
  const sum = pOver + pUnder;
  return {
    pOverImp: round4(pOver),
    pUnderImp: round4(pUnder),
    vig: round4(sum - 1),
    fairOver: round4(pOver / sum),
    fairUnder: round4(pUnder / sum),
    rawFairOver: pOver / sum,
    rawFairUnder: pUnder / sum,
  };
}

function singleLeg(yesOdds: number) {
  const pYes = impliedAmerican(yesOdds);
  const fair = pYes / SINGLE_LEG_DIVISOR;
  return {
    pYesImp: round4(pYes),
    legacyNoImp: round4(1 - pYes),
    vig: round4(SINGLE_LEG_DIVISOR - 1),
    fairYes: round4(fair),
    fairNo: round4(1 - fair),
    rawFairYes: fair,
    rawFairNo: 1 - fair,
  };
}

describe("recorded double-double no-vig bodies", () => {
  it("recomputes both recorded bodies from the American prices", () => {
    const dk = twoSided(-250, 200);
    const fd = singleLeg(-240);
    const legacy = noVigResponseSchema.parse(legacyBody);
    const next = noVigResponseSchema.parse(oneSidedBody);

    for (const body of [legacy, next]) {
      const draftkings = body.results.find((row) => row.bookmaker === "draftkings");
      expect(draftkings).toMatchObject({
        yes_price: -250,
        no_price: 200,
        p_yes_imp: dk.pOverImp,
        p_no_imp: dk.pUnderImp,
        vig: dk.vig,
        yes_fair_prob: dk.fairOver,
        no_fair_prob: dk.fairUnder,
      });
      expect(usesSingleLegPrior(draftkings!)).toBe(false);
      expect(noPriceText(draftkings!, true)).toBe("+200");
    }

    const legacyFanDuel = legacy.results.find((row) => row.bookmaker === "fanduel");
    expect(legacyFanDuel).toMatchObject({
      yes_price: -240,
      no_price: null,
      under_odds: -240,
      p_yes_imp: fd.pYesImp,
      p_under_imp: fd.legacyNoImp,
      p_no_imp: null,
      vig: fd.vig,
      yes_fair_prob: fd.fairYes,
      no_fair_prob: fd.fairNo,
    });
    expect(usesSingleLegPrior(legacyFanDuel!)).toBe(true);
    expect(noPriceText(legacyFanDuel!, true)).toBe("—");
    expect(noPriceText(legacyFanDuel!, true)).not.toBe("-240");
    expect(noImpliedText(legacyFanDuel!, true)).toBe("—");
    expect(lineText(legacyFanDuel!, legacy.market)).toBe("Yes/No");

    const nextFanDuel = next.results.find((row) => row.bookmaker === "fanduel");
    expect(nextFanDuel).toMatchObject({
      yes_price: -240,
      no_price: null,
      under_odds: null,
      p_under_imp: null,
      p_no_imp: null,
      line_is_synthetic: true,
      market_kind: "binary",
      p_yes_imp: fd.pYesImp,
      vig: fd.vig,
      yes_fair_prob: fd.fairYes,
      no_fair_prob: fd.fairNo,
    });
    expect(nextFanDuel?.uses_prior).toBe(true);
    expect(next.consensus?.consensus_uses_prior).toBe(true);
    expect(next.consensus?.consensus_prior_book_count).toBe(1);
    expect(usesSingleLegPrior(nextFanDuel!)).toBe(true);
    expect(noPriceText(nextFanDuel!, true)).toBe("—");
    expect(noPriceText(nextFanDuel!, true)).not.toContain("-240");
    expect(noPriceText(nextFanDuel!, true)).not.toContain("-110");
    expect(noPriceText(nextFanDuel!, true)).not.toContain("NaN");
    expect(noImpliedText(nextFanDuel!, true)).toBe("—");
    expect(lineText(nextFanDuel!, next.market)).toBe("Yes/No");

    const consensusYes = round4((dk.rawFairOver + fd.rawFairYes) / 2);
    const consensusNo = round4((dk.rawFairUnder + fd.rawFairNo) / 2);
    expect(legacy.consensus).toMatchObject({
      p_yes_fair: consensusYes,
      p_no_fair: consensusNo,
    });
    expect(next.consensus).toMatchObject({
      p_yes_fair: consensusYes,
      p_no_fair: consensusNo,
    });
  });
});
