/**
 * /wnba/page.tsx — WNBA dual-section landing (SPO-33 Phase 2)
 *
 * Phase 1 (SPO-32) shipped a "players list only" view. SPO-33 upgrades this
 * page to a dual layout that mirrors the NBA `/page.tsx` shape:
 *
 *   ┌─────────────────────────────────────────────────────┐
 *   │  Hero + dataset card                                │
 *   ├─────────────────────────────────────────────────────┤
 *   │  Events for selected date  →  /wnba/event/[id]     │
 *   ├─────────────────────────────────────────────────────┤
 *   │  All players (CSV)         →  /wnba/player/[name]  │
 *   └─────────────────────────────────────────────────────┘
 *
 * The events section uses the shared `EventList` component with `league="wnba"`
 * — same UI shape as the NBA home page, parameterized link builder
 * (`buildEventDetailHref(..., league="wnba")`).
 *
 * The players list is the Phase 1 read-only browser, preserved so historical
 * exploration still works when no live games are on the schedule.
 *
 * 💡 Why client-side rendering: react-query handles loading/error states
 * uniformly with the rest of the app, and the search filter is
 * latency-sensitive (Server Component would force a full round-trip per
 * keystroke).
 */

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  CalendarRange,
  ChevronRight,
  RefreshCw,
  Search,
  Sparkles,
  Users,
} from "lucide-react";
import { getWNBACSVPlayers, getWNBAEvents } from "@/lib/api";
import { getTodayString, getDateDisplayTitle } from "@/lib/utils";
import { EventList } from "@/components/EventList";
import { DatePicker } from "@/components/DatePicker";

