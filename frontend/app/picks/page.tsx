/**
 * picks/page.tsx - Minimal Daily Picks Page
 * 
 * Design Philosophy:
 * - Clear information hierarchy
 * - High probability in green, medium probability in yellow
 * - Cards use white background with black border
 * - Clean hover effects
 */

"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
  Calendar,
  Filter,
  X,
  Check,
  ClipboardList,
  Timer,
  Shield,
  ArrowUpRight,
  ArrowDownRight,
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
import { TeamLogo } from "@/components/TeamLogo";
import { getShortTeamName } from "@/lib/team-logos";
import { PickContextMenu } from "@/components/PickContextMenu";
import { useBetSlip } from "@/contexts/BetSlipContext";

/**
 * Probability confidence level
 */
function getProbabilityLevel(probability: number): "high" | "medium" {
  return probability >= 0.70 ? "high" : "medium";
}

/**
 * Matchup difficulty level based on opponent rank (1-30)
 * 
 * opponent_rank 的含義：
 * - 1-10: 對手防守較弱，對進攻球員有利（Easy）
 * - 11-20: 中等防守（Average）
 * - 21-30: 對手防守強，對進攻球員不利（Hard）
 * 
 * 注意：rank 低 = 對手防守弱 = 對球員有利
 */
function getMatchupLevel(rank: number | null | undefined): { label: string; color: string } | null {
  if (rank == null) return null;
  if (rank <= 10) return { label: "Easy", color: "text-green-600 bg-green-500/10" };
  if (rank <= 20) return { label: "Avg", color: "text-yellow-600 bg-yellow-500/10" };
  return { label: "Hard", color: "text-red-600 bg-red-500/10" };
}

/**
 * Format edge value with sign and color info
 * 
 * edge = projected_value - threshold
 * 正數 = 投影值高於盤口（配合 Over 方向時有利）
 * 負數 = 投影值低於盤口（配合 Under 方向時有利）
 */
function formatEdge(edge: number | null | undefined, direction: string): { text: string; favorable: boolean } | null {
  if (edge == null) return null;
  const absEdge = Math.abs(edge);
  // Edge 有利的判斷：Over 時 edge > 0 有利，Under 時 edge < 0 有利
  const favorable = direction === "over" ? edge > 0 : edge < 0;
  const sign = edge > 0 ? "+" : "";
  return { text: `${sign}${edge.toFixed(1)}`, favorable };
}

/**
 * metric → market conversion
 */
function metricToMarket(metric: string): string {
  switch (metric) {
    case "points": return "player_points";
    case "rebounds": return "player_rebounds";
    case "assists": return "player_assists";
    case "pra": return "player_points_rebounds_assists";
    default: return "player_points";
  }
}

/**
 * Single pick card
 * 
 * 支援右鍵選單添加到下注列表
 * 已添加的 pick 會顯示視覺反饋（綠色邊框和標記）
 */
