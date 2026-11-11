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
import { boardRate, nbaTierFace, tierFromBackend } from "./nba-card";
import { isOutPick, isPlayerOutInGame } from "./picks-board";
import { formatPercent, formatTierPercent } from "./player-dd";
import {
  DIRECTION_DISPLAY_NAMES,
  type DailyPick,
  type NBAEvent,
  type TopRead,
} from "./schemas";
import { teamAbbr, teamShortName } from "./team-abbr";

export type ReadTierName = "strong" | "playable" | "lean" | "pass";

export interface ReadTier {
  name: ReadTierName;
  label: string;
}

/**
 * WNBA display bucket. NBA cards do not call this. They use DailyPick.tier.
 */
export function readTier(probability: number | null | undefined): ReadTier | null {
  if (probability == null || !Number.isFinite(probability)) return null;
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

const MARKET_TO_SHORT: Record<string, string> = Object.fromEntries(
  Object.entries(METRIC_TO_MARKET).map(([metric, market]) => [
    market,
    METRIC_SHORT[metric] ?? metric,
  ]),
);

export function metricShort(metric: string): string {
  return METRIC_SHORT[metric] ?? metric;
}

/**
 * Short stat code for an Odds API market key.
 * `player_points` is "PTS". An unknown key keeps its own name, uppercased,
 * so the card does not invent a code the API did not send.
 */
export function marketShort(market: string): string {
  const known = MARKET_TO_SHORT[market];
  if (known) return known;
  return market.replace(/^player_/, "").replace(/_/g, " ").toUpperCase();
}

export function formatThreshold(threshold: number): string {
  if (!Number.isFinite(threshold)) return "—";
  return String(threshold);
}

export function directionLabel(direction: string | null | undefined): string {
  if (typeof direction !== "string") return "—";
  const known = DIRECTION_DISPLAY_NAMES[direction];
  if (known) return known;
  const trimmed = direction.trim().toLowerCase();
  if (!trimmed || trimmed === "null" || trimmed === "undefined") return "—";
  return direction;
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

const ET_WALL =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?([+-]\d{2}:\d{2})$/;

/**
 * Clock face already written on an offset timestamp.
 * `2026-11-10T20:00:00-05:00` is "8:00 PM". The machine zone is not consulted,
 * and a trailing `Z` is rejected so a UTC string is not printed as if it were ET.
 */
export function etWallClock(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const match = ET_WALL.exec(iso.trim());
  if (!match) return null;
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  if (hour > 23 || minute > 59) return null;
  const period = hour >= 12 ? "PM" : "AM";
  const hour12 = hour % 12 === 0 ? 12 : hour % 12;
  return `${hour12}:${minute.toString().padStart(2, "0")} ${period}`;
}

/**
 * Tip time for a game card.
 * NBA events carry `commence_time_et` plus `display_tz` "ET". That wall clock
 * is what the card prints. WNBA and older payloads omit both, and this falls
 * back to `commence_time` in the browser zone. A label other than ET also
 * falls back, so the card does not show an ET face under a different name.
 */
export function eventTipClock(
  event: Pick<NBAEvent, "commence_time" | "commence_time_et" | "display_tz">,
): string | null {
  const zone = event.display_tz?.trim().toUpperCase() ?? "";
  const et = event.commence_time_et?.trim() ?? "";
  if (et && (zone === "" || zone === "ET")) {
    const wall = etWallClock(et);
    if (wall) return wall;
  }
  return boardClock(event.commence_time);
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

export function rankReads(picks: DailyPick[], league: LeagueSegment): DailyPick[] {
  return picks.filter((pick) => !isOutPick(pick)).sort((a, b) => {
    const left = boardRate(a, league);
    const right = boardRate(b, league);
    if (right !== left) return right - left;
    const byName = a.player_name.localeCompare(b.player_name);
    if (byName !== 0) return byName;
    return a.metric.localeCompare(b.metric);
  });
}

function cardTier(pick: DailyPick, league: LeagueSegment): ReadTier | null {
  if (league === "nba") return tierFromBackend(pick.tier);
  return readTier(pick.probability);
}

function cardProbability(pick: DailyPick, league: LeagueSegment): string {
  if (league === "nba") return nbaTierFace(pick).probabilityText;
  return formatPercent(pick.probability);
}

export interface TodayReadCard {
  key: string;
  rank: number;
  player: string;
  matchup: string;
  propText: string;
  probabilityText: string;
  tier: ReadTier | null;
  href: string;
}

export function todayReads(
  picks: DailyPick[],
  league: LeagueSegment,
  date: string,
  limit = 3,
  events: NBAEvent[] = [],
): TodayReadCard[] {
  const tipByEvent = new Map(events.map((event) => [event.event_id, eventTipClock(event)]));
  const eligible = rankReads(picks, league).filter(
    (pick) => league !== "nba" || !isPlayerOutInGame(picks, pick.event_id, pick.player_name),
  );
  return eligible
    .slice(0, limit)
    .map((pick, index) => {
      const time = tipByEvent.get(pick.event_id) ?? boardClock(pick.commence_time);
      const storedTier = tierFromBackend(pick.tier);
      const tier = league === "nba" ? cardTier(pick, league) : storedTier;
      const probabilityText =
        league === "nba"
          ? cardProbability(pick, league)
          : storedTier
            ? formatTierPercent(pick.probability)
            : formatPercent(pick.probability);
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
        probabilityText,
        tier,
        href: readHref(pick, league, date),
      };
    });
}

export type TodayTopSource = "event" | "picks" | "none";

export interface TodayGameCard {
  eventId: string;
  awayAbbr: string;
  homeAbbr: string;
  awayName: string;
  homeName: string;
  time: string | null;
  topText: string | null;
  topProbabilityText: string | null;
  showProbability: boolean;
  tier: ReadTier | null;
  /** `event` means `NBAEvent.top_read`. `picks` is the client fallback. */
  topSource: TodayTopSource;
  href: string;
}

function topReadText(read: TopRead): string {
  return `${playerLastName(read.player)} ${directionLabel(read.side)} ${formatThreshold(read.line)} ${marketShort(read.market)}`;
}

/**
 * Badge for a tier string the API already chose.
 * `null` stays `null`. This does not look at the probability, so a high
 * rate with no tier does not become "Strong play".
 */
function samePublishedProp(pick: DailyPick, eventId: string, read: TopRead): boolean {
  return (
    pick.event_id === eventId &&
    pick.player_name === read.player &&
    pick.direction === read.side &&
    pick.threshold === read.line &&
    knownMarket(pick.metric) === read.market
  );
}

function tierForTopRead(read: TopRead, eventId: string, picks: DailyPick[]): ReadTier | null {
  const match = picks.find((pick) => samePublishedProp(pick, eventId, read));
  return match ? tierFromBackend(match.tier) : null;
}

function topReadIsOut(
  read: TopRead,
  eventId: string,
  picks: DailyPick[],
  league: LeagueSegment,
  injuryPicks: readonly DailyPick[],
): boolean {
  if (league === "nba") return isPlayerOutInGame(injuryPicks, eventId, read.player);
  return picks.some((pick) => isOutPick(pick) && samePublishedProp(pick, eventId, read));
}

export function todayGames(
  events: NBAEvent[],
  picks: DailyPick[],
  league: LeagueSegment,
  date: string,
  /**
   * Injury rows. Defaults to `picks`. Today also passes the last picks
   * body when that request failed, so a known Out player is not left on
   * the fallback `top_read`. An empty list has no injury status. The
   * events payload does not say who is Out, so that `top_read` stays.
   */
  injuryPicks: readonly DailyPick[] = picks,
): TodayGameCard[] {
  const ranked = rankReads(picks, league).filter(
    (pick) => league !== "nba" || !isPlayerOutInGame(injuryPicks, pick.event_id, pick.player_name),
  );
  return events.map((event) => {
    // NBA: the top published pick by blend. top_read is ranked on the
    // historical rate and carries no blend, so it only fills text when no
    // published pick exists, without a percent or tier.
    const publishedRead = event.top_read ?? null;
    const apiRead =
      publishedRead && topReadIsOut(publishedRead, event.event_id, picks, league, injuryPicks)
        ? null
        : publishedRead;
    const best = ranked.find((pick) => pick.event_id === event.event_id) ?? null;
    const useApi = league === "nba" ? best == null && apiRead != null : apiRead != null;
    const pick = useApi ? null : best;
    const tier = useApi
      ? league === "nba"
        ? null
        : tierForTopRead(apiRead!, event.event_id, picks)
      : pick
        ? cardTier(pick, league)
        : null;
    const href = useApi
      ? buildEventDetailHref({
          eventId: event.event_id,
          date,
          player: apiRead!.player,
          market: apiRead!.market,
          threshold: apiRead!.line,
          commenceTime: event.commence_time,
          league,
        })
      : pick
        ? readHref(pick, league, date)
        : buildEventDetailHref({
            eventId: event.event_id,
            date,
            commenceTime: event.commence_time,
            league,
          });
    let topProbabilityText: string | null = null;
    if (useApi && league !== "nba") {
      topProbabilityText = tier
        ? formatTierPercent(apiRead!.probability)
        : formatPercent(apiRead!.probability);
    } else if (pick) {
      topProbabilityText =
        league === "nba"
          ? cardProbability(pick, league)
          : tier
            ? formatTierPercent(pick.probability)
            : formatPercent(pick.probability);
    }
    return {
      eventId: event.event_id,
      awayAbbr: teamAbbr(event.away_team, league),
      homeAbbr: teamAbbr(event.home_team, league),
      awayName: teamShortName(event.away_team, league),
      homeName: teamShortName(event.home_team, league),
      time: eventTipClock(event),
      topText: useApi
        ? topReadText(apiRead!)
        : pick
          ? `${playerLastName(pick.player_name)} ${propText(pick)}`
          : null,
      topProbabilityText,
      showProbability: topProbabilityText != null,
      tier,
      topSource: useApi ? "event" : pick ? "picks" : "none",
      href,
    };
  });
}
