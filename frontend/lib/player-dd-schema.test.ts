import { describe, expect, it } from "vitest";

import { selectDDHistory, selectDDOdds } from "@/lib/player-dd";
import {
  noVigResponseSchema,
  playerDDHistoryResponseSchema,
} from "@/lib/schemas";

describe("player DD response schemas", () => {
  it("parses the player-dd-history body, including a null rate", () => {
    const populated = playerDDHistoryResponseSchema.parse({
      player: "Nikola Jokic",
      season: null,
      n_games: 75,
      dd_games: 61,
      prob_dd: 0.8133,
      message: null,
    });
    expect(populated.prob_dd).toBe(0.8133);
    expect(populated.dd_games).toBe(61);

    const empty = playerDDHistoryResponseSchema.parse({
      player: "Nobody",
      season: null,
      n_games: 0,
      dd_games: 0,
      prob_dd: null,
      message: "Player 'Nobody' not found",
    });
    expect(empty.prob_dd).toBeNull();
    expect(selectDDHistory(empty).status).toBe("empty");
  });

  it("keeps yes/no mirrors and does not require them on Over/Under rows", () => {
    const binary = noVigResponseSchema.parse({
      event_id: "evt-1",
      player_name: "Nikola Jokic",
      market: "player_double_double",
      results: [
        {
          bookmaker: "draftkings",
          line: 0.5,
          over_odds: -250,
          under_odds: 200,
          p_over_imp: 0.7143,
          p_under_imp: 0.3333,
          vig: 0.0476,
          p_over_fair: 0.6818,
          p_under_fair: 0.3182,
          fetched_at: "2026-05-08T12:00:00Z",
          yes_price: -250,
          no_price: 200,
          p_yes_imp: 0.7143,
          p_no_imp: 0.3333,
          yes_fair_prob: 0.6818,
          no_fair_prob: 0.3182,
        },
        {
          bookmaker: "fanduel",
          line: 0.5,
          over_odds: -240,
          under_odds: -240,
          p_over_imp: 0.7059,
          p_under_imp: 0.2941,
          vig: 0.045,
          p_over_fair: 0.6755,
          p_under_fair: 0.3245,
          fetched_at: "2026-05-08T12:00:00Z",
          yes_price: -240,
          no_price: null,
          p_yes_imp: 0.7059,
          p_no_imp: null,
          yes_fair_prob: 0.6755,
          no_fair_prob: 0.3245,
        },
      ],
      consensus: {
        method: "mean",
        p_over_fair: 0.6787,
        p_under_fair: 0.3213,
        p_yes_fair: 0.6787,
        p_no_fair: 0.3213,
      },
      message: null,
    });

    expect(binary.results[0]?.yes_price).toBe(-250);
    expect(binary.results[0]?.no_price).toBe(200);
    expect(binary.results[1]?.no_price).toBeNull();
    expect(binary.results[1]?.p_no_imp).toBeNull();
    expect(binary.consensus?.p_yes_fair).toBe(0.6787);
    expect(binary.consensus?.p_no_fair).toBe(0.3213);

    const selected = selectDDOdds(binary);
    expect(selected.status).toBe("ready");
    if (selected.status === "ready") {
      expect(selected.books[1]?.noPrice).toBeNull();
      expect(selected.books[0]?.yesPrice).toBe(-250);
      expect(selected.consensusYesFair).toBe(0.6787);
    }

    const overUnder = noVigResponseSchema.parse({
      event_id: "evt-2",
      player_name: "Stephen Curry",
      market: "player_points",
      results: [
        {
          bookmaker: "draftkings",
          line: 24.5,
          over_odds: -110,
          under_odds: -110,
          p_over_imp: 0.5238,
          p_under_imp: 0.5238,
          vig: 0.0476,
          p_over_fair: 0.5,
          p_under_fair: 0.5,
          fetched_at: "2026-05-08T12:00:00Z",
        },
      ],
      consensus: {
        method: "mean",
        p_over_fair: 0.5,
        p_under_fair: 0.5,
      },
      message: null,
    });

    expect(overUnder.results[0]?.yes_price).toBeUndefined();
    expect(overUnder.consensus?.p_yes_fair).toBeUndefined();
    expect(selectDDOdds(overUnder).status).toBe("unavailable");
  });
});
