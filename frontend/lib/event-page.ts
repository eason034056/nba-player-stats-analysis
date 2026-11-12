/**
 * event-page.ts
 *
 * Turns event, odds, history, projection, and lineup payloads into the
 * game page. A missing field stays blank. Nothing here invents a player,
 * a line, a rank, or a Supports / Neutral / Against label.
 */

import { format, parseISO } from "date-fns";
import { enUS } from "date-fns/locale";

import { nbaTierFace, tierFromBackend, tierProbability } from "./nba-card";
import { canonicalInjuryTag, injuryTag, type InjuryTag } from "./injury-tag";
import { injuryTagForPlayer, isOutPick, isPlayerOutInGame } from "./picks-board";
import { formatPercent, formatTierPercent } from "./player-dd";
import {
  etWallClock,
  formatThreshold,
  playerLastName,
  readTier,
  type ReadTier,
} from "./today-board";
import { METRIC_TO_MARKET, type MetricKey } from "./metric-to-market";
import type { LeagueSegment } from "./event-detail-link";
import { teamAbbr } from "./team-abbr";
import type {
  BulkPropPlayer,
  DailyPick,
  EventLineupStatus,
  GameLog,
  NBAEvent,
  PlayerHistoryResponse,
  PropRead,
  TeamLineup,
} from "./schemas";

export type EventTab = "read" | "log" | "filters" | "odds";

export const EVENT_TABS: ReadonlyArray<{ id: EventTab; label: string }> = [
  { id: "read", label: "Our read" },
  { id: "log", label: "Game log" },
  { id: "filters", label: "Filters" },
  { id: "odds", label: "Odds" },
];

/** NBA mobile drops the Filters tab. Filters open in a sheet from the game log. */
export const NBA_EVENT_TABS: ReadonlyArray<{ id: EventTab; label: string }> = EVENT_TABS.filter(
  (tab) => tab.id !== "filters",
);

const MARKET_TO_METRIC: Record<string, MetricKey> = Object.fromEntries(
  Object.entries(METRIC_TO_MARKET).map(([metric, market]) => [market, metric]),
) as Record<string, MetricKey>;

export function marketToMetric(market: string): MetricKey {
  return MARKET_TO_METRIC[market] ?? "points";
}

export function eventWhen(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    const date = parseISO(iso);
    if (Number.isNaN(date.getTime())) return null;
    const day = format(date, "EEE, MMM d", { locale: enUS });
    const clock = format(date, "h:mm a", { locale: enUS });
    return `${day} · ${clock}`;
  } catch {
    return null;
  }
}

export type LineupTone = "confirmed" | "projected" | "partial" | "unavailable" | "missing";

export interface LineupChipModel {
  abbr: string;
  tone: LineupTone;
  label: string;
}

/**
 * Confirmed is a source-snapshot word (`source_snapshots.*.status`),
 * not the consensus `status` (projected | partial | unavailable).
 * The chip says confirmed only when every snapshot says confirmed.
 */
export function lineupChip(
  abbr: string,
  lineup: TeamLineup | null | undefined,
): LineupChipModel {
  const code = abbr || "Team";
  if (!lineup) {
    return {
      abbr: abbr,
      tone: "missing",
      label: `${code} lineup status unavailable`,
    };
  }
  const statuses = Object.values(lineup.source_snapshots ?? {})
    .map((snapshot) => (snapshot?.status ?? "").trim().toLowerCase())
    .filter(Boolean);
  if (statuses.length > 0 && statuses.every((status) => status === "confirmed")) {
    return { abbr, tone: "confirmed", label: `${code} lineup confirmed` };
  }
  if (lineup.status === "unavailable") {
    return { abbr, tone: "unavailable", label: `${code} lineup unavailable` };
  }
  if (lineup.status === "partial") {
    return { abbr, tone: "partial", label: `${code} lineup partial` };
  }
  return { abbr, tone: "projected", label: `${code} lineup projected` };
}

function statusChip(
  abbr: string,
  status: "confirmed" | "projected" | null | undefined,
): LineupChipModel {
  const code = abbr || "Team";
  if (status === "confirmed") return { abbr, tone: "confirmed", label: `${code} lineup confirmed` };
  if (status === "projected") return { abbr, tone: "projected", label: `${code} lineup projected` };
  return { abbr, tone: "missing", label: `${code} lineup status unavailable` };
}

/**
 * NBA chips come from `NBAEvent.lineup_status`. WNBA keeps the lineup
 * snapshot word, because WNBA events do not carry `lineup_status`.
 */
export function eventLineupChips(args: {
  league: LeagueSegment;
  awayAbbr: string;
  homeAbbr: string;
  status: EventLineupStatus | null | undefined;
  awayLineup: TeamLineup | null;
  homeLineup: TeamLineup | null;
}): LineupChipModel[] {
  if (args.league !== "nba") {
    return [lineupChip(args.awayAbbr, args.awayLineup), lineupChip(args.homeAbbr, args.homeLineup)];
  }
  return [statusChip(args.awayAbbr, args.status?.away), statusChip(args.homeAbbr, args.status?.home)];
}

const ET_DATE = /^(\d{4})-(\d{2})-(\d{2})T/;

function etDateLabel(iso: string): string | null {
  const match = ET_DATE.exec(iso.trim());
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return null;
  return format(date, "EEE, MMM d", { locale: enUS });
}

/**
 * Web clock is "Tue, Nov 10 · 7:30 PM ET" when the event carries an ET
 * face. WNBA and a payload with no `commence_time_et` keep `eventWhen`,
 * which does not invent a zone label.
 */
export function eventClock(
  event: Pick<NBAEvent, "commence_time" | "commence_time_et" | "display_tz"> | null | undefined,
  league: LeagueSegment,
): { web: string | null; mobile: string | null } {
  if (!event) return { web: null, mobile: null };
  if (league === "nba") {
    const zone = event.display_tz?.trim().toUpperCase() ?? "";
    const et = event.commence_time_et?.trim() ?? "";
    if (et && (zone === "" || zone === "ET")) {
      const clock = etWallClock(et);
      const day = etDateLabel(et);
      if (clock && day) {
        const suffix = zone === "ET" ? " ET" : "";
        return { web: `${day} · ${clock}${suffix}`, mobile: `${clock}${suffix}` };
      }
    }
  }
  const web = eventWhen(event.commence_time);
  return { web, mobile: web };
}

