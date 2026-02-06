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
 * 
 * 結構說明：
 * - 使用兩層佈局：上層是 Logo 列，下層是文字列
 * - Logo 列：三欄對齊（Away Logo | VS | Home Logo）
 * - 文字列：三欄對齊（Away Text | Time | Home Text）
 * - 這樣確保 Logo 永遠在同一水平線上
 */
function EventCard({ event }: { event: NBAEvent }) {
  return (
    <Link
      href={`/event/${event.event_id}`}
      className="group block"
    >
      <div className="card-game">
        {/* 主要內容 - 使用 flex column 分成上下兩部分 */}
        <div className="flex flex-col gap-4 py-2">
          
          {/* 上層：Logo 列 - 確保三個 Logo 在同一水平線 */}
          <div className="flex items-center">
            {/* Away team logo */}
            <div className="flex-1 flex justify-center">
              <TeamLogo 
                teamName={event.away_team} 
                size={48} 
                className="group-hover:scale-105 transition-transform"
              />
            </div>
            
            {/* VS badge - 中央紅色方塊，固定寬度確保對齊 */}
            <div className="w-24 flex justify-center shrink-0">
              <div className="vs-badge">
                VS
              </div>
            </div>
            
            {/* Home team logo */}
            <div className="flex-1 flex justify-center">
              <TeamLogo 
                teamName={event.home_team} 
                size={48} 
                className="group-hover:scale-105 transition-transform"
              />
            </div>
          </div>
          
          {/* 下層：文字列 - 球隊名稱和時間 */}
          <div className="flex items-center">
            {/* Away team text - 固定高度讓文字垂直置中 */}
            <div className="flex-1 text-center">
              <div className="min-h-[56px] flex flex-col items-center justify-center">
                <p className="text-base font-bold text-dark leading-tight">
                  {event.away_team}
                </p>
                <p className="text-xs text-gray font-medium uppercase tracking-wide mt-1">
                  Away
                </p>
              </div>
            </div>
            
            {/* Game time - 中央時間顯示，固定寬度確保與上層 VS 對齊 */}
            <div className="w-24 flex justify-center shrink-0">
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border-2 border-dark/20">
                <Clock className="w-3.5 h-3.5 text-gray" />
                <span className="text-sm font-mono font-semibold text-dark">
                  {formatGameTime(event.commence_time)}
                </span>
              </div>
            </div>
            
            {/* Home team text - 固定高度讓文字垂直置中 */}
            <div className="flex-1 text-center">
              <div className="min-h-[56px] flex flex-col items-center justify-center">
                <p className="text-base font-bold text-dark leading-tight">
                  {event.home_team}
                </p>
                <p className="text-xs text-gray font-medium uppercase tracking-wide mt-1">
                  Home
                </p>
              </div>
            </div>
          </div>
        </div>
        
        {/* Arrow indicator - hover 時顯示 */}
        <div className="absolute right-4 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-all">
          <ChevronRight className="w-5 h-5 text-red" />
        </div>
      </div>
    </Link>
  );
}

/**
 * Loading skeleton - 載入中骨架屏
 * 結構與 EventCard 相同，使用灰色區塊模擬內容
 */
function EventSkeleton() {
  return (
    <div className="card">
      <div className="flex flex-col gap-4 py-2">
        {/* 上層：Logo 列 */}
        <div className="flex items-center">
          <div className="flex-1 flex justify-center">
            <div className="skeleton w-12 h-12 rounded-lg" />
          </div>
          <div className="w-24 flex justify-center shrink-0">
            <div className="skeleton w-12 h-12 rounded-lg" />
          </div>
          <div className="flex-1 flex justify-center">
            <div className="skeleton w-12 h-12 rounded-lg" />
          </div>
        </div>
        
        {/* 下層：文字列 */}
        <div className="flex items-center">
          <div className="flex-1 flex flex-col items-center gap-2">
            <div className="skeleton h-4 w-24" />
            <div className="skeleton h-3 w-12" />
          </div>
          <div className="w-24 flex justify-center shrink-0">
            <div className="skeleton h-8 w-20 rounded-full" />
          </div>
          <div className="flex-1 flex flex-col items-center gap-2">
            <div className="skeleton h-4 w-24" />
            <div className="skeleton h-3 w-12" />
          </div>
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
