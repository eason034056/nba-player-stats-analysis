/**
 * picks-board.ts
 *
 * View model for Daily Picks. Every number comes from a DailyPick field.
 * Last-10 hits, a blended probability, and a signal verdict are not on
 * the payload, so this module does not invent them.
 */

import { buildEventDetailHref, type LeagueSegment } from "./event-detail-link";
import { metricToMarket } from "./metric-to-market";
import { formatPercent } from "./player-dd";
import type { DailyPick } from "./schemas";
import { teamAbbr } from "./team-abbr";
import { boardClock, metricShort, readTier, type ReadTierName } from "./today-board";

export type ConfidenceFilter = "all" | "strong" | "playable";

export const CONFIDENCE_FILTERS: { id: ConfidenceFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "strong", label: "Strong ≥70%" },
  { id: "playable", label: "Playable 65–<70%" },
];

/** Market chips the prototype draws, in that order. */
export const PROTOTYPE_MARKETS = ["PTS", "REB", "AST", "3PM", "PRA"] as const;

const METRIC_PHRASE: Record<string, string> = {
  points: "points",
  rebounds: "rebounds",
  assists: "assists",
  pra: "pts+reb+ast",
  ra: "reb+ast",
  pr: "pts+reb",
  pa: "pts+ast",
  threes_made: "threes",
  steals: "steals",
  ftm: "free throws",
  fgm: "field goals",
  dd: "double-double",
};

const TIER_SHORT: Record<ReadTierName, string> = {
  strong: "Strong",
  playable: "Playable",
  lean: "Lean",
  pass: "Pass",
};

export interface PickTag {
  text: string;
}

export interface PickRowModel {
  key: string;
  rank: string;
  team: string;
  player: string;
  matchup: string;
  propText: string;
  probabilityText: string;
  barPercent: number;
  tierShort: string | null;
  tierName: ReadTierName | null;
  tags: PickTag[];
  href: string;
}

export function picksEyebrow(date: string, analyzedAt: string | null | undefined): string {
  const [year, month, day] = date.split("-").map(Number);
  let head = date;
  if (year && month && day) {
    const local = new Date(year, month - 1, day);
    const weekday = local.toLocaleDateString("en-US", { weekday: "short" }).toUpperCase();
    const mon = local.toLocaleDateString("en-US", { month: "short" }).toUpperCase();
    head = `${weekday} · ${mon} ${day}`;
  }
  if (!analyzedAt) return head;
  const updated = boardClock(analyzedAt);
  if (!updated) return head;
  return `${head} · UPDATED ${updated.toUpperCase()}`;
}

export function matchesConfidence(probability: number, filter: ConfidenceFilter): boolean {
  if (filter === "all") return true;
  if (!Number.isFinite(probability)) return false;
  if (filter === "strong") return probability >= 0.7;
  return probability >= 0.65 && probability < 0.7;
}

export function marketChipList(picks: DailyPick[]): string[] {
  const present = new Set(picks.map((pick) => metricShort(pick.metric)));
  const extras = Array.from(present)
    .filter((key) => !PROTOTYPE_MARKETS.includes(key as (typeof PROTOTYPE_MARKETS)[number]))
    .sort();
  return ["ALL", ...PROTOTYPE_MARKETS, ...extras];
}

export function propPhrase(pick: Pick<DailyPick, "direction" | "threshold" | "metric">): string {
  const side = pick.direction === "under" ? "Under" : pick.direction === "over" ? "Over" : pick.direction;
  const line = Number.isFinite(pick.threshold) ? String(pick.threshold) : "—";
  const phrase = METRIC_PHRASE[pick.metric] ?? metricShort(pick.metric);
  return `${side} ${line} ${phrase}`;
}

function finite(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * Tags that quote stored fields. A missing projection or rank is omitted.
 * There is no last-10 hit count on DailyPick, so no "L10" tag.
 */
export function pickTags(pick: DailyPick): PickTag[] {
  const tags: PickTag[] = [];
  if (finite(pick.n_games) && pick.n_games > 0) {
    tags.push({ text: `${pick.n_games} games` });
  }
  if (pick.has_projection && finite(pick.projected_value)) {
    tags.push({ text: `Proj ${pick.projected_value.toFixed(1)}` });
  }
  if (pick.has_projection && finite(pick.edge)) {
    const sign = pick.edge > 0 ? "+" : "";
    tags.push({ text: `Edge ${sign}${pick.edge.toFixed(1)}` });
  }
  if (finite(pick.projected_minutes)) {
    tags.push({ text: `${Math.round(pick.projected_minutes)} min` });
  }
  const rank = finite(pick.opponent_position_rank)
    ? pick.opponent_position_rank
    : finite(pick.opponent_rank)
      ? pick.opponent_rank
      : null;
  if (rank != null) {
    tags.push({ text: `Def #${rank}` });
  }
  return tags;
}

export function pickTeamCode(pick: DailyPick, league: LeagueSegment): string {
  const code = pick.player_team_code?.trim();
  if (code && code.length <= 4) return code.toUpperCase();
  return teamAbbr(pick.player_team || pick.home_team, league);
}

export function pickMatchup(pick: DailyPick, league: LeagueSegment): string {
  const away = teamAbbr(pick.away_team, league) || pick.away_team;
  const home = teamAbbr(pick.home_team, league) || pick.home_team;
  const time = boardClock(pick.commence_time);
  const teams = `${away} @ ${home}`;
  return time ? `${teams} · ${time}` : teams;
}

export function sortPicks(picks: DailyPick[]): DailyPick[] {
  return [...picks].sort((left, right) => {
    const leftRank = Number.isFinite(left.probability) ? left.probability : -1;
    const rightRank = Number.isFinite(right.probability) ? right.probability : -1;
    return rightRank - leftRank;
  });
}

export function countStrong(picks: DailyPick[]): number {
  return picks.filter((pick) => Number.isFinite(pick.probability) && pick.probability >= 0.7).length;
}

export function buildPickRows(
  picks: DailyPick[],
  league: LeagueSegment,
  date: string,
): PickRowModel[] {
  return sortPicks(picks).map((pick, index) => {
    const tier = readTier(pick.probability);
    const bar = Number.isFinite(pick.probability)
      ? Math.max(0, Math.min(100, pick.probability * 100))
      : 0;
    return {
      key: `${pick.event_id}-${pick.player_name}-${pick.metric}-${pick.direction}`,
      rank: String(index + 1).padStart(2, "0"),
      team: pickTeamCode(pick, league),
      player: pick.player_name,
      matchup: pickMatchup(pick, league),
      propText: propPhrase(pick),
      probabilityText: formatPercent(pick.probability),
      barPercent: bar,
      tierShort: tier ? TIER_SHORT[tier.name] : null,
      tierName: tier?.name ?? null,
      tags: pickTags(pick),
      href: buildEventDetailHref({
        eventId: pick.event_id,
        date,
        player: pick.player_name,
        market: metricToMarket(pick.metric),
        threshold: pick.threshold,
        league,
      }),
    };
  });
}
