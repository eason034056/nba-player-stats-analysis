/**
 * NBA card face. The tier string comes from the API. This module does
 * not turn a probability into a tier.
 */

import type { LeagueSegment } from "./event-detail-link";
import { formatPercent, formatTierPercent } from "./player-dd";

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

/**
 * Rate used by the NBA 65% floor and the strong / playable chips.
 * A missing blend keeps the historical rate.
 */
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
 * Main NBA probability. A tier floors the number that tier describes.
 * No tier and no blend is an em dash.
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
  return { probabilityText: formatPercent(pick.combined_probability), tier: null };
}

/**
 * Bet slip face. An older saved leg has no blend and no tier, so it
 * keeps the one-decimal historical percent and no tier label.
 */
export function slipFace(pick: {
  probability: number;
  combined_probability?: number | null;
  tier?: string | null;
}): CardFace {
  if (pick.tier == null && pick.combined_probability === undefined) {
    return { probabilityText: formatPercent(pick.probability), tier: null };
  }
  return nbaTierFace({
    probability: pick.probability,
    combined_probability: pick.combined_probability ?? null,
    tier: pick.tier,
  });
}
