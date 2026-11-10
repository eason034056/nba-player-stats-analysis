import { describe, expect, it } from "vitest";

import {
  buildPickRows,
  countStrong,
  marketChipList,
  matchesConfidence,
  pickTags,
  sortPicks,
} from "@/lib/picks-board";
import { dailyPicksResponseSchema } from "@/lib/schemas";
import boardFixture from "@/test/fixtures/picks/nba-daily-picks-board.json";
import nbaPicksFixture from "@/test/fixtures/picks/nba-daily-picks.json";

const picks = dailyPicksResponseSchema.parse(nbaPicksFixture).picks;
const board = dailyPicksResponseSchema.parse(boardFixture).picks;

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
    expect(rows[0].probabilityText).toBe("—");
    expect(rows[2].tierShort).toBeNull();
    expect(rows[0].href).toContain("/event/evt-mia-bos?");
    expect(rows[0].href).toContain("player=Bam+Adebayo");
  });
});

describe("picks board sort, filter, and market grouping", () => {
  it("sorts an unsorted fixture by hit rate and keeps equal rates in input order", () => {
    const names = board.map((pick) => pick.player_name);
    const sorted = sortPicks(board, "nba");

    expect(board.map((pick) => pick.player_name)).toEqual(names);
    expect(sorted.map((pick) => pick.player_name)).toEqual([
      "Bam Adebayo",
      "Joel Embiid",
      "Jalen Brunson",
      "Tyrese Haliburton",
      "Herb Jones",
      "Jrue Holiday",
      "Myles Turner",
      "Pascal Siakam",
    ]);

    const broken = { ...board[0], probability: Number.NaN };
    const withGap = sortPicks([broken, ...board], "nba");
    expect(withGap.at(-1)?.probability).toBeNaN();
    expect(withGap[0]?.player_name).toBe("Bam Adebayo");
  });

  it("filters strong and playable on the 65% and 70% boundaries", () => {
    const names = (filter: "all" | "strong" | "playable") =>
      board
        .filter((pick) => matchesConfidence(pick.probability, filter))
        .map((pick) => pick.player_name);

    expect(names("strong")).toEqual([
      "Bam Adebayo",
      "Jalen Brunson",
      "Joel Embiid",
    ]);
    expect(names("playable")).toEqual([
      "Tyrese Haliburton",
      "Herb Jones",
      "Jrue Holiday",
      "Myles Turner",
    ]);
    expect(names("all")).toContain("Pascal Siakam");
    expect(matchesConfidence(0.7, "strong")).toBe(true);
    expect(matchesConfidence(0.7, "playable")).toBe(false);
    expect(matchesConfidence(0.65, "playable")).toBe(true);
    expect(matchesConfidence(0.649, "playable")).toBe(false);
    expect(matchesConfidence(Number.NaN, "strong")).toBe(false);
    expect(matchesConfidence(Number.POSITIVE_INFINITY, "playable")).toBe(false);
    expect(matchesConfidence(Number.NaN, "all")).toBe(true);
    expect(countStrong(board, "nba")).toBe(3);
  });

  it("groups prototype market chips before extra markets, including chips with no rows", () => {
    expect(marketChipList(board)).toEqual([
      "ALL",
      "PTS",
      "REB",
      "AST",
      "3PM",
      "PRA",
      "FTM",
      "STL",
    ]);
  });

  it("uses overall rank when position rank is missing and quotes a negative edge", () => {
    const hali = board.find((pick) => pick.player_name === "Tyrese Haliburton");
    const herb = board.find((pick) => pick.player_name === "Herb Jones");
    const siakam = board.find((pick) => pick.player_name === "Pascal Siakam");
    expect(hali).toBeDefined();
    expect(herb).toBeDefined();
    expect(siakam).toBeDefined();
    if (!hali || !herb || !siakam) return;

    expect(pickTags(hali).map((tag) => tag.text)).toContain("Def #14");
    expect(pickTags(herb).map((tag) => tag.text)).toContain("Edge -0.1");
    expect(pickTags(siakam).map((tag) => tag.text).join(" ")).not.toMatch(/games/);

    const rows = buildPickRows(board, "nba", "2026-11-10");
    expect(rows.map((row) => row.player)[0]).toBe("Bam Adebayo");
    expect(rows[0]?.rank).toBe("01");
    expect(rows.find((row) => row.player === "Jrue Holiday")?.propText).toBe(
      "Under 2.5 free throws",
    );
  });
});
