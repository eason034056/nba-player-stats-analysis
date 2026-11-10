import { describe, expect, it } from "vitest";

import {
  lineForProjectionEdge,
  marketToProjectionCard,
} from "@/lib/projection-metric";

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
});
