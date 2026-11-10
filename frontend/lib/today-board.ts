/**
 * today-board.ts
 *
 * Turns events and daily picks into the Today cards.
 * Every number on a card comes from those payloads. A game with no
 * pick does not get a made-up percent.
 */

import { format, parseISO } from "date-fns";
import { enUS } from "date-fns/locale";

import { buildEventDetailHref, type LeagueSegment } from "./event-detail-link";
import { METRIC_TO_MARKET, type MetricKey } from "./metric-to-market";
import { formatPercent } from "./player-dd";
import {
  DIRECTION_DISPLAY_NAMES,
  type DailyPick,
  type NBAEvent,
} from "./schemas";
import { teamAbbr, teamShortName } from "./team-abbr";

export type ReadTierName = "strong" | "playable" | "lean" | "pass";

export interface ReadTier {
  name: ReadTierName;
  label: string;
}

/**
 * Display bucket for a probability the API already computed.
 * 70% and 65% match the picks page (high versus medium) and the
 * prototype's Strong / Playable labels. Below that, the daily-picks
 * service does not return a row.
 */
export function readTier(probability: number): ReadTier {
  if (probability >= 0.7) return { name: "strong", label: "Strong play" };
  if (probability >= 0.65) return { name: "playable", label: "Playable" };
  if (probability >= 0.56) return { name: "lean", label: "Lean only" };
  return { name: "pass", label: "Pass" };
}

const METRIC_SHORT: Record<string, string> = {
  points: "PTS",
  rebounds: "REB",
  assists: "AST",
  pra: "PRA",
  ra: "R+A",
  pr: "P+R",
  pa: "P+A",
  threes_made: "3PM",
  steals: "STL",
  ftm: "FTM",
  fgm: "FGM",
  dd: "DD",
};

export function metricShort(metric: string): string {
  return METRIC_SHORT[metric] ?? metric;
}

export function formatThreshold(threshold: number): string {
  if (!Number.isFinite(threshold)) return "—";
  return String(threshold);
}

export function directionLabel(direction: string): string {
  return DIRECTION_DISPLAY_NAMES[direction] ?? direction;
}

export function propText(
  pick: Pick<DailyPick, "direction" | "threshold" | "metric">,
): string {
  return `${directionLabel(pick.direction)} ${formatThreshold(pick.threshold)} ${metricShort(pick.metric)}`;
}

export function playerLastName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : name;
}

export function slateEyebrow(date: string, gameCount: number): string {
  const [year, month, day] = date.split("-").map(Number);
  if (!year || !month || !day) return date;
  const local = new Date(year, month - 1, day);
  const weekday = format(local, "EEE", { locale: enUS }).toUpperCase();
  const mon = format(local, "MMM", { locale: enUS }).toUpperCase();
  const games = gameCount === 1 ? "1 GAME" : `${gameCount} GAMES`;
  return `${weekday} · ${mon} ${day} · ${games}`;
}

export function boardClock(iso: string): string | null {
  try {
    const date = parseISO(iso);
    if (Number.isNaN(date.getTime())) return null;
    return format(date, "h:mm a", { locale: enUS });
  } catch {
    return null;
  }
}

export function matchupLine(
  away: string,
  home: string,
  time: string | null,
): string {
  const teams = `${away} @ ${home}`;
  return time ? `${teams} · ${time}` : teams;
}

function knownMarket(metric: string): string | null {
  if (Object.prototype.hasOwnProperty.call(METRIC_TO_MARKET, metric)) {
    return METRIC_TO_MARKET[metric as MetricKey];
  }
  return null;
}

function readHref(pick: DailyPick, league: LeagueSegment, date: string): string {
  return buildEventDetailHref({
    eventId: pick.event_id,
    date,
    player: pick.player_name,
    market: knownMarket(pick.metric),
    threshold: pick.threshold,
    league,
  });
}

export function rankReads(picks: DailyPick[]): DailyPick[] {
  return [...picks].sort((a, b) => {
    if (b.probability !== a.probability) return b.probability - a.probability;
    const byName = a.player_name.localeCompare(b.player_name);
    if (byName !== 0) return byName;
    return a.metric.localeCompare(b.metric);
  });
}

export interface TodayReadCard {
  key: string;
  rank: number;
  player: string;
  matchup: string;
  propText: string;
  probabilityText: string;
  tier: ReadTier;
  href: string;
}

export function todayReads(
  picks: DailyPick[],
  league: LeagueSegment,
  date: string,
  limit = 3,
): TodayReadCard[] {
  return rankReads(picks)
    .slice(0, limit)
    .map((pick, index) => {
      const time = boardClock(pick.commence_time);
      return {
        key: `${pick.event_id}-${pick.player_name}-${pick.metric}-${pick.direction}`,
        rank: index + 1,
        player: pick.player_name,
        matchup: matchupLine(
          teamAbbr(pick.away_team, league),
          teamAbbr(pick.home_team, league),
          time,
        ),
        propText: propText(pick),
        probabilityText: formatPercent(pick.probability),
        tier: readTier(pick.probability),
        href: readHref(pick, league, date),
      };
    });
}

export interface TodayGameCard {
  eventId: string;
  awayAbbr: string;
  homeAbbr: string;
  awayName: string;
  homeName: string;
  time: string | null;
  topText: string | null;
  topProbabilityText: string | null;
  tier: ReadTier | null;
  href: string;
}

export function todayGames(
  events: NBAEvent[],
  picks: DailyPick[],
  league: LeagueSegment,
  date: string,
): TodayGameCard[] {
  const ranked = rankReads(picks);
  return events.map((event) => {
    const best = ranked.find((pick) => pick.event_id === event.event_id) ?? null;
    return {
      eventId: event.event_id,
      awayAbbr: teamAbbr(event.away_team, league),
      homeAbbr: teamAbbr(event.home_team, league),
      awayName: teamShortName(event.away_team, league),
      homeName: teamShortName(event.home_team, league),
      time: boardClock(event.commence_time),
      topText: best
        ? `${playerLastName(best.player_name)} ${propText(best)}`
        : null,
      topProbabilityText: best ? formatPercent(best.probability) : null,
      tier: best ? readTier(best.probability) : null,
      href: best
        ? readHref(best, league, date)
        : buildEventDetailHref({
            eventId: event.event_id,
            date,
            commenceTime: event.commence_time,
            league,
          }),
    };
  });
}
