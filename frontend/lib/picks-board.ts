/**
 * picks-board.ts
 *
 * View model for Daily Picks. Every number comes from a DailyPick field.
 * Last-10 hits, a blended probability, and a signal verdict are not on
 * the payload, so this module does not invent them.
 */

import { buildEventDetailHref, type LeagueSegment } from "./event-detail-link";
import {
  canonicalInjuryTag,
  injuryKey,
  injurySeverity,
  injuryTag,
  type InjuryTag,
} from "./injury-tag";
import { metricToMarket } from "./metric-to-market";
import { boardRate, nbaTierFace } from "./nba-card";
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
  injury?: InjuryTag;
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
  /** Out has no model read. The card stays, dimmed, without a percent or bar. */
  dimmed: boolean;
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

/** True when the stored status is Out. The raw BDL word is not read, so Doubtful cannot block. */
export function isOutPick(pick: { injury_status?: string | null }): boolean {
  return injuryKey(pick.injury_status) === "out";
}

/**
 * True when any loaded row for this player in this game is Out.
 * One Out line blocks every other line and market. Doubtful does not.
 */
function samePlayerInGame(
  pick: { event_id?: string | null; player_name?: string | null },
  eventId: string,
  playerName: string,
): boolean {
  const event = eventId.trim();
  const name = playerName.trim().toLowerCase();
  if (!event || !name) return false;
  const pickEvent = pick.event_id?.trim() ?? "";
  const pickName = pick.player_name?.trim().toLowerCase() ?? "";
  return pickEvent === event && pickName === name;
}

export function isPlayerOutInGame(
  picks: readonly {
    event_id?: string | null;
    player_name?: string | null;
    injury_status?: string | null;
  }[],
  eventId: string,
  playerName: string,
): boolean {
  return picks.some((pick) => samePlayerInGame(pick, eventId, playerName) && isOutPick(pick));
}

/**
 * Strongest tag for this player in this game.
 * A stored Out wins, and the chip keeps that row's raw word.
 * Doubtful does not win over a stored Out, and it does not block.
 */
export function injuryTagForPlayer(
  picks: readonly {
    event_id?: string | null;
    player_name?: string | null;
    injury_status?: string | null;
    injury_status_raw?: string | null;
  }[],
  eventId: string,
  playerName: string,
): InjuryTag | null {
  const rows = picks.filter((pick) => samePlayerInGame(pick, eventId, playerName));
  const outRow = rows.find((pick) => isOutPick(pick));
  if (outRow) return injuryTag(outRow.injury_status_raw, outRow.injury_status) ?? canonicalInjuryTag("out");
  let best: InjuryTag | null = null;
  for (const row of rows) {
    const tag = injuryTag(row.injury_status_raw, row.injury_status);
    if (!tag) continue;
    if (!best || injurySeverity(tag) < injurySeverity(best)) best = tag;
  }
  return best;
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
  const injury = injuryTag(pick.injury_status_raw, pick.injury_status);
  if (injury) tags.push({ text: injury.text, injury });
  if (pick.lineup_confirmed === false) tags.push({ text: "Lineup unconfirmed" });
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
  return teamAbbr(pick.player_team, league);
}

export function pickMatchup(pick: DailyPick, league: LeagueSegment): string {
  const away = teamAbbr(pick.away_team, league) || pick.away_team;
  const home = teamAbbr(pick.home_team, league) || pick.home_team;
  const time = boardClock(pick.commence_time);
  const teams = `${away} @ ${home}`;
  return time ? `${teams} · ${time}` : teams;
}

export function sortPicks(picks: DailyPick[], league: LeagueSegment): DailyPick[] {
  return [...picks].sort((left, right) => {
    const leftOut = isOutPick(left);
    const rightOut = isOutPick(right);
    if (leftOut !== rightOut) return leftOut ? 1 : -1;
    const leftRate = boardRate(left, league);
    const rightRate = boardRate(right, league);
    const leftRank = Number.isFinite(leftRate) ? leftRate : -1;
    const rightRank = Number.isFinite(rightRate) ? rightRate : -1;
    return rightRank - leftRank;
  });
}

export function countStrong(picks: DailyPick[], league: LeagueSegment): number {
  return picks.filter((pick) => {
    if (isOutPick(pick)) return false;
    const rate = boardRate(pick, league);
    return Number.isFinite(rate) && rate >= 0.7;
  }).length;
}

export function buildPickRows(
  picks: DailyPick[],
  league: LeagueSegment,
  date: string,
): PickRowModel[] {
  return sortPicks(picks, league).map((pick, index) => {
    const out = isOutPick(pick);
    const face = league === "nba" ? nbaTierFace(pick) : null;
    let tier = face ? face.tier : readTier(pick.probability);
    let probabilityText = face ? face.probabilityText : formatPercent(pick.probability);
    let barRate = boardRate(pick, league);
    let tags = pickTags(pick);
    if (out) {
      tier = null;
      probabilityText = "";
      barRate = Number.NaN;
      tags = tags.filter((tag) => tag.injury != null);
    }
    const bar = Number.isFinite(barRate) ? Math.max(0, Math.min(100, barRate * 100)) : 0;
    return {
      key: `${pick.event_id}-${pick.player_name}-${pick.metric}-${pick.direction}`,
      rank: String(index + 1).padStart(2, "0"),
      team: pickTeamCode(pick, league),
      player: pick.player_name,
      matchup: pickMatchup(pick, league),
      propText: propPhrase(pick),
      probabilityText,
      barPercent: bar,
      tierShort: tier ? (league === "nba" ? tier.label : TIER_SHORT[tier.name]) : null,
      tierName: tier?.name ?? null,
      tags,
      dimmed: out,
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
