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
import { RefreshCw, AlertCircle } from "lucide-react";
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
      <div className="max-w-4xl mx-auto px-6 py-12">
        {/* Page title section - minimal bold typography */}
        <div className="text-center mb-16">
          {/* Badge */}
          <div className="inline-block mb-6">
            <span className="badge-neutral">
              No-Vig Probability Calculator
            </span>
          </div>
          
          {/* Main title */}
          <h1 className="hero-title mb-4">
            NBA <span className="text-red">Events</span>
          </h1>
          
          {/* Red accent line */}
          <div className="accent-line mx-auto mb-6" />
          
          {/* Subtitle */}
          <p className="text-lg text-gray max-w-md mx-auto">
            Calculate no-vig probabilities to find the best betting opportunities
          </p>
        </div>

        {/* Date selection section */}
        <div className="card mb-10">
          <DatePicker
            value={selectedDate}
            onChange={setSelectedDate}
          />
        </div>

        {/* Events title row */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <h2 className="text-2xl font-bold text-dark">
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

        {/* Error message */}
        {isError && (
          <div className="card mb-6 border-red">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-lg bg-red flex items-center justify-center shrink-0">
                <AlertCircle className="w-5 h-5 text-white" />
              </div>
              <div>
                <h3 className="font-bold text-dark mb-1">
                  Load Failed
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

        {/* Events list */}
        <EventList
          events={data?.events || []}
          isLoading={isLoading}
        />

        {/* Bottom hint */}
        <div className="mt-16 text-center">
          <p className="text-sm text-gray">
            Click any game → Enter player name → View no-vig probability
          </p>
        </div>
      </div>
    </div>
  );
}
