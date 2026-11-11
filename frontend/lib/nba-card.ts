/**
 * NBA card face. The tier string comes from the API. This module does
 * not turn a probability into a tier.
 */

import type { LeagueSegment } from "./event-detail-link";
import { formatTierPercent } from "./player-dd";

export interface ApiTier {
  name: "strong" | "playable" | "lean";
  label: string;
}

const API_TIERS: Record<string, ApiTier> = {
  "Strong play": { name: "strong", label: "Strong play" },
  Playable: { name: "playable", label: "Playable" },
  Lean: { name: "lean", label: "Lean" },
};

export function tierFromBackend(tier: string | null | undefined): ApiTier | null {
  if (!tier) return null;
  return API_TIERS[tier] ?? null;
}

export function finiteRate(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Rate for the NBA 65% filter and the strong / playable chips. */
export function boardRate(
  pick: { probability: number; combined_probability?: number | null },
  league: LeagueSegment,
): number {
  if (league === "nba" && finiteRate(pick.combined_probability)) {
    return pick.combined_probability;
  }
  return pick.probability;
}

export interface CardFace {
  probabilityText: string;
  tier: ApiTier | null;
}

/**
 * The probability an NBA tier label describes.
 * The blend wins. A missing blend keeps the probability already on the pick.
 */
export function tierProbability(pick: {
  probability?: number | null;
  combined_probability?: number | null;
}): number | null {
  if (pick.combined_probability != null && Number.isFinite(pick.combined_probability)) {
    return pick.combined_probability;
  }
  if (pick.probability != null && Number.isFinite(pick.probability)) {
    return pick.probability;
  }
  return null;
}

/**
 * Main NBA probability. A tier floors the blend that tier describes.
 * A blend with no tier floors the same way. No blend is an em dash.
 */
export function nbaTierFace(pick: {
  probability?: number | null;
  combined_probability?: number | null;
  tier?: string | null;
}): CardFace {
  const tier = tierFromBackend(pick.tier);
  if (tier) return { probabilityText: formatTierPercent(tierProbability(pick)), tier };
  if (!finiteRate(pick.combined_probability)) {
    return { probabilityText: "—", tier: null };
  }
  return { probabilityText: formatTierPercent(pick.combined_probability), tier: null };
}

/**
 * Bet slip face. Every percent on the NBA slip floors, with or without
 * a tier. An older saved leg has no blend, so the pill uses the stored
 * probability. No tier and an explicit missing blend is an em dash.
 */
export function slipFace(pick: {
  probability: number;
  combined_probability?: number | null;
  tier?: string | null;
}): CardFace {
  const tier = tierFromBackend(pick.tier);
  if (tier) {
    return { probabilityText: formatTierPercent(tierProbability(pick)), tier };
  }
  if (pick.combined_probability === undefined) {
    return { probabilityText: formatTierPercent(pick.probability), tier: null };
  }
  if (!finiteRate(pick.combined_probability)) {
    return { probabilityText: "—", tier: null };
  }
  return { probabilityText: formatTierPercent(pick.combined_probability), tier: null };
}
