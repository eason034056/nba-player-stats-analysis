// @vitest-environment node
import { describe, expect, it } from "vitest";

import { gameLogTiles } from "@/lib/event-page";

describe("gameLogTiles", () => {
  it("prints the rates with the counts they came from and the average against the line", () => {
    const tiles = gameLogTiles({ n_games: 10, p_over: 0.7, p_under: 0.3, mean: 20.1 }, 18.5);

    expect(tiles).toEqual([
      { key: "over", label: "Over 18.5", value: "70%", sub: "7 of 10 games" },
      { key: "under", label: "Under 18.5", value: "30%", sub: "3 of 10 games" },
      { key: "average", label: "Average", value: "20.1", sub: "+1.6 vs line" },
      { key: "games", label: "Games", value: "10", sub: null },
    ]);
  });

  it("signs a below-line average and keeps a push out of both counts", () => {
    const tiles = gameLogTiles({ n_games: 5, p_over: 0.4, p_under: 0.4, mean: 17.9 }, 18);

    expect(tiles.map((tile) => tile.sub)).toEqual(["2 of 5 games", "2 of 5 games", "-0.1 vs line", null]);
  });

  it("prints dashes and no subline when the history has no rates or average", () => {
    const tiles = gameLogTiles({ n_games: 0, p_over: null, p_under: undefined, mean: null }, null);

    expect(tiles.map((tile) => [tile.label, tile.value, tile.sub])).toEqual([
      ["Over", "—", null],
      ["Under", "—", null],
      ["Average", "—", null],
      ["Games", "0", null],
    ]);
  });
});
