import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlayerHistoryStats } from "@/components/PlayerHistoryStats";
import type { NoVigResponse, PlayerDDHistoryResponse } from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";

const history: PlayerDDHistoryResponse = {
  player: "A'ja Wilson",
  season: null,
  n_games: 40,
  dd_games: 28,
  prob_dd: 0.7,
  message: null,
};

const odds: NoVigResponse = {
  event_id: "wnba-evt",
  player_name: "A'ja Wilson",
  market: "player_double_double",
  results: [
    {
      bookmaker: "draftkings",
      line: 0.5,
      over_odds: -150,
      under_odds: 130,
      p_over_imp: 0.6,
      p_under_imp: 0.4348,
      vig: 0.0348,
      p_over_fair: 0.58,
      p_under_fair: 0.42,
      fetched_at: "2026-05-13T17:00:00Z",
      yes_price: -150,
      no_price: 130,
      p_yes_imp: 0.6,
      p_no_imp: 0.4348,
      yes_fair_prob: 0.58,
      no_fair_prob: 0.42,
    },
  ],
  consensus: {
    method: "mean",
    p_over_fair: 0.58,
    p_under_fair: 0.42,
    p_yes_fair: 0.58,
    p_no_fair: 0.42,
  },
  message: null,
};

describe("PlayerHistoryStats double-double wiring", () => {
  it("loads the WNBA tile from the event id and does not call the continuous history route", async () => {
    const historyFn = vi.fn().mockResolvedValue(history);
    const oddsFn = vi.fn().mockResolvedValue(odds);
    const continuousHistory = vi.fn();

    renderWithProviders(
      <PlayerHistoryStats
        eventId="wnba-evt"
        initialPlayer="A'ja Wilson"
        initialMarket="player_double_double"
        cacheNamespace="wnba"
        getCSVPlayersFn={vi.fn().mockResolvedValue({ players: [], total: 0 })}
        getPlayerHistoryFn={continuousHistory}
        getPlayerDDHistoryFn={historyFn}
        calculateNoVigFn={oddsFn}
      />,
    );

    expect(await screen.findByText("70.0%")).toBeInTheDocument();
    expect(screen.getByText("28 of 40 games")).toBeInTheDocument();
    expect(screen.getByText("-150")).toBeInTheDocument();
    expect(screen.getByText("+130")).toBeInTheDocument();
    expect(historyFn).toHaveBeenCalledWith({ player: "A'ja Wilson" });
    expect(oddsFn).toHaveBeenCalledWith(
      expect.objectContaining({
        event_id: "wnba-evt",
        player_name: "A'ja Wilson",
        market: "player_double_double",
      }),
    );
    expect(continuousHistory).not.toHaveBeenCalled();
    expect(screen.queryByText("0.5")).not.toBeInTheDocument();
  });
});
