/**
 * PlayerHistoryStats.tsx - 球員歷史數據統計元件
 * 
 * 顯示球員在指定指標上的歷史數據統計和視覺化
 * 
 * 功能：
 * - 從 CSV 讀取球員歷史比賽數據
 * - 計算並顯示 Over/Under 經驗機率
 * - 使用 Recharts 繪製時間序列圖表（X軸：日期+對手，Y軸：數值）
 * - 支援對手篩選功能
 * - 在圖表上標記用戶設定的閾值線
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
import { getCSVPlayers, getPlayerHistory } from "@/lib/api";
import {
  HISTORY_METRICS,
  RECENT_GAMES_OPTIONS,
  type HistoryMetricKey,
  type GameLog,
} from "@/lib/schemas";
import { cn } from "@/lib/utils";

/**
 * 將博彩公司市場類型映射到歷史數據指標
 * 
 * @param marketKey - 博彩公司市場 key（如 "player_points"）
 * @returns 歷史數據指標 key（如 "points"）
 * 
 * 映射關係：
 * - player_points -> points
 * - player_assists -> assists
 * - player_rebounds -> rebounds
 * - player_points_rebounds_assists -> pra
 */
function marketToHistoryMetric(marketKey?: string): HistoryMetricKey {
  switch (marketKey) {
    case "player_points":
      return "points";
    case "player_assists":
      return "assists";
    case "player_rebounds":
      return "rebounds";
    case "player_points_rebounds_assists":
      return "pra";
    default:
      return "points";
  }
}

/**
 * PlayerHistoryStats Props
 * 
 * @property onPlayerSelect - 當用戶選擇球員時的回調（可選）
 * @property initialPlayer - 初始選擇的球員（可選）
 * @property initialMarket - 初始選擇的市場類型（可選，會自動映射到歷史數據指標）
 */
interface PlayerHistoryStatsProps {
  onPlayerSelect?: (playerName: string) => void;
  initialPlayer?: string;
  initialMarket?: string;  // 博彩公司的市場 key（如 "player_points"）
}

/**
 * PlayerHistoryStats 元件
 * 
 * 顯示球員歷史數據統計和時間序列圖表
 */
