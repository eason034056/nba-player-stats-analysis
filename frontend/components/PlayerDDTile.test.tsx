import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlayerDDTile, type PlayerDDTileProps } from "@/components/PlayerDDTile";
import {
  calculateNoVig,
  calculateWNBANoVig,
  getPlayerDDHistory,
  getWNBAPlayerDDHistory,
} from "@/lib/api";
import type {
  NoVigResponse,
  PlayerDDHistoryResponse,
} from "@/lib/schemas";
import jokicHistory from "@/test/fixtures/player-dd-history/jokic.json";
import jokicEmptySeason from "@/test/fixtures/player-dd-history/jokic-empty-season.json";
import recordedNoVig from "@/test/fixtures/props-no-vig/player-double-double.json";
import { renderWithProviders } from "@/test/test-utils";

vi.mock("@/lib/api", () => {
  class ApiError extends Error {
    status: number;
    statusText: string;
    detail?: string;
    constructor(status: number, statusText: string, detail?: string) {
      super(`API Error: ${status} ${statusText}`);
      this.name = "ApiError";
      this.status = status;
      this.statusText = statusText;
      this.detail = detail;
    }
  }
  return {
    ApiError,
    getPlayerDDHistory: vi.fn(),
    getWNBAPlayerDDHistory: vi.fn(),
    calculateNoVig: vi.fn(),
    calculateWNBANoVig: vi.fn(),
  };
});

function bookmakerRow(
  overrides: Partial<NoVigResponse["results"][number]> &
    Pick<NoVigResponse["results"][number], "bookmaker">,
): NoVigResponse["results"][number] {
  return {
    line: 0.5,
    over_odds: -777,
    under_odds: 333,
    p_over_imp: 0.888,
    p_under_imp: 0.222,
    vig: 0.11,
    p_over_fair: 0.4242,
    p_under_fair: 0.5758,
    fetched_at: "2026-05-08T12:00:00Z",
    yes_price: null,
    no_price: null,
    p_yes_imp: null,
    p_no_imp: null,
    yes_fair_prob: null,
    no_fair_prob: null,
    ...overrides,
  };
}

const nullFieldOdds: NoVigResponse = {
  event_id: "evt-1",
  player_name: "Nikola Jokic",
  market: "player_double_double",
  results: [bookmakerRow({ bookmaker: "draftkings" })],
  consensus: {
    method: "mean",
    p_over_fair: 0.4242,
    p_under_fair: 0.5758,
    p_yes_fair: null,
    p_no_fair: null,
  },
  message: null,
};

function renderTile(overrides: Partial<PlayerDDTileProps> = {}) {
  const props: PlayerDDTileProps = {
    playerName: "Nikola Jokic",
    league: "nba",
    eventId: "evt-1",
    ...overrides,
  };
  return renderWithProviders(<PlayerDDTile {...props} />);
}

