"use client";

/**
 * TanStack Query entry for the double-double tile.
 *
 * Components call this hook. They do not call `fetch`. NBA and WNBA each
 * have a history route and a no-vig route; the league argument picks the
 * pair. An unknown league disables both queries.
 */

import { useQuery } from "@tanstack/react-query";

import {
  calculateNoVig,
  calculateWNBANoVig,
  getPlayerDDHistory,
  getWNBAPlayerDDHistory,
} from "@/lib/api";
import { METRIC_TO_MARKET } from "@/lib/metric-to-market";
import type {
  NoVigRequest,
  NoVigResponse,
  PlayerDDHistoryRequest,
  PlayerDDHistoryResponse,
} from "@/lib/schemas";

export type DDLeague = "nba" | "wnba";

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
  const leagueSupported = league === "nba" || league === "wnba";
  const canQueryHistory = leagueSupported && trimmedPlayer.length > 0;
  const canQueryOdds = canQueryHistory && Boolean(eventId);

  const historyFn =
    getPlayerDDHistoryFn ??
    (league === "wnba" ? getWNBAPlayerDDHistory : getPlayerDDHistory);
  const oddsFn =
    calculateNoVigFn ?? (league === "wnba" ? calculateWNBANoVig : calculateNoVig);

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
