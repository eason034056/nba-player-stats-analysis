/**
 * /wnba/picks/page.tsx — WNBA daily high-probability picks (SPO-35 Phase 3)
 *
 * Mirrors the NBA `/picks/page.tsx` structure: card grid driven by the same
 * `DailyPicksResponse` shape, sorted by historical probability, served from
 * the league-aware `daily_analysis_service.run_daily_analysis(league="wnba")`
 * pipeline behind `/api/wnba/daily-picks`.
 *
 * Deliberate scope reduction vs NBA — these are *follow-ups*, not omissions:
 *   1. No lineup badges. The shared `getLineups` helper only knows the NBA
 *      route on `origin/dev`. SPO-34's WNBA lineup endpoint
 *      (`GET /api/wnba/lineups`) is still in PR #13; once it merges we can
 *      wire `getWnbaLineups` here in a one-line follow-up.
 *   2. No bet-slip / agent-widget / context-menu wiring. Those contexts are
 *      NBA-coupled today (`createAgentPickContextFromDailyPick`, `useBetSlip`,
 *      `useAgentWidget`). Adding WNBA support is a parallel effort tracked
 *      separately; this page renders the picks correctly without it.
 *   3. No projection edge column. WNBA projections aren't wired
 *      (`has_projection` is False on every WNBA pick by design — see SPO-35
 *      task summary). The card still shows the projection row when present,
 *      so this becomes a "tile lights up" change when WNBA projections land,
 *      not a UI rewrite.
 *
 * What is the same:
 *   - Same DailyPick schema (`@/lib/schemas`), zod parsed by `getWnbaDailyPicks`.
 *   - Same probability tiering (`getProbabilityLevel`) so green=high / yellow=medium
 *     reads consistently across leagues.
 *   - Same `DatePicker`, `formatProbability`, and visual hierarchy as NBA.
 */

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Calendar,
  Clock,
  Flame,
  RefreshCw,
  Target,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { getWnbaDailyPicks, triggerWnbaDailyAnalysis } from "@/lib/api";
import { getTodayString, getDateDisplayTitle, formatProbability } from "@/lib/utils";
import {
  type DailyPick,
  METRIC_DISPLAY_NAMES,
  DIRECTION_DISPLAY_NAMES,
} from "@/lib/schemas";
import { DatePicker } from "@/components/DatePicker";
import { buildEventDetailHref } from "@/lib/event-detail-link";
import { metricToMarket } from "@/lib/metric-to-market";

// ---------------------------------------------------------------- helpers --

function getProbabilityLevel(probability: number): "high" | "medium" {
  // 0.70 cutoff matches NBA — keeps the green/yellow read aligned across
  // leagues so cross-page comparison stays intuitive for the user.
  return probability >= 0.7 ? "high" : "medium";
}

// ---------------------------------------------------------------- card -----

function PickCard({
  pick,
  index,
  selectedDate,
}: {
  pick: DailyPick;
  index: number;
  selectedDate: string;
}) {
  const level = getProbabilityLevel(pick.probability);
  const metricName = METRIC_DISPLAY_NAMES[pick.metric] || pick.metric;
  const directionName = DIRECTION_DISPLAY_NAMES[pick.direction] || pick.direction;
  const animationDelay = `${index * 50}ms`;

  // Reuse the league-aware event-detail link builder so the card deep-links
  // to the correct `/wnba/event/...` route, not the NBA one.
  const marketKey = metricToMarket(pick.metric);
  const linkHref = buildEventDetailHref({
    eventId: pick.event_id,
    date: selectedDate,
    player: pick.player_name,
    market: marketKey,
    threshold: pick.threshold,
    league: "wnba",
  });

  const DirectionIcon = pick.direction === "over" ? ArrowUpRight : ArrowDownRight;

  return (
    <div className="animate-fade-in" style={{ animationDelay }}>
      <Link
        href={linkHref}
        className={`
          card group block
          transition-all duration-200 hover:-translate-y-1
          ${level === "high" ? "hover:border-green-500" : "hover:border-yellow"}
        `}
      >
        <div className="p-4">
          {/* Header — player + probability badge */}
          <div className="flex items-start justify-between gap-3 mb-3">
            <div className="min-w-0">
              <div className="font-semibold text-base truncate" title={pick.player_name}>
                {pick.player_name}
              </div>
              {pick.player_team && (
                <div className="text-xs text-muted-foreground mt-0.5">
                  {pick.player_team}
                </div>
              )}
            </div>
            <div
              className={`
                shrink-0 flex items-center gap-1 px-2 py-1 rounded
                text-sm font-semibold
                ${level === "high"
                  ? "bg-green-500/10 text-green-600"
                  : "bg-yellow/10 text-yellow"}
              `}
            >
              {level === "high" && <Flame className="w-3.5 h-3.5" />}
              {formatProbability(pick.probability)}
            </div>
          </div>

          {/* Metric + threshold + direction */}
          <div className="flex items-center gap-2 text-sm mb-3">
            <Target className="w-4 h-4 text-muted-foreground" />
            <span className="font-medium">{metricName}</span>
            <DirectionIcon
              className={`w-4 h-4 ${
                pick.direction === "over" ? "text-green-600" : "text-red-500"
              }`}
            />
            <span className="font-semibold">
              {directionName} {pick.threshold}
            </span>
          </div>

          {/* Matchup */}
          <div className="text-xs text-muted-foreground flex items-center gap-1.5 mb-2">
            <Users className="w-3.5 h-3.5" />
            <span className="truncate">
              {pick.away_team} @ {pick.home_team}
            </span>
          </div>

          {/* Sample size + bookmaker count */}
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <BarChart3 className="w-3.5 h-3.5" />
              {pick.n_games} games
            </span>
            <span className="flex items-center gap-1">
              <Zap className="w-3.5 h-3.5" />
              {pick.bookmakers_count} books
            </span>
          </div>
        </div>
      </Link>
    </div>
  );
}

