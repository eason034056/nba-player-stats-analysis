import { describe, expect, it } from "vitest";

import { tierFromBackend } from "@/lib/nba-card";
import { buildPickRows } from "@/lib/picks-board";
import { dailyPickSchema, type DailyPick } from "@/lib/schemas";
import { todayReads } from "@/lib/today-board";
import combinedFixture from "@/test/fixtures/spo-121b/combined-tier.json";

const known = dailyPickSchema.parse(combinedFixture.alexanderWalker);

function withTier(tier: string, combined: number | null): DailyPick {
  return { ...known, tier, combined_probability: combined } as DailyPick;
}

describe("unknown tier strings stay off the NBA cards", () => {
  it("accepts only the backend tier values", () => {
    expect(tierFromBackend("Strong play")?.label).toBe("Strong play");
    expect(tierFromBackend("Playable")?.label).toBe("Playable");
    expect(tierFromBackend("Lean")?.label).toBe("Lean");
    expect(tierFromBackend("Elite lock")).toBeNull();
    expect(tierFromBackend("Pass")).toBeNull();
    expect(tierFromBackend("strong")).toBeNull();
  });

  it("does not print a planted tier on Today or the picks board", () => {
    const planted = withTier("Elite lock", 0.673);
    const [today] = todayReads([planted], "nba", "2026-11-10");
    const [row] = buildPickRows([planted], "nba", "2026-11-10");

    expect(today.tier).toBeNull();
    expect(row.tierShort).toBeNull();
    expect(row.tierName).toBeNull();
    expect(JSON.stringify(today)).not.toContain("Elite lock");
    expect(JSON.stringify(row)).not.toContain("Elite lock");

    const bare = withTier("Not a tier", null);
    expect(todayReads([bare], "nba", "2026-11-10")[0]?.probabilityText).toBe("—");
    expect(todayReads([bare], "nba", "2026-11-10")[0]?.tier).toBeNull();
    expect(buildPickRows([bare], "nba", "2026-11-10")[0]?.probabilityText).toBe("—");
  });
});