describe("PlayerDDTile", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders historical rate and explicit yes/no odds", async () => {
    const historyFn = vi.fn().mockResolvedValue(jokicHistory);
    const oddsFn = vi.fn().mockResolvedValue(recordedNoVig);

    renderTile({
      getPlayerDDHistoryFn: historyFn,
      calculateNoVigFn: oddsFn,
    });

    expect(await screen.findByText("81.3%")).toBeInTheDocument();
    expect(screen.getByText("61 of 75 games")).toBeInTheDocument();
    expect(screen.getByText("DraftKings")).toBeInTheDocument();
    expect(screen.getByText("-250")).toBeInTheDocument();
    expect(screen.getByText("+200")).toBeInTheDocument();
    expect(screen.getByText("71.4%")).toBeInTheDocument();
    expect(screen.getByText("33.3%")).toBeInTheDocument();
    expect(screen.getByText("68.2%")).toBeInTheDocument();
    expect(screen.getByText("31.8%")).toBeInTheDocument();
    expect(screen.getByText("FanDuel")).toBeInTheDocument();
    expect(screen.getByText("-240")).toBeInTheDocument();
    expect(screen.getByText("No leg not posted")).toBeInTheDocument();
    expect(screen.getByText("67.6%")).toBeInTheDocument();
    expect(screen.getByText("67.9%")).toBeInTheDocument();
    expect(screen.getByText("32.1%")).toBeInTheDocument();
    expect(screen.getByText("+13.5 pts")).toBeInTheDocument();
    expect(screen.getByText(/ML projection is not available/)).toBeInTheDocument();
    expect(screen.queryByText(/pending/i)).not.toBeInTheDocument();
    expect(screen.queryByText("-777")).not.toBeInTheDocument();
    expect(screen.queryByText("42.4%")).not.toBeInTheDocument();
    expect(screen.queryByText("0.5")).not.toBeInTheDocument();

    expect(historyFn).toHaveBeenCalledWith({ player: "Nikola Jokic" });
    expect(oddsFn).toHaveBeenCalledWith({
      event_id: "evt-1",
      player_name: "Nikola Jokic",
      market: "player_double_double",
      regions: "us",
      bookmakers: null,
      odds_format: "american",
    });
  });

  it("does not backfill null yes/no fields from over/under stand-ins", async () => {
    renderTile({
      getPlayerDDHistoryFn: vi.fn().mockResolvedValue(jokicHistory),
      calculateNoVigFn: vi.fn().mockResolvedValue(nullFieldOdds),
    });

    expect(
      await screen.findByText(/Over\/Under numbers are not shown in their place/),
    ).toBeInTheDocument();
    expect(screen.getByText("81.3%")).toBeInTheDocument();
    expect(screen.queryByText("-777")).not.toBeInTheDocument();
    expect(screen.queryByText("+333")).not.toBeInTheDocument();
    expect(screen.queryByText("42.4%")).not.toBeInTheDocument();
    expect(screen.queryByText("88.8%")).not.toBeInTheDocument();
    expect(screen.queryByText("0.5")).not.toBeInTheDocument();
    expect(screen.queryByText("+13.5 pts")).not.toBeInTheDocument();
    expect(screen.queryByText("DraftKings")).not.toBeInTheDocument();
  });

  it("shows an empty state when history and odds are empty", async () => {
    renderTile({
      playerName: "Rookie Two-Way",
      getPlayerDDHistoryFn: vi.fn().mockResolvedValue({
        player: "Rookie Two-Way",
        season: null,
        n_games: 0,
        dd_games: 0,
        prob_dd: null,
        message: "Player 'Rookie Two-Way' not found",
      }),
      calculateNoVigFn: vi.fn().mockResolvedValue({
        event_id: "evt-1",
        player_name: "Rookie Two-Way",
        market: "player_double_double",
        results: [],
        consensus: null,
        message: "No props data for this player at the selected bookmakers",
      }),
    });

    expect(
      await screen.findByText("Player 'Rookie Two-Way' not found"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No props data for this player at the selected bookmakers"),
    ).toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
    expect(screen.queryByText(/0 of 0/)).not.toBeInTheDocument();
    expect(screen.queryByText("-777")).not.toBeInTheDocument();
  });

  it("shows the history error and still renders odds that did arrive", async () => {
    renderTile({
      getPlayerDDHistoryFn: vi.fn().mockRejectedValue(
        Object.assign(new Error("API Error: 500 Internal Server Error"), {
          detail: "DD history calculation failed: csv missing",
        }),
      ),
      calculateNoVigFn: vi.fn().mockResolvedValue(recordedNoVig),
    });

    expect(
      await screen.findByText("DD history calculation failed: csv missing"),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Double-double history unavailable",
    );
    expect(await screen.findByText("-250")).toBeInTheDocument();
    expect(screen.queryByText("81.3%")).not.toBeInTheDocument();
    expect(screen.queryByText("61 of 75 games")).not.toBeInTheDocument();
  });

  it("shows an odds error without inventing prices", async () => {
    renderTile({
      getPlayerDDHistoryFn: vi.fn().mockResolvedValue(jokicHistory),
      calculateNoVigFn: vi.fn().mockRejectedValue(new Error("No-vig request failed")),
    });

    expect(await screen.findByText("No-vig request failed")).toBeInTheDocument();
    expect(screen.getByText("Double-double odds unavailable")).toBeInTheDocument();
    expect(screen.getByText("81.3%")).toBeInTheDocument();
    expect(screen.queryByText("-250")).not.toBeInTheDocument();
    expect(screen.queryByText("+13.5 pts")).not.toBeInTheDocument();
  });

  it("shows loading copy until both requests settle", async () => {
    let resolveHistory: (value: PlayerDDHistoryResponse) => void = () => {};
    let resolveOdds: (value: NoVigResponse) => void = () => {};
    const historyFn = vi.fn(
      () =>
        new Promise<PlayerDDHistoryResponse>((resolve) => {
          resolveHistory = resolve;
        }),
    );
    const oddsFn = vi.fn(
      () =>
        new Promise<NoVigResponse>((resolve) => {
          resolveOdds = resolve;
        }),
    );

    renderTile({
      getPlayerDDHistoryFn: historyFn,
      calculateNoVigFn: oddsFn,
    });

    expect(await screen.findByText("Loading double-double history")).toBeInTheDocument();
    expect(screen.getByText("Loading double-double odds")).toBeInTheDocument();
    expect(screen.queryByText("81.3%")).not.toBeInTheDocument();

    resolveHistory(jokicHistory);
    resolveOdds(recordedNoVig);

    expect(await screen.findByText("81.3%")).toBeInTheDocument();
    expect(screen.queryByText("Loading double-double history")).not.toBeInTheDocument();
    expect(screen.queryByText("Loading double-double odds")).not.toBeInTheDocument();
  });

  it("asks for an event instead of showing odds when eventId is absent", async () => {
    const oddsFn = vi.fn();
    renderTile({
      eventId: undefined,
      getPlayerDDHistoryFn: vi.fn().mockResolvedValue(jokicHistory),
      calculateNoVigFn: oddsFn,
    });

    expect(await screen.findByText("81.3%")).toBeInTheDocument();
    expect(screen.getByText(/Live Yes\/No prices need a game/)).toBeInTheDocument();
    expect(oddsFn).not.toHaveBeenCalled();
    expect(screen.queryByText("-250")).not.toBeInTheDocument();
  });

  it("uses the WNBA routes when league is wnba and no override is passed", async () => {
    vi.mocked(getWNBAPlayerDDHistory).mockResolvedValue(jokicHistory);
    vi.mocked(calculateWNBANoVig).mockResolvedValue(recordedNoVig);

    renderTile({ league: "wnba", eventId: "wnba-evt" });

    expect(await screen.findByText("81.3%")).toBeInTheDocument();
    expect(getWNBAPlayerDDHistory).toHaveBeenCalledWith({ player: "Nikola Jokic" });
    expect(calculateWNBANoVig).toHaveBeenCalledWith(
      expect.objectContaining({
        event_id: "wnba-evt",
        player_name: "Nikola Jokic",
        market: "player_double_double",
      }),
    );
    expect(getPlayerDDHistory).not.toHaveBeenCalled();
    expect(calculateNoVig).not.toHaveBeenCalled();
  });

  it("does not call either league when the league is unsupported", async () => {
    renderTile({ league: null });

    expect(
      await screen.findByText(/not available for this league/),
    ).toBeInTheDocument();
    expect(getPlayerDDHistory).not.toHaveBeenCalled();
    expect(getWNBAPlayerDDHistory).not.toHaveBeenCalled();
    expect(calculateNoVig).not.toHaveBeenCalled();
    expect(calculateWNBANoVig).not.toHaveBeenCalled();
    expect(screen.queryByText("81.3%")).not.toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("renders the recorded Jokic rate and the route's yes/no prices", async () => {
    renderTile({
      getPlayerDDHistoryFn: vi.fn().mockResolvedValue(jokicHistory),
      calculateNoVigFn: vi.fn().mockResolvedValue(recordedNoVig),
    });

    expect(await screen.findByText("81.3%")).toBeInTheDocument();
    expect(screen.getByText("61 of 75 games")).toBeInTheDocument();
    expect(screen.getByText("-250")).toBeInTheDocument();
    expect(screen.getByText("+200")).toBeInTheDocument();
    expect(screen.getByText("71.4%")).toBeInTheDocument();
    expect(screen.getByText("33.3%")).toBeInTheDocument();
    expect(screen.getByText("68.2%")).toBeInTheDocument();
    expect(screen.getByText("31.8%")).toBeInTheDocument();
    expect(screen.getByText("-240")).toBeInTheDocument();
    expect(screen.getByText("No leg not posted")).toBeInTheDocument();
    expect(screen.getByText("70.6%")).toBeInTheDocument();
    expect(screen.getByText("32.5%")).toBeInTheDocument();
    expect(screen.getByText("67.9%")).toBeInTheDocument();
    expect(screen.getByText("32.1%")).toBeInTheDocument();
    expect(screen.getByText("+13.5 pts")).toBeInTheDocument();
    expect(screen.queryByText("0.5")).not.toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("shows an explicit empty state for a real zero-game season", async () => {
    renderTile({
      getPlayerDDHistoryFn: vi.fn().mockResolvedValue(jokicEmptySeason),
      calculateNoVigFn: vi.fn().mockResolvedValue({
        ...recordedNoVig,
        results: [],
        consensus: null,
        message: "No props data for this player at the selected bookmakers",
      }),
    });

    expect(
      await screen.findByText(
        "No qualifying games for Nikola Jokic in season 1999-00",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
    expect(screen.queryByText("0 of 0 games")).not.toBeInTheDocument();
    expect(screen.queryByText("-250")).not.toBeInTheDocument();
  });

  it("does not invent a hit rate when prob_dd is null and games were played", async () => {
    renderTile({
      getPlayerDDHistoryFn: vi.fn().mockResolvedValue({
        ...jokicHistory,
        prob_dd: null,
        message: null,
      }),
      calculateNoVigFn: vi.fn().mockResolvedValue(recordedNoVig),
    });

    expect(
      await screen.findByText("No double-double games are in the sample."),
    ).toBeInTheDocument();
    expect(screen.queryByText("81.3%")).not.toBeInTheDocument();
    expect(screen.queryByText("61 of 75 games")).not.toBeInTheDocument();
    expect(await screen.findByText("-250")).toBeInTheDocument();
  });

  it("does not show a No-only row as a posted price", async () => {
    const yesOnlyBook = recordedNoVig.results[0];
    renderTile({
      getPlayerDDHistoryFn: vi.fn().mockResolvedValue(jokicEmptySeason),
      calculateNoVigFn: vi.fn().mockResolvedValue({
        ...recordedNoVig,
        results: [
          {
            ...yesOnlyBook,
            yes_price: null,
            p_yes_imp: null,
            yes_fair_prob: null,
          },
        ],
        consensus: {
          method: "mean",
          p_over_fair: yesOnlyBook.p_over_fair,
          p_under_fair: yesOnlyBook.p_under_fair,
          p_yes_fair: null,
          p_no_fair: null,
        },
        message: null,
      }),
    });

    expect(
      await screen.findByText(/Over\/Under numbers are not shown in their place/),
    ).toBeInTheDocument();
    expect(screen.queryByText("-250")).not.toBeInTheDocument();
    expect(screen.queryByText("+200")).not.toBeInTheDocument();
    expect(screen.queryByText("31.8%")).not.toBeInTheDocument();
    expect(screen.queryByText("68.2%")).not.toBeInTheDocument();
  });

  it("does not renormalize yes and no fair probabilities", async () => {
    const book = recordedNoVig.results[0];
    renderTile({
      getPlayerDDHistoryFn: vi.fn().mockResolvedValue(jokicHistory),
      calculateNoVigFn: vi.fn().mockResolvedValue({
        ...recordedNoVig,
        results: [
          {
            ...book,
            p_yes_imp: 0.7,
            p_no_imp: 0.7,
            yes_fair_prob: 0.7,
            no_fair_prob: 0.7,
          },
        ],
        consensus: {
          method: "mean",
          p_over_fair: 0.7,
          p_under_fair: 0.7,
          p_yes_fair: 0.7,
          p_no_fair: 0.7,
        },
      }),
    });

    expect(await screen.findByText("81.3%")).toBeInTheDocument();
    expect(screen.getAllByText("70.0%").length).toBeGreaterThanOrEqual(4);
    expect(screen.queryByText("50.0%")).not.toBeInTheDocument();
  });

  it(
    "rounds a published 0.6755 fair probability half-up to 67.6%",
    async () => {
      renderTile({
        getPlayerDDHistoryFn: vi.fn().mockResolvedValue(jokicHistory),
        calculateNoVigFn: vi.fn().mockResolvedValue(recordedNoVig),
      });

      expect(await screen.findByText("81.3%")).toBeInTheDocument();
      expect(screen.getByText("67.6%")).toBeInTheDocument();
    },
  );

  it(
    "treats a blank player name as unavailable instead of a permanent loading spinner",
    async () => {
      const historyFn = vi.fn();
      renderTile({
        playerName: "   ",
        getPlayerDDHistoryFn: historyFn,
        calculateNoVigFn: vi.fn(),
      });

      expect(screen.queryByText("Loading double-double history")).not.toBeInTheDocument();
      expect(historyFn).not.toHaveBeenCalled();
      expect(screen.getByText(/enter a player/i)).toBeInTheDocument();
    },
  );

  it("does not load history or odds for an empty player name", () => {
    const historyFn = vi.fn();
    const oddsFn = vi.fn();
    renderTile({
      playerName: "",
      eventId: "evt-spo26-smoke",
      getPlayerDDHistoryFn: historyFn,
      calculateNoVigFn: oddsFn,
    });

    expect(screen.queryByText("Loading double-double history")).not.toBeInTheDocument();
    expect(screen.queryByText("Loading double-double odds")).not.toBeInTheDocument();
    expect(screen.queryByText(/select a game/i)).not.toBeInTheDocument();
    expect(historyFn).not.toHaveBeenCalled();
    expect(oddsFn).not.toHaveBeenCalled();
    expect(screen.getByText(/enter a player/i)).toBeInTheDocument();
  });

  it("keeps recorded prices and hides the stale warning when age and cache state are absent", async () => {
    const { cache_state: _cacheState, data_age_seconds: _age, ...withoutMeta } =
      recordedNoVig;
    renderTile({
      getPlayerDDHistoryFn: vi.fn().mockResolvedValue(jokicHistory),
      calculateNoVigFn: vi.fn().mockResolvedValue({
        ...withoutMeta,
        data_age_seconds: null,
      }),
    });

    expect(await screen.findByText("-250")).toBeInTheDocument();
    expect(screen.getByText("+200")).toBeInTheDocument();
    expect(screen.getByText("81.3%")).toBeInTheDocument();
    expect(screen.queryByText(/stale line/i)).not.toBeInTheDocument();
  });

  it("warns at 31 seconds of age while the recorded Yes price stays visible", async () => {
    renderTile({
      getPlayerDDHistoryFn: vi.fn().mockResolvedValue(jokicHistory),
      calculateNoVigFn: vi.fn().mockResolvedValue({
        ...recordedNoVig,
        cache_state: "fresh",
        data_age_seconds: 31,
      }),
    });

    expect(await screen.findByText("-250")).toBeInTheDocument();
    expect(screen.getByText(/stale line/i)).toBeInTheDocument();
    expect(screen.getByText(/31 seconds old/)).toBeInTheDocument();
  });

  it(
    "warns when the no-vig snapshot is stale instead of presenting it as a live price",
    async () => {
      renderTile({
        getPlayerDDHistoryFn: vi.fn().mockResolvedValue(jokicHistory),
        calculateNoVigFn: vi.fn().mockResolvedValue({
          ...recordedNoVig,
          cache_state: "stale",
          data_age_seconds: 90,
        }),
      });

      expect(await screen.findByText("81.3%")).toBeInTheDocument();
      expect(screen.getByText(/stale/i)).toBeInTheDocument();
      expect(screen.getByText(/90/)).toBeInTheDocument();
    },
  );
});
