/**
 * /wnba/player/[name]/page.tsx - WNBA player history detail
 *
 * Read-only view of a single WNBA player's empirical Over/Under
 * distribution + game log. Powered entirely by
 * `GET /api/wnba/player-history`. No odds, no event linkage, no agent
 * integration — Phase 1 scope (SPO-32).
 *
 * 💡 Why a thin page that delegates to react-query:
 * - The CSV is small, the response is small, the chart library is heavy.
 *   Loading everything client-side and letting TanStack Query cache the
 *   result keeps the user's back-and-forth between players instantaneous.
 * - We don't reuse `PlayerHistoryStats` (the NBA inline component)
 *   because it's deeply wired to event/odds context that Phase 1 doesn't
 *   have. A standalone read-only view is cleaner than ripping odds out
 *   of PlayerHistoryStats and threading a `league` flag through.
 *
 * ⚠ Metrics here are the **continuous** subset of SPO-16
 * `CONTINUOUS_METRIC_EXTRACTORS`. Binary metrics (DD) require a separate
 * endpoint and a separate UI path — out of scope for the first read-only
 * page. We'll layer them in once the Phase 5 agent work consumes them.
 */

"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  BarChart3,
  Calculator,
  Calendar,
  Loader2,
  Sparkles,
  TrendingUp,
  TrendingDown,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from "recharts";
import { getWNBAPlayerHistory } from "@/lib/api";

// Continuous metrics (Phase 1) — must stay in lockstep with the backend's
// `CONTINUOUS_METRIC_EXTRACTORS`. Adding/removing one here without the
// backend side will produce a 400 from the API. Single source of truth is
// the backend dispatch table; this list intentionally mirrors a subset.
const METRIC_OPTIONS: { value: string; label: string }[] = [
  { value: "points", label: "Points" },
  { value: "rebounds", label: "Rebounds" },
  { value: "assists", label: "Assists" },
  { value: "threes_made", label: "3-Pointers Made" },
  { value: "steals", label: "Steals" },
  { value: "ftm", label: "Free Throws Made" },
  { value: "fgm", label: "Field Goals Made" },
  { value: "pra", label: "PRA (P + R + A)" },
  { value: "ra", label: "Rebounds + Assists" },
  { value: "pr", label: "Points + Rebounds" },
  { value: "pa", label: "Points + Assists" },
];

const DEFAULT_THRESHOLDS: Record<string, number> = {
  points: 15.5,
  rebounds: 6.5,
  assists: 3.5,
  threes_made: 1.5,
  steals: 1.5,
  ftm: 3.5,
  fgm: 5.5,
  pra: 25.5,
  ra: 9.5,
  pr: 21.5,
  pa: 18.5,
};