function PickCard({ pick, index }: { pick: DailyPick; index: number }) {
  const { isInSlip } = useBetSlip();
  const level = getProbabilityLevel(pick.probability);
  const metricName = METRIC_DISPLAY_NAMES[pick.metric] || pick.metric;
  const directionName = DIRECTION_DISPLAY_NAMES[pick.direction] || pick.direction;
  const animationDelay = `${index * 50}ms`;
  
  // 檢查是否已在下注列表中
  const isAdded = isInSlip(pick.player_name, pick.metric);
  
  const marketKey = metricToMarket(pick.metric);
  const linkHref = `/event/${pick.event_id}?player=${encodeURIComponent(pick.player_name)}&market=${marketKey}&threshold=${pick.threshold}`;
  
  return (
    <div 
      className="animate-fade-in"
      style={{ animationDelay }}
    >
      {/* 右鍵選單包裹 */}
      <PickContextMenu pick={pick}>
        <Link href={linkHref}>
          <div className={`
            card group cursor-pointer
            transition-all duration-200
            hover:-translate-y-1
            ${isAdded 
              ? "border-green-500 bg-green-50/50" 
              : level === "high" 
                ? "hover:border-green-500" 
                : "hover:border-yellow"
            }
          `}>
            {/* 已添加到下注列表的標記 */}
            {isAdded && (
              <div className="absolute top-4 left-4">
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-500 text-white text-xs font-bold">
                  <ClipboardList className="w-3 h-3" />
                  IN SLIP
                </div>
              </div>
            )}
            
            {/* High probability badge */}
            {level === "high" && (
              <div className={`absolute top-4 ${isAdded ? "right-4" : "right-4"}`}>
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-500 text-white text-xs font-bold">
                  <Flame className="w-3 h-3" />
                  HOT
                </div>
              </div>
            )}
            
            {/* Player info */}
            <div className={`flex items-center gap-4 mb-4 ${isAdded ? "mt-8" : ""}`}>
              <TeamLogo 
                teamName={pick.player_team || pick.home_team} 
                size={40} 
                className="shrink-0"
              />
              <div className="flex-1 min-w-0 pr-16">
                <h3 className="text-lg font-bold text-dark truncate">
                  {pick.player_name}
                </h3>
                <p className="text-sm text-gray truncate">
                  {pick.away_team} @ {pick.home_team}
                </p>
              </div>
            </div>
            
            {/* Prediction content */}
            <div className="flex items-center justify-between mb-4">
              <div className={`
                px-4 py-2 rounded-lg text-sm font-bold
                ${pick.direction === "over"
                  ? "bg-green-500/10 text-green-600 border-2 border-green-500/30"
                  : "bg-blue-500/10 text-blue-600 border-2 border-blue-500/30"
                }
              `}>
                {metricName} {directionName} {pick.threshold}
              </div>
              
              {/* Probability display */}
              <div className={`
                text-3xl font-mono font-bold
                ${level === "high" ? "text-green-500" : "text-yellow"}
              `}>
                {formatProbability(pick.probability)}
              </div>
            </div>
            
            {/* Projection info row (Edge + Minutes + Matchup) */}
            {pick.has_projection && (
              <div className="flex items-center gap-2 mb-4 flex-wrap">
                {/* Edge badge */}
                {(() => {
                  const edgeInfo = formatEdge(pick.edge, pick.direction);
                  if (!edgeInfo) return null;
                  return (
                    <span className={`
                      inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-bold
                      ${edgeInfo.favorable 
                        ? "bg-green-500/10 text-green-600" 
                        : "bg-red-500/10 text-red-600"
                      }
                    `}>
                      {edgeInfo.favorable 
                        ? <ArrowUpRight className="w-3 h-3" />
                        : <ArrowDownRight className="w-3 h-3" />
                      }
                      Edge {edgeInfo.text}
                    </span>
                  );
                })()}
                
                {/* Projected minutes */}
                {pick.projected_minutes != null && (
                  <span className={`
                    inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-bold
                    ${pick.projected_minutes < 20 
                      ? "bg-red-500/10 text-red-600" 
                      : "bg-gray/10 text-gray"
                    }
                  `}>
                    <Timer className="w-3 h-3" />
                    {pick.projected_minutes.toFixed(0)}min
                    {pick.projected_minutes < 20 && " ⚠️"}
                  </span>
                )}
                
                {/* Opponent matchup rank */}
                {(() => {
                  const matchup = getMatchupLevel(pick.opponent_position_rank || pick.opponent_rank);
                  if (!matchup) return null;
                  return (
                    <span className={`
                      inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-bold
                      ${matchup.color}
                    `}>
                      <Shield className="w-3 h-3" />
                      {matchup.label}
                    </span>
                  );
                })()}
              </div>
            )}
            
            {/* Probability progress bar */}
            <div className="progress-bar mb-4">
              <div 
                className={`progress-bar-fill ${level === "high" ? "high" : "medium"}`}
                style={{ width: `${pick.probability * 100}%` }}
              />
            </div>
            
            {/* Bottom info */}
            <div className="flex items-center justify-between text-sm text-gray">
              <div className="flex items-center gap-4">
                <span className="flex items-center gap-1.5">
                  <BarChart3 className="w-4 h-4" />
                  {pick.n_games} games
                </span>
                <span className="flex items-center gap-1.5">
                  <Users className="w-4 h-4" />
                  {pick.bookmakers_count} bookmakers
                </span>
              </div>
              
              <div className="flex items-center gap-2">
                {/* 右鍵提示 */}
                <span className="text-xs text-gray/60 hidden group-hover:inline">
                  Right-click to add
                </span>
                <ChevronRight className="w-5 h-5 text-gray group-hover:text-red transition-colors" />
              </div>
            </div>
          </div>
        </Link>
      </PickContextMenu>
    </div>
  );
}

