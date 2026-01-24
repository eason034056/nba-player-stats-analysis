/**
 * page.tsx - 首頁
 * 
 * NBA 賽事列表頁面
 * 
 * 功能：
 * - 日期選擇
 * - 顯示當日賽事列表
 * - 點擊賽事進入計算頁面
 */

"use client";

import { useState, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, AlertCircle, Sparkles } from "lucide-react";
import { getEvents } from "@/lib/api";
import { getTodayString, getDateDisplayTitle } from "@/lib/utils";
import { EventList } from "@/components/EventList";
import { DatePicker } from "@/components/DatePicker";

/**
 * 首頁元件
 * 
 * 顯示 NBA 賽事列表，讓使用者選擇要分析的比賽
 */
export default function HomePage() {
  // 取得今天的日期
  const todayString = getTodayString();
  console.log('🔍 Current date from getTodayString():', todayString);
  
  // 選擇的日期（預設今天）
  const [selectedDate, setSelectedDate] = useState(todayString);
  
  // 用於追蹤組件初始化時的日期，用於判斷是否需要自動更新
  const [initialDate, setInitialDate] = useState(todayString);
  
  console.log('📅 selectedDate:', selectedDate, 'initialDate:', initialDate);

  /**
   * 檢查日期是否已經改變（跨過午夜）
   * 
   * 當用戶重新聚焦視窗時，檢查「今天」是否已經變了
   * 如果變了，而且用戶之前選的是「舊的今天」，就自動更新到「新的今天」
   */
  const checkAndUpdateDate = useCallback(() => {
    const currentToday = getTodayString();
    
    // 如果今天的日期已經改變（跨過午夜）
    if (currentToday !== initialDate) {
      // 如果用戶選擇的是「舊的今天」，自動更新為「新的今天」
      if (selectedDate === initialDate) {
        setSelectedDate(currentToday);
      }
      // 更新初始日期的參考
      setInitialDate(currentToday);
    }
  }, [initialDate, selectedDate]);

  // 監聽視窗聚焦事件，當用戶回到頁面時檢查日期
  useEffect(() => {
    // 頁面可見性改變時檢查日期
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        checkAndUpdateDate();
      }
    };

    // 視窗獲得焦點時檢查日期
    const handleFocus = () => {
      checkAndUpdateDate();
    };

    // 添加事件監聽器
    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("focus", handleFocus);

    // 清理事件監職器
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("focus", handleFocus);
    };
  }, [checkAndUpdateDate]);

  // 使用 React Query 取得賽事列表
  const {
    data,          // 查詢結果
    isLoading,     // 是否正在載入
    isError,       // 是否發生錯誤
    error,         // 錯誤物件
    refetch,       // 重新查詢函數
    isFetching,    // 是否正在背景更新
  } = useQuery({
    queryKey: ["events", selectedDate],
    queryFn: async () => {
      console.log('🔄 Fetching events for date:', selectedDate);
      const result = await getEvents(selectedDate);
      console.log('✅ Received events:', result.events?.length, 'events');
      console.log('📋 Event details:', result.events?.map(e => ({
        id: e.event_id,
        home: e.home_team,
        away: e.away_team,
        time: e.commence_time
      })));
      return result;
    },
    staleTime: 60 * 1000,
  });
  
  console.log('🔍 Query state - isLoading:', isLoading, 'isFetching:', isFetching, 'data:', data);

  // 取得友好的日期顯示標題
  const dateTitle = getDateDisplayTitle(selectedDate);
  const eventCount = data?.events?.length || 0;
  
  console.log('🏷️ dateTitle:', dateTitle, 'for selectedDate:', selectedDate);
  console.log('🎯 eventCount:', eventCount);

  return (
    <div className="min-h-screen">
      {/* 頁面背景裝飾 */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-20 left-1/4 w-96 h-96 bg-blue-500/5 rounded-full blur-3xl" />
        <div className="absolute bottom-20 right-1/4 w-96 h-96 bg-amber-500/5 rounded-full blur-3xl" />
      </div>

      <div className="relative max-w-4xl mx-auto px-6 py-10 page-enter">
        {/* 頁面標題區 */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400 text-sm font-medium mb-4">
            <Sparkles className="w-4 h-4" />
            <span>去水機率計算器</span>
          </div>
          <h1 className="text-4xl md:text-5xl font-bold mb-4">
            <span className="text-gradient">NBA 賽事</span>
          </h1>
          <p className="text-slate-400 text-lg max-w-md mx-auto">
            計算去水機率，找到最佳投注機會
          </p>
        </div>

        {/* 日期選擇區（置中設計） */}
        <div className="card-glass mb-8 py-5">
          <DatePicker
            value={selectedDate}
            onChange={setSelectedDate}
          />
        </div>

        {/* 賽事標題行 */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold text-slate-100">
              {dateTitle}的比賽
            </h2>
            {!isLoading && (
              <span className="px-3 py-1 rounded-full bg-slate-800 text-slate-400 text-sm font-medium">
                {eventCount} 場
              </span>
            )}
          </div>
          
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="btn-refresh"
          >
            <RefreshCw className={`w-4 h-4 ${isFetching ? "animate-spin" : ""}`} />
            <span>重新整理</span>
          </button>
        </div>

        {/* 錯誤提示 */}
        {isError && (
          <div className="card mb-6 border-red-800/50 bg-red-900/10">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-6 h-6 text-red-400 shrink-0 mt-0.5" />
              <div>
                <h3 className="font-semibold text-red-300 mb-1">
                  載入失敗
                </h3>
                <p className="text-slate-400 text-sm">
                  {error instanceof Error ? error.message : "無法取得賽事資料，請稍後再試"}
                </p>
                <button
                  onClick={() => refetch()}
                  className="mt-3 text-sm text-blue-400 hover:text-blue-300 transition-colors"
                >
                  點擊重試
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 賽事列表 */}
        <EventList
          events={data?.events || []}
          isLoading={isLoading}
        />

        {/* 底部提示（簡化版） */}
        <div className="mt-10 text-center">
          <p className="text-sm text-slate-500">
            點擊任一比賽 → 輸入球員名稱 → 查看去水機率
          </p>
        </div>
      </div>
    </div>
  );
}