// ---------------------------------------------------------------- page -----

export default function WNBADailyPicksPage() {
  const queryClient = useQueryClient();
  const todayString = getTodayString();
  const [selectedDate, setSelectedDate] = useState(todayString);
  const [minProbability, setMinProbability] = useState(0.65);

  // Cross-midnight refresh — same pattern as the NBA picks page and
  // `/wnba/page.tsx` so the auto-pinned date rolls if the tab is left
  // open overnight.
  const [initialDate, setInitialDate] = useState(todayString);
  const checkAndUpdateDate = useCallback(() => {
    const currentToday = getTodayString();
    if (currentToday !== initialDate) {
      if (selectedDate === initialDate) {
        setSelectedDate(currentToday);
      }
      setInitialDate(currentToday);
    }
  }, [initialDate, selectedDate]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === "visible") checkAndUpdateDate();
    };
    const handleFocus = () => checkAndUpdateDate();
    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("focus", handleFocus);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("focus", handleFocus);
    };
  }, [checkAndUpdateDate]);

  const { data, isLoading, isError, error, refetch, isRefetching } = useQuery({
    queryKey: ["wnba-daily-picks", selectedDate, minProbability],
    queryFn: () =>
      getWnbaDailyPicks({
        date: selectedDate,
        min_probability: minProbability,
      }),
    staleTime: 5 * 60 * 1000, // 5 min — same as cache TTL is 15 min, but staleTime is on the client
  });

  const picks = data?.picks ?? [];
  const stats = data?.stats;

  const handleRefresh = useCallback(async () => {
    // Force a server-side re-analysis (ignore Redis cache), then refetch
    // so the page picks up the freshly stored result.
    await triggerWnbaDailyAnalysis(selectedDate);
    await queryClient.invalidateQueries({ queryKey: ["wnba-daily-picks", selectedDate] });
    await refetch();
  }, [queryClient, refetch, selectedDate]);

  const dateTitle = useMemo(() => getDateDisplayTitle(selectedDate), [selectedDate]);

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <TrendingUp className="w-6 h-6 text-orange-500" />
          <h1 className="text-2xl font-bold">WNBA Daily Picks</h1>
        </div>
        <p className="text-sm text-muted-foreground">
          High-probability player props for {dateTitle}. Picks are filtered to
          historical p(over) or p(under) ≥ {Math.round(minProbability * 100)}%.
        </p>
      </div>

      {/* Controls row */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <div className="flex items-center gap-2">
          <Calendar className="w-4 h-4 text-muted-foreground" />
          <DatePicker value={selectedDate} onChange={setSelectedDate} />
        </div>

        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Min prob.</span>
          <select
            className="border rounded px-2 py-1 text-sm bg-background"
            value={minProbability}
            onChange={(e) => setMinProbability(Number(e.target.value))}
          >
            <option value={0.6}>60%</option>
            <option value={0.65}>65%</option>
            <option value={0.7}>70%</option>
            <option value={0.75}>75%</option>
            <option value={0.8}>80%</option>
          </select>
        </label>

        <button
          type="button"
          onClick={handleRefresh}
          disabled={isLoading || isRefetching}
          className="
            inline-flex items-center gap-1.5
            border rounded px-3 py-1.5 text-sm
            hover:border-orange-500 hover:text-orange-500
            disabled:opacity-50 disabled:cursor-not-allowed
            transition-colors
          "
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isRefetching ? "animate-spin" : ""}`} />
          {isRefetching ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {/* Stats summary */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <div className="card p-3">
            <div className="text-xs text-muted-foreground">Events</div>
            <div className="text-lg font-semibold">{stats.total_events}</div>
          </div>
          <div className="card p-3">
            <div className="text-xs text-muted-foreground">Players</div>
            <div className="text-lg font-semibold">{stats.total_players}</div>
          </div>
          <div className="card p-3">
            <div className="text-xs text-muted-foreground">Props scanned</div>
            <div className="text-lg font-semibold">{stats.total_props}</div>
          </div>
          <div className="card p-3">
            <div className="text-xs text-muted-foreground">Hi-prob picks</div>
            <div className="text-lg font-semibold">{stats.high_prob_count}</div>
          </div>
        </div>
      )}

      {/* States */}
      {isLoading && (
        <div className="text-center py-12 text-muted-foreground">
          <Clock className="w-6 h-6 mx-auto mb-2 animate-pulse" />
          Loading WNBA picks...
        </div>
      )}

      {isError && (
        <div className="card p-4 flex items-start gap-3 border-red-500">
          <AlertCircle className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
          <div>
            <div className="font-medium">Failed to load WNBA picks</div>
            <div className="text-sm text-muted-foreground mt-1">
              {(error as Error)?.message ?? "Unknown error"}
            </div>
          </div>
        </div>
      )}

      {!isLoading && !isError && data?.message && picks.length === 0 && (
        <div className="card p-6 text-center text-muted-foreground">
          {data.message}
        </div>
      )}

      {!isLoading && !isError && picks.length === 0 && !data?.message && (
        <div className="card p-6 text-center text-muted-foreground">
          No high-probability picks for {dateTitle}. Try lowering the
          probability threshold or pick another date.
        </div>
      )}

      {picks.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {picks.map((pick, idx) => (
            <PickCard
              key={`${pick.player_name}-${pick.metric}-${pick.direction}`}
              pick={pick}
              index={idx}
              selectedDate={selectedDate}
            />
          ))}
        </div>
      )}
    </div>
  );
}
