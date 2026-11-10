import { describe, expect, it } from "vitest";

import {
  formatPercent,
  selectDDOdds,
  staleLineWarning,
} from "@/lib/player-dd";
import { noVigResponseSchema, type NoVigResponse } from "@/lib/schemas";
import recordedNoVig from "@/test/fixtures/props-no-vig/player-double-double.json";

function parseOdds(overrides: Partial<NoVigResponse> = {}): NoVigResponse {
  return noVigResponseSchema.parse({ ...recordedNoVig, ...overrides });
}

describe("formatPercent", () => {
  it("rounds half away from zero, including the recorded 0.6755 fair probability", () => {
    expect(formatPercent(0)).toBe("0.0%");
    expect(formatPercent(1)).toBe("100.0%");
    expect(formatPercent(0.99995)).toBe("100.0%");
    expect(formatPercent(0.6755)).toBe("67.6%");
    expect(formatPercent(0.6745)).toBe("67.5%");
    expect(formatPercent(0.6744)).toBe("67.4%");
    expect(formatPercent(-0.6755)).toBe("-67.6%");
    expect(formatPercent(-0)).toBe("0.0%");
  });

  it("returns an em dash for null instead of 0.0%", () => {
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(undefined)).toBe("—");
    expect(formatPercent(null)).not.toBe("0.0%");
  });

  it("does not throw or invent 0% when the input is not finite", () => {
    expect(formatPercent(Number.NaN)).toBe("NaN%");
    expect(formatPercent(Number.POSITIVE_INFINITY)).toBe("Infinity%");
    expect(formatPercent(Number.NEGATIVE_INFINITY)).toBe("-Infinity%");
  });
});

describe("stale line metadata", () => {
  it("keeps fetched_at, data_age_seconds, cache_state, and source from the recorded snapshot", () => {
    const parsed = parseOdds();

    expect(parsed.fetched_at).toBe("2026-05-08T12:00:00Z");
    expect(parsed.data_age_seconds).toBe(12);
    expect(parsed.cache_state).toBe("fresh");
    expect(parsed.source).toBe("snapshot_cache");

    const selection = selectDDOdds(parsed);
    expect(selection.status).toBe("ready");
    expect(staleLineWarning(selection)).toBeNull();
  });

  it("stays quiet at 30 seconds and warns at 31 while the recorded prices remain", () => {
    const atBudget = selectDDOdds(
      parseOdds({ data_age_seconds: 30, cache_state: "fresh" }),
    );
    const pastBudget = selectDDOdds(
      parseOdds({ data_age_seconds: 31, cache_state: "fresh" }),
    );

    expect(atBudget.status).toBe("ready");
    expect(pastBudget.status).toBe("ready");
    if (atBudget.status !== "ready" || pastBudget.status !== "ready") {
      return;
    }

    expect(staleLineWarning(atBudget)).toBeNull();
    expect(staleLineWarning(pastBudget)).toContain("31 seconds");
    expect(atBudget.books[0]?.yesPrice).toBe(-250);
    expect(pastBudget.books[0]?.yesPrice).toBe(-250);
  });

  it("does not treat a null age or a missing cache state as stale", () => {
    const nulled = selectDDOdds(
      parseOdds({ data_age_seconds: null, cache_state: null }),
    );
    expect(nulled.status).toBe("ready");
    if (nulled.status === "ready") {
      expect(nulled.dataAgeSeconds).toBeNull();
      expect(nulled.cacheState).toBeNull();
      expect(nulled.books[0]?.yesPrice).toBe(-250);
    }
    expect(staleLineWarning(nulled)).toBeNull();

    const { cache_state: _cacheState, data_age_seconds: _age, ...withoutMeta } =
      recordedNoVig;
    const missing = selectDDOdds(noVigResponseSchema.parse(withoutMeta));
    expect(missing.status).toBe("ready");
    if (missing.status === "ready") {
      expect(missing.dataAgeSeconds).toBeNull();
      expect(missing.cacheState).toBeNull();
    }
    expect(staleLineWarning(missing)).toBeNull();
  });

  it("warns on cache_state stale even when the age is null, without a seconds count", () => {
    const selection = selectDDOdds(
      parseOdds({ data_age_seconds: null, cache_state: "stale" }),
    );

    expect(selection.status).toBe("ready");
    const warning = staleLineWarning(selection);
    expect(warning).toContain("Stale line");
    expect(warning).not.toContain("seconds old");
    if (selection.status === "ready") {
      expect(selection.books[0]?.yesPrice).toBe(-250);
    }
  });
});
