/**
 * page.tsx - Minimal Home Page
 * 
 * Design Philosophy:
 * - Bold title typography
 * - Red accent line as decoration
 * - Generous whitespace
 * - Clear information hierarchy
 */

"use client";

import { useState, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, AlertCircle, CalendarRange, Sparkles, ArrowRight } from "lucide-react";
import { getEvents } from "@/lib/api";
import { getTodayString, getDateDisplayTitle } from "@/lib/utils";
import { EventList } from "@/components/EventList";
import { DatePicker } from "@/components/DatePicker";

/**
 * Home page component
 */
export default function HomePage() {
  const todayString = getTodayString();
  const [selectedDate, setSelectedDate] = useState(todayString);
  const [initialDate, setInitialDate] = useState(todayString);

  /**
   * Check if date has changed (crossed midnight)
   */
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
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        checkAndUpdateDate();
      }
    };

    const handleFocus = () => {
      checkAndUpdateDate();
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("focus", handleFocus);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("focus", handleFocus);
    };
  }, [checkAndUpdateDate]);

  // Use React Query to fetch events list
  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["events", selectedDate],
    queryFn: async () => {
      return await getEvents(selectedDate);
    },
    staleTime: 60 * 1000,
  });

  const dateTitle = getDateDisplayTitle(selectedDate);
  const eventCount = data?.events?.length || 0;

  return (
    <div className="min-h-screen page-enter">
      <div className="mx-auto max-w-6xl px-6 py-10">
        <section className="grid gap-6 md:grid-cols-[1.3fr_0.7fr] md:items-end mb-10">
          <div className="card">
            <div className="section-eyebrow">
              <Sparkles className="mr-2 h-3.5 w-3.5" />
              NBA probability board
            </div>

            <h1 className="hero-title mb-5">
              Tonight&apos;s Slate
            </h1>

            <div className="accent-line mb-6" />

            <p className="max-w-2xl text-lg leading-8 text-gray">
              Browse the daily schedule, enter any matchup, and follow bookmaker odds into a cleaner no-vig line before moving into picks or deeper player analysis.
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
                  {isFetching ? "Refreshing" : "Ready"}
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-light">Games</p>
                  <p className="mt-2 text-3xl font-semibold text-dark">{eventCount}</p>
                </div>
                <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-light">Flow</p>
                  <p className="mt-2 text-sm font-semibold text-dark">Schedule</p>
                  <p className="text-xs text-gray">Go to matchup</p>
                </div>
                <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-light">Refresh</p>
                  <p className="mt-2 text-sm font-semibold text-dark">60 sec</p>
                  <p className="text-xs text-gray">React Query cache</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        <div className="card mb-8">
          <div className="mb-5 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-full border border-white/10 bg-white/6">
              <CalendarRange className="h-5 w-5 text-red" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-light">Date control</p>
              <h2 className="text-xl font-semibold text-dark">Navigate the schedule</h2>
            </div>
          </div>
          <DatePicker
            value={selectedDate}
            onChange={setSelectedDate}
          />
        </div>

        <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <h2 className="text-2xl font-semibold text-dark">
              {dateTitle} Games
            </h2>
            {!isLoading && (
              <span className="badge-neutral">
                {eventCount} games
              </span>
            )}
          </div>
          
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="btn-refresh"
          >
            <RefreshCw className={`w-4 h-4 ${isFetching ? "animate-spin" : ""}`} />
            <span>Refresh</span>
          </button>
        </div>

        {isError && (
          <div className="card mb-6 border-red">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-full bg-red flex items-center justify-center shrink-0">
                <AlertCircle className="w-5 h-5 text-white" />
              </div>
              <div>
                <h3 className="font-semibold text-dark mb-1">
                  Failed to load
                </h3>
                <p className="text-gray text-sm mb-3">
                  {error instanceof Error ? error.message : "Unable to fetch events data, please try again later"}
                </p>
                <button
                  onClick={() => refetch()}
                  className="text-sm font-bold text-red hover:underline"
                >
                  Click to retry →
                </button>
              </div>
            </div>
          </div>
        )}

        <EventList
          events={data?.events || []}
          selectedDate={selectedDate}
          isLoading={isLoading}
        />

        <section className="mt-10 grid gap-4 sm:grid-cols-2 md:grid-cols-3">
          <div className="card">
            <p className="text-xs uppercase tracking-[0.22em] text-light mb-2">Step 1</p>
            <h3 className="text-xl font-semibold text-dark mb-2">Choose a game</h3>
            <p className="text-sm leading-7 text-gray">Start with the overview and drill down into any matchup that deserves a closer look at the pricing.</p>
          </div>
          <div className="card">
            <p className="text-xs uppercase tracking-[0.22em] text-light mb-2">Step 2</p>
            <h3 className="text-xl font-semibold text-dark mb-2">Examine the player market</h3>
            <p className="text-sm leading-7 text-gray">Compare market types, player options, sportsbook coverage, projections, and historical hit rates all in one place.</p>
          </div>
          <div className="card">
            <p className="text-xs uppercase tracking-[0.22em] text-light mb-2">Step 3</p>
            <h3 className="text-xl font-semibold text-dark mb-2">Take your best reads further</h3>
            <p className="text-sm leading-7 text-gray">Use Daily Picks and Bet Slip for fast curation, saving, and easy-to-share summaries.</p>
          </div>
        </section>

        <div className="mt-12 flex items-center justify-center gap-2 text-sm text-gray">
          <ArrowRight className="h-4 w-4 text-red" />
          <p>Open any matchup to calculate no-vig probabilities and see deeper player context.</p>
        </div>
      </div>
    </div>
  );
}
