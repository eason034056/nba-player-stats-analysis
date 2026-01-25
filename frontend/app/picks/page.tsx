/**
 * picks/page.tsx - 每日精選頁面
 * 
 * 顯示當日所有發生機率超過 65% 的高機率球員投注選擇
 * 
 * 功能：
 * - 自動載入當日高機率球員
 * - 按機率排序顯示
 * - 支援重新分析
 * - 點擊可查看詳細歷史
 */

"use client";

import { useState, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { 
  RefreshCw, 
  AlertCircle, 
  TrendingUp, 
  Target, 
  Clock,
  Users,
  Zap,
  ChevronRight,
  Flame,
  BarChart3,
  Calendar
} from "lucide-react";
import Link from "next/link";
import { getDailyPicks, triggerDailyAnalysis } from "@/lib/api";
import { getTodayString, getDateDisplayTitle, formatProbability } from "@/lib/utils";
import { 
  type DailyPick, 
  METRIC_DISPLAY_NAMES, 
  DIRECTION_DISPLAY_NAMES 
} from "@/lib/schemas";
import { DatePicker } from "@/components/DatePicker";

/**
 * 機率信心等級
 * - high: >= 70% (綠色)
 * - medium: >= 65% (琥珀色)
 */
function getProbabilityLevel(probability: number): "high" | "medium" {
  return probability >= 0.70 ? "high" : "medium";
}

/**
 * 單一精選卡片元件
 */
function PickCard({ pick, index }: { pick: DailyPick; index: number }) {
  const level = getProbabilityLevel(pick.probability);
  const metricName = METRIC_DISPLAY_NAMES[pick.metric] || pick.metric;
  const directionName = DIRECTION_DISPLAY_NAMES[pick.direction] || pick.direction;
  
  // 動畫延遲
  const animationDelay = `${index * 50}ms`;
  
  return (
    <div 
      className="animate-fade-in"
      style={{ animationDelay }}
    >
      <Link href={`/event/${pick.event_id}`}>
        <div className={`
          relative overflow-hidden rounded-2xl p-5
          bg-gradient-to-br from-slate-900/80 to-slate-800/40
          border transition-all duration-300 ease-out
          hover:-translate-y-1 hover:shadow-xl
          cursor-pointer group
          ${level === "high" 
            ? "border-emerald-500/30 hover:border-emerald-400/50 hover:shadow-emerald-500/10" 
            : "border-amber-500/30 hover:border-amber-400/50 hover:shadow-amber-500/10"
          }
        `}>
          {/* 背景光效 */}
          <div className={`
            absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300
            ${level === "high"
              ? "bg-gradient-to-br from-emerald-500/5 to-transparent"
              : "bg-gradient-to-br from-amber-500/5 to-transparent"
            }
          `} />
          
          {/* 高機率標籤 */}
          {level === "high" && (
            <div className="absolute top-3 right-3">
              <div className="flex items-center gap-1 px-2 py-1 rounded-full bg-emerald-500/20 border border-emerald-500/30">
                <Flame className="w-3 h-3 text-emerald-400" />
                <span className="text-xs font-semibold text-emerald-400">HOT</span>
              </div>
            </div>
          )}
          
          {/* 內容區 */}
          <div className="relative">
            {/* 球員名稱 */}
            <div className="flex items-center gap-3 mb-3">
              <div className={`
                w-10 h-10 rounded-xl flex items-center justify-center
                ${level === "high" 
                  ? "bg-emerald-500/20" 
                  : "bg-amber-500/20"
                }
              `}>
                <span className="text-lg">🏀</span>
              </div>
              <div>
                <h3 className="text-lg font-bold text-slate-100 group-hover:text-white transition-colors">
                  {pick.player_name}
                </h3>
                <p className="text-sm text-slate-400">
                  {pick.away_team} @ {pick.home_team}
                </p>
              </div>
            </div>
            
            {/* 預測內容 */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <span className={`
                  px-3 py-1.5 rounded-lg text-sm font-semibold
                  ${pick.direction === "over"
                    ? "bg-emerald-500/20 text-emerald-400"
                    : "bg-blue-500/20 text-blue-400"
                  }
                `}>
                  {metricName} {directionName} {pick.threshold}
                </span>
              </div>
              
              {/* 機率顯示 */}
              <div className={`
                text-2xl font-bold font-mono
                ${level === "high" ? "text-emerald-400" : "text-amber-400"}
              `}>
                {formatProbability(pick.probability)}
              </div>
            </div>
            
            {/* 機率進度條 */}
            <div className="mb-4">
              <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                <div 
                  className={`
                    h-full rounded-full transition-all duration-500
                    ${level === "high"
                      ? "bg-gradient-to-r from-emerald-500 to-emerald-400"
                      : "bg-gradient-to-r from-amber-500 to-amber-400"
                    }
                  `}
                  style={{ width: `${pick.probability * 100}%` }}
                />
              </div>
            </div>
            
            {/* 底部資訊 */}
            <div className="flex items-center justify-between text-xs text-slate-500">
              <div className="flex items-center gap-4">
                <span className="flex items-center gap-1">
                  <BarChart3 className="w-3.5 h-3.5" />
                  {pick.n_games} 場樣本
                </span>
                <span className="flex items-center gap-1">
                  <Users className="w-3.5 h-3.5" />
                  {pick.bookmakers_count} 家博彩公司
                </span>
              </div>
              
              <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-slate-400 transition-colors" />
            </div>
          </div>
        </div>
      </Link>
    </div>
  );
}

/**
 * 載入骨架屏
 */
function PickSkeleton() {
  return (
    <div className="rounded-2xl p-5 border border-slate-800/50 bg-slate-900/40">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-10 h-10 skeleton rounded-xl" />
        <div className="flex-1">
          <div className="h-5 w-32 skeleton mb-2" />
          <div className="h-4 w-48 skeleton" />
        </div>
      </div>
      <div className="flex items-center justify-between mb-4">
        <div className="h-8 w-36 skeleton rounded-lg" />
        <div className="h-8 w-16 skeleton" />
      </div>
      <div className="h-2 skeleton rounded-full mb-4" />
      <div className="flex items-center justify-between">
        <div className="h-4 w-40 skeleton" />
        <div className="h-4 w-4 skeleton" />
      </div>
    </div>
  );
}

/**
 * 統計卡片
 */
function StatCard({ 
  icon: Icon, 
  label, 
  value, 
  subValue 
}: { 
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | number;
  subValue?: string;
}) {
  return (
    <div className="bg-slate-900/30 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-slate-800/50 flex items-center justify-center">
          <Icon className="w-5 h-5 text-slate-400" />
        </div>
        <div>
          <p className="text-sm text-slate-500">{label}</p>
          <p className="text-xl font-bold text-slate-100">{value}</p>
          {subValue && (
            <p className="text-xs text-slate-500">{subValue}</p>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * 主頁面元件
 */
export default function PicksPage() {
  const todayString = getTodayString();
  const [selectedDate, setSelectedDate] = useState(todayString);
  const [isTriggering, setIsTriggering] = useState(false);
  
  // 使用 React Query 獲取數據
  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["daily-picks", selectedDate],
    queryFn: async () => {
      return await getDailyPicks({ date: selectedDate });
    },
    staleTime: 5 * 60 * 1000, // 5 分鐘
    refetchOnWindowFocus: false,
  });
  
  // 手動觸發分析
  const handleTriggerAnalysis = useCallback(async () => {
    setIsTriggering(true);
    try {
      await triggerDailyAnalysis(selectedDate);
      await refetch();
    } catch (e) {
      console.error("觸發分析失敗:", e);
    } finally {
      setIsTriggering(false);
    }
  }, [selectedDate, refetch]);
  
  const dateTitle = getDateDisplayTitle(selectedDate);
  const picks = data?.picks || [];
  const stats = data?.stats;
  
  // 統計高機率數量
  const highProbCount = picks.filter(p => p.probability >= 0.70).length;
  const mediumProbCount = picks.filter(p => p.probability >= 0.65 && p.probability < 0.70).length;
  
  return (
    <div className="min-h-screen">
      {/* 頁面背景裝飾 */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-20 left-1/4 w-96 h-96 bg-emerald-500/5 rounded-full blur-3xl" />
        <div className="absolute bottom-20 right-1/4 w-96 h-96 bg-amber-500/5 rounded-full blur-3xl" />
      </div>

      <div className="relative max-w-6xl mx-auto px-6 py-10 page-enter">
        {/* 頁面標題區 */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-sm font-medium mb-4">
            <Target className="w-4 h-4" />
            <span>AI 自動分析</span>
          </div>
          <h1 className="text-4xl md:text-5xl font-bold mb-4">
            <span className="text-gradient">每日精選</span>
          </h1>
          <p className="text-slate-400 text-lg max-w-md mx-auto">
            基於歷史數據，自動篩選發生機率超過 65% 的高價值投注選擇
          </p>
        </div>

        {/* 日期選擇區 */}
        <div className="card-glass mb-8 py-5">
          <DatePicker
            value={selectedDate}
            onChange={setSelectedDate}
          />
        </div>

        {/* 統計卡片區 */}
        {!isLoading && stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <StatCard 
              icon={Target}
              label="高機率選擇"
              value={picks.length}
              subValue={`${highProbCount} 個 ≥70%`}
            />
            <StatCard 
              icon={Calendar}
              label="分析賽事"
              value={stats.total_events}
              subValue="場比賽"
            />
            <StatCard 
              icon={Users}
              label="分析球員"
              value={stats.total_players}
              subValue="位球員"
            />
            <StatCard 
              icon={Clock}
              label="分析耗時"
              value={`${stats.analysis_duration_seconds.toFixed(1)}s`}
              subValue={data?.analyzed_at ? new Date(data.analyzed_at).toLocaleTimeString() : ""}
            />
          </div>
        )}

        {/* 操作區 */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold text-slate-100">
              {dateTitle}的精選
            </h2>
            {!isLoading && (
              <span className="px-3 py-1 rounded-full bg-slate-800 text-slate-400 text-sm font-medium">
                {picks.length} 個選擇
              </span>
            )}
          </div>
          
          <div className="flex items-center gap-3">
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="btn-refresh"
            >
              <RefreshCw className={`w-4 h-4 ${isFetching ? "animate-spin" : ""}`} />
              <span>重新整理</span>
            </button>
            
            <button
              onClick={handleTriggerAnalysis}
              disabled={isTriggering || isFetching}
              className="btn-primary flex items-center gap-2"
            >
              <Zap className={`w-4 h-4 ${isTriggering ? "animate-pulse" : ""}`} />
              <span>{isTriggering ? "分析中..." : "重新分析"}</span>
            </button>
          </div>
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
                  {error instanceof Error ? error.message : "無法取得分析資料，請稍後再試"}
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

        {/* 載入中狀態 */}
        {isLoading && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[...Array(6)].map((_, i) => (
              <PickSkeleton key={i} />
            ))}
          </div>
        )}

        {/* 無數據狀態 */}
        {!isLoading && picks.length === 0 && (
          <div className="card-glass text-center py-16">
            <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-slate-800/50 flex items-center justify-center">
              <TrendingUp className="w-8 h-8 text-slate-500" />
            </div>
            <h3 className="text-xl font-semibold text-slate-300 mb-2">
              尚無高機率選擇
            </h3>
            <p className="text-slate-500 mb-6 max-w-md mx-auto">
              {data?.message || "今日沒有找到發生機率超過 65% 的投注選擇，或數據尚未分析完成"}
            </p>
            <button
              onClick={handleTriggerAnalysis}
              disabled={isTriggering}
              className="btn-primary"
            >
              <Zap className="w-4 h-4 mr-2" />
              {isTriggering ? "分析中..." : "立即分析"}
            </button>
          </div>
        )}

        {/* 精選列表 */}
        {!isLoading && picks.length > 0 && (
          <>
            {/* 分組：高機率 (>=70%) */}
            {highProbCount > 0 && (
              <div className="mb-8">
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center">
                    <Flame className="w-4 h-4 text-emerald-400" />
                  </div>
                  <h3 className="text-lg font-semibold text-slate-200">
                    高信心選擇
                    <span className="text-emerald-400 ml-2">≥70%</span>
                  </h3>
                  <span className="px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 text-xs font-medium">
                    {highProbCount}
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {picks
                    .filter(p => p.probability >= 0.70)
                    .map((pick, index) => (
                      <PickCard key={`${pick.player_name}-${pick.metric}`} pick={pick} index={index} />
                    ))
                  }
                </div>
              </div>
            )}

            {/* 分組：中等機率 (65-70%) */}
            {mediumProbCount > 0 && (
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-8 h-8 rounded-lg bg-amber-500/20 flex items-center justify-center">
                    <TrendingUp className="w-4 h-4 text-amber-400" />
                  </div>
                  <h3 className="text-lg font-semibold text-slate-200">
                    中等信心選擇
                    <span className="text-amber-400 ml-2">65-70%</span>
                  </h3>
                  <span className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 text-xs font-medium">
                    {mediumProbCount}
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {picks
                    .filter(p => p.probability >= 0.65 && p.probability < 0.70)
                    .map((pick, index) => (
                      <PickCard key={`${pick.player_name}-${pick.metric}`} pick={pick} index={index} />
                    ))
                  }
                </div>
              </div>
            )}
          </>
        )}

        {/* 底部說明 */}
        <div className="mt-12 text-center">
          <p className="text-sm text-slate-500 max-w-lg mx-auto">
            機率基於歷史數據計算，僅供參考。門檻值取自所有博彩公司的眾數。
            <br />
            點擊任一選擇可查看詳細歷史數據和分析。
          </p>
        </div>
      </div>
    </div>
  );
}

