/**
 * event-page.ts
 *
 * Turns event, odds, history, projection, and lineup payloads into the
 * game page. A missing field stays blank. Nothing here invents a player,
 * a line, a rank, or a Supports / Neutral / Against label.
 */

import { format, parseISO } from "date-fns";
import { enUS } from "date-fns/locale";

import { formatPercent } from "./player-dd";
import {
  formatThreshold,
  playerLastName,
  readTier,
  type ReadTier,
} from "./today-board";
import { marketToProjectionCard, projectionCardValue } from "./projection-metric";
import { METRIC_TO_MARKET, type MetricKey } from "./metric-to-market";
import type { LeagueSegment } from "./event-detail-link";
import { teamAbbr } from "./team-abbr";
import type {
  DailyPick,
  GameLog,
  PlayerHistoryResponse,
  PlayerProjection,
  TeamLineup,
} from "./schemas";

export type EventTab = "read" | "log" | "filters" | "odds";

export const EVENT_TABS: ReadonlyArray<{ id: EventTab; label: string }> = [
  { id: "read", label: "Our read" },
  { id: "log", label: "Game log" },
  { id: "filters", label: "Filters" },
  { id: "odds", label: "Odds" },
];

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

export interface ReadSignal {
  key: "market" | "last10" | "history" | "projection" | "defense";
  label: string;
  detail: string;
  value: string | null;
  /** 0–1 when the value is a rate. Rank and projection do not draw a meter. */
  meter: number | null;
}

export interface SignalInput {
  binary: boolean;
  supportsProjection: boolean;
  line: number | null;
  consensus: {
    p_over_fair?: number | null;
    p_under_fair?: number | null;
    p_yes_fair?: number | null;
    p_no_fair?: number | null;
  } | null;
  last10: GameLog[];
  history: Pick<PlayerHistoryResponse, "p_over" | "p_under" | "n_games"> | null;
  projection: PlayerProjection | null;
  pick: DailyPick | null;
  market: string;
}

function marketSignal(input: SignalInput): ReadSignal {
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

function last10Signal(input: SignalInput): ReadSignal {
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

function historySignal(input: SignalInput): ReadSignal {
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
  return {
    key: "history",
    label: "All-game hit rate",
    detail: `Over ${formatPercent(over)} · under ${formatPercent(under)} across ${sample}. Not a season filter.`,
    value: formatPercent(over),
    meter: over,
  };
}

function projectedNumber(input: SignalInput): number | null {
  const card = marketToProjectionCard(input.market);
  if (input.projection && card) {
    const fromCard = projectionCardValue(input.projection, card);
    if (finite(fromCard)) return fromCard;
  }
  if (input.pick && input.pick.metric === marketToMetric(input.market) && finite(input.pick.projected_value)) {
    return input.pick.projected_value;
  }
  return null;
}

function projectionSignal(input: SignalInput): ReadSignal {
  const projected = projectedNumber(input);
  if (projected == null) {
    return {
      key: "projection",
      label: "Projection",
      detail: input.supportsProjection
        ? "Projected value is not on this response."
        : "Projection is not available for WNBA.",
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

function defenseSignal(input: SignalInput): ReadSignal {
  const position = firstNumber(
    input.projection?.opponent_position_rank,
    input.pick?.opponent_position_rank,
  );
  const overall = firstNumber(input.projection?.opponent_rank, input.pick?.opponent_rank);
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
  ];
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
}

export interface EventPlayerRow {
  name: string;
  team: string | null;
  lineText: string;
  leanText: string;
  hasLean: boolean;
  probability: number | null;
}

function namesMatch(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

function onRoster(name: string, lineup: TeamLineup | null | undefined): boolean {
  if (!lineup) return false;
  const players = [...(lineup.starters ?? []), ...(lineup.bench_candidates ?? [])];
  return players.some((player) => namesMatch(player, name));
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
  for (const name of args.suggested) push(name);
  if (args.selectedName) push(args.selectedName);

  const rows = names.map((name) => {
    const pick = byName.get(name.toLowerCase()) ?? null;
    const teamFromPick = pick
      ? pick.player_team_code || teamAbbr(pick.player_team, args.league) || null
      : null;
    const onAway = onRoster(name, args.awayLineup);
    const onHome = onRoster(name, args.homeLineup);
    const lineupTeam =
      onAway && !onHome ? args.awayAbbr : onHome && !onAway ? args.homeAbbr : null;
    const pickInGame =
      teamFromPick && (teamFromPick === args.awayAbbr || teamFromPick === args.homeAbbr)
        ? teamFromPick
        : null;
    // Tonight's lineup beats a CSV or projection club. A code that is
    // neither home nor away (CHI on BOS@PHI) is not shown.
    const team = lineupTeam || pickInGame;
    const selected = namesMatch(name, args.selectedName);
    const line =
      pick != null
        ? pick.threshold
        : selected && args.postedLine != null
          ? args.postedLine
          : null;
    return {
      name,
      team: team || null,
      lineText: line == null ? "—" : formatThreshold(line),
      leanText: pick ? `${pick.direction === "under" ? "U" : "O"} ${formatPercent(pick.probability)}` : "No read",
      hasLean: pick != null,
      probability: pick?.probability ?? null,
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

export function buildOurRead(args: {
  player: string;
  marketName: string;
  market: string;
  binary: boolean;
  supportsProjection: boolean;
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
  projection: PlayerProjection | null;
}): OurReadModel {
  const signals = buildReadSignals({
    binary: args.binary,
    supportsProjection: args.supportsProjection,
    line: args.line,
    consensus: args.consensus,
    last10: args.last10,
    history: args.history,
    projection: args.projection,
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
  };
}

export function slipButtonLabel(seed: SlipSeed, inSlip: boolean): string {
  const side = seed.direction === "under" ? "U" : "O";
  if (inSlip) return `In slip · ${playerLastName(seed.player_name)} ${side} ${formatThreshold(seed.threshold)}`;
  return `Add ${playerLastName(seed.player_name)} ${side} ${formatThreshold(seed.threshold)} ${formatPercent(seed.probability)}`;
}

export function errorText(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "The request failed.";
}