/** Position and team with a separator only when both exist. */
export function joinMeta(
  position: string | null | undefined,
  team: string | null | undefined,
  separator: string,
): string | null {
  const pos = position?.trim() ?? "";
  const club = team?.trim() ?? "";
  if (pos && club) return `${pos}${separator}${club}`;
  return pos || club || null;
}

/**
 * A percent printed in the same control as a backend tier rounds down.
 * No tier keeps half-away `formatPercent`. This does not choose the tier.
 */
export function percentBesideTier(
  probability: number | null | undefined,
  tier: ReadTier | null,
): string {
  if (tier) return formatTierPercent(probability);
  return formatPercent(probability);
}

const READ_MARKET_NAME: Record<string, string> = {
  player_points: "points",
  player_rebounds: "rebounds",
  player_assists: "assists",
  player_threes: "threes",
  player_points_rebounds_assists: "pts+reb+ast",
  player_steals: "steals",
  player_frees_made: "free throws",
  player_field_goals: "field goals",
  player_rebounds_assists: "reb+ast",
  player_points_rebounds: "pts+reb",
  player_points_assists: "pts+ast",
  player_double_double: "double-double",
};

export function readMarketName(market: string, fallback: string): string {
  return READ_MARKET_NAME[market] ?? fallback.trim().toLowerCase();
}

export interface FairSplit {
  sourceLabel: string;
  overLabel: string;
  underLabel: string;
  overText: string;
  underText: string;
  /** Width of the over segment. The two texts are the payload numbers. */
  overWidth: number;
}

function splitWidth(over: number, under: number): number {
  const total = over + under;
  if (!Number.isFinite(total) || total <= 0) return 0;
  return Math.max(0, Math.min(100, (over / total) * 100));
}

