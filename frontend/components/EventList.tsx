/**
 * EventList.tsx - 賽事列表元件
 * 
 * 顯示 NBA 賽事的列表
 * 每個賽事以卡片形式呈現，可點擊進入詳情頁
 * 
 * 功能：
 * - 顯示主客隊名稱
 * - 顯示比賽時間（本地時間）
 * - 點擊進入計算頁面
 */

"use client";

import Link from "next/link";
import { Clock, ChevronRight } from "lucide-react";
import { type NBAEvent } from "@/lib/schemas";
import { formatGameTime, cn } from "@/lib/utils";

/**
 * EventList Props
 * 
 * @property events - 賽事陣列
 * @property isLoading - 是否正在載入
 */
interface EventListProps {
  events: NBAEvent[];
  isLoading?: boolean;
}

/**
 * 單一賽事卡片元件
 * 
 * 顯示一場比賽的資訊
 */
function EventCard({ event, index }: { event: NBAEvent; index: number }) {
  return (
    <Link
      href={`/event/${event.event_id}`}
      className="group block"
    >
      <div className="card-game">
        {/* 主要內容 */}
        <div className="flex items-center gap-4">
          {/* 左側：客隊 */}
          <div className="flex-1 text-center">
            <div className="inline-flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-slate-700 to-slate-800 mb-2 group-hover:from-blue-600/20 group-hover:to-blue-700/20 transition-all">
              <span className="text-lg">🏀</span>
            </div>
            <p className="text-base font-bold text-slate-100 group-hover:text-white transition-colors">
              {event.away_team}
            </p>
            <p className="text-xs text-slate-500 mt-0.5">客場</p>
          </div>
          
          {/* 中間：VS 和時間 */}
          <div className="flex flex-col items-center gap-2 px-4">
            {/* VS 標籤 */}
            <div className="relative">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-amber-500/20 to-orange-600/20 border border-amber-500/30 flex items-center justify-center group-hover:from-amber-500/30 group-hover:to-orange-600/30 group-hover:border-amber-500/50 transition-all">
                <span className="text-xl font-black text-amber-400 group-hover:text-amber-300">VS</span>
              </div>
              {/* 發光效果 */}
              <div className="absolute inset-0 rounded-2xl bg-amber-500/10 blur-xl opacity-0 group-hover:opacity-100 transition-opacity" />
            </div>
            
            {/* 比賽時間 */}
            <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-slate-800/80">
              <Clock className="w-3.5 h-3.5 text-slate-500" />
              <span className="text-sm font-mono text-slate-400">{formatGameTime(event.commence_time)}</span>
            </div>
          </div>
          
          {/* 右側：主隊 */}
          <div className="flex-1 text-center">
            <div className="inline-flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-slate-700 to-slate-800 mb-2 group-hover:from-orange-600/20 group-hover:to-orange-700/20 transition-all">
              <span className="text-lg">🏀</span>
            </div>
            <p className="text-base font-bold text-slate-100 group-hover:text-white transition-colors">
              {event.home_team}
            </p>
            <p className="text-xs text-slate-500 mt-0.5">主場</p>
          </div>

          {/* 箭頭指示 */}
          <div className="pl-2 opacity-0 group-hover:opacity-100 transition-all group-hover:translate-x-1">
            <ChevronRight className="w-5 h-5 text-amber-400" />
          </div>
        </div>
      </div>
    </Link>
  );
}

/**
 * 載入骨架屏
 * 
 * 資料載入中時顯示的佔位元素
 */
function EventSkeleton() {
  return (
    <div className="card-game">
      <div className="flex items-center gap-4">
        {/* 左側 */}
        <div className="flex-1 flex flex-col items-center">
          <div className="skeleton w-10 h-10 rounded-xl mb-2" />
          <div className="skeleton h-5 w-28 mb-1" />
          <div className="skeleton h-3 w-10" />
        </div>
        
        {/* 中間 */}
        <div className="flex flex-col items-center gap-2 px-4">
          <div className="skeleton w-14 h-14 rounded-2xl" />
          <div className="skeleton h-6 w-16 rounded-full" />
        </div>
        
        {/* 右側 */}
        <div className="flex-1 flex flex-col items-center">
          <div className="skeleton w-10 h-10 rounded-xl mb-2" />
          <div className="skeleton h-5 w-28 mb-1" />
          <div className="skeleton h-3 w-10" />
        </div>
      </div>
    </div>
  );
}

/**
 * EventList 元件
 * 
 * 顯示賽事列表
 */
export function EventList({ events, isLoading }: EventListProps) {
  // 載入中狀態
  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        {[...Array(4)].map((_, i) => (
          <EventSkeleton key={i} />
        ))}
      </div>
    );
  }

  // 沒有賽事
  if (events.length === 0) {
    return (
      <div className="card-glass text-center py-16">
        <div className="text-7xl mb-6">🏀</div>
        <h3 className="text-2xl font-bold text-slate-200 mb-3">
          今天沒有比賽
        </h3>
        <p className="text-slate-500">
          請選擇其他日期查看賽事
        </p>
      </div>
    );
  }

  // 顯示賽事列表（雙欄佈局）
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {events.map((event, index) => (
        <div
          key={event.event_id}
          className="animate-fade-in"
          style={{ animationDelay: `${index * 50}ms` }}
        >
          <EventCard event={event} index={index} />
        </div>
      ))}
    </div>
  );
}

