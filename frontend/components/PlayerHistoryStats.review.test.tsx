import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PlayerHistoryStats } from "@/components/PlayerHistoryStats";
import type { NoVigResponse, PlayerHistoryResponse } from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";

const players = vi.fn().mockResolvedValue({ players: [], total: 0 });

function lineResponse(line: number, market: string): NoVigResponse {
  return {
    event_id: "evt-1",
    player_name: "A'ja Wilson",
    market,
    results: [
      {
        bookmaker: "draftkings",
        line,
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
    consensus: { method: "mean", p_over_fair: 0.5, p_under_fair: 0.5 },
    message: null,
  };
}

const emptyBoard: NoVigResponse = {
  event_id: "evt-1",
  player_name: "A'ja Wilson",
  market: "player_frees_made",
  results: [],
  consensus: null,
  message: "No bookmaker inventory",
};

function historyBody(
  overrides: Partial<PlayerHistoryResponse> = {},
): PlayerHistoryResponse {
  return {
    player: "A'ja Wilson",
    metric: "points",
    threshold: 18.5,
    n_games: 10,
    p_over: 0.6,
    p_under: 0.4,
    equal_count: 0,
    mean: 19,
    std: 3,
    histogram: [],
    game_logs: [],
    opponents: [],
    teammates: [],
    message: null,
    ...overrides,
  };
}

describe("PlayerHistoryStats review fixes", () => {
  it("labels the full season as 82 NBA games and 44 WNBA games", async () => {
    const user = userEvent.setup();
    const nbaHistory = vi.fn().mockResolvedValue(historyBody());
    const { unmount } = renderWithProviders(
      <PlayerHistoryStats
        eventId="evt-1"
        initialPlayer="A'ja Wilson"
        initialMarket="player_points"
        cacheNamespace="nba"
        getCSVPlayersFn={players}
        getPlayerHistoryFn={nbaHistory}
        calculateNoVigFn={vi.fn().mockResolvedValue(lineResponse(18.5, "player_points"))}
      />,
    );

    expect(await screen.findByRole("option", { name: "Full Season (82 games)" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Full Season (44 games)" })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(nbaHistory).toHaveBeenCalledWith(expect.objectContaining({ n: 0 }));
    });
    await user.selectOptions(screen.getByRole("combobox", { name: "Game Range" }), "82");
    await waitFor(() => {
      expect(nbaHistory).toHaveBeenCalledWith(expect.objectContaining({ n: 82 }));
    });
    unmount();

    const wnbaHistory = vi.fn().mockResolvedValue(historyBody());
    renderWithProviders(
      <PlayerHistoryStats
        eventId="evt-1"
        initialPlayer="A'ja Wilson"
        initialMarket="player_points"
        cacheNamespace="wnba"
        getCSVPlayersFn={players}
        getPlayerHistoryFn={wnbaHistory}
        calculateNoVigFn={vi.fn().mockResolvedValue(lineResponse(18.5, "player_points"))}
      />,
    );

    expect(await screen.findByRole("option", { name: "Full Season (44 games)" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Full Season (82 games)" })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(wnbaHistory).toHaveBeenCalledWith(expect.objectContaining({ n: 0 }));
    });
    await user.selectOptions(screen.getByRole("combobox", { name: "Game Range" }), "44");
    await waitFor(() => {
      expect(wnbaHistory).toHaveBeenCalledWith(expect.objectContaining({ n: 44 }));
    });
    expect(wnbaHistory).not.toHaveBeenCalledWith(expect.objectContaining({ n: 82 }));
  });

  it("does not compute an Over/Under rate against a placeholder when the board is empty", async () => {
    const history = vi.fn().mockResolvedValue(
      historyBody({
        metric: "ftm",
        threshold: 24.5,
        p_over: 0.99,
        n_games: 40,
      }),
    );

    renderWithProviders(
      <PlayerHistoryStats
        eventId="evt-1"
        initialPlayer="A'ja Wilson"
        initialMarket="player_frees_made"
        cacheNamespace="wnba"
        getCSVPlayersFn={players}
        getPlayerHistoryFn={history}
        calculateNoVigFn={vi.fn().mockResolvedValue(emptyBoard)}
      />,
    );

    expect(await screen.findByTestId("no-posted-line")).toHaveTextContent("No posted line");
    expect(screen.getByTestId("no-posted-line")).toHaveTextContent(
      "no placeholder line is used",
    );
    expect(screen.queryByText("24.5")).not.toBeInTheDocument();
    expect(screen.queryByText(/Over Probability/)).not.toBeInTheDocument();
    expect(history).not.toHaveBeenCalled();
  });

  it("does not compute an Over/Under rate when the odds fetch fails", async () => {
    const history = vi.fn().mockResolvedValue(
      historyBody({
        metric: "ftm",
        threshold: 24.5,
        p_over: 0.99,
        n_games: 40,
      }),
    );

    renderWithProviders(
      <PlayerHistoryStats
        eventId="evt-1"
        initialPlayer="A'ja Wilson"
        initialMarket="player_frees_made"
        cacheNamespace="wnba"
        getCSVPlayersFn={players}
        getPlayerHistoryFn={history}
        calculateNoVigFn={vi.fn().mockRejectedValue(new Error("odds down"))}
      />,
    );

    expect(await screen.findByTestId("no-posted-line")).toHaveTextContent("No posted line");
    expect(screen.queryByText("24.5")).not.toBeInTheDocument();
    expect(screen.queryByText(/Over Probability/)).not.toBeInTheDocument();
    expect(screen.queryByText("NaN")).not.toBeInTheDocument();
    expect(history).not.toHaveBeenCalled();
  });

  it("renders historyData.message when the sample has zero games", async () => {
    const history = vi.fn().mockResolvedValue(
      historyBody({
        n_games: 0,
        p_over: null,
        p_under: null,
        mean: null,
        std: null,
        message: "No qualifying games for A'ja Wilson in this window",
      }),
    );

    renderWithProviders(
      <PlayerHistoryStats
        initialPlayer="A'ja Wilson"
        initialMarket="player_points"
        initialThreshold="18.5"
        cacheNamespace="wnba"
        getCSVPlayersFn={players}
        getPlayerHistoryFn={history}
      />,
    );

    expect(
      await screen.findByText("No qualifying games for A'ja Wilson in this window"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("history-zero-games")).toBeInTheDocument();
    expect(screen.queryByText(/Over Probability/)).not.toBeInTheDocument();
    expect(screen.queryByText("60.0%")).not.toBeInTheDocument();
  });
});
