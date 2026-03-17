/**
 * PlayerHistoryStats.tsx - Player History Stats Component (Minimal Design)
 * 
 * Design Philosophy:
 * - Cream background with clean cards
 * - Red/yellow/green for data visualization
 * - Clear, readable charts
 */

"use client";

import { useState, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from "recharts";
import {
  TrendingUp,
  TrendingDown,
  BarChart3,
  Calculator,
  Search,
  User,
  Users,
  Loader2,
  AlertCircle,
  Info,
  Filter,
  Target,
  X,
} from "lucide-react";
import { getCSVPlayers, getPlayerHistory, calculateNoVig } from "@/lib/api";
import {
  HISTORY_METRICS,
  RECENT_GAMES_OPTIONS,
  type HistoryMetricKey,
  type GameLog,
  type PlayerProjection,
} from "@/lib/schemas";
import { cn } from "@/lib/utils";

/**
 * Map market key to history metric
 */
function marketToHistoryMetric(marketKey?: string): HistoryMetricKey {
  switch (marketKey) {
    case "player_points": return "points";
    case "player_assists": return "assists";
    case "player_rebounds": return "rebounds";
    case "player_points_rebounds_assists": return "pra";
    default: return "points";
  }
}

/**
 * Map history metric to market key
 */
function historyMetricToMarket(metricKey: HistoryMetricKey): string {
  switch (metricKey) {
    case "points": return "player_points";
    case "assists": return "player_assists";
    case "rebounds": return "player_rebounds";
    case "pra": return "player_points_rebounds_assists";
    default: return "player_points";
  }
}

/**
 * Calculate mode
 */
function calculateMode(numbers: number[]): number | null {
  if (numbers.length === 0) return null;
  
  const counts = new Map<number, number>();
  for (const num of numbers) {
    const rounded = Math.round(num * 10) / 10;
    counts.set(rounded, (counts.get(rounded) || 0) + 1);
  }
  
  const maxCount = Math.max(...Array.from(counts.values()));
  const modes = Array.from(counts.entries())
    .filter(([_, count]) => count === maxCount)
    .map(([value]) => value);
  
  if (maxCount === 1) {
    const sorted = [...numbers].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    if (sorted.length % 2 === 0) {
      return Math.round(((sorted[mid - 1] + sorted[mid]) / 2) * 10) / 10;
    }
    return Math.round(sorted[mid] * 10) / 10;
  }
  
  if (modes.length === 1) return modes[0];
  return Math.round((modes.reduce((a, b) => a + b, 0) / modes.length) * 10) / 10;
}

/**
 * getProjectionValueForMetric - 從投影資料中取出對應 metric 的數值
 *
 * 叫 "getProjectionValueForMetric" 因為它根據 HistoryMetricKey
 * 從 PlayerProjection 物件中取出正確的投影數值。
 * 例如 metric="points" → projection.points
 *
 * @param projection - 球員投影資料
 * @param metric - 統計指標 key
 * @returns 該 metric 的投影數值，或 null
 */
function getProjectionValueForMetric(
  projection: PlayerProjection | undefined,
  metric: HistoryMetricKey
): number | null {
  if (!projection) return null;
  switch (metric) {
    case "points": return projection.points ?? null;
    case "rebounds": return projection.rebounds ?? null;
    case "assists": return projection.assists ?? null;
    case "pra": return projection.pra ?? null;
    default: return null;
  }
}

interface PlayerHistoryStatsProps {
  eventId?: string;
  onPlayerSelect?: (playerName: string) => void;
  initialPlayer?: string;
  initialMarket?: string;
  initialThreshold?: string;
  /**
   * 球員投影資料（可選）
   * 
   * 當從 Event Detail Page 傳入時，用於：
   * 1. 在圖表上繪製投影值的參考線（藍色實線）
   * 2. 在 stat cards 中新增第 5 張「Projected」卡片
   */
  projection?: PlayerProjection;
}

/**
 * PlayerHistoryStats Component
 */
export function PlayerHistoryStats({
  eventId,
  onPlayerSelect,
  initialPlayer = "",
  initialMarket,
  initialThreshold,
  projection,
}: PlayerHistoryStatsProps) {
  const [searchInput, setSearchInput] = useState(initialPlayer);
  const [selectedPlayer, setSelectedPlayer] = useState(initialPlayer);
  const [metric, setMetric] = useState<HistoryMetricKey>(
    marketToHistoryMetric(initialMarket)
  );
  const [threshold, setThreshold] = useState<string>(initialThreshold || "24.5");
  const [selectedOpponent, setSelectedOpponent] = useState<string>("");
  const [starterFilter, setStarterFilter] = useState<string>("all");
  const [teammateFilter, setTeammateFilter] = useState<string[]>([]);
  const [teammatePlayedFilter, setTeammatePlayedFilter] = useState<string>("all");
  const [teammateSearchInput, setTeammateSearchInput] = useState<string>("");
  const [isTeammateDropdownOpen, setIsTeammateDropdownOpen] = useState(false);
  const [isFetchingOdds, setIsFetchingOdds] = useState(false);

  useEffect(() => {
    if (initialPlayer && initialPlayer !== selectedPlayer) {
      setSelectedPlayer(initialPlayer);
      setSearchInput(initialPlayer);
      setSelectedOpponent("");
    }
  }, [initialPlayer, selectedPlayer]);

  useEffect(() => {
    if (initialMarket) {
      const mappedMetric = marketToHistoryMetric(initialMarket);
      if (mappedMetric !== metric) {
        setMetric(mappedMetric);
      }
    }
  }, [initialMarket, metric]);
  
  const [recentN, setRecentN] = useState<number>(0);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  const { data: playersData, isLoading: isLoadingPlayers } = useQuery({
    queryKey: ["csvPlayers", searchInput],
    queryFn: () => getCSVPlayers(searchInput),
    enabled: isDropdownOpen || searchInput.length > 0,
    staleTime: 60 * 1000,
  });

  const {
    data: historyData,
    isLoading: isLoadingHistory,
    isError: isHistoryError,
    error: historyError,
  } = useQuery({
    queryKey: ["playerHistory", selectedPlayer, metric, threshold, recentN, selectedOpponent, starterFilter, teammateFilter, teammatePlayedFilter],
    queryFn: () =>
      getPlayerHistory({
        player: selectedPlayer,
        metric,
        threshold: parseFloat(threshold),
        n: recentN,
        bins: 15,
        exclude_dnp: true,
        opponent: selectedOpponent || undefined,
        is_starter: starterFilter === "all" ? undefined : starterFilter === "starter",
        teammate_filter: teammateFilter.length > 0 ? teammateFilter : undefined,
        teammate_played: teammatePlayedFilter === "all" ? undefined : teammatePlayedFilter === "with",
      }),
    enabled: !!selectedPlayer && !!threshold && !isNaN(parseFloat(threshold)),
    staleTime: 30 * 1000,
  });

  const fetchOddsAndSetThreshold = useCallback(
    async (playerName: string, metricKey: HistoryMetricKey) => {
      if (!eventId) return;
      
      setIsFetchingOdds(true);
      
      try {
        const marketKey = historyMetricToMarket(metricKey);
        const result = await calculateNoVig({
          event_id: eventId,
          player_name: playerName,
          market: marketKey,
          regions: "us",
          bookmakers: null,
          odds_format: "american",
        });
        
        if (result.results && result.results.length > 0) {
          const lines = result.results.map((r) => r.line);
          const modeValue = calculateMode(lines);
          
          if (modeValue !== null) {
            setThreshold(modeValue.toString());
          }
        }
      } catch (error) {
        console.log("Unable to fetch odds data, using default threshold");
      } finally {
        setIsFetchingOdds(false);
      }
    },
    [eventId]
  );

  const handleSelectPlayer = useCallback(
    (playerName: string) => {
      setSelectedPlayer(playerName);
      setSearchInput(playerName);
      setIsDropdownOpen(false);
      setSelectedOpponent("");
      setTeammateFilter([]);
      setTeammatePlayedFilter("all");
      setTeammateSearchInput("");
      onPlayerSelect?.(playerName);
      
      if (eventId) {
        fetchOddsAndSetThreshold(playerName, metric);
      }
    },
    [onPlayerSelect, eventId, metric, fetchOddsAndSetThreshold]
  );

  const handleThresholdChange = (value: string) => {
    setThreshold(value);
  };

  const handleMetricChange = (newMetric: HistoryMetricKey) => {
    setMetric(newMetric);
    if (selectedPlayer && eventId) {
      fetchOddsAndSetThreshold(selectedPlayer, newMetric);
    }
  };

  const playerList = playersData?.players || [];
  const opponentList = historyData?.opponents || [];
  const teammateList = historyData?.teammates || [];
  const gameLogs = historyData?.game_logs || [];

  const filteredTeammateList = teammateSearchInput
    ? teammateList.filter(
        (t) =>
          t.toLowerCase().includes(teammateSearchInput.toLowerCase()) &&
          !teammateFilter.includes(t)
      )
    : teammateList.filter((t) => !teammateFilter.includes(t));

  // 從投影資料取得當前 metric 的投影數值
  // projectedValue 用於：(1) 圖表的藍色參考線 (2) 第 5 張 stat card
  const projectedValue = getProjectionValueForMetric(projection, metric);

  return (
    <div className="space-y-6">
      {/* Title */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-red flex items-center justify-center">
          <BarChart3 className="w-4 h-4 text-white" />
        </div>
        <h3 className="text-lg font-bold text-dark">Historical Data Analysis</h3>
      </div>

      {/* Player selection */}
      <div className="space-y-4">
        {/* Player search */}
        <div className="relative">
          <label className="control-label mb-2">
            <User className="h-4 w-4 text-red" />
            Select Player (from CSV database)
          </label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-light" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => {
                setSearchInput(e.target.value);
                setIsDropdownOpen(true);
              }}
              onFocus={() => setIsDropdownOpen(true)}
              placeholder="Search player name..."
              className="control-input w-full pl-12"
            />
            {isLoadingPlayers && (
              <Loader2 className="absolute right-4 top-1/2 h-5 w-5 -translate-y-1/2 animate-spin text-red" />
            )}
          </div>

          {/* Dropdown */}
          {isDropdownOpen && playerList.length > 0 && (
            <ul className="control-popover absolute z-50 mt-2 max-h-60 w-full">
              {playerList.slice(0, 50).map((player) => (
                <li
                  key={player}
                  onClick={() => handleSelectPlayer(player)}
                  className={cn(
                    "control-option flex items-center gap-3 px-4 py-3",
                    player === selectedPlayer
                      ? "control-option-active"
                      : "text-dark"
                  )}
                >
                  <User className="h-4 w-4 text-light" />
                  <span className="font-medium text-inherit">{player}</span>
                </li>
              ))}
              {playerList.length > 50 && (
                <li className="px-4 py-2 text-center text-sm text-light">
                  Showing first 50, please enter keywords to narrow down
                </li>
              )}
            </ul>
          )}
        </div>

        {/* Options: metric + threshold + games + opponent + starter */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
          {/* Stat metric */}
          <div>
            <label className="block text-sm font-bold text-dark mb-2">
              Stat Metric
            </label>
            <select
              value={metric}
              onChange={(e) => handleMetricChange(e.target.value as HistoryMetricKey)}
              className="input w-full"
            >
              {HISTORY_METRICS.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>

          {/* Threshold */}
          <div>
            <label className="block text-sm font-bold text-dark mb-2">
              <Calculator className="inline w-4 h-4 mr-1" />
              Threshold
            </label>
            <div className="relative">
              <input
                type="number"
                step="0.5"
                value={threshold}
                onChange={(e) => handleThresholdChange(e.target.value)}
                placeholder="e.g., 24.5"
                className="input w-full"
                disabled={isFetchingOdds}
              />
              {isFetchingOdds && (
                <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-red animate-spin" />
              )}
            </div>
          </div>

          {/* Game range */}
          <div>
            <label className="block text-sm font-bold text-dark mb-2">
              Game Range
            </label>
            <select
              value={recentN}
              onChange={(e) => setRecentN(Number(e.target.value))}
              className="input w-full"
            >
              {RECENT_GAMES_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Opponent filter */}
          <div>
            <label className="block text-sm font-bold text-dark mb-2">
              <Filter className="inline w-4 h-4 mr-1" />
              Opponent Filter
            </label>
            <select
              value={selectedOpponent}
              onChange={(e) => setSelectedOpponent(e.target.value)}
              className="input w-full"
              disabled={!selectedPlayer || opponentList.length === 0}
            >
              <option value="">All Opponents</option>
              {opponentList.map((opp) => (
                <option key={opp} value={opp}>
                  vs {opp}
                </option>
              ))}
            </select>
          </div>

          {/* Starter filter */}
          <div>
            <label className="block text-sm font-bold text-dark mb-2">
              <Filter className="inline w-4 h-4 mr-1" />
              Starter Filter
            </label>
            <select
              value={starterFilter}
              onChange={(e) => setStarterFilter(e.target.value)}
              className="input w-full"
            >
              <option value="all">All Games</option>
              <option value="starter">Starter Only</option>
              <option value="bench">Bench Only</option>
            </select>
          </div>
        </div>

        {/* Teammate Impact Filter - 僅限同隊隊友 */}
        {selectedPlayer && teammateList.length > 0 && (
          <div className="space-y-3 pt-2">
            <div>
              <label className="control-label">
                <Users className="h-4 w-4 text-red" />
                Teammate Impact Filter
              </label>
              <p className="control-hint mt-1">
                Only teammates from the same team can be selected
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Teammate search + multi-select */}
              <div className="relative">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-light" />
                  <input
                    type="text"
                    value={teammateSearchInput}
                    onChange={(e) => {
                      setTeammateSearchInput(e.target.value);
                      setIsTeammateDropdownOpen(true);
                    }}
                    onFocus={() => setIsTeammateDropdownOpen(true)}
                    placeholder="Search teammate to add..."
                    className="control-input w-full pl-11 text-sm"
                  />
                </div>

                {isTeammateDropdownOpen && filteredTeammateList.length > 0 && (
                  <ul className="control-popover absolute z-50 mt-1 max-h-48 w-full">
                    {filteredTeammateList.slice(0, 30).map((teammate) => (
                      <li
                        key={teammate}
                        onClick={() => {
                          setTeammateFilter((prev) => [...prev, teammate]);
                          setTeammateSearchInput("");
                          setIsTeammateDropdownOpen(false);
                          if (teammatePlayedFilter === "all") {
                            setTeammatePlayedFilter("without");
                          }
                        }}
                        className="control-option flex items-center gap-2 px-3 py-2 text-sm text-dark"
                      >
                        <User className="h-3 w-3 text-light" />
                        {teammate}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* With / Without toggle */}
              <div>
                <select
                  value={teammatePlayedFilter}
                  onChange={(e) => setTeammatePlayedFilter(e.target.value)}
                  className="input w-full text-sm"
                  disabled={teammateFilter.length === 0}
                >
                  <option value="all">All Games (no teammate filter)</option>
                  <option value="with">With selected teammates</option>
                  <option value="without">Without selected teammates</option>
                </select>
              </div>
            </div>

            {/* Selected teammate chips */}
            {teammateFilter.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {teammateFilter.map((t) => (
                  <span
                    key={t}
                    className="control-chip-active inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold"
                  >
                    {t}
                    <button
                      onClick={() => {
                        const next = teammateFilter.filter((x) => x !== t);
                        setTeammateFilter(next);
                        if (next.length === 0) {
                          setTeammatePlayedFilter("all");
                        }
                      }}
                      className="transition-colors hover:text-white/70"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
                <button
                  onClick={() => {
                    setTeammateFilter([]);
                    setTeammatePlayedFilter("all");
                  }}
                  className="text-xs text-red font-bold hover:underline"
                >
                  Clear all
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Error */}
      {isHistoryError && (
        <div className="card border-red">
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-lg bg-red flex items-center justify-center shrink-0">
              <AlertCircle className="w-5 h-5 text-white" />
            </div>
            <div>
              <p className="font-bold text-dark">Load Failed</p>
              <p className="text-sm text-gray">
                {historyError instanceof Error
                  ? historyError.message
                  : "Unable to fetch historical data"}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Results */}
      {selectedPlayer && historyData && (
        <div className="space-y-6 animate-fade-in">
          {/* Stats cards */}
          {/* 
            當有投影資料時，grid 從 4 欄變為 5 欄，多出一張「Projected」卡片。
            grid-cols-2: 手機上 2 欄
            md:grid-cols-4 / md:grid-cols-5: 桌面上 4 或 5 欄
          */}
          <div className={cn(
            "grid grid-cols-2 gap-4",
            projectedValue != null ? "md:grid-cols-5" : "md:grid-cols-4"
          )}>
            {/* Over probability */}
            <div className="card bg-green-50 border-green-300">
              <div className="flex items-center gap-2 text-green-700 mb-2">
                <TrendingUp className="w-4 h-4" />
                <span className="text-sm font-bold">Over Probability</span>
              </div>
              <p className="text-2xl font-bold text-green-600">
                {historyData.p_over !== null && historyData.p_over !== undefined
                  ? `${(historyData.p_over * 100).toFixed(1)}%`
                  : "N/A"}
              </p>
              <p className="text-xs text-gray mt-1">
                &gt; {threshold}
              </p>
            </div>

            {/* Under probability */}
            <div className="card bg-red/5 border-red/30">
              <div className="flex items-center gap-2 text-red mb-2">
                <TrendingDown className="w-4 h-4" />
                <span className="text-sm font-bold">Under Probability</span>
              </div>
              <p className="text-2xl font-bold text-red">
                {historyData.p_under !== null && historyData.p_under !== undefined
                  ? `${(historyData.p_under * 100).toFixed(1)}%`
                  : "N/A"}
              </p>
              <p className="text-xs text-gray mt-1">
                &lt; {threshold}
              </p>
            </div>

            {/* Average */}
            <div className="card">
              <p className="text-sm font-bold text-dark mb-1">Average</p>
              <p className="text-xl font-bold text-dark">
                {historyData.mean?.toFixed(1) ?? "N/A"}
              </p>
            </div>

            {/* Sample games */}
            <div className="card">
              <p className="text-sm font-bold text-dark mb-1">Sample Games</p>
              <p className="text-xl font-bold text-dark">
                {historyData.n_games} games
                {(selectedOpponent || starterFilter !== "all" || teammateFilter.length > 0) && (
                  <span className="text-sm text-gray ml-1">
                    (
                    {selectedOpponent && `vs ${selectedOpponent}`}
                    {selectedOpponent && (starterFilter !== "all" || teammateFilter.length > 0) && ", "}
                    {starterFilter === "starter" && "Starter"}
                    {starterFilter === "bench" && "Bench"}
                    {starterFilter !== "all" && teammateFilter.length > 0 && ", "}
                    {teammateFilter.length > 0 && teammatePlayedFilter === "with" && `w/ ${teammateFilter.join(", ")}`}
                    {teammateFilter.length > 0 && teammatePlayedFilter === "without" && `w/o ${teammateFilter.join(", ")}`}
                    )
                  </span>
                )}
              </p>
            </div>

            {/* Projected Value (5th card) — 只在有投影資料時顯示 */}
            {/* 
              這張卡片橋接「歷史分析」和「投影預測」兩種資料來源：
              使用者可以同時看到 "歷史上 72% Over" 和 "投影 29.3 也支持 Over +2.8"
            */}
            {projectedValue != null && (
              <div className="card bg-blue-50 border-blue-300">
                <div className="flex items-center gap-2 text-blue-700 mb-2">
                  <Target className="w-4 h-4" />
                  <span className="text-sm font-bold">Projected</span>
                </div>
                <p className="text-2xl font-bold text-blue-600">
                  {projectedValue.toFixed(1)}
                </p>
                {threshold && !isNaN(parseFloat(threshold)) && (
                  <p className={cn(
                    "text-xs font-bold mt-1",
                    projectedValue >= parseFloat(threshold) ? "text-green-600" : "text-red"
                  )}>
                    Edge: {projectedValue >= parseFloat(threshold) ? "+" : ""}
                    {(projectedValue - parseFloat(threshold)).toFixed(1)} vs line
                  </p>
                )}
                <p className="text-[10px] text-gray mt-0.5">
                  SportsDataIO ML
                </p>
              </div>
            )}
          </div>

          {/* Chart */}
          {gameLogs && gameLogs.length > 0 && (
            <div className="card">
              <h4 className="text-sm font-bold text-dark mb-4 flex items-center gap-2">
                <BarChart3 className="w-4 h-4" />
                {HISTORY_METRICS.find((m) => m.key === metric)?.name} Historical Trend
                {(selectedOpponent || starterFilter !== "all" || teammateFilter.length > 0) && (
                  <span className="text-red ml-2">
                    (
                    {selectedOpponent && `vs ${selectedOpponent}`}
                    {selectedOpponent && (starterFilter !== "all" || teammateFilter.length > 0) && ", "}
                    {starterFilter === "starter" && "Starter Only"}
                    {starterFilter === "bench" && "Bench Only"}
                    {starterFilter !== "all" && teammateFilter.length > 0 && ", "}
                    {teammateFilter.length > 0 && teammatePlayedFilter === "with" && `w/ ${teammateFilter.join(", ")}`}
                    {teammateFilter.length > 0 && teammatePlayedFilter === "without" && `w/o ${teammateFilter.join(", ")}`}
                    )
                  </span>
                )}
              </h4>
              <div className="h-72 md:h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={gameLogs}
                    margin={{ top: 20, right: 30, left: 20, bottom: 60 }}
                  >
                    <XAxis
                      dataKey="date"
                      tick={{ fill: "#6B6B6B", fontSize: 10 }}
                      axisLine={{ stroke: "#1A1A1A" }}
                      tickLine={{ stroke: "#1A1A1A" }}
                      angle={-45}
                      textAnchor="end"
                      height={60}
                      tickFormatter={(value, index) => {
                        const log = gameLogs[index];
                        const oppAbbr = log?.opponent?.substring(0, 3).toUpperCase() || "";
                        return `${value} ${oppAbbr}`;
                      }}
                    />
                    <YAxis
                      tick={{ fill: "#6B6B6B", fontSize: 12 }}
                      axisLine={{ stroke: "#1A1A1A" }}
                      tickLine={{ stroke: "#1A1A1A" }}
                      domain={[0, 'auto']}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#FFFFFF",
                        border: "2px solid #1A1A1A",
                        borderRadius: "8px",
                        padding: "12px",
                        color: "#1A1A1A",
                      }}
                      labelStyle={{
                        color: "#1A1A1A",
                        fontWeight: "700",
                        marginBottom: "8px",
                      }}
                      itemStyle={{
                        color: "#1A1A1A",
                      }}
                      formatter={(value, name, props) => {
                        const log = props.payload as any;
                        const metricName = HISTORY_METRICS.find((m) => m.key === metric)?.name || metric;
                        
                        return [
                          <div key="value" className="space-y-1">
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-lg" style={{ color: log.is_over ? "#22C55E" : "#E92016" }}>
                                {value}
                              </span>
                              <span className="text-xs px-2 py-0.5 rounded font-bold" style={{ 
                                backgroundColor: log.is_over ? "#22C55E" : "#E92016",
                                color: "#FFFFFF"
                              }}>
                                {log.is_over ? "Over" : "Under"}
                              </span>
                            </div>
                            <div className="text-sm space-y-0.5">
                              <div>⏱️ Minutes: <span className="font-bold">{log.minutes || 0} min</span></div>
                              <div>
                                {log.is_starter ? (
                                  <span className="text-yellow font-bold">⭐ Starter</span>
                                ) : (
                                  <span className="text-gray">🪑 Bench</span>
                                )}
                              </div>
                            </div>
                          </div>,
                          metricName
                        ];
                      }}
                      labelFormatter={(value, payload) => {
                        if (payload && payload[0]) {
                          const log = payload[0].payload as any;
                          return (
                            <div className="font-bold border-b border-dark/20 pb-2 mb-2">
                              📅 {log.date_full} vs {log.opponent}
                            </div>
                          );
                        }
                        return value;
                      }}
                    />
                    {/* Threshold line（紅色虛線）— 盤口閾值 */}
                    <ReferenceLine
                      y={parseFloat(threshold)}
                      stroke="#E92016"
                      strokeWidth={2}
                      strokeDasharray="5 5"
                      label={{
                        value: `Threshold: ${threshold}`,
                        fill: "#E92016",
                        fontSize: 12,
                        fontWeight: 700,
                        position: "right",
                      }}
                    />
                    {/* Projected value line（藍色實線）— SportsDataIO 投影值 */}
                    {/* 
                      只在有投影資料時顯示。
                      藍色實線 vs 紅色虛線，讓使用者在同一圖表上
                      看到投影值相對於盤口和歷史數據的位置。
                    */}
                    {projectedValue != null && (
                      <ReferenceLine
                        y={projectedValue}
                        stroke="#2563EB"
                        strokeWidth={2}
                        label={{
                          value: `Projected: ${projectedValue.toFixed(1)}`,
                          fill: "#2563EB",
                          fontSize: 12,
                          fontWeight: 700,
                          position: "left",
                        }}
                      />
                    )}
                    <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                      {gameLogs.map((entry, index) => (
                        <Cell
                          key={`cell-${index}`}
                          fill={entry.is_over ? "#22C55E" : "#F87171"}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="flex justify-center gap-6 mt-4 text-xs flex-wrap">
                <div className="flex items-center gap-2">
                  <div className="w-4 h-4 rounded bg-green-500" />
                  <span className="text-dark font-medium">Over (above threshold)</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-4 h-4 rounded bg-red/70" />
                  <span className="text-dark font-medium">Under (below threshold)</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-8 h-0.5 bg-red border-dashed border" />
                  <span className="text-dark font-medium">Threshold line</span>
                </div>
                {/* 投影參考線圖例 — 只在有投影資料時顯示 */}
                {projectedValue != null && (
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-0.5 bg-blue-600" />
                    <span className="text-dark font-medium">Projected value</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Notes */}
          <div className="card">
            <div className="flex items-start gap-3">
              <Info className="w-5 h-5 text-gray shrink-0 mt-0.5" />
              <div className="text-xs text-gray space-y-1">
                <p>
                  📊 The above data is calculated based on CSV historical game records, representing &quot;empirical probability&quot;
                </p>
                <p>
                  ⚠️ This data is for reference only and does not represent actual prediction results, please bet responsibly
                </p>
                {historyData.equal_count && historyData.equal_count > 0 && (
                  <p>
                    📌 {historyData.equal_count} games exactly equal the threshold {threshold}, these games are not counted as Over or Under
                  </p>
                )}
                {selectedOpponent && (
                  <p>
                    🎯 Currently showing only games against {selectedOpponent}
                  </p>
                )}
                {starterFilter === "starter" && (
                  <p>
                    ⭐ Currently showing only starter games
                  </p>
                )}
                {starterFilter === "bench" && (
                  <p>
                    🪑 Currently showing only bench games
                  </p>
                )}
                {teammateFilter.length > 0 && teammatePlayedFilter === "with" && (
                  <p>
                    👥 Currently showing games where {teammateFilter.join(", ")} played
                  </p>
                )}
                {teammateFilter.length > 0 && teammatePlayedFilter === "without" && (
                  <p>
                    👤 Currently showing games where {teammateFilter.join(", ")} did NOT play
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Loading */}
      {isLoadingHistory && selectedPlayer && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 text-red animate-spin" />
          <span className="ml-3 text-gray font-medium">Calculating historical data...</span>
        </div>
      )}

      {/* No player selected */}
      {!selectedPlayer && (
        <div className="text-center py-12">
          <User className="w-12 h-12 mx-auto mb-3 text-gray opacity-50" />
          <p className="text-gray">Please select a player to view historical data analysis</p>
        </div>
      )}
    </div>
  );
}
