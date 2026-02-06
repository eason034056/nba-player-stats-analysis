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
  Loader2,
  AlertCircle,
  Info,
  Filter,
} from "lucide-react";
import { getCSVPlayers, getPlayerHistory, calculateNoVig } from "@/lib/api";
import {
  HISTORY_METRICS,
  RECENT_GAMES_OPTIONS,
  type HistoryMetricKey,
  type GameLog,
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

interface PlayerHistoryStatsProps {
  eventId?: string;
  onPlayerSelect?: (playerName: string) => void;
  initialPlayer?: string;
  initialMarket?: string;
  initialThreshold?: string;
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
}: PlayerHistoryStatsProps) {
  const [searchInput, setSearchInput] = useState(initialPlayer);
  const [selectedPlayer, setSelectedPlayer] = useState(initialPlayer);
  const [metric, setMetric] = useState<HistoryMetricKey>(
    marketToHistoryMetric(initialMarket)
  );
  const [threshold, setThreshold] = useState<string>(initialThreshold || "24.5");
  const [selectedOpponent, setSelectedOpponent] = useState<string>("");
  const [starterFilter, setStarterFilter] = useState<string>("all");
  const [isFetchingOdds, setIsFetchingOdds] = useState(false);

  useEffect(() => {
    if (initialPlayer && initialPlayer !== selectedPlayer) {
      setSelectedPlayer(initialPlayer);
      setSearchInput(initialPlayer);
      setSelectedOpponent("");
    }
  }, [initialPlayer]);

  useEffect(() => {
    if (initialMarket) {
      const mappedMetric = marketToHistoryMetric(initialMarket);
      if (mappedMetric !== metric) {
        setMetric(mappedMetric);
      }
    }
  }, [initialMarket]);
  
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
    queryKey: ["playerHistory", selectedPlayer, metric, threshold, recentN, selectedOpponent, starterFilter],
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
  const gameLogs = historyData?.game_logs || [];

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
          <label className="block text-sm font-bold text-dark mb-2">
            <User className="inline w-4 h-4 mr-1.5" />
            Select Player (from CSV database)
          </label>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => {
                setSearchInput(e.target.value);
                setIsDropdownOpen(true);
              }}
              onFocus={() => setIsDropdownOpen(true)}
              placeholder="Search player name..."
              className="input pl-10 w-full"
            />
            {isLoadingPlayers && (
              <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-red animate-spin" />
            )}
          </div>

          {/* Dropdown */}
          {isDropdownOpen && playerList.length > 0 && (
            <ul className="absolute z-50 w-full mt-2 max-h-60 overflow-auto bg-white border-2 border-dark rounded-lg">
              {playerList.slice(0, 50).map((player) => (
                <li
                  key={player}
                  onClick={() => handleSelectPlayer(player)}
                  className={cn(
                    "px-4 py-3 cursor-pointer flex items-center gap-3 transition-colors",
                    player === selectedPlayer
                      ? "bg-yellow text-dark"
                      : "text-dark hover:bg-cream"
                  )}
                >
                  <User className="w-4 h-4 text-gray" />
                  <span className="font-medium">{player}</span>
                </li>
              ))}
              {playerList.length > 50 && (
                <li className="px-4 py-2 text-sm text-gray text-center">
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
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
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
                {(selectedOpponent || starterFilter !== "all") && (
                  <span className="text-sm text-gray ml-1">
                    (
                    {selectedOpponent && `vs ${selectedOpponent}`}
                    {selectedOpponent && starterFilter !== "all" && ", "}
                    {starterFilter === "starter" && "Starter"}
                    {starterFilter === "bench" && "Bench"}
                    )
                  </span>
                )}
              </p>
            </div>
          </div>

          {/* Chart */}
          {gameLogs && gameLogs.length > 0 && (
            <div className="card">
              <h4 className="text-sm font-bold text-dark mb-4 flex items-center gap-2">
                <BarChart3 className="w-4 h-4" />
                {HISTORY_METRICS.find((m) => m.key === metric)?.name} Historical Trend
                {(selectedOpponent || starterFilter !== "all") && (
                  <span className="text-red ml-2">
                    (
                    {selectedOpponent && `vs ${selectedOpponent}`}
                    {selectedOpponent && starterFilter !== "all" && ", "}
                    {starterFilter === "starter" && "Starter Only"}
                    {starterFilter === "bench" && "Bench Only"}
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
                    {/* Threshold line */}
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
              <div className="flex justify-center gap-6 mt-4 text-xs">
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
              </div>
            </div>
          )}

          {/* Notes */}
          <div className="card">
            <div className="flex items-start gap-3">
              <Info className="w-5 h-5 text-gray shrink-0 mt-0.5" />
              <div className="text-xs text-gray space-y-1">
                <p>
                  📊 The above data is calculated based on CSV historical game records, representing "empirical probability"
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
