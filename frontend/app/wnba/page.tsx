/**
 * /wnba/page.tsx - WNBA player list (read-only, SPO-32 Phase 1)
 *
 * Design intent:
 * - Read-only listing of every player in `data/wnba_player_game_logs.csv`,
 *   surfaced via `GET /api/wnba/csv/players`. No event/odds wiring yet —
 *   Phase 2+ owns that.
 * - Mirrors NBA visual vocabulary (hero card + section-eyebrow + grid)
 *   so users can switch leagues without a context shift.
 * - Each row links to `/wnba/player/[name]` for the empirical stats view.
 *
 * 💡 Why client-side rendering: react-query handles the loading/error
 * states uniformly with the rest of the app, and the search filter is
 * latency-sensitive — Server Component would force a full round-trip
 * per keystroke. The CSV is also cached server-side, so re-fetching is
 * cheap.
 */

"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  ChevronRight,
  Search,
  Sparkles,
  Users,
} from "lucide-react";
import { getWNBACSVPlayers } from "@/lib/api";

export default function WNBAPlayersPage() {
  const [query, setQuery] = useState("");

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["wnba-csv-players"],
    queryFn: () => getWNBACSVPlayers(),
    staleTime: 5 * 60 * 1000,
  });

  // Client-side filter so each keystroke is instant — backend supports
  // `q=` but a 184-player payload is small enough to filter locally and
  // avoid extra round-trips.
  const filteredPlayers = useMemo(() => {
    if (!data?.players) return [];
    if (!query.trim()) return data.players;
    const needle = query.trim().toLowerCase();
    return data.players.filter((p) => p.toLowerCase().includes(needle));
  }, [data?.players, query]);

  return (
    <div className="min-h-screen page-enter">
      <div className="mx-auto max-w-6xl px-6 py-10">
        <section className="grid gap-6 md:grid-cols-[1.3fr_0.7fr] md:items-end mb-10">
          <div className="card">
            <div className="section-eyebrow">
              <Sparkles className="mr-2 h-3.5 w-3.5" />
              WNBA probability board
            </div>

            <h1 className="hero-title mb-5">WNBA Player History</h1>

            <div className="accent-line mb-6" />

            <p className="max-w-2xl text-lg leading-8 text-gray">
              Browse historical performance for every WNBA player in our
              dataset. Pick a name to dive into empirical Over/Under
              probabilities, opponent splits, and full game logs. Live odds
              and event-level no-vig math arrive in a later phase.
            </p>
          </div>

          <div className="card">
            <p className="text-xs uppercase tracking-[0.24em] text-light mb-3">
              Dataset snapshot
            </p>
            <div className="space-y-4">
              <div className="flex items-end justify-between gap-4">
                <div>
                  <p className="text-sm text-gray">Source</p>
                  <p className="text-lg font-semibold text-dark">
                    wnba_player_game_logs.csv
                  </p>
                </div>
                <div className="rounded-full border border-white/10 bg-white/6 px-3 py-1 text-xs uppercase tracking-[0.24em] text-light">
                  {isLoading ? "Loading" : "Ready"}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-light">
                    Players
                  </p>
                  <p className="mt-2 text-3xl font-semibold text-dark">
                    {data?.total ?? "—"}
                  </p>
                </div>
                <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-light">
                    Mode
                  </p>
                  <p className="mt-2 text-sm font-semibold text-dark">
                    Read-only
                  </p>
                  <p className="text-xs text-gray">Historical only</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        <div className="card mb-8">
          <div className="mb-5 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-full border border-white/10 bg-white/6">
              <Search className="h-5 w-5 text-red" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-light">
                Search
              </p>
              <h2 className="text-xl font-semibold text-dark">
                Find a player
              </h2>
            </div>
          </div>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a name (e.g. A'ja Wilson)"
            className="w-full rounded-[18px] border border-white/12 bg-white/6 px-4 py-3 text-base text-dark outline-none transition-colors placeholder:text-light/70 focus:border-red"
          />
        </div>

        <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <h2 className="text-2xl font-semibold text-dark">Players</h2>
            {!isLoading && (
              <span className="badge-neutral">
                {filteredPlayers.length}
                {filteredPlayers.length !== data?.total && data?.total
                  ? ` of ${data.total}`
                  : ""}
              </span>
            )}
          </div>
        </div>

        {isError && (
          <div className="card mb-6 border-red">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-full bg-red flex items-center justify-center shrink-0">
                <AlertCircle className="w-5 h-5 text-white" />
              </div>
              <div>
                <h3 className="font-semibold text-dark mb-1">Failed to load</h3>
                <p className="text-gray text-sm">
                  {error instanceof Error
                    ? error.message
                    : "Unable to fetch WNBA player list."}
                </p>
              </div>
            </div>
          </div>
        )}

        {isLoading && (
          <div className="card">
            <div className="flex items-center gap-3 text-gray">
              <Users className="h-5 w-5 animate-pulse" />
              <span>Loading player list…</span>
            </div>
          </div>
        )}

        {!isLoading && !isError && filteredPlayers.length === 0 && (
          <div className="card">
            <p className="text-gray">
              No players match your search. Try a different query.
            </p>
          </div>
        )}

        {!isLoading && !isError && filteredPlayers.length > 0 && (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {filteredPlayers.map((player) => (
              <li key={player}>
                <Link
                  href={`/wnba/player/${encodeURIComponent(player)}`}
                  className="group flex items-center justify-between gap-3 rounded-[18px] border border-white/10 bg-white/4 px-4 py-3 transition-colors hover:border-red/60 hover:bg-white/8"
                >
                  <span className="truncate text-base font-medium text-dark">
                    {player}
                  </span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-light transition-colors group-hover:text-red" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