export function PlayerHistoryStats({
  onPlayerSelect,
  initialPlayer = "",
  initialMarket,
}: PlayerHistoryStatsProps) {
  // ==================== 狀態管理 ====================
  
  // 球員搜尋輸入
  const [searchInput, setSearchInput] = useState(initialPlayer);
  
  // 選擇的球員
  const [selectedPlayer, setSelectedPlayer] = useState(initialPlayer);
  
  // 統計指標（預設得分，或從初始市場類型映射）
  const [metric, setMetric] = useState<HistoryMetricKey>(
    marketToHistoryMetric(initialMarket)
  );
  
  // 閾值輸入
  const [threshold, setThreshold] = useState<string>("24.5");

  // 對手篩選（空字串表示全部）
  const [selectedOpponent, setSelectedOpponent] = useState<string>("");

  // ==================== 同步外部 props ====================
  
  // 當上方選擇的球員改變時，同步到歷史數據分析區
  useEffect(() => {
    if (initialPlayer && initialPlayer !== selectedPlayer) {
      setSelectedPlayer(initialPlayer);
      setSearchInput(initialPlayer);
      setSelectedOpponent(""); // 重置對手篩選
    }
  }, [initialPlayer]);

  // 當上方選擇的市場類型改變時，同步到歷史數據分析區的指標
  useEffect(() => {
    if (initialMarket) {
      const mappedMetric = marketToHistoryMetric(initialMarket);
      if (mappedMetric !== metric) {
        setMetric(mappedMetric);
      }
    }
  }, [initialMarket]);
  
  // 最近 N 場
  const [recentN, setRecentN] = useState<number>(0);
  
  // 下拉選單是否展開
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  // ==================== API 查詢 ====================

  // 取得所有球員列表（用於搜尋）
  const { data: playersData, isLoading: isLoadingPlayers } = useQuery({
    queryKey: ["csvPlayers", searchInput],
    queryFn: () => getCSVPlayers(searchInput),
    enabled: isDropdownOpen || searchInput.length > 0,
    staleTime: 60 * 1000, // 60 秒快取
  });

  // 取得球員歷史統計
  const {
    data: historyData,
    isLoading: isLoadingHistory,
    isError: isHistoryError,
    error: historyError,
  } = useQuery({
    queryKey: ["playerHistory", selectedPlayer, metric, threshold, recentN, selectedOpponent],
    queryFn: () =>
      getPlayerHistory({
        player: selectedPlayer,
        metric,
        threshold: parseFloat(threshold),
        n: recentN,
        bins: 15,
        exclude_dnp: true,
        opponent: selectedOpponent || undefined,
      }),
    enabled: !!selectedPlayer && !!threshold && !isNaN(parseFloat(threshold)),
    staleTime: 30 * 1000,
  });

  // ==================== 事件處理 ====================

  // 選擇球員
  const handleSelectPlayer = useCallback(
    (playerName: string) => {
      setSelectedPlayer(playerName);
      setSearchInput(playerName);
      setIsDropdownOpen(false);
      setSelectedOpponent(""); // 重置對手篩選
      onPlayerSelect?.(playerName);
    },
    [onPlayerSelect]
  );

  // 閾值變更
  const handleThresholdChange = (value: string) => {
    setThreshold(value);
  };

  // 球員列表
  const playerList = playersData?.players || [];

  // 對手列表
  const opponentList = historyData?.opponents || [];

  // Game logs 資料（用於圖表）
  const gameLogs = historyData?.game_logs || [];

  // ==================== 渲染 ====================

  return (
    <div className="space-y-6">
      {/* 標題 */}
      <div className="flex items-center gap-2 text-amber-400">
        <BarChart3 className="w-5 h-5" />
        <h3 className="text-lg font-semibold">歷史數據分析</h3>
      </div>

      {/* 球員選擇區 */}
      <div className="space-y-4">
        {/* 球員搜尋 */}
        <div className="relative">
          <label className="block text-sm font-medium text-slate-300 mb-2">
            <User className="inline w-4 h-4 mr-1.5" />
            選擇球員（從 CSV 資料庫）
          </label>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => {
                setSearchInput(e.target.value);
                setIsDropdownOpen(true);
              }}
              onFocus={() => setIsDropdownOpen(true)}
              placeholder="搜尋球員名稱..."
              className="input pl-10 w-full"
            />
            {isLoadingPlayers && (
              <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500 animate-spin" />
            )}
          </div>

          {/* 下拉選單 */}
          {isDropdownOpen && playerList.length > 0 && (
            <ul className="absolute z-50 w-full mt-1 max-h-60 overflow-auto bg-slate-800 border border-slate-700 rounded-lg shadow-xl">
              {playerList.slice(0, 50).map((player) => (
                <li
                  key={player}
                  onClick={() => handleSelectPlayer(player)}
                  className={cn(
                    "px-4 py-2.5 cursor-pointer flex items-center gap-3 transition-colors",
                    player === selectedPlayer
                      ? "bg-amber-600/20 text-amber-300"
                      : "text-slate-300 hover:bg-slate-700/50"
                  )}
                >
                  <User className="w-4 h-4 text-slate-500" />
                  <span>{player}</span>
                </li>
              ))}
              {playerList.length > 50 && (
                <li className="px-4 py-2 text-sm text-slate-500 text-center">
                  顯示前 50 位，請輸入關鍵字縮小範圍
                </li>
              )}
            </ul>
          )}
        </div>

        {/* 選項區：指標 + 閾值 + 場次 + 對手 */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* 統計指標選擇 */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              統計指標
            </label>
            <select
              value={metric}
              onChange={(e) => setMetric(e.target.value as HistoryMetricKey)}
              className="input w-full"
            >
              {HISTORY_METRICS.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>

          {/* 閾值輸入 */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              <Calculator className="inline w-4 h-4 mr-1" />
              閾值 (Threshold)
            </label>
            <input
              type="number"
              step="0.5"
              value={threshold}
              onChange={(e) => handleThresholdChange(e.target.value)}
              placeholder="例如 24.5"
              className="input w-full"
            />
          </div>

          {/* 最近 N 場 */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              場次範圍
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

          {/* 對手篩選 */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              <Filter className="inline w-4 h-4 mr-1" />
              對手篩選
            </label>
            <select
              value={selectedOpponent}
              onChange={(e) => setSelectedOpponent(e.target.value)}
              className="input w-full"
              disabled={!selectedPlayer || opponentList.length === 0}
            >
              <option value="">全部對手</option>
              {opponentList.map((opp) => (
                <option key={opp} value={opp}>
                  vs {opp}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* 錯誤提示 */}
      {isHistoryError && (
        <div className="p-4 bg-red-900/20 border border-red-800/50 rounded-lg flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-red-300 font-medium">載入失敗</p>
            <p className="text-sm text-slate-400">
              {historyError instanceof Error
                ? historyError.message
                : "無法取得歷史數據"}
            </p>
          </div>
        </div>
      )}

      {/* 結果區域 */}
      {selectedPlayer && historyData && (
        <div className="space-y-6 animate-in fade-in-50 duration-300">
          {/* 機率統計卡片 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {/* Over 機率 */}
            <div className="p-4 bg-gradient-to-br from-emerald-900/30 to-emerald-800/20 border border-emerald-700/30 rounded-xl">
              <div className="flex items-center gap-2 text-emerald-400 mb-2">
                <TrendingUp className="w-4 h-4" />
                <span className="text-sm font-medium">Over 機率</span>
              </div>
              <p className="text-2xl font-bold text-emerald-300">
                {historyData.p_over !== null && historyData.p_over !== undefined
                  ? `${(historyData.p_over * 100).toFixed(1)}%`
                  : "N/A"}
              </p>
              <p className="text-xs text-slate-500 mt-1">
                &gt; {threshold}
              </p>
            </div>

            {/* Under 機率 */}
            <div className="p-4 bg-gradient-to-br from-rose-900/30 to-rose-800/20 border border-rose-700/30 rounded-xl">
              <div className="flex items-center gap-2 text-rose-400 mb-2">
                <TrendingDown className="w-4 h-4" />
                <span className="text-sm font-medium">Under 機率</span>
              </div>
              <p className="text-2xl font-bold text-rose-300">
                {historyData.p_under !== null && historyData.p_under !== undefined
                  ? `${(historyData.p_under * 100).toFixed(1)}%`
                  : "N/A"}
              </p>
              <p className="text-xs text-slate-500 mt-1">
                &lt; {threshold}
              </p>
            </div>

            {/* 平均值 */}
            <div className="p-4 bg-slate-800/50 border border-slate-700/50 rounded-xl">
              <p className="text-sm text-slate-400 mb-1">平均值</p>
              <p className="text-xl font-semibold text-slate-200">
                {historyData.mean?.toFixed(1) ?? "N/A"}
              </p>
            </div>

            {/* 樣本數 */}
            <div className="p-4 bg-slate-800/50 border border-slate-700/50 rounded-xl">
              <p className="text-sm text-slate-400 mb-1">樣本場次</p>
              <p className="text-xl font-semibold text-slate-200">
                {historyData.n_games} 場
                {selectedOpponent && (
                  <span className="text-sm text-slate-500 ml-1">
                    (vs {selectedOpponent})
                  </span>
                )}
              </p>
            </div>
          </div>

          {/* 時間序列圖表 - 每場比賽 */}
          {gameLogs && gameLogs.length > 0 && (
            <div className="p-6 bg-slate-800/30 border border-slate-700/50 rounded-xl">
              <h4 className="text-sm font-medium text-slate-300 mb-4 flex items-center gap-2">
                <BarChart3 className="w-4 h-4" />
                {HISTORY_METRICS.find((m) => m.key === metric)?.name} 歷史走勢
                {selectedOpponent && (
                  <span className="text-amber-400 ml-2">(vs {selectedOpponent})</span>
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
                      tick={{ fill: "#94a3b8", fontSize: 10 }}
                      axisLine={{ stroke: "#475569" }}
                      tickLine={{ stroke: "#475569" }}
                      angle={-45}
                      textAnchor="end"
                      height={60}
                      tickFormatter={(value, index) => {
                        const log = gameLogs[index];
                        // 顯示日期 + 對手縮寫
                        const oppAbbr = log?.opponent?.substring(0, 3).toUpperCase() || "";
                        return `${value} ${oppAbbr}`;
                      }}
                    />
                    <YAxis
                      tick={{ fill: "#94a3b8", fontSize: 12 }}
                      axisLine={{ stroke: "#475569" }}
                      tickLine={{ stroke: "#475569" }}
                      domain={[0, 'auto']}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1e293b",
                        border: "1px solid #475569",
                        borderRadius: "8px",
                        color: "#e2e8f0",
                      }}
                      formatter={(value, name, props) => {
                        const log = props.payload as GameLog;
                        return [
                          `${value} ${log.is_over ? "(Over)" : "(Under)"}`,
                          HISTORY_METRICS.find((m) => m.key === metric)?.name || metric
                        ];
                      }}
                      labelFormatter={(value, payload) => {
                        if (payload && payload[0]) {
                          const log = payload[0].payload as GameLog;
                          return `${log.date_full} vs ${log.opponent}`;
                        }
                        return value;
                      }}
                    />
                    {/* 閾值參考線 */}
                    <ReferenceLine
                      y={parseFloat(threshold)}
                      stroke="#f59e0b"
                      strokeWidth={2}
                      strokeDasharray="5 5"
                      label={{
                        value: `閾值: ${threshold}`,
                        fill: "#f59e0b",
                        fontSize: 12,
                        position: "right",
                      }}
                    />
                    <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                      {gameLogs.map((entry, index) => (
                        <Cell
                          key={`cell-${index}`}
                          fill={entry.is_over ? "#10b981" : "#f43f5e"}
                          fillOpacity={0.8}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="flex justify-center gap-6 mt-4 text-xs">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded bg-emerald-500/80" />
                  <span className="text-slate-400">Over（超過閾值）</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded bg-rose-500/80" />
                  <span className="text-slate-400">Under（低於閾值）</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-6 h-0.5 bg-amber-500 border-dashed border" />
                  <span className="text-slate-400">閾值線</span>
                </div>
              </div>
            </div>
          )}

          {/* 統計詳情 */}
          <div className="p-4 bg-slate-900/30 rounded-lg border border-slate-800/50">
            <div className="flex items-start gap-2">
              <Info className="w-4 h-4 text-slate-500 shrink-0 mt-0.5" />
              <div className="text-xs text-slate-500 space-y-1">
                <p>
                  📊 以上數據基於 CSV 歷史比賽記錄計算，為「經驗機率」
                  (empirical probability)
                </p>
                <p>
                  ⚠️ 此數據僅供參考，不代表實際預測結果，請謹慎投注
                </p>
                {historyData.equal_count && historyData.equal_count > 0 && (
                  <p>
                    📌 有 {historyData.equal_count} 場比賽剛好等於閾值
                    {threshold}，這些場次不計入 Over 或 Under
                  </p>
                )}
                {selectedOpponent && (
                  <p>
                    🎯 目前僅顯示對上 {selectedOpponent} 的比賽記錄
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 載入中 */}
      {isLoadingHistory && selectedPlayer && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 text-amber-400 animate-spin" />
          <span className="ml-3 text-slate-400">正在計算歷史數據...</span>
        </div>
      )}

      {/* 未選擇球員提示 */}
      {!selectedPlayer && (
        <div className="text-center py-12 text-slate-500">
          <User className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>請選擇一位球員以查看歷史數據分析</p>
        </div>
      )}
    </div>
  );
}
