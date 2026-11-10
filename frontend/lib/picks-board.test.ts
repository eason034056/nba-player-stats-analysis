import { describe, expect, it } from "vitest";

import { buildPickRows, pickTags } from "@/lib/picks-board";
import { dailyPicksResponseSchema } from "@/lib/schemas";
import nbaPicksFixture from "@/test/fixtures/picks/nba-daily-picks.json";

const picks = dailyPicksResponseSchema.parse(nbaPicksFixture).picks;

describe("picks board view model", () => {
  it("quotes stored projection and rank fields and skips missing ones", () => {
    const [bam, embiid] = picks;
    expect(pickTags(bam).map((tag) => tag.text)).toEqual([
      "40 games",
      "Proj 20.4",
      "Edge +1.9",
      "34 min",
      "Def #9",
    ]);
    expect(pickTags(embiid).map((tag) => tag.text)).toEqual(["18 games"]);
    expect(pickTags(embiid).map((tag) => tag.text).join(" ")).not.toMatch(/L10|Supports|Against/);
  });

  it("renders a non-finite hit rate as a dash", () => {
    const broken = { ...picks[0], probability: Number.NaN };
    const [row] = buildPickRows([broken], "nba", "2026-11-10");
    expect(row.probabilityText).toBe("—");
    expect(row.tierShort).toBeNull();
  });

  it("ranks the fixture by historical hit rate", () => {
    const rows = buildPickRows(picks, "nba", "2026-11-10");
    expect(rows.map((row) => row.player)).toEqual([
      "Bam Adebayo",
      "Joel Embiid",
      "Tyrese Haliburton",
    ]);
    expect(rows[0].probabilityText).toBe("72.0%");
    expect(rows[2].tierShort).toBe("Playable");
    expect(rows[0].href).toContain("/event/evt-mia-bos?");
    expect(rows[0].href).toContain("player=Bam+Adebayo");
  });
});