function finite(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function consensusSplit(
  consensus: {
    p_over_fair?: number | null;
    p_under_fair?: number | null;
    p_yes_fair?: number | null;
    p_no_fair?: number | null;
  } | null | undefined,
  binary: boolean,
): FairSplit | null {
  if (!consensus) return null;
  const over = binary ? consensus.p_yes_fair : consensus.p_over_fair;
  const under = binary ? consensus.p_no_fair : consensus.p_under_fair;
  if (!finite(over) || !finite(under)) return null;
  return {
    sourceLabel: "No-vig consensus",
    overLabel: binary ? "Yes" : "Over",
    underLabel: binary ? "No" : "Under",
    overText: formatPercent(over),
    underText: formatPercent(under),
    overWidth: splitWidth(over, under),
  };
}

export function historySplit(
  history: Pick<PlayerHistoryResponse, "p_over" | "p_under"> | null | undefined,
): FairSplit | null {
  if (!history || !finite(history.p_over) || !finite(history.p_under)) return null;
  return {
    sourceLabel: "Hit rate",
    overLabel: "Over",
    underLabel: "Under",
    overText: formatPercent(history.p_over),
    underText: formatPercent(history.p_under),
    overWidth: splitWidth(history.p_over, history.p_under),
  };
}

export type SignalVerdict = "supports" | "neutral" | "against";

export interface ReadSignal {
  key: string;
  label: string;
  detail: string;
  value: string | null;
  /** 0–1 when the value is a rate. Rank and projection do not draw a meter. */
  meter: number | null;
  /** Null when the payload did not judge the signal. That is not "neutral". */
  verdict: SignalVerdict | null;
}

export interface SignalInput {
  binary: boolean;
  line: number | null;
  consensus: {
    p_over_fair?: number | null;
    p_under_fair?: number | null;
    p_yes_fair?: number | null;
    p_no_fair?: number | null;
  } | null;
  last10: GameLog[];
  history: Pick<PlayerHistoryResponse, "p_over" | "p_under" | "n_games" | "season_mean"> | null;
  pick: DailyPick | null;
  market: string;
}

function marketSignal(input: SignalInput): Omit<ReadSignal, "verdict"> {
  const over = input.binary ? input.consensus?.p_yes_fair : input.consensus?.p_over_fair;
  const under = input.binary ? input.consensus?.p_no_fair : input.consensus?.p_under_fair;
  const overName = input.binary ? "Yes" : "Over";
  const underName = input.binary ? "No" : "Under";
  if (!finite(over) || !finite(under)) {
    return {
      key: "market",
      label: "Market price",
      detail: "No-vig consensus is not on this response.",
      value: null,
      meter: null,
    };
  }
  return {
    key: "market",
    label: "Market price",
    detail: `No-vig ${overName.toLowerCase()} ${formatPercent(over)} · ${underName.toLowerCase()} ${formatPercent(under)}`,
    value: formatPercent(over),
    meter: over,
  };
}

function last10Signal(input: SignalInput): Omit<ReadSignal, "verdict"> {
  if (input.binary) {
    return {
      key: "last10",
      label: "Last 10 games",
      detail: "Last-10 bars are for Over/Under stats. Double-double uses its own history.",
      value: null,
      meter: null,
    };
  }
  if (input.line == null) {
    return {
      key: "last10",
      label: "Last 10 games",
      detail: "Last-10 hit rate needs a posted line.",
      value: null,
      meter: null,
    };
  }
  if (input.last10.length === 0) {
    return {
      key: "last10",
      label: "Last 10 games",
      detail: "No last-10 games on this response.",
      value: null,
      meter: null,
    };
  }
  const hits = input.last10.filter((game) => game.value > input.line!).length;
  const total = input.last10.length;
  return {
    key: "last10",
    label: "Last 10 games",
    detail: `Cleared ${formatThreshold(input.line)} in ${hits} of ${total}.`,
    value: `${hits}/${total}`,
    meter: hits / total,
  };
}

function historySignal(input: SignalInput): Omit<ReadSignal, "verdict"> {
  if (input.binary) {
    return {
      key: "history",
      label: "All-game hit rate",
      detail: "The continuous history route does not score a double-double.",
      value: null,
      meter: null,
    };
  }
  const over = input.history?.p_over;
  const under = input.history?.p_under;
  if (!finite(over) || !finite(under)) {
    return {
      key: "history",
      label: "All-game hit rate",
      detail: "Player history has no season field. This row is every returned game, and none came back.",
      value: null,
      meter: null,
    };
  }
  const games = input.history?.n_games;
  const sample = finite(games) ? `${games} games` : "the returned games";
  const seasonMean = input.history?.season_mean;
  const seasonSentence =
    typeof seasonMean === "number" && Number.isFinite(seasonMean)
      ? ` Season mean ${seasonMean.toFixed(1)}.`
      : "";
  return {
    key: "history",
    label: "All-game hit rate",
    detail: `Over ${formatPercent(over)} · under ${formatPercent(under)} across ${sample}. Not a season filter.${seasonSentence}`,
    value: formatPercent(over),
    meter: over,
  };
}

function projectedNumber(input: SignalInput): number | null {
  if (input.pick && input.pick.metric === marketToMetric(input.market) && finite(input.pick.projected_value)) {
    return input.pick.projected_value;
  }
  return null;
}

function projectionSignal(input: SignalInput): Omit<ReadSignal, "verdict"> {
  const projected = projectedNumber(input);
  if (projected == null) {
    return {
      key: "projection",
      label: "Projection",
      detail: "Projection is not available for WNBA.",
      value: null,
      meter: null,
    };
  }
  const edge =
    input.line == null ? null : Math.round((projected - input.line) * 10) / 10;
  const edgeText =
    edge == null ? "Posted line is not on this response." : `${edge > 0 ? "+" : ""}${edge.toFixed(1)} vs the posted line.`;
  return {
    key: "projection",
    label: "Projection",
    detail: edgeText,
    value: projected.toFixed(1),
    meter: null,
  };
}

function defenseSignal(input: SignalInput): Omit<ReadSignal, "verdict"> {
  const position = firstNumber(input.pick?.opponent_position_rank);
  const overall = firstNumber(input.pick?.opponent_rank);
  if (position != null) {
    return {
      key: "defense",
      label: "Opponent defense",
      detail: "Opponent defense vs this position.",
      value: `#${position}`,
      meter: null,
    };
  }
  if (overall != null) {
    return {
      key: "defense",
      label: "Opponent defense",
      detail: "Opponent overall defense rank.",
      value: `#${overall}`,
      meter: null,
    };
  }
  return {
    key: "defense",
    label: "Opponent defense",
    detail: "Opponent defense rank is not on this response.",
    value: null,
    meter: null,
  };
}

function firstNumber(...values: Array<number | null | undefined>): number | null {
  for (const value of values) {
    if (finite(value)) return value;
  }
  return null;
}

export function buildReadSignals(input: SignalInput): ReadSignal[] {
  return [
    marketSignal(input),
    last10Signal(input),
    historySignal(input),
    projectionSignal(input),
    defenseSignal(input),
  ].map((signal) => ({ ...signal, verdict: null }));
}

export interface SlipSeed {
  player_name: string;
  player_team: string;
  event_id: string;
  home_team: string;
  away_team: string;
  commence_time: string;
  metric: string;
  threshold: number;
  direction: string;
  probability: number;
  n_games: number;
  tier?: string | null;
  combined_probability?: number | null;
}

export interface EventPlayerRow {
  name: string;
  team: string | null;
  position: string | null;
  /** Backend tier for this row. Null when the pick has no tier. */
  tier: ReadTier | null;
  lineText: string;
  leanText: string;
  hasLean: boolean;
  probability: number | null;
  /** True only when injury_status is Out. A raw word of "out" does not set this. */
  listedOut: boolean;
  /** NBA injury chip. Null on WNBA and when the player has no status word. */
  injury: InjuryTag | null;
}

/** Fold a name so CSV and lineup spellings compare as the same person. */
function nameKey(name: string): string {
  const folded = name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/-/g, " ")
    .replace(/[.'’`]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
  return joinInitials(folded);
}

function joinInitials(folded: string): string {
  const out: string[] = [];
  let initials = "";
  for (const part of folded.split(" ")) {
    if (part.length === 1) {
      initials += part;
      continue;
    }
    if (initials) {
      out.push(initials);
      initials = "";
    }
    if (part) out.push(part);
  }
  if (initials) out.push(initials);
  return out.join(" ");
}

function namesMatch(a: string, b: string): boolean {
  const left = nameKey(a);
  const right = nameKey(b);
  return left.length > 0 && left === right;
}

function onRoster(name: string, lineup: TeamLineup | null | undefined): boolean {
  if (!lineup) return false;
  const players = [...(lineup.starters ?? []), ...(lineup.bench_candidates ?? [])];
  return players.some((player) => namesMatch(player, name));
}

function samePlayer(left: string, right: string): boolean {
  return left.trim().toLowerCase() === right.trim().toLowerCase();
}

function readForPlayer(reads: PropRead[] | undefined, name: string): PropRead | null {
  return reads?.find((read) => samePlayer(read.player, name)) ?? null;
}

function bulkForPlayer(players: BulkPropPlayer[] | undefined, name: string): BulkPropPlayer | null {
  return players?.find((player) => samePlayer(player.player, name)) ?? null;
}

export type ReadsStatus = "loading" | "error" | "ready";

export function nbaReadsStatus(isLoading: boolean, isError: boolean): ReadsStatus {
  if (isLoading) return "loading";
  if (isError) return "error";
  return "ready";
}

export function nbaRequestNote(kind: "reads" | "props", status: ReadsStatus): string | null {
  if (status === "loading") return kind === "reads" ? "Loading reads." : "Loading props.";
  if (status === "error") return kind === "reads" ? "Reads failed." : "Props failed.";
  return null;
}

function leanLetter(side: string | null | undefined): "U" | "O" | null {
  if (side === "under") return "U";
  if (side === "over") return "O";
  return null;
}

function leanLine(letter: "U" | "O" | null, face: { probabilityText: string; tier: { label: string } | null }, rate: number | null) {
  const label = face.tier ? ` ${face.tier.label}` : "";
  if (!letter) return { text: "—", rate };
  return { text: `${letter} ${face.probabilityText}${label}`, rate };
}

/** Line, side, probability, and tier from the daily pick alone. */
function nbaLeanFromPick(pick: DailyPick): { text: string; rate: number | null } {
  const face = nbaTierFace(pick);
  return leanLine(leanLetter(pick.direction), face, tierProbability(pick));
}

/** Line, side, probability, and tier from the reads entry alone. */
function nbaLeanFromRead(read: PropRead): { text: string; rate: number | null } {
  const face = nbaTierFace({
    combined_probability: read.combined_probability,
    tier: read.tier,
  });
  const rate =
    typeof read.combined_probability === "number" && Number.isFinite(read.combined_probability)
      ? read.combined_probability
      : null;
  return leanLine(leanLetter(read.side), face, rate);
}

export function eventPlayerRows(args: {
  suggested: string[];
  picks: DailyPick[];
  metric: string;
  eventId: string;
  selectedName: string;
  postedLine: number | null;
  awayLineup: TeamLineup | null;
  homeLineup: TeamLineup | null;
  awayAbbr: string;
  homeAbbr: string;
  league: LeagueSegment;
  reads?: PropRead[];
  readsStatus?: ReadsStatus;
  bulkPlayers?: BulkPropPlayer[];
}): EventPlayerRow[] {
  const metric = marketToMetric(args.metric);
  const picks = args.picks.filter(
    (pick) => pick.event_id === args.eventId && pick.metric === metric,
  );
  const byName = new Map<string, DailyPick>();
  for (const pick of picks) {
    const key = pick.player_name.trim().toLowerCase();
    const current = byName.get(key);
    if (!current || pick.probability > current.probability) byName.set(key, pick);
  }
  const names: string[] = [];
  const seen = new Set<string>();
  const push = (name: string) => {
    const key = name.trim().toLowerCase();
    if (!key || seen.has(key)) return;
    seen.add(key);
    names.push(name.trim());
  };
  for (const pick of picks) push(pick.player_name);
  for (const read of args.reads ?? []) push(read.player);
  for (const name of args.suggested) push(name);
  if (args.selectedName) push(args.selectedName);

  const rows = names.map((name) => {
    const pick = byName.get(name.toLowerCase()) ?? null;
    const read = args.league === "nba" ? readForPlayer(args.reads, name) : null;
    const bulk = args.league === "nba" ? bulkForPlayer(args.bulkPlayers, name) : null;
    const teamFromPick = pick?.player_team_code?.trim()
      ? pick.player_team_code
      : pick
        ? teamAbbr(pick.player_team, args.league) || null
        : null;
    const onAway = onRoster(name, args.awayLineup);
    const onHome = onRoster(name, args.homeLineup);
    const lineupTeam =
      onAway && !onHome ? args.awayAbbr : onHome && !onAway ? args.homeAbbr : null;
    const inGame = (code: string | null | undefined) =>
      code && (code === args.awayAbbr || code === args.homeAbbr) ? code : null;
    // Tonight's lineup beats a CSV or projection club. A code that is
    // neither home nor away (CHI on BOS@PHI) is not shown. The snapshot
    // team_code is held to the same rule.
    const team = lineupTeam || inGame(teamFromPick) || inGame(bulk?.team_code?.trim());
    const selected = namesMatch(name, args.selectedName);
    const readsStatus = args.league === "nba" ? args.readsStatus ?? "ready" : "ready";
    const sourcePick = args.league === "nba" ? pick : null;
    const sourceRead = args.league === "nba" && sourcePick == null ? read : null;
    const line =
      sourcePick != null
        ? sourcePick.threshold
        : sourceRead != null
          ? sourceRead.line
          : pick != null
            ? pick.threshold
            : selected && args.postedLine != null
              ? args.postedLine
              : null;
    const out =
      args.league === "nba" && isPlayerOutInGame(args.picks, args.eventId, name);
    const nba = out
      ? { text: "Out", rate: null }
      : sourcePick != null
        ? nbaLeanFromPick(sourcePick)
        : sourceRead != null
          ? nbaLeanFromRead(sourceRead)
          : args.league === "nba" && readsStatus === "loading"
            ? { text: "Loading", rate: null }
            : args.league === "nba" && readsStatus === "error"
              ? { text: "Unavailable", rate: null }
              : null;
    const tier = out
      ? null
      : args.league === "nba" && sourcePick
        ? tierFromBackend(sourcePick.tier)
        : args.league === "nba" && sourceRead
          ? tierFromBackend(sourceRead.tier)
          : null;
    return {
      name,
      team: team || null,
      position: pick?.position?.trim() || bulk?.position?.trim() || null,
      tier,
      lineText: line == null ? "—" : formatThreshold(line),
      leanText: out
        ? "Out"
        : nba
          ? nba.text
          : pick
            ? `${pick.direction === "under" ? "U" : "O"} ${formatPercent(pick.probability)}`
            : "No read",
      hasLean: out ? false : nba != null || pick != null,
      probability: out ? null : nba?.rate ?? pick?.probability ?? null,
      listedOut: out,
      injury:
        args.league === "nba"
          ? out
            ? injuryTagForPlayer(args.picks, args.eventId, name)
            : pick
              ? injuryTag(pick.injury_status_raw, pick.injury_status)
              : null
          : null,
    };
  });

  return rows.sort((a, b) => {
    if (a.hasLean !== b.hasLean) return a.hasLean ? -1 : 1;
    if (a.probability != null && b.probability != null && a.probability !== b.probability) {
      return b.probability - a.probability;
    }
    return a.name.localeCompare(b.name);
  });
}

function rosterNames(lineup: TeamLineup | null | undefined): string[] {
  if (!lineup) return [];
  return [...(lineup.starters ?? []), ...(lineup.bench_candidates ?? [])];
}

/**
 * Teammates for the event filter.
 *
 * ``historyTeammates`` is already limited to a club in this game. A
 * teammate who is out tonight is absent from the lineup and still belongs
 * in the filter. When the player is on exactly one side, that side's
 * starters and bench are appended. Names already in the history list stay
 * in that order. The lineup list is used alone only when history is empty.
 * The player himself is left out.
 */
export function eventTeammates(args: {
  player: string;
  awayLineup: TeamLineup | null;
  homeLineup: TeamLineup | null;
  historyTeammates: string[];
}): string[] {
  const history = args.historyTeammates.filter((name) => name.trim() && !namesMatch(name, args.player));
  const onAway = onRoster(args.player, args.awayLineup);
  const onHome = onRoster(args.player, args.homeLineup);
  const side = onAway && !onHome ? args.awayLineup : onHome && !onAway ? args.homeLineup : null;
  if (!side) return history;
  const lineup = rosterNames(side).filter((name) => name.trim() && !namesMatch(name, args.player));
  if (history.length === 0) return uniqueNames(lineup);
  return uniqueNames([...history, ...lineup]);
}

function uniqueNames(names: string[]): string[] {
  const out: string[] = [];
  for (const name of names) {
    const trimmed = name.trim();
    if (!trimmed || out.some((existing) => namesMatch(existing, trimmed))) continue;
    out.push(trimmed);
  }
  return out;
}

export interface PostedLineRow {
  line: number;
  line_is_synthetic?: boolean | null;
  market_kind?: string | null;
}

/** Modal posted line. A binary or synthetic row is not a stat line. */
export function postedLine(rows: PostedLineRow[] | null | undefined): number | null {
  if (!rows?.length) return null;
  const lines = rows
    .filter((row) => row.line_is_synthetic !== true && row.market_kind !== "binary")
    .map((row) => row.line)
    .filter((line) => Number.isFinite(line));
  if (lines.length === 0) return null;
  const counts = new Map<number, number>();
  for (const line of lines) {
    const rounded = Math.round(line * 10) / 10;
    counts.set(rounded, (counts.get(rounded) ?? 0) + 1);
  }
  let best: number | null = null;
  let bestCount = 0;
  counts.forEach((count, value) => {
    if (count > bestCount) {
      best = value;
      bestCount = count;
    }
  });
  if (bestCount > 1 && best != null) return best;
  const sorted = [...lines].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const median = sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  return Math.round(median * 10) / 10;
}

export function chartLine(posted: number | null, steps: number): number | null {
  if (posted == null || !Number.isFinite(posted)) return null;
  const next = Math.round((posted + steps * 0.5) * 10) / 10;
  return Math.max(0, next);
}

export interface ChartBar {
  key: string;
  value: number;
  valueText: string;
  opponent: string;
  over: boolean | null;
  date: string;
  dateFull: string;
  minutes: number;
  starter: boolean;
  heightPct: number;
}

export interface ChartTick {
  pos: string;
  label: string;
}

export interface ChartModel {
  bars: ChartBar[];
  linePct: number | null;
  lineText: string | null;
  ticks: ChartTick[];
  empty: boolean;
}

function tickLabel(value: number): string {
  if (value >= 10) return String(Math.round(value));
  return value.toFixed(1);
}

export function gameLogChart(logs: GameLog[], line: number | null): ChartModel {
  const ordered = [...logs].sort((a, b) => {
    if (a.date_full && b.date_full && a.date_full !== b.date_full) {
      return a.date_full < b.date_full ? -1 : 1;
    }
    return 0;
  });
  if (ordered.length === 0) {
    return { bars: [], linePct: null, lineText: line == null ? null : formatThreshold(line), ticks: [], empty: true };
  }
  const peak = Math.max(...ordered.map((game) => game.value), line ?? 0, 1);
  const max = peak * 1.15;
  const bars = ordered.map((game, index) => ({
    key: `${game.date_full || game.date}-${index}`,
    value: game.value,
    valueText: Number.isInteger(game.value) ? String(game.value) : game.value.toFixed(1),
    opponent: game.opponent,
    over: line == null ? null : game.value > line,
    date: game.date,
    dateFull: game.date_full,
    minutes: game.minutes,
    starter: game.is_starter,
    heightPct: Math.max(2, (game.value / max) * 100),
  }));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => ({
    pos: `${fraction * 100}%`,
    label: tickLabel(max * fraction),
  }));
  return {
    bars,
    linePct: line == null ? null : (line / max) * 100,
    lineText: line == null ? null : formatThreshold(line),
    ticks,
    empty: false,
  };
}

export interface OurReadModel {
  player: string | null;
  meta: string | null;
  headlineLead: string;
  headlineMarket: string | null;
  caption: string;
  tier: ReadTier | null;
  bar: FairSplit | null;
  signals: ReadSignal[];
  primary: SlipSeed | null;
  other: SlipSeed | null;
  /** Probability printed next to the tier. The slip still stores `primary.probability`. */
  leanProbability: number | null;
  /** The selected player is listed Out. Ask stays hidden. */
  listedOut: boolean;
  /** NBA injury chip for this read. Null on WNBA. */
  injury: InjuryTag | null;
}

function sameLine(a: number | null | undefined, b: number | null): boolean {
  if (a == null || b == null) return false;
  return Math.abs(a - b) < 0.051;
}

function historySide(
  history: PlayerHistoryResponse | null,
  line: number | null,
  direction: "over" | "under",
): { probability: number; nGames: number } | null {
  if (!history || !sameLine(history.threshold, line)) return null;
  const probability = direction === "over" ? history.p_over : history.p_under;
  if (!finite(probability)) return null;
  return { probability, nGames: history.n_games };
}

function asVerdict(value: string | null | undefined): SignalVerdict | null {
  if (value === "supports" || value === "neutral" || value === "against") return value;
  return null;
}

function meterFromDisplayed(value: string | null, verdict: SignalVerdict | null): number | null {
  if (!verdict || !value) return null;
  const percent = /^(-?\d+(?:\.\d+)?)%$/.exec(value.trim());
  if (percent) {
    const n = Number(percent[1]);
    if (!Number.isFinite(n)) return null;
    return Math.max(0, Math.min(1, n / 100));
  }
  const ratio = /^(\d+)\s*\/\s*(\d+)$/.exec(value.trim());
  if (!ratio) return null;
  const den = Number(ratio[2]);
  if (den <= 0) return null;
  return Math.max(0, Math.min(1, Number(ratio[1]) / den));
}

function signedTenths(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  const abs = Math.abs(rounded).toFixed(1);
  if (rounded > 0) return `+${abs}`;
  if (rounded < 0) return `\u2212${abs}`;
  return abs;
}

function oneDecimal(value: number): string {
  return (Math.round(value * 10) / 10).toFixed(1);
}

function defenseWord(rank: number): "Easy" | "Average" | "Tough" {
  if (rank <= 10) return "Easy";
  if (rank > 20) return "Tough";
  return "Average";
}

function rankFromValue(value: string | null): number | null {
  const match = /^#(\d+(?:\.\d+)?)$/.exec(value?.trim() ?? "");
  if (!match) return null;
  const n = Number(match[1]);
  return Number.isFinite(n) ? n : null;
}

function opponentCode(
  pick: DailyPick,
  homeTeam: string,
  awayTeam: string,
  league: LeagueSegment,
): string | null {
  const code = (pick.player_team_code || teamAbbr(pick.player_team, league) || "").toUpperCase();
  const home = teamAbbr(homeTeam || pick.home_team, league);
  const away = teamAbbr(awayTeam || pick.away_team, league);
  if (code && home && code === home) return away || null;
  if (code && away && code === away) return home || null;
  return null;
}

function signalDetail(
  key: string,
  pick: DailyPick,
  value: string | null,
  side: string,
  line: number,
  homeTeam: string,
  awayTeam: string,
  league: LeagueSegment,
): string {
  if (key === "market") {
    const books = pick.bookmakers_count;
    return `No-vig ${side} across ${books} ${books === 1 ? "book" : "books"}`;
  }
  if (key === "last10") {
    const match = value ? /^(\d+)\s*\/\s*(\d+)$/.exec(value.trim()) : null;
    if (!match || !Number.isFinite(line)) return "Last 10 games are not on this response.";
    return `Went ${side} ${formatThreshold(line)} in ${match[1]} of ${match[2]}`;
  }
  if (key === "history") {
    if (!value) return "All-game hit rate is not on this response.";
    return `Across ${pick.n_games} games`;
  }
  if (key === "projection") {
    if (!finite(pick.projected_value)) return "Projected value is not on this response.";
    const projected = `${oneDecimal(pick.projected_value)} projected`;
    if (!finite(pick.edge)) return projected;
    return `${projected}, ${signedTenths(pick.edge)} vs line`;
  }
  if (key === "defense") {
    const rank = rankFromValue(value);
    if (rank == null) return "Opponent defense rank is not on this response.";
    const shown = Number.isInteger(rank) ? String(rank) : String(rank);
    const opp = opponentCode(pick, homeTeam, awayTeam, league);
    const pos = pick.position?.trim();
    const who = opp ? `${opp} ranks #${shown}` : `Rank #${shown}`;
    const vs = pos ? ` vs ${pos}s` : "";
    return `${who}${vs} · ${defenseWord(rank)}`;
  }
  if (!value) return "Not on this response.";
  return "";
}

function signalsFromPick(
  pick: DailyPick,
  homeTeam: string,
  awayTeam: string,
  league: LeagueSegment,
): ReadSignal[] | null {
  if (!pick.signals || pick.signals.length === 0) return null;
  const side = pick.direction === "under" ? "under" : pick.direction === "over" ? "over" : pick.direction;
  return pick.signals.map((signal) => {
    const verdict = asVerdict(signal.verdict);
    const value = signal.value?.trim() ? signal.value : null;
    return {
      key: signal.key,
      label: signal.label,
      value,
      detail: signalDetail(signal.key, pick, value, side, pick.threshold, homeTeam, awayTeam, league),
      meter: meterFromDisplayed(value, verdict),
      verdict,
    };
  });
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

export type OtherSideSource = "model" | "history";

/**
 * Rate for the opposite-side slip button.
 * A finite `combined_probability` stores `1 − combined_probability`, clamped
 * to [0, 1], matching the model bar. Null, NaN, and non-finite values keep
 * the historical opposite field when that field is finite. A null result
 * means the caller should try the history response, then hide the button.
 * This does not choose a tier.
 */
export function nbaOtherSideProbability(
  combined: number | null | undefined,
  historical: number | null | undefined,
): { probability: number; source: OtherSideSource } | null {
  if (finite(combined)) {
    return { probability: clamp01(1 - combined), source: "model" };
  }
  if (finite(historical)) {
    return { probability: clamp01(historical), source: "history" };
  }
  return null;
}

function modelSplit(combined: number, side: "over" | "under", binary: boolean): FairSplit {
  const lean = clamp01(combined);
  const over = side === "over" ? lean : 1 - lean;
  const under = 1 - over;
  return {
    sourceLabel: "Model",
    overLabel: binary ? "Yes" : "Over",
    underLabel: binary ? "No" : "Under",
    overText: formatTierPercent(over),
    underText: formatTierPercent(under),
    overWidth: over * 100,
  };
}

function buildNbaRead(args: {
  player: string;
  marketName: string;
  market: string;
  binary: boolean;
  eventId: string;
  homeTeam: string;
  awayTeam: string;
  commenceTime: string;
  team: string | null;
  position: string | null;
  line: number | null;
  pick: DailyPick | null;
  history: PlayerHistoryResponse | null;
  read?: PropRead | null;
  listedOut?: boolean;
}): OurReadModel {
  const meta = joinMeta(args.position, args.team, ", ");
  const headlineMarket = readMarketName(args.market, args.marketName);
  const base = {
    player_name: args.player,
    player_team: args.team ?? "",
    event_id: args.eventId,
    home_team: args.homeTeam,
    away_team: args.awayTeam,
    commence_time: args.commenceTime,
    metric: marketToMetric(args.market),
  };
  const pick = args.pick;
  const postedRead = args.read;
  if (args.listedOut || (pick != null && isOutPick(pick))) {
    const headlineLead = pick
      ? `${pick.direction === "under" ? "Under" : "Over"} ${formatThreshold(pick.threshold)}`
      : args.line == null
        ? "No posted line"
        : `Line ${formatThreshold(args.line)}`;
    return {
      player: args.player,
      meta,
      headlineLead,
      headlineMarket,
      caption: "Listed Out. No model read.",
      tier: null,
      bar: null,
      signals: [],
      primary: null,
      other: null,
      leanProbability: null,
      listedOut: true,
      injury:
        pick != null && isOutPick(pick)
          ? injuryTag(pick.injury_status_raw, pick.injury_status) ?? canonicalInjuryTag("out")
          : canonicalInjuryTag("out"),
    };
  }
  if (!pick) {
    if (postedRead && (postedRead.side === "over" || postedRead.side === "under")) {
      const face = nbaTierFace(postedRead);
      return {
        player: args.player,
        meta,
        headlineLead: `${postedRead.side === "under" ? "Under" : "Over"} ${formatThreshold(postedRead.line)}`,
        headlineMarket,
        caption: `Combined probability ${face.probabilityText}.`,
        tier: face.tier,
        bar: null,
        signals: [],
        primary: null,
        other: null,
        leanProbability: null,
        listedOut: false,
        injury: null,
      };
    }
    return {
      player: args.player,
      meta,
      headlineLead: args.line == null ? "No posted line" : `Line ${formatThreshold(args.line)}`,
      headlineMarket,
      caption: "No stored read for this player.",
      tier: null,
      bar: null,
      signals: [],
      primary: null,
      other: null,
      leanProbability: null,
      listedOut: false,
      injury: null,
    };
  }
  const direction = pick.direction === "under" ? "under" : "over";
  const otherDirection = direction === "over" ? "under" : "over";
  const tier = tierFromBackend(pick.tier);
  const signals = signalsFromPick(pick, args.homeTeam, args.awayTeam, "nba");
  const sideWord = direction;
  const signalSentence =
    signals == null
      ? "Signal verdicts are not on this response."
      : `${signals.filter((signal) => signal.verdict === "supports").length} of ${signals.length} signals support the ${sideWord}.`;
  const combinedText = finite(pick.combined_probability)
    ? formatTierPercent(pick.combined_probability)
    : "—";
  const caption = `Combined probability ${combinedText}. Historical hit rate ${formatPercent(pick.probability)} over ${pick.n_games} games. ${signalSentence}`;
  const primary: SlipSeed = {
    ...base,
    player_team: pick.player_team || base.player_team,
    threshold: pick.threshold,
    direction,
    probability: pick.probability,
    n_games: pick.n_games,
    tier: pick.tier ?? null,
    combined_probability: pick.combined_probability ?? null,
  };
  // Primary stores pick.probability. The number beside a tier is
  // tierProbability, floored. The other side stores 1 − combined_probability
  // when that blend is finite, on both `probability` and
  // `combined_probability`, so the slip saves the same complement the model
  // bar draws. The tier stays null. When the blend is missing, fall back to
  // the pick's opposite field (p_under / p_over), then the /history rate for
  // that side and line. That fallback leaves combined_probability null and
  // the button says History. The printed percent is formatTierPercent, the
  // same floor the slip card uses. This does not choose a tier.
  let other: SlipSeed | null = null;
  const oppositeField = otherDirection === "over" ? pick.p_over : pick.p_under;
  const decided = nbaOtherSideProbability(pick.combined_probability, oppositeField);
  if (decided) {
    other = {
      ...primary,
      direction: otherDirection,
      probability: decided.probability,
      tier: null,
      combined_probability: decided.source === "model" ? decided.probability : null,
    };
  } else {
    const otherSide = historySide(args.history, pick.threshold, otherDirection);
    if (otherSide) {
      other = {
        ...primary,
        direction: otherDirection,
        probability: otherSide.probability,
        n_games: otherSide.nGames,
        tier: null,
        combined_probability: null,
      };
    }
  }
  const bar = finite(pick.combined_probability)
    ? modelSplit(pick.combined_probability, direction, args.binary)
    : null;
  return {
    player: args.player,
    meta,
    headlineLead: `${direction === "under" ? "Under" : "Over"} ${formatThreshold(pick.threshold)}`,
    headlineMarket,
    caption,
    tier,
    bar,
    signals: signals ?? [],
    primary,
    other,
    leanProbability: finite(pick.probability) ? pick.probability : null,
    listedOut: false,
    injury: injuryTag(pick.injury_status_raw, pick.injury_status),
  };
}

export function buildOurRead(args: {
  player: string;
  marketName: string;
  market: string;
  binary: boolean;
  eventId: string;
  homeTeam: string;
  awayTeam: string;
  commenceTime: string;
  team: string | null;
  position: string | null;
  line: number | null;
  pick: DailyPick | null;
  consensus: SignalInput["consensus"];
  last10: GameLog[];
  history: PlayerHistoryResponse | null;
  /** NBA uses stored signals and the backend tier. WNBA keeps the previous read. */
  league?: LeagueSegment;
  read?: PropRead | null;
  /** True when any pick for this player in the game is Out, including another line. */
  listedOut?: boolean;
}): OurReadModel {
  if (args.league === "nba") return buildNbaRead(args);
  const signals = buildReadSignals({
    binary: args.binary,
    line: args.line,
    consensus: args.consensus,
    last10: args.last10,
    history: args.history,
    pick: args.pick,
    market: args.market,
  });
  const metaParts = [args.position, args.team].filter((part): part is string => Boolean(part));
  const bar = consensusSplit(args.consensus, args.binary) ?? (args.binary ? null : historySplit(args.history));
  const metric = marketToMetric(args.market);
  const base = {
    player_name: args.player,
    player_team: args.team ?? "",
    event_id: args.eventId,
    home_team: args.homeTeam,
    away_team: args.awayTeam,
    commence_time: args.commenceTime,
    metric,
  };

  if (!args.player) {
    return {
      player: null,
      meta: null,
      headlineLead: "Choose a player",
      headlineMarket: null,
      caption: "The list is the players with a posted price for this stat.",
      tier: null,
      bar: null,
      signals: [],
      primary: null,
      other: null,
      leanProbability: null,
      listedOut: false,
      injury: null,
    };
  }

  const pick = args.pick;
  let primary: SlipSeed | null = null;
  let other: SlipSeed | null = null;
  let headlineLead = args.line == null ? "No posted line" : `Line ${formatThreshold(args.line)}`;
  let caption = "No stored read for this player. Daily picks keep a side at 65% or higher.";
  let tier: ReadTier | null = null;

  if (pick) {
    const direction = pick.direction === "under" ? "under" : "over";
    const otherDirection = direction === "over" ? "under" : "over";
    primary = {
      ...base,
      player_team: pick.player_team || base.player_team,
      threshold: pick.threshold,
      direction,
      probability: pick.probability,
      n_games: pick.n_games,
    };
    const otherSide = historySide(args.history, pick.threshold, otherDirection);
    if (otherSide) {
      other = {
        ...base,
        player_team: primary.player_team,
        threshold: pick.threshold,
        direction: otherDirection,
        probability: otherSide.probability,
        n_games: otherSide.nGames,
      };
    }
    headlineLead = `${direction === "under" ? "Under" : "Over"} ${formatThreshold(pick.threshold)}`;
    caption = `Historical hit rate ${formatPercent(pick.probability)} over ${pick.n_games} games. The tier is a display bucket on that rate.`;
    tier = readTier(pick.probability);
  } else if (args.line != null && !args.binary) {
    const overSide = historySide(args.history, args.line, "over");
    const underSide = historySide(args.history, args.line, "under");
    if (overSide) {
      primary = {
        ...base,
        threshold: args.line,
        direction: "over",
        probability: overSide.probability,
        n_games: overSide.nGames,
      };
    }
    if (underSide) {
      const underSeed: SlipSeed = {
        ...base,
        threshold: args.line,
        direction: "under",
        probability: underSide.probability,
        n_games: underSide.nGames,
      };
      if (primary) other = underSeed;
      else primary = underSeed;
    }
  }

  return {
    player: args.player,
    meta: metaParts.length ? metaParts.join(", ") : null,
    headlineLead,
    headlineMarket: args.marketName,
    caption,
    tier,
    bar,
    signals,
    primary,
    other,
    leanProbability: primary?.probability ?? null,
    listedOut: false,
    injury: null,
  };
}

export function webPrimaryCopy(seed: SlipSeed, inSlip: boolean, league: LeagueSegment): string {
  const side = seed.direction === "under" ? "Under" : "Over";
  const line = formatThreshold(seed.threshold);
  if (league === "nba") {
    return inSlip ? `✓ ${side} ${line} in slip` : `Add ${side} ${line} to slip`;
  }
  return inSlip ? `In slip · ${side}` : `Add ${side} ${line}`;
}

export function webOtherCopy(seed: SlipSeed, inSlip: boolean, league: LeagueSegment): string {
  const side = seed.direction === "under" ? "Under" : "Over";
  const line = formatThreshold(seed.threshold);
  if (league === "nba") {
    // seed.probability is 1 − combined_probability when the blend exists,
    // otherwise the historical fallback. Whole percent, floored, matching the slip card.
    return inSlip ? `✓ ${side} in slip` : `${side} instead (${formatTierPercent(seed.probability)})`;
  }
  return inSlip ? "Other side in slip" : `${side} ${line}`;
}

/** Mobile bar. The percent uses the tier rounding only when a tier is shown. */
export function mobilePrimaryCopy(
  seed: SlipSeed,
  inSlip: boolean,
  tier: ReadTier | null,
  shown: number | null,
): { label: string; prob: string | null } {
  const last = playerLastName(seed.player_name);
  if (inSlip) return { label: `✓ ${last} in slip`, prob: null };
  const side = seed.direction === "under" ? "U" : "O";
  return {
    label: `Add ${last} ${side} ${formatThreshold(seed.threshold)}`,
    prob: percentBesideTier(shown, tier),
  };
}

export function mobileOtherCopy(seed: SlipSeed): string {
  const side = seed.direction === "under" ? "Under" : "Over";
  return `${side} ${formatTierPercent(seed.probability)}`;
}

/** Percent on the NBA action bar, beside the tier. WNBA keeps its short label. */
export function actionBarPercent(
  seed: {
    probability?: number | null;
    combined_probability?: number | null;
    tier?: string | null;
  } | null,
  league: LeagueSegment,
): string | null {
  if (league !== "nba" || !seed || !tierFromBackend(seed.tier)) return null;
  return formatTierPercent(tierProbability(seed));
}

export function slipButtonLabel(seed: SlipSeed, inSlip: boolean): string {
  const side = seed.direction === "under" ? "U" : "O";
  if (inSlip) return `In slip · ${playerLastName(seed.player_name)} ${side} ${formatThreshold(seed.threshold)}`;
  const percent = tierFromBackend(seed.tier)
    ? formatTierPercent(tierProbability(seed))
    : formatPercent(seed.probability);
  return `Add ${playerLastName(seed.player_name)} ${side} ${formatThreshold(seed.threshold)} ${percent}`;
}

export function errorText(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "The request failed.";
}

export type GameLogTileKey = "over" | "under" | "average" | "games";

export interface GameLogTile {
  key: GameLogTileKey;
  label: string;
  value: string;
  sub: string | null;
}

function sideCount(rate: number | null | undefined, games: number): string | null {
  if (typeof rate !== "number" || !Number.isFinite(rate) || games <= 0) return null;
  return `${Math.round(rate * games)} of ${games} ${games === 1 ? "game" : "games"}`;
}

export function gameLogTiles(
  history: Pick<PlayerHistoryResponse, "n_games" | "p_over" | "p_under" | "mean">,
  line: number | null,
): GameLogTile[] {
  const games = history.n_games;
  const lineLabel = line == null ? "" : ` ${formatThreshold(line)}`;
  const mean = typeof history.mean === "number" && Number.isFinite(history.mean) ? history.mean : null;
  const diff = mean != null && line != null ? Math.round((mean - line) * 10) / 10 : null;
  return [
    { key: "over", label: `Over${lineLabel}`, value: formatPercent(history.p_over), sub: sideCount(history.p_over, games) },
    { key: "under", label: `Under${lineLabel}`, value: formatPercent(history.p_under), sub: sideCount(history.p_under, games) },
    {
      key: "average",
      label: "Average",
      value: mean == null ? "—" : mean.toFixed(1),
      sub: diff == null ? null : `${diff >= 0 ? "+" : ""}${diff.toFixed(1)} vs line`,
    },
    { key: "games", label: "Games", value: String(games), sub: null },
  ];
}
