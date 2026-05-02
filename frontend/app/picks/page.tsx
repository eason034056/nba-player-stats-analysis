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
  AlertCircle, 
  Bot,
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
  ArrowLeftRight,
} from "lucide-react";
import Link from "next/link";
import { getDailyPicks, getLineups, triggerDailyAnalysis } from "@/lib/api";
import { getTodayString, getDateDisplayTitle, formatProbability } from "@/lib/utils";
import { 
  type DailyPick,
  type TeamLineup,
  METRIC_DISPLAY_NAMES, 
  DIRECTION_DISPLAY_NAMES 
} from "@/lib/schemas";
import { DatePicker } from "@/components/DatePicker";
import { TeamLogo } from "@/components/TeamLogo";
import { getCanonicalTeamCode, getShortTeamName } from "@/lib/team-logos";
import { PickContextMenu } from "@/components/PickContextMenu";
import { useAgentWidget } from "@/contexts/AgentWidgetContext";
import { useBetSlip } from "@/contexts/BetSlipContext";
import { createAgentPickContextFromDailyPick } from "@/lib/agent-chat";
import { LineupStatusBadge } from "@/components/LineupStatusBadge";
import { buildEventDetailHref } from "@/lib/event-detail-link";

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
function PickCard({
  pick,
  index,
  selectedDate,
  lineup,
  isLineupLoading = false,
  isLineupError = false,
}: {
  pick: DailyPick;
  index: number;
  selectedDate: string;
  lineup?: TeamLineup | null;
  isLineupLoading?: boolean;
  isLineupError?: boolean;
}) {
  const { setSelectedPickContext, submitAction } = useAgentWidget();
  const { picks, isInSlip, addPick, removePick } = useBetSlip();
  const level = getProbabilityLevel(pick.probability);
  const metricName = METRIC_DISPLAY_NAMES[pick.metric] || pick.metric;
  const directionName = DIRECTION_DISPLAY_NAMES[pick.direction] || pick.direction;
  const animationDelay = `${index * 50}ms`;

  const isAdded = isInSlip(pick.player_name, pick.metric);
  const marketKey = metricToMarket(pick.metric);
  const linkHref = buildEventDetailHref({
    eventId: pick.event_id,
    date: selectedDate,
    player: pick.player_name,
    market: marketKey,
    threshold: pick.threshold,
  });
  const reverseDirection = pick.direction === "over" ? "under" : "over";
  const reverseDirectionName = DIRECTION_DISPLAY_NAMES[reverseDirection] || reverseDirection;
  const existingPick = picks.find(
    (item) => item.player_name === pick.player_name && item.metric === pick.metric
  );
  const isReversedInSlip = existingPick?.direction === reverseDirection;

  const buildBetSlipPick = (direction: string, probability: number) => ({
    player_name: pick.player_name,
    player_team: pick.player_team || "",
    event_id: pick.event_id,
    home_team: pick.home_team,
    away_team: pick.away_team,
    commence_time: pick.commence_time,
    metric: pick.metric,
    threshold: pick.threshold,
    direction,
    probability,
    n_games: pick.n_games,
  });

  const handleToggleBetSlip = () => {
    const id = `${pick.player_name}-${pick.metric}`;

    if (isAdded && !isReversedInSlip) {
      removePick(id);
      return;
    }

    removePick(id);
    addPick(buildBetSlipPick(pick.direction, pick.probability));
  };

  const handleAddReverseBet = () => {
    removePick(`${pick.player_name}-${pick.metric}`);
    addPick(buildBetSlipPick(reverseDirection, 1 - pick.probability));
  };

  const handleAskAgent = async () => {
    const pickContext = createAgentPickContextFromDailyPick(pick);
    setSelectedPickContext(pickContext);
    await submitAction({
      action: "analyze_pick",
      message: "Should I bet this?",
      contextPatch: {
        selected_pick: pickContext,
      },
    });
  };

  return (
    <div className="animate-fade-in" style={{ animationDelay }}>
      <PickContextMenu pick={pick}>
        <div
          className={`
            card group
            transition-all duration-200
            hover:-translate-y-1
            ${isAdded
              ? "border-green-500 bg-green-50/50"
              : level === "high"
                ? "hover:border-green-500"
                : "hover:border-yellow"
            }
          `}
        >
          <Link href={linkHref} className="block cursor-pointer">
            {isAdded && (
              <div className="absolute top-4 left-4">
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-500 text-white text-xs font-bold">
                  <ClipboardList className="w-3 h-3" />
                  IN SLIP
                </div>
              </div>
            )}

            {level === "high" && (
              <div className="absolute top-4 right-4">
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-500 text-white text-xs font-bold">
                  <Flame className="w-3 h-3" />
                  HOT
                </div>
              </div>
            )}

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

            <div className="mb-4">
              <LineupStatusBadge
                lineup={lineup}
                playerName={pick.player_name}
                isLoading={isLineupLoading}
                isError={isLineupError}
              />
            </div>

            <div className="flex items-center justify-between mb-4">
              <div
                className={`
                  px-4 py-2 rounded-lg text-sm font-bold
                  ${pick.direction === "over"
                    ? "bg-green-500/10 text-green-600 border-2 border-green-500/30"
                    : "bg-blue-500/10 text-blue-600 border-2 border-blue-500/30"
                  }
                `}
              >
                {metricName} {directionName} {pick.threshold}
              </div>

              <div
                className={`
                  text-3xl font-mono font-bold
                  ${level === "high" ? "text-green-500" : "text-yellow"}
                `}
              >
                {formatProbability(pick.probability)}
              </div>
            </div>

            {pick.has_projection && (
              <div className="flex items-center gap-2 mb-4 flex-wrap">
                {(() => {
                  const edgeInfo = formatEdge(pick.edge, pick.direction);
                  if (!edgeInfo) return null;
                  return (
                    <span
                      className={`
                        inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-bold
                        ${edgeInfo.favorable
                          ? "bg-green-500/10 text-green-600"
                          : "bg-red-500/10 text-red-600"
                        }
                      `}
                    >
                      {edgeInfo.favorable
                        ? <ArrowUpRight className="w-3 h-3" />
                        : <ArrowDownRight className="w-3 h-3" />
                      }
                      Edge {edgeInfo.text}
                    </span>
                  );
                })()}

                {pick.projected_minutes != null && (
                  <span
                    className={`
                      inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-bold
                      ${pick.projected_minutes < 20
                        ? "bg-red-500/10 text-red-600"
                        : "bg-gray/10 text-gray"
                      }
                    `}
                  >
                    <Timer className="w-3 h-3" />
                    {pick.projected_minutes.toFixed(0)}min
                    {pick.projected_minutes < 20 && " ⚠️"}
                  </span>
                )}

                {(() => {
                  const matchup = getMatchupLevel(pick.opponent_position_rank || pick.opponent_rank);
                  if (!matchup) return null;
                  return (
                    <span
                      className={`
                        inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-bold
                        ${matchup.color}
                      `}
                    >
                      <Shield className="w-3 h-3" />
                      {matchup.label}
                    </span>
                  );
                })()}
              </div>
            )}

            <div className="progress-bar mb-4">
              <div
                className={`progress-bar-fill ${level === "high" ? "high" : "medium"}`}
                style={{ width: `${pick.probability * 100}%` }}
              />
            </div>

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
                <span className="text-xs text-gray/60 hidden group-hover:inline">
                  Right-click for more
                </span>
                <ChevronRight className="w-5 h-5 text-gray group-hover:text-red transition-colors" />
              </div>
            </div>
          </Link>

          <div className="mt-4 flex flex-wrap gap-2 border-t border-dark/10 pt-4">
            <button
              type="button"
              onClick={handleToggleBetSlip}
              className={`
                inline-flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm font-bold transition-colors min-h-[44px]
                ${isAdded && !isReversedInSlip
                  ? "bg-green-500 text-white"
                  : "bg-dark text-cream hover:bg-dark/85"
                }
              `}
            >
              <ClipboardList className="w-4 h-4" />
              <span>{isAdded && !isReversedInSlip ? "Added to Bet Slip" : "Add to Bet Slip"}</span>
            </button>

            <button
              type="button"
              onClick={handleAddReverseBet}
              className={`
                inline-flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm font-semibold transition-colors min-h-[44px]
                ${isReversedInSlip
                  ? "border-blue-500 bg-blue-500 text-white"
                  : "border-dark/20 bg-white text-dark hover:border-blue-500 hover:text-blue-600"
                }
              `}
            >
              <ArrowLeftRight className="w-4 h-4" />
              <span>{isReversedInSlip ? `Reverse Added (${reverseDirectionName})` : `Add ${reverseDirectionName}`}</span>
            </button>

            <button
              type="button"
              onClick={() => void handleAskAgent()}
              className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm font-semibold text-dark transition-colors hover:border-white/20 hover:bg-white/10 min-h-[44px]"
              aria-label={`Ask Agent about ${pick.player_name}`}
            >
              <Bot className="w-4 h-4 text-red" />
              <span>Ask Agent</span>
            </button>
          </div>
        </div>
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
        <div className="w-12 h-12 rounded-full bg-red flex items-center justify-center">
          <Icon className="w-6 h-6 text-white" />
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-light">{label}</p>
          <p className="text-2xl font-semibold text-dark">{value}</p>
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
          <span className="font-semibold text-dark">Filter by Team</span>
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
                transition-all duration-200 border
                ${isSelected
                  ? "bg-red text-white border-red shadow-[0_12px_32px_rgba(255,136,108,0.2)]"
                  : "bg-white/5 text-dark border-white/10 hover:border-red hover:text-red"
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
const STORAGE_KEY_TEAMS = "picks-filter-teams:v2";
const STALE_BOARD_MINUTES = 15;

/**
 * Main page component
 */
export default function PicksPage() {
  const { setPageContext, submitAction } = useAgentWidget();
  const todayString = getTodayString();
  const [selectedDate, setSelectedDate] = useState(todayString);
  const [isTriggering, setIsTriggering] = useState(false);
  const [selectedTeams, setSelectedTeams] = useState<Set<string>>(new Set());
  const queryClient = useQueryClient();
  const dailyPicksQueryKey = useMemo(
    () => ["daily-picks", selectedDate] as const,
    [selectedDate],
  );
  const fetchDailyPicks = useCallback(
    async (refresh = false) => {
      return await getDailyPicks({ date: selectedDate, refresh });
    },
    [selectedDate],
  );
  
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
    queryKey: dailyPicksQueryKey,
    queryFn: async () => {
      return await fetchDailyPicks();
    },
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const {
    data: lineupsData,
    isLoading: isLineupsLoading,
    isError: isLineupsError,
  } = useQuery({
    queryKey: ["lineups", selectedDate],
    queryFn: async () => getLineups(selectedDate),
    staleTime: 60 * 1000,
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

  const handleTriggerAnalysis = useCallback(async () => {
    setIsTriggering(true);
    try {
      await triggerDailyAnalysis(selectedDate);
      await queryClient.invalidateQueries({ 
        queryKey: dailyPicksQueryKey,
      });
      await refetch();
    } catch (e) {
      console.error("Failed to trigger analysis:", e);
    } finally {
      setIsTriggering(false);
    }
  }, [dailyPicksQueryKey, queryClient, refetch, selectedDate]);
  
  // 從 picks 中提取所有唯一的球隊（使用 player_team）
  // Extract unique teams from picks (using player_team)
  const allTeams = useMemo(() => {
    const picks = data?.picks || [];
    const teamsSet = new Set<string>();
    picks.forEach((pick: DailyPick) => {
      const teamCode = pick.player_team_code || getCanonicalTeamCode(pick.player_team);
      if (teamCode) {
        teamsSet.add(teamCode);
      }
    });
    // 按字母順序排序
    return Array.from(teamsSet).sort();
  }, [data?.picks]);

  useEffect(() => {
    if (allTeams.length === 0) {
      return;
    }

    setSelectedTeams((prev) => {
      const filtered = new Set(Array.from(prev).filter((team) => allTeams.includes(team)));
      if (filtered.size === prev.size) {
        return prev;
      }

      sessionStorage.setItem(STORAGE_KEY_TEAMS, JSON.stringify(Array.from(filtered)));
      return filtered;
    });
  }, [allTeams]);
  
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
  const allPicks = useMemo(() => data?.picks ?? [], [data?.picks]);
  const stats = data?.stats;
  const lineupsByTeam = useMemo(() => {
    return new Map(
      (lineupsData?.lineups ?? []).map((lineup) => [
        getCanonicalTeamCode(lineup.team),
        lineup,
      ]),
    );
  }, [lineupsData?.lineups]);
  
  // 根據選擇的球隊篩選 picks
  // Filter picks based on selected teams
  const picks = useMemo(() => {
    if (selectedTeams.size === 0) {
      return allPicks;
    }
    return allPicks.filter((pick: DailyPick) => 
      selectedTeams.has(pick.player_team_code || getCanonicalTeamCode(pick.player_team))
    );
  }, [allPicks, selectedTeams]);
  
  const highProbCount = picks.filter((p: DailyPick) => p.probability >= 0.70).length;
  const mediumProbCount = picks.filter((p: DailyPick) => p.probability >= 0.65 && p.probability < 0.70).length;
  const analyzedAt = data?.analyzed_at ? new Date(data.analyzed_at) : null;
  const boardAgeMinutes =
    analyzedAt != null ? Math.floor((Date.now() - analyzedAt.getTime()) / 60000) : null;
  const isStaleBoard = boardAgeMinutes != null && boardAgeMinutes > STALE_BOARD_MINUTES;
  const isFilterEmptyState = !isLoading && allPicks.length > 0 && picks.length === 0;
  const isBoardEmptyState = !isLoading && allPicks.length === 0;

  useEffect(() => {
    if (!isFilterEmptyState) {
      return;
    }

    console.debug("filter_empty_state", {
      date: selectedDate,
      selectedTeams: Array.from(selectedTeams),
      totalPicks: allPicks.length,
    });
  }, [allPicks.length, isFilterEmptyState, selectedDate, selectedTeams]);

  useEffect(() => {
    setPageContext({
      route: "/picks",
      date: selectedDate,
      selected_teams: Array.from(selectedTeams),
    });
  }, [selectedDate, selectedTeams, setPageContext]);

  const handleReviewBoard = useCallback(async () => {
    await submitAction({
      action: "review_board",
      message: "Review this board and identify the cleanest bet.",
      contextPatch: {
        visible_picks: picks
          .slice(0, 6)
          .map((pick) => createAgentPickContextFromDailyPick(pick)),
      },
    });
  }, [picks, submitAction]);
  
  return (
    <div className="min-h-screen page-enter">
      <div className="mx-auto max-w-6xl px-6 py-10">
        <section className="grid gap-6 md:grid-cols-[1.2fr_0.8fr] mb-8">
          <div className="card">
            <div className="section-eyebrow">
              <Target className="mr-2 h-3.5 w-3.5" />
              AI Auto Analysis
            </div>

            <h1 className="hero-title mb-4">
              Daily Picks
            </h1>

            <div className="accent-line mb-6" />

            <p className="max-w-2xl text-lg leading-8 text-gray">
              This board surfaces the strongest historical edges for the day, then lets you add, reverse, filter, and move directly into the deeper event workspace without breaking your flow.
            </p>
          </div>

          <div className="card">
            <p className="text-xs uppercase tracking-[0.22em] text-light mb-3">Board status</p>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-light">Day</p>
                <p className="mt-2 text-xl font-semibold text-dark">{dateTitle}</p>
              </div>
              <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-light">Filters</p>
                <p className="mt-2 text-xl font-semibold text-dark">{selectedTeams.size}</p>
              </div>
              <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-light">High</p>
                <p className="mt-2 text-xl font-semibold text-dark">{highProbCount}</p>
              </div>
              <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-light">Medium</p>
                <p className="mt-2 text-xl font-semibold text-dark">{mediumProbCount}</p>
              </div>
            </div>
            {data?.analyzed_at ? (
              <div className="mt-4 flex items-center justify-between rounded-[18px] border border-white/8 bg-white/4 px-4 py-3 text-sm">
                <span
                  className={`rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.18em] ${
                    isStaleBoard
                      ? "bg-yellow-500/15 text-yellow-700"
                      : "bg-green-500/15 text-green-700"
                  }`}
                >
                  {isStaleBoard ? "Stale board" : "Fresh board"}
                </span>
                <span className="text-gray">
                  Updated {new Date(data.analyzed_at).toLocaleTimeString()}
                </span>
              </div>
            ) : null}
          </div>
        </section>

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
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-8">
          <div className="flex items-center gap-4">
            <h2 className="text-xl sm:text-2xl font-bold text-dark">
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

          <div className="flex items-center gap-2 sm:gap-3">
            <button
              onClick={() => void handleReviewBoard()}
              className="btn-refresh"
            >
              <Bot className="w-4 h-4 text-red" />
              <span className="hidden sm:inline">Review Board</span>
              <span className="sm:hidden">Review</span>
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

        {/* Empty board state */}
        {isBoardEmptyState && (
          <div className="card text-center py-16">
            <div className="w-20 h-20 mx-auto mb-6 rounded-full border-2 border-dark/20 flex items-center justify-center">
              <TrendingUp className="w-10 h-10 text-gray" />
            </div>
            <h3 className="text-2xl font-bold text-dark mb-3">
              No High Probability Picks
            </h3>
            <p className="text-gray mb-8 max-w-md mx-auto">
              {data?.message || `No betting options with over 65% probability were found for ${selectedDate}.`}
            </p>
            <div className="flex flex-wrap items-center justify-center gap-3">
              <button
                onClick={handleTriggerAnalysis}
                disabled={isTriggering}
                className="btn-primary"
              >
                <Zap className="w-4 h-4 mr-2" />
                {isTriggering ? "Analyzing..." : "Analyze Now"}
              </button>
              {selectedDate !== todayString ? (
                <button
                  type="button"
                  onClick={() => handleDateChange(todayString)}
                  className="btn-refresh"
                >
                  Jump to Today
                </button>
              ) : null}
            </div>
          </div>
        )}

        {/* Filter empty state */}
        {isFilterEmptyState && (
          <div className="card text-center py-16">
            <div className="w-20 h-20 mx-auto mb-6 rounded-full border-2 border-dark/20 flex items-center justify-center">
              <Filter className="w-10 h-10 text-gray" />
            </div>
            <h3 className="text-2xl font-bold text-dark mb-3">
              No Picks Match Current Filters
            </h3>
            <p className="text-gray mb-8 max-w-md mx-auto">
              {allPicks.length} picks are available for {selectedDate}, but none match the selected team filters.
            </p>
            <button
              type="button"
              onClick={handleClearTeams}
              className="btn-primary"
            >
              Clear filters
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
                    .map((pick: DailyPick, index: number) => {
                      const teamCode = pick.player_team_code || getCanonicalTeamCode(pick.player_team);
                      return (
                        <PickCard
                          key={`${pick.player_name}-${pick.metric}`}
                          pick={pick}
                          index={index}
                          selectedDate={selectedDate}
                          lineup={lineupsByTeam.get(teamCode) ?? null}
                          isLineupLoading={isLineupsLoading}
                          isLineupError={isLineupsError}
                        />
                      );
                    })
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
                    .map((pick: DailyPick, index: number) => {
                      const teamCode = pick.player_team_code || getCanonicalTeamCode(pick.player_team);
                      return (
                        <PickCard
                          key={`${pick.player_name}-${pick.metric}`}
                          pick={pick}
                          index={index}
                          selectedDate={selectedDate}
                          lineup={lineupsByTeam.get(teamCode) ?? null}
                          isLineupLoading={isLineupsLoading}
                          isLineupError={isLineupsError}
                        />
                      );
                    })
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
