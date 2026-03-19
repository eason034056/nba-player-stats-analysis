/**
 * PlayerProjectionPanel.tsx - 球員投影面板組件
 *
 * 顯示 SportsDataIO 的球員投影數據，包括：
 * 1. 核心投影數據（Points, Rebounds, Assists, PRA）— 4 格 Grid
 * 2. 輔助投影數據（Minutes, Matchup, Usage%, DK Salary）— 4 格 Grid
 * 3. Edge 視覺化長條（Threshold vs Projected Value）
 *
 * 設計理念：
 * - 與目前的 Event Detail Page 風格一致（cream 背景、red/yellow 重點色）
 * - 當前選中的 metric 對應的投影 stat card 會被 highlight
 * - 所有 null 值顯示為 "N/A" 並使用 muted 樣式
 * - 分鐘數低於 20 時顯示警告
 *
 * Props:
 * @param projection - PlayerProjection 物件（來自 SportsDataIO API）
 * @param metric     - 目前選中的 metric key（points / rebounds / assists / pra）
 * @param threshold  - 盤口閾值（用於計算 edge）
 *
 * 使用位置：
 *   frontend/app/event/[eventId]/page.tsx
 *   插入在 No-Vig Results 和 Historical Data Analysis 之間
 */

"use client";

import { type PlayerProjection } from "@/lib/schemas";
import { cn } from "@/lib/utils";
import {
  Target,
  Timer,
  Shield,
  DollarSign,
  Activity,
  TrendingUp,
  TrendingDown,
  Loader2,
  AlertTriangle,
} from "lucide-react";

// ==================== 型別定義 ====================

/**
 * MetricKey - 支援的統計指標 key
 *
 * 對應到 PlayerProjection 物件的欄位名稱：
 * - "points"   → projection.points
 * - "rebounds"  → projection.rebounds
 * - "assists"   → projection.assists
 * - "pra"       → projection.pra（Points + Rebounds + Assists）
 */
type MetricKey = "points" | "rebounds" | "assists" | "pra";

interface PlayerProjectionPanelProps {
  /** 球員投影資料，null 表示正在載入或無資料 */
  projection: PlayerProjection | null;
  /** 目前選中的統計指標（決定哪張 stat card 被 highlight） */
  metric: MetricKey;
  /** 盤口閾值（用於計算 edge = projected - threshold） */
  threshold: number | null;
  /** 是否正在載入投影資料 */
  isLoading?: boolean;
}

// ==================== Helper Functions ====================

/**
 * getMetricLabel - 取得 metric 的中文顯示名稱
 *
 * 這個 function 叫 "getMetricLabel" 因為它把 metric key 轉成 label（標籤文字）
 *
 * @param key - 統計指標 key
 * @returns 該 metric 的英文顯示名稱
 *
 * @example
 * getMetricLabel("points") // "Points"
 * getMetricLabel("pra")    // "PRA"
 */
function getMetricLabel(key: MetricKey): string {
  const labels: Record<MetricKey, string> = {
    points: "Points",
    rebounds: "Rebounds",
    assists: "Assists",
    pra: "PRA",
  };
  return labels[key];
}

/**
 * getProjectedValue - 從 projection 物件中取出指定 metric 的投影值
 *
 * 叫 "getProjectedValue" 因為它根據 metric key 從投影資料中「取出」對應的預測數值
 *
 * @param projection - 球員投影資料
 * @param key - 要取出的統計指標
 * @returns 該 metric 的投影數值，或 null
 *
 * @example
 * getProjectedValue(projection, "points")  // 29.3
 * getProjectedValue(projection, "assists") // null（API 未回傳）
 */
function getProjectedValue(
  projection: PlayerProjection,
  key: MetricKey
): number | null | undefined {
  return projection[key];
}

/**
 * getMatchupInfo - 根據對手排名回傳對位難度的樣式和文字
 *
 * 叫 "getMatchupInfo" 因為它把數字排名轉換為「對位資訊」（Easy/Avg/Hard）
 * 排名 1-10 = Hard（對手防守排前 10 名）
 * 排名 11-20 = Average
 * 排名 21-30 = Easy（對手防守排最後 10 名，容易得分）
 *
 * @param rank - 對手防守排名（1 = 最強防守，30 = 最弱防守）
 * @returns 包含 label（文字）、color（文字色）、bg（背景色）的物件
 */
