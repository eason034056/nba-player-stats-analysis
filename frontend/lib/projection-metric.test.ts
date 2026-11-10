import { describe, expect, it } from "vitest";

import { MARKETS } from "@/components/MarketSelect";
import {
  lineForProjectionEdge,
  marketToProjectionCard,
  type ProjectionCardKey,
} from "@/lib/projection-metric";

const MARKET_CARDS: ReadonlyArray<{
  market: (typeof MARKETS)[number]["key"];
  card: ProjectionCardKey | null;
  line: number;
}> = [
  { market: "player_points", card: "points", line: 27.5 },
  { market: "player_rebounds", card: "rebounds", line: 10.5 },
  { market: "player_assists", card: "assists", line: 8.5 },
  { market: "player_threes", card: "threes", line: 3.5 },
  { market: "player_steals", card: "steals", line: 1.5 },
  { market: "player_frees_made", card: "ftm", line: 4.5 },
  { market: "player_field_goals", card: "fgm", line: 9.5 },
  { market: "player_points_rebounds_assists", card: "pra", line: 45.5 },
  { market: "player_rebounds_assists", card: "ra", line: 18.5 },
  { market: "player_points_rebounds", card: "pr", line: 36.5 },
  { market: "player_points_assists", card: "pa", line: 32.5 },
  { market: "player_double_double", card: null, line: 0.5 },
];

describe("projection card mapping", () => {
  it("maps each market to its own card and does not draw a 0.5 edge for double-double", () => {
    expect(marketToProjectionCard("player_points")).toBe("points");
    expect(marketToProjectionCard("player_rebounds")).toBe("rebounds");
    expect(marketToProjectionCard("player_assists")).toBe("assists");
    expect(marketToProjectionCard("player_threes")).toBe("threes");
    expect(marketToProjectionCard("player_steals")).toBe("steals");
    expect(marketToProjectionCard("player_frees_made")).toBe("ftm");
    expect(marketToProjectionCard("player_field_goals")).toBe("fgm");
    expect(marketToProjectionCard("player_points_rebounds_assists")).toBe("pra");
    expect(marketToProjectionCard("player_rebounds_assists")).toBe("ra");
    expect(marketToProjectionCard("player_points_rebounds")).toBe("pr");
    expect(marketToProjectionCard("player_points_assists")).toBe("pa");
    expect(marketToProjectionCard("player_double_double")).toBeNull();
    expect(marketToProjectionCard("player_unknown")).toBeNull();

    expect(
      lineForProjectionEdge({
        market: "player_double_double",
        line: 0.5,
      }),
    ).toBeNull();
    expect(
      lineForProjectionEdge({
        market: "player_points",
        line: 0.5,
        lineIsSynthetic: true,
        marketKind: "binary",
      }),
    ).toBeNull();
    expect(
      lineForProjectionEdge({
        market: "player_threes",
        line: 2.5,
        lineIsSynthetic: false,
        marketKind: "over_under",
      }),
    ).toBe(2.5);
  });

  it("lists the same 12 market keys MarketSelect offers", () => {
    expect(MARKET_CARDS.map((row) => row.market)).toEqual(MARKETS.map((row) => row.key));
  });

  it.each(MARKET_CARDS)(
    "$market maps to its own card and a double-double line is not an edge",
    ({ market, card, line }) => {
      expect(marketToProjectionCard(market)).toBe(card);
      if (card === null) {
        expect(lineForProjectionEdge({ market, line })).toBeNull();
        expect(
          lineForProjectionEdge({
            market,
            line,
            lineIsSynthetic: true,
            marketKind: "binary",
          }),
        ).toBeNull();
        return;
      }
      expect(
        lineForProjectionEdge({
          market,
          line,
          lineIsSynthetic: false,
          marketKind: "over_under",
        }),
      ).toBe(line);
    },
  );
});
