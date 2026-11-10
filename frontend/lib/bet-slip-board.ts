/**
 * bet-slip-board.ts
 *
 * Display math for the slip summary. The average and the all-hit
 * figure are the mean and the product of the probabilities already
 * stored on the slip. They are not a joint model.
 */

import type { BetSlipPick } from "@/contexts/BetSlipContext";
import { buildEventDetailHref, type LeagueSegment } from "./event-detail-link";
import { metricToMarket } from "./metric-to-market";
import { formatPercent } from "./player-dd";
import { teamAbbr } from "./team-abbr";
import { boardClock, readTier } from "./today-board";
import { propPhrase } from "./picks-board";

export interface SlipSummary {
  count: number;
  averageText: string;
  allHitText: string;
}

export function slipSummary(probabilities: number[]): SlipSummary {
  const count = probabilities.length;
  if (count === 0 || probabilities.some((value) => !Number.isFinite(value))) {
    return { count, averageText: "—", allHitText: "—" };
  }
  const average = probabilities.reduce((sum, value) => sum + value, 0) / count;
  const allHit = probabilities.reduce((product, value) => product * value, 1);
  return {
    count,
    averageText: formatPercent(average),
    allHitText: formatPercent(allHit),
  };
}

export function slipPropText(pick: Pick<BetSlipPick, "direction" | "threshold" | "metric">): string {
  return propPhrase(pick);
}

/**
 * Caption for a reverse add. The stored number is 1 − the other side's
 * historical hit rate. It is not a market price and not a de-vigged Under.
 */
export function complementHitRateLabel(
  pick: Pick<BetSlipPick, "direction" | "probability" | "rate_basis">,
): string | null {
  if (pick.rate_basis !== "complement" || !Number.isFinite(pick.probability)) return null;
  const side = pick.direction === "under" ? "Under" : pick.direction === "over" ? "Over" : pick.direction;
  const other = pick.direction === "under" ? "Over" : pick.direction === "over" ? "Under" : "other side";
  return `${side} hit rate ${formatPercent(pick.probability)} (1 − ${other} ${formatPercent(1 - pick.probability)})`;
}

export function slipMatchup(pick: BetSlipPick, league: LeagueSegment): string {
  const away = teamAbbr(pick.away_team, league) || pick.away_team;
  const home = teamAbbr(pick.home_team, league) || pick.home_team;
  const time = boardClock(pick.commence_time);
  const teams = `${away} @ ${home}`;
  return time ? `${teams} · ${time}` : teams;
}

export function slipTeamCode(pick: BetSlipPick, league: LeagueSegment): string {
  return teamAbbr(pick.player_team, league) || pick.player_team.slice(0, 3).toUpperCase();
}

export function slipTierLabel(probability: number): string | null {
  return readTier(probability)?.label ?? null;
}

export function slipDetailHref(pick: BetSlipPick, league: LeagueSegment): string {
  return buildEventDetailHref({
    eventId: pick.event_id,
    commenceTime: pick.commence_time,
    player: pick.player_name,
    market: metricToMarket(pick.metric),
    threshold: pick.threshold,
    league,
  });
}