function getMatchupInfo(rank: number | null | undefined): {
  label: string;
  color: string;
  bg: string;
} {
  if (rank == null) {
    return { label: "N/A", color: "text-gray", bg: "bg-gray/10" };
  }
  if (rank >= 21) {
    // 排名 21-30 = 防守最弱 = 容易得分
    return { label: `Easy #${rank}`, color: "text-green-700", bg: "bg-green-50" };
  }
  if (rank >= 11) {
    return { label: `Avg #${rank}`, color: "text-yellow-700", bg: "bg-yellow-50" };
  }
  // 排名 1-10 = 防守最強 = 難以得分
  return { label: `Hard #${rank}`, color: "text-red", bg: "bg-red/5" };
}

/**
 * formatStat - 格式化數值為顯示字串
 *
 * 叫 "formatStat" 因為它把原始統計數值格式化為適合顯示的字串
 * null/undefined → "N/A"
 * 其他 → 保留一位小數
 *
 * @param value - 原始數值
 * @returns 格式化後的字串
 */
function formatStat(value: number | null | undefined): string {
  if (value == null) return "N/A";
  return value.toFixed(1);
}

// ==================== Sub Components ====================

/**
 * StatCard - 單個統計數據卡片
 *
 * 叫 "StatCard" 因為它是顯示一個統計數據的「卡片」（card）元素
 * 包含 icon、標題、數值、副標題
 * 當 isHighlighted=true 時，卡片會有粗邊框和黃色背景
 */
function StatCard({
  icon,
  label,
  value,
  subtitle,
  isHighlighted = false,
  warning = false,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  subtitle?: string;
  isHighlighted?: boolean;
  warning?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border-2 p-3 transition-all duration-200",
        isHighlighted
          ? "border-dark bg-yellow/20 shadow-sm"
          : "border-dark/10 bg-white",
        warning && "border-orange-300"
      )}
    >
      <div className="flex items-center gap-1.5 mb-1">
        {icon}
        <span className="text-xs font-bold text-gray uppercase tracking-wide">
          {label}
        </span>
      </div>
      <p
        className={cn(
          "text-xl font-bold",
          value === "N/A" ? "text-gray/50" : "text-dark"
        )}
      >
        {value}
      </p>
      {subtitle && (
        <p className="text-xs text-gray mt-0.5">{subtitle}</p>
      )}
      {warning && (
        <div className="flex items-center gap-1 mt-1 text-xs text-orange-600">
          <AlertTriangle className="w-3 h-3" />
          <span>Low minutes</span>
        </div>
      )}
    </div>
  );
}

/**
 * EdgeBar - 視覺化 Edge 長條圖
 *
 * 叫 "EdgeBar" 因為它用一個長條（bar）來視覺化 edge（價值差距）
 * 左邊是 threshold（盤口線），右邊是 projected（投影值），或反之
 * 綠色 = 投影 > 盤口（Over 有利），紅色 = 投影 < 盤口（Under 有利）
 *
 * @param threshold - 盤口閾值
 * @param projected - 投影值
 * @param metricLabel - 當前指標名稱（如 "Points"）
 */
