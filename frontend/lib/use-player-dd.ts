"use client";

/**
 * TanStack Query entry for the double-double tile.
 *
 * Components call this hook. They do not call `fetch`. `null` disables
 * both queries. A player name is still required before history loads.
 */

import { useQuery } from "@tanstack/react-query";

import { calculateNoVig, getPlayerDDHistory } from "@/lib/api";
import { METRIC_TO_MARKET } from "@/lib/metric-to-market";
import type {
  NoVigRequest,
  NoVigResponse,
  PlayerDDHistoryRequest,
  PlayerDDHistoryResponse,
} from "@/lib/schemas";

export type DDLeague = "nba";

/** Odds API market key. Matches backend `BINARY_MARKET_KEYS`. */
export const PLAYER_DOUBLE_DOUBLE_MARKET = METRIC_TO_MARKET.dd;

export interface UsePlayerDDTileDataArgs {
  playerName: string;
  league: DDLeague | null;
  eventId?: string;
  season?: string;
  getPlayerDDHistoryFn?: (
    request: PlayerDDHistoryRequest,
  ) => Promise<PlayerDDHistoryResponse>;
  calculateNoVigFn?: (request: NoVigRequest) => Promise<NoVigResponse>;
}

export function usePlayerDDTileData({
  playerName,
  league,
  eventId,
  season,
  getPlayerDDHistoryFn,
  calculateNoVigFn,
}: UsePlayerDDTileDataArgs) {
  const trimmedPlayer = playerName.trim();
  const trimmedSeason = season?.trim() ? season.trim() : undefined;
  const leagueSupported = league === "nba";
  const canQueryHistory = leagueSupported && trimmedPlayer.length > 0;
  const canQueryOdds = canQueryHistory && Boolean(eventId);

  const historyFn = getPlayerDDHistoryFn ?? getPlayerDDHistory;
  const oddsFn = calculateNoVigFn ?? calculateNoVig;

  const historyQuery = useQuery({
    queryKey: [
      "playerDDHistory",
      league,
      trimmedPlayer,
      trimmedSeason ?? null,
    ],
    queryFn: () =>
      historyFn({
        player: trimmedPlayer,
        ...(trimmedSeason ? { season: trimmedSeason } : {}),
      }),
    enabled: canQueryHistory,
    staleTime: 60 * 1000,
  });

  const oddsQuery = useQuery({
    queryKey: ["playerDDOdds", league, eventId ?? null, trimmedPlayer],
    queryFn: () =>
      oddsFn({
        event_id: eventId ?? "",
        player_name: trimmedPlayer,
        market: PLAYER_DOUBLE_DOUBLE_MARKET,
        regions: "us",
        bookmakers: null,
        odds_format: "american",
      }),
    enabled: canQueryOdds,
    staleTime: 30 * 1000,
  });

  return {
    historyQuery,
    oddsQuery,
    canQueryHistory,
    canQueryOdds,
    leagueSupported,
  };
}