export default function WNBAPlayerPage() {
  // ⚠ Next.js 14 ships dynamic route params as a plain object on a
  // hook — `useParams()` from `next/navigation`. The Next.js 15 idiom
  // (`params: Promise<...>` + `use(params)`) throws at runtime here
  // ("unsupported type was passed to use()"). Mirror the existing
  // `/event/[eventId]/page.tsx` pattern so the next major Next upgrade
  // only has to migrate one place.
  const params = useParams();
  const encodedName = params.name as string;
  const playerName = useMemo(() => decodeURIComponent(encodedName), [encodedName]);

  const [metric, setMetric] = useState<string>("points");
  const [thresholdInput, setThresholdInput] = useState<string>(
    DEFAULT_THRESHOLDS["points"].toString()
  );
  const threshold = useMemo(() => {
    const parsed = parseFloat(thresholdInput);
    return Number.isFinite(parsed) ? parsed : DEFAULT_THRESHOLDS[metric] ?? 0;
  }, [thresholdInput, metric]);

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ["wnba-player-history", playerName, metric, threshold],
    queryFn: () =>
      getWNBAPlayerHistory({
        player: playerName,
        metric,
        threshold,
      }),
    // Stale while user tweaks inputs; long-lived because CSV doesn't
    // change between requests in the same session.
    staleTime: 5 * 60 * 1000,
  });

  // Build histogram data for recharts. `game_logs` is reversed
  // chronologically (oldest first) by the backend; here we want a
  // value-frequency view, so we re-aggregate.
  const histogramData = useMemo(() => {
    if (!data?.histogram?.length) return [];
    return data.histogram.map((bin) => ({
      // Mid-point label so the X axis stays compact on mobile
      midpoint: ((bin.binStart + bin.binEnd) / 2).toFixed(1),
      count: bin.count,
      isOver: bin.binStart > threshold,
    }));
  }, [data?.histogram, threshold]);

  return (
    <div className="min-h-screen page-enter">
      <div className="mx-auto max-w-6xl px-6 py-10">
        <div className="mb-6">
          <Link
            href="/wnba"
            className="inline-flex items-center gap-2 text-sm font-medium text-light hover:text-red"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to player list
          </Link>
        </div>

        <section className="card mb-8">
          <div className="section-eyebrow">
            <Sparkles className="mr-2 h-3.5 w-3.5" />
            WNBA player history
          </div>
          <h1 className="hero-title mb-4">{playerName}</h1>
          <div className="accent-line mb-6" />
          <p className="max-w-2xl text-base leading-7 text-gray">
            Empirical Over/Under probability for the selected stat and
            threshold, computed from {data?.n_games ?? "—"} historical
            games. Probabilities are{" "}
            <strong className="text-dark">strictly</strong> greater than
            (Over) or less than (Under) the threshold — equal-to-threshold
            games sit outside both buckets, matching sportsbook convention.
          </p>
        </section>

        <section className="card mb-8">
          <div className="mb-5 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-full border border-white/10 bg-white/6">
              <Calculator className="h-5 w-5 text-red" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-light">
                Controls
              </p>
              <h2 className="text-xl font-semibold text-dark">
                Pick a stat & threshold
              </h2>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-2 block text-xs uppercase tracking-[0.2em] text-light">
                Metric
              </span>
              <select
                value={metric}
                onChange={(e) => {
                  const next = e.target.value;
                  setMetric(next);
                  setThresholdInput(
                    (DEFAULT_THRESHOLDS[next] ?? 0).toString()
                  );
                }}
                className="w-full rounded-[18px] border border-white/12 bg-white/6 px-4 py-3 text-base text-dark outline-none transition-colors focus:border-red"
              >
                {METRIC_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="mb-2 block text-xs uppercase tracking-[0.2em] text-light">
                Threshold
              </span>
              <input
                type="number"
                step="0.5"
                value={thresholdInput}
                onChange={(e) => setThresholdInput(e.target.value)}
                className="w-full rounded-[18px] border border-white/12 bg-white/6 px-4 py-3 text-base text-dark outline-none transition-colors focus:border-red"
              />
            </label>
          </div>
        </section>

        {isError && (
          <div className="card mb-6 border-red">
            <h3 className="font-semibold text-dark mb-1">Failed to load</h3>
            <p className="text-gray text-sm">
              {error instanceof Error
                ? error.message
                : "Unable to compute history."}
            </p>
          </div>
        )}

        {isLoading && (
          <div className="card">
            <div className="flex items-center gap-3 text-gray">
              <Loader2 className="h-5 w-5 animate-spin" />
              <span>Computing history…</span>
            </div>
          </div>
        )}

        {data && data.n_games === 0 && (
          <div className="card">
            <p className="text-gray">
              {data.message ?? "No qualifying games for this query."}
            </p>
          </div>
        )}

        {data && data.n_games > 0 && (
          <>
            <section className="grid gap-4 md:grid-cols-3 mb-8">
              <div className="card">
                <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-light">
                  <TrendingUp className="h-4 w-4" />
                  P(Over)
                </div>
                <p className="mt-3 text-4xl font-semibold text-dark">
                  {data.p_over != null
                    ? `${(data.p_over * 100).toFixed(1)}%`
                    : "—"}
                </p>
                <p className="mt-1 text-xs text-gray">
                  value &gt; {data.threshold}
                </p>
              </div>

              <div className="card">
                <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-light">
                  <TrendingDown className="h-4 w-4" />
                  P(Under)
                </div>
                <p className="mt-3 text-4xl font-semibold text-dark">
                  {data.p_under != null
                    ? `${(data.p_under * 100).toFixed(1)}%`
                    : "—"}
                </p>
                <p className="mt-1 text-xs text-gray">
                  value &lt; {data.threshold}
                </p>
              </div>

              <div className="card">
                <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-light">
                  <BarChart3 className="h-4 w-4" />
                  Sample
                </div>
                <p className="mt-3 text-4xl font-semibold text-dark">
                  {data.n_games}
                </p>
                <p className="mt-1 text-xs text-gray">
                  μ = {data.mean ?? "—"} · σ = {data.std ?? "—"}
                </p>
              </div>
            </section>

            <section className="card mb-8">
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-full border border-white/10 bg-white/6">
                  <BarChart3 className="h-5 w-5 text-red" />
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-light">
                    Distribution
                  </p>
                  <h2 className="text-xl font-semibold text-dark">
                    Histogram with threshold line
                  </h2>
                </div>
                {isFetching && (
                  <Loader2 className="ml-auto h-4 w-4 animate-spin text-light" />
                )}
              </div>

              <div className="h-72 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={histogramData}>
                    <XAxis
                      dataKey="midpoint"
                      tick={{ fill: "#9ca3af", fontSize: 11 }}
                      stroke="#9ca3af"
                    />
                    <YAxis
                      allowDecimals={false}
                      tick={{ fill: "#9ca3af", fontSize: 11 }}
                      stroke="#9ca3af"
                    />
                    <Tooltip
                      contentStyle={{
                        background: "rgba(7, 12, 24, 0.92)",
                        border: "1px solid rgba(255,255,255,0.12)",
                        borderRadius: "12px",
                        color: "#fff",
                      }}
                      // recharts types `value` as `number | undefined` to
                      // cover the empty-cell case — coerce defensively so
                      // the tooltip never renders `undefined`.
                      formatter={(value) => [
                        typeof value === "number" ? value : 0,
                        "games",
                      ]}
                      labelFormatter={(label) => `value ≈ ${label}`}
                    />
                    <ReferenceLine
                      x={threshold.toString()}
                      stroke="#E92016"
                      strokeDasharray="3 3"
                      label={{
                        value: `line ${threshold}`,
                        fill: "#E92016",
                        position: "top",
                        fontSize: 11,
                      }}
                    />
                    <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                      {histogramData.map((entry, i) => (
                        <Cell
                          key={i}
                          fill={entry.isOver ? "#22c55e" : "#94a3b8"}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </section>

            <section className="card">
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-full border border-white/10 bg-white/6">
                  <Calendar className="h-5 w-5 text-red" />
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-light">
                    Game log
                  </p>
                  <h2 className="text-xl font-semibold text-dark">
                    Per-game values (oldest → newest)
                  </h2>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-[0.18em] text-light">
                      <th className="py-2 pr-4">Date</th>
                      <th className="py-2 pr-4">Opponent</th>
                      <th className="py-2 pr-4">Team</th>
                      <th className="py-2 pr-4">Min</th>
                      <th className="py-2 pr-4">Starter</th>
                      <th className="py-2 pr-4 text-right">Value</th>
                      <th className="py-2 text-right">vs Line</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.game_logs.map((g, i) => (
                      <tr
                        key={`${g.date_full}-${i}`}
                        className="border-t border-white/8 text-dark"
                      >
                        <td className="py-2 pr-4">{g.date_full || g.date}</td>
                        <td className="py-2 pr-4">{g.opponent || "—"}</td>
                        <td className="py-2 pr-4">{g.team || "—"}</td>
                        <td className="py-2 pr-4">
                          {g.minutes ? g.minutes.toFixed(1) : "0"}
                        </td>
                        <td className="py-2 pr-4">
                          {g.is_starter ? "Yes" : "No"}
                        </td>
                        <td className="py-2 pr-4 text-right font-semibold">
                          {g.value}
                        </td>
                        <td
                          className={`py-2 text-right font-semibold ${
                            g.is_over ? "text-green-600" : "text-slate-400"
                          }`}
                        >
                          {g.is_over ? "Over" : "Under"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