function EdgeBar({
  threshold,
  projected,
  metricLabel,
}: {
  threshold: number;
  projected: number;
  metricLabel: string;
}) {
  // edge: 投影值和盤口的差距
  // 正數 = 投影超過盤口 = Over 有利
  // 負數 = 投影低於盤口 = Under 有利
  const edge = projected - threshold;
  const isPositive = edge >= 0;

  // 計算 bar 的視覺比例
  // range: 在 threshold ± 15 的範圍內視覺化
  const range = Math.max(Math.abs(edge) * 2, 10);
  const min = Math.min(threshold, projected) - range * 0.2;
  const max = Math.max(threshold, projected) + range * 0.2;
  const totalRange = max - min;

  // thresholdPercent: threshold 在整個 bar 中的百分比位置
  const thresholdPercent = ((threshold - min) / totalRange) * 100;
  // projectedPercent: projected 在整個 bar 中的百分比位置
  const projectedPercent = ((projected - min) / totalRange) * 100;

  // fillLeft/fillRight: 上色區域的左邊界和右邊界
  const fillLeft = Math.min(thresholdPercent, projectedPercent);
  const fillRight = Math.max(thresholdPercent, projectedPercent);

  return (
    <div className="mt-4 pt-4 border-t border-dark/10">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-bold text-dark">
          Edge vs Line ({metricLabel} {isPositive ? "Over" : "Under"} {threshold})
        </span>
        <span
          className={cn(
            "text-sm font-bold flex items-center gap-1",
            isPositive ? "text-green-600" : "text-red"
          )}
        >
          {isPositive ? (
            <TrendingUp className="w-4 h-4" />
          ) : (
            <TrendingDown className="w-4 h-4" />
          )}
          {isPositive ? "+" : ""}
          {edge.toFixed(1)}
        </span>
      </div>

      {/* Bar 視覺化 */}
      <div className="relative h-8 bg-dark/5 rounded-full overflow-hidden">
        {/* 上色區域：threshold 和 projected 之間 */}
        <div
          className={cn(
            "absolute top-0 h-full rounded-full transition-all duration-500",
            isPositive ? "bg-green-400/40" : "bg-red/20"
          )}
          style={{
            left: `${fillLeft}%`,
            width: `${fillRight - fillLeft}%`,
          }}
        />

        {/* Threshold 標記線 */}
        <div
          className="absolute top-0 h-full w-0.5 bg-dark/60"
          style={{ left: `${thresholdPercent}%` }}
        />

        {/* Projected 標記線 */}
        <div
          className={cn(
            "absolute top-0 h-full w-1 rounded-full",
            isPositive ? "bg-green-600" : "bg-red"
          )}
          style={{ left: `${projectedPercent}%` }}
        />
      </div>

      {/* 標籤 */}
      <div className="relative h-5 mt-1">
        <span
          className="absolute text-[10px] font-medium text-gray -translate-x-1/2"
          style={{ left: `${thresholdPercent}%` }}
        >
          {threshold} (line)
        </span>
        <span
          className={cn(
            "absolute text-[10px] font-bold -translate-x-1/2",
            isPositive ? "text-green-700" : "text-red"
          )}
          style={{ left: `${projectedPercent}%` }}
        >
          {projected.toFixed(1)} (proj)
        </span>
      </div>
    </div>
  );
}

/**
 * LoadingSkeleton - 載入中的骨架畫面
 *
 * 叫 "LoadingSkeleton" 因為它在資料載入時顯示一個灰色「骨架」佔位
 * 讓使用者知道這裡有內容正在載入，避免畫面跳動
 */
function LoadingSkeleton() {
  return (
    <div className="card animate-pulse">
      <div className="flex items-center gap-3 mb-4">
        <Loader2 className="w-5 h-5 text-gray/40 animate-spin" />
        <div className="skeleton h-5 w-48" />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="skeleton h-20 rounded-lg" />
        ))}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
        {[5, 6, 7, 8].map((i) => (
          <div key={i} className="skeleton h-20 rounded-lg" />
        ))}
      </div>
    </div>
  );
}

// ==================== Main Component ====================

/**
 * PlayerProjectionPanel - 球員投影面板主組件
 *
 * 叫 "PlayerProjectionPanel" 因為它是一個 Panel（面板）元素，
 * 專門用來顯示球員 Projection（投影/預測）資料。
 *
 * 使用方式：
 * ```tsx
 * <PlayerProjectionPanel
 *   projection={projectionData}
 *   metric="points"
 *   threshold={26.5}
 *   isLoading={false}
 * />
 * ```
 *
 * 結構：
 * 1. 標題列（球員名、隊伍、對手）
 * 2. 核心投影 Grid（Pts, Reb, Ast, PRA）
 * 3. 輔助數據 Grid（Minutes, Matchup, Usage%, DK Salary）
 * 4. Edge 視覺化 Bar（threshold vs projected）
 */
