/**
 * EventList.tsx - Minimal Events List Component
 * 
 * Design Philosophy:
 * - White cards with black borders
 * - Clear typography
 * - Red VS badge as visual focus
 * - Border turns red on hover
 */

"use client";

import Link from "next/link";
import { Clock, ChevronRight, CalendarOff } from "lucide-react";
import { type NBAEvent } from "@/lib/schemas";
import { formatGameTime } from "@/lib/utils";
import { TeamLogo } from "./TeamLogo";

interface EventListProps {
  events: NBAEvent[];
  isLoading?: boolean;
}

/**
 * Single event card component
 */
function EventCard({ event }: { event: NBAEvent }) {
  return (
    <Link
      href={`/event/${event.event_id}`}
      className="group block"
    >
      <div className="card-game">
        {/* Main content */}
        <div className="flex items-center gap-4 w-full">
          {/* Left: Away team */}
          <div className="flex-1 text-center">
            <div className="flex flex-col items-center py-4">
              <div className="h-12 flex items-center justify-center mb-3">
                <TeamLogo 
                  teamName={event.away_team} 
                  size={44} 
                  className="group-hover:scale-105 transition-transform"
                />
              </div>
              <p className="text-base font-bold text-dark">
                {event.away_team}
              </p>
              <p className="text-xs text-gray font-medium uppercase tracking-wide mt-1">
                Away
              </p>
            </div>
          </div>
          
          {/* Center: VS and time */}
          <div className="flex flex-col items-center gap-3 px-2">
            {/* VS badge - red square */}
            <div className="vs-badge">
              VS
            </div>
            
            {/* Game time */}
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border-2 border-dark/20">
              <Clock className="w-3.5 h-3.5 text-gray" />
              <span className="text-sm font-mono font-semibold text-dark">
                {formatGameTime(event.commence_time)}
              </span>
            </div>
          </div>
          
          {/* Right: Home team */}
          <div className="flex-1 text-center">
            <div className="flex flex-col items-center py-4">
              <div className="h-12 flex items-center justify-center mb-3">
                <TeamLogo 
                  teamName={event.home_team} 
                  size={44} 
                  className="group-hover:scale-105 transition-transform"
                />
              </div>
              <p className="text-base font-bold text-dark">
                {event.home_team}
              </p>
              <p className="text-xs text-gray font-medium uppercase tracking-wide mt-1">
                Home
              </p>
            </div>
          </div>

          {/* Arrow indicator */}
          <div className="pl-2 opacity-0 group-hover:opacity-100 transition-all">
            <ChevronRight className="w-5 h-5 text-red" />
          </div>
        </div>
      </div>
    </Link>
  );
}

/**
 * Loading skeleton
 */
function EventSkeleton() {
  return (
    <div className="card">
      <div className="flex items-center gap-4">
        {/* Left */}
        <div className="flex-1 flex flex-col items-center py-4">
          <div className="skeleton w-11 h-11 rounded-lg mb-3" />
          <div className="skeleton h-4 w-24 mb-2" />
          <div className="skeleton h-3 w-12" />
        </div>
        
        {/* Center */}
        <div className="flex flex-col items-center gap-3 px-2">
          <div className="skeleton w-12 h-12 rounded-lg" />
          <div className="skeleton h-6 w-16 rounded-full" />
        </div>
        
        {/* Right */}
        <div className="flex-1 flex flex-col items-center py-4">
          <div className="skeleton w-11 h-11 rounded-lg mb-3" />
          <div className="skeleton h-4 w-24 mb-2" />
          <div className="skeleton h-3 w-12" />
        </div>
      </div>
    </div>
  );
}

/**
 * EventList 元件
 */
export function EventList({ events, isLoading }: EventListProps) {
  // Loading state
  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        {[...Array(4)].map((_, i) => (
          <EventSkeleton key={i} />
        ))}
      </div>
    );
  }

  // No events
  if (events.length === 0) {
    return (
      <div className="card text-center py-16">
        <div className="mb-6 flex justify-center">
          <div className="w-20 h-20 rounded-full border-2 border-dark/20 flex items-center justify-center">
            <CalendarOff className="w-10 h-10 text-gray" />
          </div>
        </div>
        <h3 className="text-2xl font-bold text-dark mb-3">
          No Games Today
        </h3>
        <p className="text-gray">
          Please select another date to view events
        </p>
      </div>
    );
  }

  // Display events list
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {events.map((event, index) => (
        <div
          key={event.event_id}
          className="animate-fade-in"
          style={{ animationDelay: `${index * 50}ms` }}
        >
          <EventCard event={event} />
        </div>
      ))}
    </div>
  );
}
