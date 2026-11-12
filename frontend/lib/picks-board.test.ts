import { describe, expect, it } from "vitest";

import {
  buildPickRows,
  countStrong,
  isOutPick,
  marketChipList,
  matchesConfidence,
  pickTags,
  pickTeamCode,
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

  it("does not borrow the home club when the player team is empty", () => {
    const blank = {
      ...picks[0],
      player_name: "Anfernee Simons",
      player_team: "",
      player_team_code: "",
      home_team: "Philadelphia 76ers",
      away_team: "Boston Celtics",
    };
    expect(pickTeamCode(blank, "nba")).toBe("");
    expect(buildPickRows([blank], "nba", "2026-11-10")[0]?.team).toBe("");
    expect(
      pickTeamCode(
        { ...blank, player_team: "Bulls", player_team_code: "" },
        "nba",
      ),
    ).toBe("CHI");
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

  it("omits projection, edge, minutes, injury, and lineup when those fields are null", () => {
    const blank = {
      ...board[0],
      has_projection: false,
      projected_value: null,
      projected_minutes: null,
      edge: null,
      injury_status: null,
      lineup_confirmed: null,
    };
    const text = pickTags(blank).map((tag) => tag.text).join(" ");
    expect(text).not.toMatch(/Proj|Edge|min|NaN|—|Lineup|Questionable|Out/);
  });

  it("tags the five injury words and skips Active, blank, and null", () => {
    const marked = {
      ...board[0],
      has_projection: false,
      projected_value: null,
      projected_minutes: null,
      edge: null,
      injury_status: "Questionable",
      lineup_confirmed: true as const,
    };
    const texts = (status: string | null) =>
      pickTags({ ...marked, injury_status: status }).map((tag) => tag.text);

    expect(texts("Out")).toContain("Out");
    expect(texts("out")).toContain("Out");
    expect(texts("Questionable")).toContain("Questionable");
    expect(texts("Doubtful")).toContain("Doubtful");
    expect(texts("  doubtful  ")).toContain("Doubtful");
    expect(texts("Probable")).toContain("Probable");
    expect(texts("Day-To-Day")).toContain("Day-To-Day");
    for (const status of ["Active", null, "   "]) {
      const tags = texts(status);
      expect(tags).not.toContain("Active");
      expect(tags).not.toContain("Out");
      expect(tags).not.toContain("Questionable");
    }
    expect(texts("Unknown injury")).toContain("Unknown injury");
    expect(texts("Questionable")).not.toContain("Lineup confirmed");
    expect(pickTags({ ...marked, lineup_confirmed: false }).map((tag) => tag.text)).toContain(
      "Lineup unconfirmed",
    );
  });

  it("keeps an Out pick off the strong count, the bar, and the front of the board", () => {
    const base = board[0];
    const out = {
      ...base,
      player_name: "Jimmy Butler",
      injury_status: " OUT ",
      tier: "Strong play" as const,
      combined_probability: null,
      probability: 0.95,
    };
    const questionable = {
      ...base,
      player_name: "Bam Adebayo",
      injury_status: "Questionable",
      tier: "Playable" as const,
      combined_probability: 0.74,
      probability: 0.66,
    };
    expect(isOutPick(out)).toBe(true);
    expect(isOutPick({ injury_status: "out" })).toBe(true);
    expect(isOutPick(questionable)).toBe(false);
    expect(isOutPick({ injury_status: "Doubtful" })).toBe(false);
    expect(isOutPick({ injury_status: null })).toBe(false);

    expect(countStrong([out, questionable], "nba")).toBe(1);
    expect(sortPicks([out, questionable], "nba").map((pick) => pick.player_name)).toEqual([
      "Bam Adebayo",
      "Jimmy Butler",
    ]);

    const rows = buildPickRows([out, questionable], "nba", "2026-11-10");
    expect(rows.map((row) => row.player)).toEqual(["Bam Adebayo", "Jimmy Butler"]);
    const [kept, dropped] = rows;
    expect(kept.dimmed).toBe(false);
    expect(kept.probabilityText).toBe("74%");
    expect(kept.tags.map((tag) => tag.text)).toContain("Questionable");
    expect(dropped.dimmed).toBe(true);
    expect(dropped.probabilityText).toBe("");
    expect(dropped.barPercent).toBe(0);
    expect(dropped.tierShort).toBeNull();
    expect(dropped.tierName).toBeNull();
    expect(dropped.tags.map((tag) => tag.text)).toEqual(["Out"]);
    expect(dropped.href).toContain("/event/");
  });
});
