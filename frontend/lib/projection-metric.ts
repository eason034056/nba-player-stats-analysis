/**
 * Market key → projection card.
 *
 * The panel has one card per projected stat. A market with no card
 * (double-double) highlights nothing. The 0.5 DD sentinel is not an edge.
 */

import type { PlayerProjection } from "@/lib/schemas";

export const PROJECTION_CARDS = [
  { key: "points", label: "Points", field: "points" },
  { key: "rebounds", label: "Rebounds", field: "rebounds" },
  { key: "assists", label: "Assists", field: "assists" },
  { key: "pra", label: "PRA", field: "pra" },
  { key: "threes", label: "3PM", field: "three_pointers_made" },
  { key: "steals", label: "Steals", field: "steals" },
  { key: "ftm", label: "FTM", field: "free_throws_made" },
  { key: "fgm", label: "FGM", field: "field_goals_made" },
  { key: "ra", label: "R+A", field: "r_a" },
  { key: "pr", label: "P+R", field: "p_r" },
  { key: "pa", label: "P+A", field: "p_a" },
] as const;

export type ProjectionCardKey = (typeof PROJECTION_CARDS)[number]["key"];

const MARKET_TO_CARD: Record<string, ProjectionCardKey | null> = {
  player_points: "points",
  player_rebounds: "rebounds",
  player_assists: "assists",
  player_threes: "threes",
  player_steals: "steals",
  player_frees_made: "ftm",
  player_field_goals: "fgm",
  player_points_rebounds_assists: "pra",
  player_rebounds_assists: "ra",
  player_points_rebounds: "pr",
  player_points_assists: "pa",
  player_double_double: null,
};

export function marketToProjectionCard(market: string): ProjectionCardKey | null {
  if (Object.prototype.hasOwnProperty.call(MARKET_TO_CARD, market)) {
    return MARKET_TO_CARD[market];
  }
  return null;
}

export function projectionCardLabel(key: ProjectionCardKey): string {
  return PROJECTION_CARDS.find((card) => card.key === key)?.label ?? key;
}

export function projectionCardValue(
  projection: PlayerProjection,
  key: ProjectionCardKey,
): number | null | undefined {
  const card = PROJECTION_CARDS.find((item) => item.key === key);
  if (!card) return null;
  return projection[card.field];
}

/**
 * Line passed into the projection edge bar.
 * Synthetic and binary rows do not produce an edge. When the SPO-104
 * flags are absent, a double-double market is treated the same way.
 */
export function lineForProjectionEdge(args: {
  market?: string | null;
  line?: number | null;
  lineIsSynthetic?: boolean | null;
  marketKind?: string | null;
}): number | null {
  if (args.marketKind === "binary" || args.lineIsSynthetic === true) return null;
  const flagsAbsent = args.lineIsSynthetic == null && (args.marketKind == null);
  if (
    flagsAbsent &&
    (args.market === "player_double_double" || args.market === "dd")
  ) {
    return null;
  }
  if (typeof args.line !== "number" || !Number.isFinite(args.line)) return null;
  return args.line;
}
