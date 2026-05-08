import type { MarketKey } from "@/components/MarketSelect";

/**
 * picks API metric key → MarketSelect MarketKey
 *
 * Single source of truth. Adding a new metric requires only one entry here;
 * `as const satisfies` makes a typo (e.g. "player_pints") a compile error,
 * and `MetricKey` below stays narrowed to the literal union of these 12 keys.
 */
export const METRIC_TO_MARKET = {
  points: "player_points",
  rebounds: "player_rebounds",
  assists: "player_assists",
  pra: "player_points_rebounds_assists",
  ra: "player_rebounds_assists",
  pr: "player_points_rebounds",
  pa: "player_points_assists",
  threes_made: "player_threes",
  steals: "player_steals",
  ftm: "player_frees_made",
  fgm: "player_field_goals",
  dd: "player_double_double",
} as const satisfies Record<string, MarketKey>;

export type MetricKey = keyof typeof METRIC_TO_MARKET;

export function metricToMarket(metric: string): MarketKey {
  if (Object.prototype.hasOwnProperty.call(METRIC_TO_MARKET, metric)) {
    return METRIC_TO_MARKET[metric as MetricKey];
  }
  if (typeof console !== "undefined") {
    console.warn(
      `metricToMarket: unknown metric "${metric}", falling back to player_points`,
    );
  }
  return "player_points";
}
