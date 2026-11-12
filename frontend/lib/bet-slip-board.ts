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
import { slipFace } from "./nba-card";
import { formatTierPercent } from "./player-dd";
import { teamAbbr } from "./team-abbr";
import { boardClock } from "./today-board";
import { propPhrase } from "./picks-board";
import type { DailyPick } from "./schemas";

export interface SlipSummary {
  count: number;
  averageText: string;
  allHitText: string;
}

function legHasBlend(pick: BetSlipPick): pick is BetSlipPick & { combined_probability: number } {
  return typeof pick.combined_probability === "number" && Number.isFinite(pick.combined_probability);
}

export interface SlipTotals {
  summary: SlipSummary;
  averageLabel: string;
  allHitLabel: string;
  basis: "blend" | "history" | "stored";
}

export const OUT_LEGS_NOTE = "Avg and all hit leave out Out legs.";

export function slipSummaryCaption(basis: SlipTotals["basis"], omitsOutLegs: boolean): string {
  const body =
    basis === "blend"
      ? "Avg and all hit use the combined probability on each same-side leg. All hit is the product of those blends. It is not a joint probability from the API."
      : basis === "history"
        ? "History: a leg has no blend, so avg and all hit use the historical rate on every leg. A reverse add stores the complement of the other side's hit rate, not a de-vigged price."
        : "Avg and all hit use the stored hit rates. A reverse add stores the complement of the other side's hit rate, not a de-vigged price. All hit is the product of those stored rates. It is not a joint probability from the API.";
  return omitsOutLegs ? `${body} ${OUT_LEGS_NOTE}` : body;
}

/**
 * Same-side legs with a blend contribute that blend.
 * A slip that also has a leg with no blend is labelled History and uses
 * the historical rate on every leg, so the totals are not a mixed number.
 */
export function slipTotals(picks: BetSlipPick[], outIds?: ReadonlySet<string>): SlipTotals {
  const live = outIds ? picks.filter((pick) => !outIds.has(pick.id)) : picks;
  const summaryOf = (values: number[], basis: SlipTotals["basis"], averageLabel: string, allHitLabel: string): SlipTotals => {
    const math = slipSummary(values);
    return {
      summary: { count: picks.length, averageText: math.averageText, allHitText: math.allHitText },
      averageLabel,
      allHitLabel,
      basis,
    };
  };
  const blended = live.filter(legHasBlend);
  if (live.length > 0 && blended.length === live.length) {
    return summaryOf(
      blended.map((pick) => pick.combined_probability),
      "blend",
      "avg. blend",
      "all hit",
    );
  }
  if (live.some(legHasBlend)) {
    return summaryOf(
      live.map((pick) => pick.probability),
      "history",
      "History",
      "History",
    );
  }
  return summaryOf(
    live.map((pick) => pick.probability),
    "stored",
    "avg. probability",
    "all hit",
  );
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
    averageText: formatTierPercent(average),
    allHitText: formatTierPercent(allHit),
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
  return `${side} hit rate ${formatTierPercent(pick.probability)} (1 − ${other} ${formatTierPercent(1 - pick.probability)})`;
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

export function slipCardFace(pick: BetSlipPick) {
  return slipFace(pick);
}

export function sameSideSlipRead(
  pick: { direction: string; tier?: string | null; combined_probability?: number | null },
  direction: string,
): { tier?: string | null; combined_probability?: number | null } {
  if (direction !== pick.direction) return {};
  return {
    tier: pick.tier ?? null,
    combined_probability: pick.combined_probability ?? null,
  };
}

export type SlipPickInput = Omit<BetSlipPick, "id" | "added_at">;

export function slipPickFromDaily(
  pick: DailyPick,
  direction: string,
  probability: number,
  rateBasis?: "complement",
): SlipPickInput {
  return {
    player_name: pick.player_name,
    player_team: pick.player_team || "",
    event_id: pick.event_id,
    home_team: pick.home_team,
    away_team: pick.away_team,
    commence_time: pick.commence_time,
    metric: pick.metric,
    threshold: pick.threshold,
    direction,
    probability,
    n_games: pick.n_games,
    rate_basis: rateBasis,
    ...sameSideSlipRead(pick, direction),
  };
}

export function reverseSlipPick(pick: DailyPick): SlipPickInput {
  const reverse = pick.direction === "over" ? "under" : "over";
  return slipPickFromDaily(pick, reverse, 1 - pick.probability, "complement");
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