/**
 * Loading skeleton
 */
function PickSkeleton() {
  return (
    <div className="card">
      <div className="flex items-center gap-4 mb-4">
        <div className="w-10 h-10 skeleton rounded-lg" />
        <div className="flex-1">
          <div className="h-5 w-32 skeleton mb-2" />
          <div className="h-4 w-48 skeleton" />
        </div>
      </div>
      <div className="flex items-center justify-between mb-4">
        <div className="h-10 w-36 skeleton rounded-lg" />
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
 * Stat card
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
    <div className="card">
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-lg bg-red flex items-center justify-center">
          <Icon className="w-6 h-6 text-white" />
        </div>
        <div>
          <p className="text-sm text-gray font-medium">{label}</p>
          <p className="text-2xl font-bold text-dark">{value}</p>
          {subValue && (
            <p className="text-xs text-gray">{subValue}</p>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Team filter component - multi-select
 * 
 * 球隊篩選器組件，支援多選
 * - teams: 所有可選的球隊列表
 * - selectedTeams: 已選擇的球隊
 * - onToggle: 切換選擇狀態的回調
 * - onClear: 清除所有選擇的回調
 */
function TeamFilter({
  teams,
  selectedTeams,
  onToggle,
  onClear,
}: {
  teams: string[];
  selectedTeams: Set<string>;
  onToggle: (team: string) => void;
  onClear: () => void;
}) {
  if (teams.length === 0) return null;
  
  return (
    <div className="card mb-8">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Filter className="w-5 h-5 text-gray" />
          <span className="font-bold text-dark">Filter by Team</span>
          {selectedTeams.size > 0 && (
            <span className="badge-neutral">
              {selectedTeams.size} selected
            </span>
          )}
        </div>
        {selectedTeams.size > 0 && (
          <button
            onClick={onClear}
            className="flex items-center gap-1.5 text-sm text-gray hover:text-red transition-colors"
          >
            <X className="w-4 h-4" />
            Clear all
          </button>
        )}
      </div>
      
      <div className="flex flex-wrap gap-2">
        {teams.map((team) => {
          const isSelected = selectedTeams.has(team);
          return (
            <button
              key={team}
              onClick={() => onToggle(team)}
              className={`
                flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium
                transition-all duration-200 border-2
                ${isSelected
                  ? "bg-red text-white border-red"
                  : "bg-white text-dark border-dark/20 hover:border-red hover:text-red"
                }
              `}
            >
              <TeamLogo teamName={team} size={20} />
              <span>{getShortTeamName(team)}</span>
              {isSelected && <Check className="w-4 h-4" />}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ==================== sessionStorage keys ====================

/**
 * STORAGE_KEY_DATE - 儲存使用者選擇的日期
 * STORAGE_KEY_TEAMS - 儲存使用者選擇的球隊篩選
 * 
 * 使用 sessionStorage（而非 localStorage），
 * 因為篩選條件只需要在當前瀏覽器 session（分頁）期間保留，
 * 關閉分頁後自動清除，不會影響下次開啟的預設值。
 */
const STORAGE_KEY_DATE = "picks-filter-date";
const STORAGE_KEY_TEAMS = "picks-filter-teams";

/**
 * Main page component
 */
export default function PicksPage() {
  const todayString = getTodayString();
  const [selectedDate, setSelectedDate] = useState(todayString);
  const [isTriggering, setIsTriggering] = useState(false);
  const [selectedTeams, setSelectedTeams] = useState<Set<string>>(new Set());
  const queryClient = useQueryClient();
  
  // ==================== 從 sessionStorage 還原篩選狀態 ====================
  
  /**
   * useEffect - 元件掛載時從 sessionStorage 還原上次的篩選設定
   * 
   * 為什麼用 useEffect 而不是 useState 的 lazy initializer？
   * → 因為 Next.js 的 "use client" 元件仍會在 server 端先渲染一次，
   *   server 端沒有 sessionStorage（window 未定義），
   *   如果在 useState 初始化時讀取 sessionStorage，
   *   server 和 client 的初始值會不一致，導致 hydration mismatch 錯誤。
   * → 改用 useEffect 保證只在 client 端執行，安全地還原狀態。
   * 
   * 還原邏輯：
   * 1. 讀取 STORAGE_KEY_DATE → 如果存在就還原日期（這會觸發 React Query 重新取資料）
   * 2. 讀取 STORAGE_KEY_TEAMS → 如果存在就還原球隊篩選（JSON string → Set）
   */
  useEffect(() => {
    const storedDate = sessionStorage.getItem(STORAGE_KEY_DATE);
    if (storedDate) {
      setSelectedDate(storedDate);
    }
    
    const storedTeams = sessionStorage.getItem(STORAGE_KEY_TEAMS);
    if (storedTeams) {
      try {
        const teams = JSON.parse(storedTeams);
        if (Array.isArray(teams) && teams.length > 0) {
          setSelectedTeams(new Set(teams));
        }
      } catch {
        // JSON 解析失敗時忽略，使用預設空 Set
      }
    }
  }, []);
  
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
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
  
  // ==================== 篩選操作（含 sessionStorage 持久化） ====================
  
  /**
   * handleDateChange - 日期變更處理
   * 
   * 當使用者透過 DatePicker 選擇新日期時觸發：
   * 1. 更新 React state（selectedDate）→ 觸發 React Query 重新取該日的 picks
   * 2. 同步寫入 sessionStorage → 下次回到頁面時可還原
   * 3. 清空球隊篩選 → 因為不同日期的比賽球隊可能不同
   * 
   * 使用方式：<DatePicker onChange={handleDateChange} />
   */
  const handleDateChange = useCallback((date: string) => {
    setSelectedDate(date);
    sessionStorage.setItem(STORAGE_KEY_DATE, date);
    // 切換日期時清除球隊篩選，因為不同日期的比賽球隊不同
    setSelectedTeams(new Set());
    sessionStorage.setItem(STORAGE_KEY_TEAMS, JSON.stringify([]));
  }, []);

  const handleRefresh = useCallback(async () => {
    await queryClient.invalidateQueries({ 
      queryKey: ["daily-picks", selectedDate] 
    });
    await refetch();
  }, [selectedDate, refetch, queryClient]);
  
  const handleTriggerAnalysis = useCallback(async () => {
    setIsTriggering(true);
    try {
      await triggerDailyAnalysis(selectedDate);
      await queryClient.invalidateQueries({ 
        queryKey: ["daily-picks", selectedDate] 
      });
      await refetch();
    } catch (e) {
      console.error("Failed to trigger analysis:", e);
    } finally {
      setIsTriggering(false);
    }
  }, [selectedDate, refetch, queryClient]);
  
  // 從 picks 中提取所有唯一的球隊（使用 player_team）
  // Extract unique teams from picks (using player_team)
  const allTeams = useMemo(() => {
    const picks = data?.picks || [];
    const teamsSet = new Set<string>();
    picks.forEach((pick: DailyPick) => {
      if (pick.player_team) {
        teamsSet.add(pick.player_team);
      }
    });
    // 按字母順序排序
    return Array.from(teamsSet).sort();
  }, [data?.picks]);
  
  /**
   * handleToggleTeam - 切換單個球隊的選擇/取消選擇
   * 
   * 當使用者點擊球隊按鈕時觸發：
   * 1. 如果該球隊已選擇 → 從 Set 中移除
   * 2. 如果該球隊未選擇 → 加入 Set
   * 3. 同步寫入 sessionStorage → 持久化篩選狀態
   * 
   * 使用方式：<TeamFilter onToggle={handleToggleTeam} />
   */
  const handleToggleTeam = useCallback((team: string) => {
    setSelectedTeams((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(team)) {
        newSet.delete(team);
      } else {
        newSet.add(team);
      }
      // 在 setState callback 內同步寫入 sessionStorage
      sessionStorage.setItem(STORAGE_KEY_TEAMS, JSON.stringify(Array.from(newSet)));
      return newSet;
    });
  }, []);
  
  /**
   * handleClearTeams - 清除所有球隊篩選
   * 
   * 當使用者點擊「Clear all」按鈕時觸發：
   * 1. 重置 selectedTeams 為空 Set（顯示所有球隊的 picks）
   * 2. 同步清除 sessionStorage 中的球隊篩選
   * 
   * 使用方式：<TeamFilter onClear={handleClearTeams} />
   */
  const handleClearTeams = useCallback(() => {
    setSelectedTeams(new Set());
    sessionStorage.setItem(STORAGE_KEY_TEAMS, JSON.stringify([]));
  }, []);
  
  const dateTitle = getDateDisplayTitle(selectedDate);
  const allPicks = data?.picks || [];
  const stats = data?.stats;
  
  // 根據選擇的球隊篩選 picks
  // Filter picks based on selected teams
  const picks = useMemo(() => {
    if (selectedTeams.size === 0) {
      return allPicks;
    }
    return allPicks.filter((pick: DailyPick) => 
      pick.player_team && selectedTeams.has(pick.player_team)
    );
  }, [allPicks, selectedTeams]);
  
  const highProbCount = picks.filter((p: DailyPick) => p.probability >= 0.70).length;
  const mediumProbCount = picks.filter((p: DailyPick) => p.probability >= 0.65 && p.probability < 0.70).length;
  
  return (
    <div className="min-h-screen page-enter">
      <div className="max-w-4xl mx-auto px-6 py-12">
        {/* Page title section */}
        <div className="text-center mb-16">
          <div className="inline-block mb-6">
            <span className="badge-danger">
              <Target className="w-3.5 h-3.5 mr-1.5" />
              AI Auto Analysis
            </span>
          </div>
          
          <h1 className="hero-title mb-4">
            Daily <span className="text-red">Picks</span>
          </h1>
          
          <div className="accent-line mx-auto mb-6" />
          
          <p className="text-lg text-gray max-w-lg mx-auto">
            Automatically filter high-value betting options with over 65% probability based on historical data
          </p>
        </div>

        {/* Date selection section */}
        <div className="card mb-10">
          <DatePicker
            value={selectedDate}
            onChange={handleDateChange}
          />
        </div>

        {/* Stats cards section */}
        {!isLoading && stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10">
            <StatCard 
              icon={Target}
              label="High Prob Picks"
              value={allPicks.length}
              subValue={`${allPicks.filter((p: DailyPick) => p.probability >= 0.70).length} ≥70%`}
            />
            <StatCard 
              icon={Calendar}
              label="Events Analyzed"
              value={stats.total_events}
              subValue="games"
            />
            <StatCard 
              icon={Users}
              label="Players Analyzed"
              value={stats.total_players}
              subValue="players"
            />
            <StatCard 
              icon={Clock}
              label="Analysis Time"
              value={`${stats.analysis_duration_seconds.toFixed(1)}s`}
              subValue={data?.analyzed_at ? new Date(data.analyzed_at).toLocaleTimeString() : ""}
            />
          </div>
        )}

        {/* Team filter section */}
        {!isLoading && allTeams.length > 0 && (
          <TeamFilter
            teams={allTeams}
            selectedTeams={selectedTeams}
            onToggle={handleToggleTeam}
            onClear={handleClearTeams}
          />
        )}

        {/* Actions section */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-4">
            <h2 className="text-2xl font-bold text-dark">
              {dateTitle} Picks
            </h2>
            {!isLoading && (
              <span className="badge-neutral">
                {selectedTeams.size > 0 
                  ? `${picks.length} / ${allPicks.length} picks`
                  : `${picks.length} picks`
                }
              </span>
            )}
          </div>
          
          <div className="flex items-center gap-3">
            <button
              onClick={handleRefresh}
              disabled={isFetching}
              className="btn-refresh"
            >
              <RefreshCw className={`w-4 h-4 ${isFetching ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </button>
            
            <button
              onClick={handleTriggerAnalysis}
              disabled={isTriggering || isFetching}
              className="btn-primary flex items-center gap-2"
            >
              <Zap className={`w-4 h-4 ${isTriggering ? "animate-pulse" : ""}`} />
              <span>{isTriggering ? "Analyzing..." : "Re-analyze"}</span>
            </button>
          </div>
        </div>

        {/* Error message */}
        {isError && (
          <div className="card mb-8 border-red">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-lg bg-red flex items-center justify-center shrink-0">
                <AlertCircle className="w-5 h-5 text-white" />
              </div>
              <div>
                <h3 className="font-bold text-dark mb-1">
                  Load Failed
                </h3>
                <p className="text-gray text-sm mb-3">
                  {error instanceof Error ? error.message : "Unable to fetch analysis data, please try again later"}
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

        {/* Loading state */}
        {isLoading && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[...Array(6)].map((_, i) => (
              <PickSkeleton key={i} />
            ))}
          </div>
        )}

        {/* No data state */}
        {!isLoading && picks.length === 0 && (
          <div className="card text-center py-16">
            <div className="w-20 h-20 mx-auto mb-6 rounded-full border-2 border-dark/20 flex items-center justify-center">
              <TrendingUp className="w-10 h-10 text-gray" />
            </div>
            <h3 className="text-2xl font-bold text-dark mb-3">
              No High Probability Picks
            </h3>
            <p className="text-gray mb-8 max-w-md mx-auto">
              {data?.message || "No betting options with over 65% probability found today, or data analysis is not yet complete"}
            </p>
            <button
              onClick={handleTriggerAnalysis}
              disabled={isTriggering}
              className="btn-primary"
            >
              <Zap className="w-4 h-4 mr-2" />
              {isTriggering ? "Analyzing..." : "Analyze Now"}
            </button>
          </div>
        )}

        {/* Picks list */}
        {!isLoading && picks.length > 0 && (
          <>
            {/* High probability (>=70%) */}
            {highProbCount > 0 && (
              <div className="mb-10">
                <div className="flex items-center gap-3 mb-6">
                  <div className="w-10 h-10 rounded-lg bg-green-500 flex items-center justify-center">
                    <Flame className="w-5 h-5 text-white" />
                  </div>
                  <h3 className="text-xl font-bold text-dark">
                    High Confidence Picks
                    <span className="text-green-500 ml-2">≥70%</span>
                  </h3>
                  <span className="badge-success">
                    {highProbCount}
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {picks
                    .filter((p: DailyPick) => p.probability >= 0.70)
                    .map((pick: DailyPick, index: number) => (
                      <PickCard key={`${pick.player_name}-${pick.metric}`} pick={pick} index={index} />
                    ))
                  }
                </div>
              </div>
            )}

            {/* Medium probability (65-70%) */}
            {mediumProbCount > 0 && (
              <div>
                <div className="flex items-center gap-3 mb-6">
                  <div className="w-10 h-10 rounded-lg bg-yellow flex items-center justify-center">
                    <TrendingUp className="w-5 h-5 text-dark" />
                  </div>
                  <h3 className="text-xl font-bold text-dark">
                    Medium Confidence Picks
                    <span className="text-yellow ml-2">65-70%</span>
                  </h3>
                  <span className="badge-warning">
                    {mediumProbCount}
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {picks
                    .filter((p: DailyPick) => p.probability >= 0.65 && p.probability < 0.70)
                    .map((pick: DailyPick, index: number) => (
                      <PickCard key={`${pick.player_name}-${pick.metric}`} pick={pick} index={index} />
                    ))
                  }
                </div>
              </div>
            )}
          </>
        )}

        {/* Bottom note */}
        <div className="mt-16 text-center">
          <div className="divider-light mb-8" />
          <p className="text-sm text-gray max-w-lg mx-auto">
            Probabilities are calculated based on historical data, for reference only. Threshold values are taken from the mode of all bookmakers.
            <br />
            Click any pick to view detailed historical data and analysis.
          </p>
        </div>
      </div>
    </div>
  );
}