export default function WNBAHomePage() {
  // ===== Date control (events section) =====
  const todayString = getTodayString();
  const [selectedDate, setSelectedDate] = useState(todayString);
  const [initialDate, setInitialDate] = useState(todayString);

  // Cross-midnight refresh — same pattern as NBA `/page.tsx`. If the user
  // leaves the tab open across midnight, the auto-pinned date rolls.
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

  const {
    data: eventsData,
    isLoading: isEventsLoading,
    isError: isEventsError,
    error: eventsError,
    isFetching: isEventsFetching,
    refetch: refetchEvents,
  } = useQuery({
    queryKey: ["wnba-events", selectedDate],
    queryFn: () => getWNBAEvents(selectedDate),
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });

  const eventCount = eventsData?.events.length ?? 0;
  const dateTitle = getDateDisplayTitle(selectedDate);

  // ===== Players list (Phase 1 surface, preserved) =====
  const [playerQuery, setPlayerQuery] = useState("");

  const {
    data: playersData,
    isLoading: isPlayersLoading,
    isError: isPlayersError,
    error: playersError,
  } = useQuery({
    queryKey: ["wnba-csv-players"],
    queryFn: () => getWNBACSVPlayers(),
    staleTime: 5 * 60 * 1000,
  });

  // Client-side filter — same logic as the Phase 1 implementation. The
  // 184-player payload is small enough to filter locally and avoid extra
  // round-trips per keystroke.
  const filteredPlayers = useMemo(() => {
    if (!playersData?.players) return [];
    if (!playerQuery.trim()) return playersData.players;
    const needle = playerQuery.trim().toLowerCase();
    return playersData.players.filter((p) => p.toLowerCase().includes(needle));
  }, [playersData?.players, playerQuery]);

  return (
    <div className="min-h-screen page-enter">
      <div className="mx-auto max-w-6xl px-6 py-10">
        {/* ===== Hero + dataset card ===== */}
        <section className="grid gap-6 md:grid-cols-[1.3fr_0.7fr] md:items-end mb-10">
          <div className="card">
            <div className="section-eyebrow">
              <Sparkles className="mr-2 h-3.5 w-3.5" />
              WNBA probability board
            </div>

            <h1 className="hero-title mb-5">WNBA Live Odds &amp; History</h1>

            <div className="accent-line mb-6" />

            <p className="max-w-2xl text-lg leading-8 text-gray">
              Browse upcoming WNBA games to inspect fair (no-vig) pricing,
              or dive into per-player historical Over/Under probabilities
              and game logs. Phase 2 wires live odds into the league
              alongside the read-only stats from Phase 1.
            </p>
          </div>

          <div className="card">
            <p className="text-xs uppercase tracking-[0.24em] text-light mb-3">
              Live board status
            </p>
            <div className="space-y-4">
              <div className="flex items-end justify-between gap-4">
                <div>
                  <p className="text-sm text-gray">Selected day</p>
                  <p className="text-2xl font-semibold text-dark">{dateTitle}</p>
                </div>
                <div className="rounded-full border border-white/10 bg-white/6 px-3 py-1 text-xs uppercase tracking-[0.24em] text-light">
                  {isEventsFetching ? "Refreshing" : "Ready"}
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-light">
                    Games
                  </p>
                  <p className="mt-2 text-3xl font-semibold text-dark">
                    {eventCount}
                  </p>
                </div>
                <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-light">
                    Players
                  </p>
                  <p className="mt-2 text-3xl font-semibold text-dark">
                    {playersData?.total ?? "—"}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ===== Date picker ===== */}
        <div className="card mb-8">
          <div className="mb-5 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-full border border-white/10 bg-white/6">
              <CalendarRange className="h-5 w-5 text-red" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-light">
                Date control
              </p>
              <h2 className="text-xl font-semibold text-dark">
                Navigate the schedule
              </h2>
            </div>
          </div>
          <DatePicker value={selectedDate} onChange={setSelectedDate} />
        </div>

        {/* ===== Events section ===== */}
        <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <h2 className="text-2xl font-semibold text-dark">
              {dateTitle} Games
            </h2>
            {!isEventsLoading && (
              <span className="badge-neutral">{eventCount} games</span>
            )}
          </div>

          <button
            onClick={() => refetchEvents()}
            disabled={isEventsFetching}
            className="btn-refresh"
          >
            <RefreshCw
              className={`w-4 h-4 ${isEventsFetching ? "animate-spin" : ""}`}
            />
            <span>Refresh</span>
          </button>
        </div>

        {isEventsError && (
          <div className="card mb-6 border-red">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-full bg-red flex items-center justify-center shrink-0">
                <AlertCircle className="w-5 h-5 text-white" />
              </div>
              <div>
                <h3 className="font-semibold text-dark mb-1">
                  Failed to load events
                </h3>
                <p className="text-gray text-sm mb-3">
                  {eventsError instanceof Error
                    ? eventsError.message
                    : "Unable to fetch WNBA events. Try again."}
                </p>
                <button
                  onClick={() => refetchEvents()}
                  className="text-sm font-bold text-red hover:underline"
                >
                  Click to retry →
                </button>
              </div>
            </div>
          </div>
        )}

        <EventList
          events={eventsData?.events || []}
          selectedDate={selectedDate}
          isLoading={isEventsLoading}
          league="wnba"
        />

        {/* ===== Players section ===== */}
        <section className="mt-14">
          <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-4">
              <h2 className="text-2xl font-semibold text-dark">Players</h2>
              {!isPlayersLoading && (
                <span className="badge-neutral">
                  {filteredPlayers.length}
                  {filteredPlayers.length !== playersData?.total &&
                  playersData?.total
                    ? ` of ${playersData.total}`
                    : ""}
                </span>
              )}
            </div>
          </div>

          <div className="card mb-6">
            <div className="mb-5 flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-full border border-white/10 bg-white/6">
                <Search className="h-5 w-5 text-red" />
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.22em] text-light">
                  Search
                </p>
                <h3 className="text-xl font-semibold text-dark">
                  Find a player
                </h3>
              </div>
            </div>
            <input
              type="search"
              value={playerQuery}
              onChange={(e) => setPlayerQuery(e.target.value)}
              placeholder="Type a name (e.g. A'ja Wilson)"
              className="w-full rounded-[18px] border border-white/12 bg-white/6 px-4 py-3 text-base text-dark outline-none transition-colors placeholder:text-light/70 focus:border-red"
            />
          </div>

          {isPlayersError && (
            <div className="card mb-6 border-red">
              <div className="flex items-start gap-4">
                <div className="w-10 h-10 rounded-full bg-red flex items-center justify-center shrink-0">
                  <AlertCircle className="w-5 h-5 text-white" />
                </div>
                <div>
                  <h3 className="font-semibold text-dark mb-1">
                    Failed to load players
                  </h3>
                  <p className="text-gray text-sm">
                    {playersError instanceof Error
                      ? playersError.message
                      : "Unable to fetch WNBA player list."}
                  </p>
                </div>
              </div>
            </div>
          )}

          {isPlayersLoading && (
            <div className="card">
              <div className="flex items-center gap-3 text-gray">
                <Users className="h-5 w-5 animate-pulse" />
                <span>Loading player list…</span>
              </div>
            </div>
          )}

          {!isPlayersLoading &&
            !isPlayersError &&
            filteredPlayers.length === 0 && (
              <div className="card">
                <p className="text-gray">
                  No players match your search. Try a different query.
                </p>
              </div>
            )}

          {!isPlayersLoading &&
            !isPlayersError &&
            filteredPlayers.length > 0 && (
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
        </section>
      </div>
    </div>
  );
}