export function PlayerProjectionPanel({
  projection,
  metric,
  threshold,
  isLoading = false,
}: PlayerProjectionPanelProps) {
  // 載入中 → 顯示骨架畫面
  if (isLoading) {
    return <LoadingSkeleton />;
  }

  // 無資料 → 不渲染
  if (!projection) {
    return null;
  }

  // 取出目前選中 metric 的投影值
  const projectedValue = getProjectedValue(projection, metric);
  const matchup = getMatchupInfo(projection.opponent_rank);

  // 核心投影 metrics — 對應的 4 張 stat cards
  const coreMetrics: { key: MetricKey; icon: React.ReactNode }[] = [
    { key: "points", icon: <Target className="w-3.5 h-3.5 text-gray" /> },
    { key: "rebounds", icon: <Activity className="w-3.5 h-3.5 text-gray" /> },
    { key: "assists", icon: <Activity className="w-3.5 h-3.5 text-gray" /> },
    { key: "pra", icon: <TrendingUp className="w-3.5 h-3.5 text-gray" /> },
  ];

  return (
    <div className="card">
      {/* 標題列 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <Target className="w-4 h-4 text-white" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-dark">
              Today&apos;s Projection
            </h3>
            <p className="text-sm text-gray">
              {projection.player_name}
              {projection.team && ` · ${projection.team}`}
              {projection.opponent &&
                ` | vs ${projection.opponent}`}
            </p>
          </div>
        </div>
        {projection.home_or_away && (
          <span className="text-xs font-bold text-gray border border-dark/10 rounded px-2 py-1">
            {projection.home_or_away === "HOME" ? "Home" : "Away"}
          </span>
        )}
      </div>

      {/* Row 1: 核心投影數據 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {coreMetrics.map(({ key, icon }) => (
          <StatCard
            key={key}
            icon={icon}
            label={`Proj ${getMetricLabel(key)}`}
            value={formatStat(getProjectedValue(projection, key))}
            isHighlighted={key === metric}
          />
        ))}
      </div>

      {/* Row 2: 輔助數據 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
        {/* Minutes */}
        <StatCard
          icon={<Timer className="w-3.5 h-3.5 text-gray" />}
          label="Minutes"
          value={
            projection.minutes != null
              ? `${projection.minutes.toFixed(1)} min`
              : "N/A"
          }
          warning={projection.minutes != null && projection.minutes < 20}
        />

        {/* Matchup */}
        <div
          className={cn(
            "rounded-lg border-2 border-dark/10 p-3",
            matchup.bg
          )}
        >
          <div className="flex items-center gap-1.5 mb-1">
            <Shield className="w-3.5 h-3.5 text-gray" />
            <span className="text-xs font-bold text-gray uppercase tracking-wide">
              Matchup
            </span>
          </div>
          <p className={cn("text-xl font-bold", matchup.color)}>
            {matchup.label}
          </p>
          <p className="text-xs text-gray mt-0.5">Opp Def Rank</p>
        </div>

        {/* Usage% */}
        <StatCard
          icon={<Activity className="w-3.5 h-3.5 text-gray" />}
          label="Usage%"
          value={
            projection.usage_rate_percentage != null
              ? `${projection.usage_rate_percentage.toFixed(1)}%`
              : "N/A"
          }
        />

        {/* DK Salary */}
        <StatCard
          icon={<DollarSign className="w-3.5 h-3.5 text-gray" />}
          label="DK Salary"
          value={
            projection.draftkings_salary != null
              ? `$${projection.draftkings_salary.toLocaleString()}`
              : "N/A"
          }
        />
      </div>

      {/* Edge Bar */}
      {threshold != null &&
        projectedValue != null &&
        projectedValue !== undefined && (
          <EdgeBar
            threshold={threshold}
            projected={projectedValue}
            metricLabel={getMetricLabel(metric)}
          />
        )}
    </div>
  );
}
