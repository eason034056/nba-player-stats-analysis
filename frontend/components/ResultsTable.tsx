/**
 * ResultsTable.tsx - 結果表格元件
 * 
 * 顯示去水機率計算結果
 * 包含：
 * - 各博彩公司的賠率和機率
 * - 市場共識
 * - 資料視覺化
 */

"use client";

import { TrendingUp, TrendingDown, AlertCircle, Calculator } from "lucide-react";
import { type NoVigResponse, type BookmakerResult } from "@/lib/schemas";
import {
  formatProbability,
  formatAmericanOdds,
  formatVig,
  getBookmakerDisplayName,
  getMarketDisplayName,
  cn,
} from "@/lib/utils";

/**
 * ResultsTable Props
 * 
 * @property data - 計算結果資料
 * @property isLoading - 是否正在載入
 */
interface ResultsTableProps {
  data: NoVigResponse | null;
  isLoading?: boolean;
}

/**
 * 機率長條圖元件
 * 
 * 視覺化顯示機率值
 */
function ProbabilityBar({ 
  probability, 
  color = "blue" 
}: { 
  probability: number;
  color?: "blue" | "amber";
}) {
  const percentage = probability * 100;
  
  return (
    <div className="relative w-24 h-2 bg-slate-800 rounded-full overflow-hidden">
      <div
        className={cn(
          "absolute left-0 top-0 h-full rounded-full transition-all duration-500",
          color === "blue" ? "bg-blue-500" : "bg-amber-500"
        )}
        style={{ width: `${percentage}%` }}
      />
    </div>
  );
}

/**
 * 單行結果元件
 * 
 * 顯示一家博彩公司的資料
 */
function ResultRow({ result }: { result: BookmakerResult }) {
  // 判斷水錢高低
  const isHighVig = result.vig > 0.06; // 6% 以上算高
  const isLowVig = result.vig < 0.04;  // 4% 以下算低

  return (
    <tr className="group">
      {/* 博彩公司名稱 */}
      <td className="font-medium text-slate-200">
        {getBookmakerDisplayName(result.bookmaker)}
      </td>

      {/* 門檻 Line */}
      <td className="font-mono text-lg text-amber-400">
        {result.line}
      </td>

      {/* Over 賠率 */}
      <td className="font-mono">
        <span className={cn(
          result.over_odds < 0 ? "text-red-400" : "text-green-400"
        )}>
          {formatAmericanOdds(result.over_odds)}
        </span>
      </td>

      {/* Under 賠率 */}
      <td className="font-mono">
        <span className={cn(
          result.under_odds < 0 ? "text-red-400" : "text-green-400"
        )}>
          {formatAmericanOdds(result.under_odds)}
        </span>
      </td>

      {/* 水錢 */}
      <td>
        <span className={cn(
          "badge",
          isHighVig && "badge-danger",
          isLowVig && "badge-success",
          !isHighVig && !isLowVig && "badge-warning"
        )}>
          {formatVig(result.vig)}
        </span>
      </td>

      {/* Over 去水機率 */}
      <td>
        <div className="flex items-center gap-2">
          <span className="font-mono text-blue-400 w-16">
            {formatProbability(result.p_over_fair)}
          </span>
          <ProbabilityBar probability={result.p_over_fair} color="blue" />
        </div>
      </td>

      {/* Under 去水機率 */}
      <td>
        <div className="flex items-center gap-2">
          <span className="font-mono text-amber-400 w-16">
            {formatProbability(result.p_under_fair)}
          </span>
          <ProbabilityBar probability={result.p_under_fair} color="amber" />
        </div>
      </td>
    </tr>
  );
}

/**
 * 共識區塊元件
 * 
 * 顯示市場共識
 */
function ConsensusBlock({ 
  consensus 
}: { 
  consensus: NoVigResponse["consensus"];
}) {
  if (!consensus) return null;

  return (
    <div className="card mt-6 bg-gradient-to-r from-blue-900/20 to-purple-900/20 border-blue-800/50">
      <div className="flex items-center gap-2 mb-4">
        <Calculator className="w-5 h-5 text-blue-400" />
        <h3 className="text-lg font-semibold text-slate-100">
          市場共識
        </h3>
        <span className="text-xs text-slate-500">
          ({consensus.method === "mean" ? "平均法" : "加權法"})
        </span>
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* Over 共識 */}
        <div className="bg-slate-900/50 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-4 h-4 text-blue-400" />
            <span className="text-sm text-slate-400">Over</span>
          </div>
          <p className="text-3xl font-mono font-bold text-blue-400">
            {formatProbability(consensus.p_over_fair)}
          </p>
          <div className="mt-2 w-full bg-slate-800 rounded-full h-2">
            <div
              className="bg-blue-500 h-full rounded-full transition-all duration-500"
              style={{ width: `${consensus.p_over_fair * 100}%` }}
            />
          </div>
        </div>

        {/* Under 共識 */}
        <div className="bg-slate-900/50 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingDown className="w-4 h-4 text-amber-400" />
            <span className="text-sm text-slate-400">Under</span>
          </div>
          <p className="text-3xl font-mono font-bold text-amber-400">
            {formatProbability(consensus.p_under_fair)}
          </p>
          <div className="mt-2 w-full bg-slate-800 rounded-full h-2">
            <div
              className="bg-amber-500 h-full rounded-full transition-all duration-500"
              style={{ width: `${consensus.p_under_fair * 100}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * 載入骨架屏
 */
function TableSkeleton() {
  return (
    <div className="space-y-4">
      <div className="skeleton h-8 w-64" />
      <div className="table-container">
        <table className="table">
          <thead>
            <tr>
              {[...Array(7)].map((_, i) => (
                <th key={i}>
                  <div className="skeleton h-4 w-20" />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...Array(4)].map((_, i) => (
              <tr key={i}>
                {[...Array(7)].map((_, j) => (
                  <td key={j}>
                    <div className="skeleton h-4 w-16" />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * ResultsTable 元件
 * 
 * 顯示去水機率計算結果
 */
export function ResultsTable({ data, isLoading }: ResultsTableProps) {
  // 載入中
  if (isLoading) {
    return <TableSkeleton />;
  }

  // 無資料
  if (!data) {
    return null;
  }

  // 有錯誤訊息
  if (data.message && data.results.length === 0) {
    return (
      <div className="card border-amber-800/50 bg-amber-900/10">
        <div className="flex items-start gap-3">
          <AlertCircle className="w-6 h-6 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <h3 className="font-semibold text-amber-300 mb-1">
              找不到資料
            </h3>
            <p className="text-slate-400 text-sm">
              {data.message}
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      {/* 標題 */}
      <div className="flex items-center gap-3 mb-4">
        <h2 className="text-xl font-semibold text-slate-100">
          {data.player_name}
        </h2>
        <span className="badge bg-slate-800 text-slate-400">
          {getMarketDisplayName(data.market)}
        </span>
      </div>

      {/* 結果表格 */}
      <div className="table-container">
        <table className="table">
          <thead>
            <tr>
              <th>博彩公司</th>
              <th>Line</th>
              <th>Over 賠率</th>
              <th>Under 賠率</th>
              <th>水錢</th>
              <th>Over 機率</th>
              <th>Under 機率</th>
            </tr>
          </thead>
          <tbody>
            {data.results.map((result) => (
              <ResultRow key={result.bookmaker} result={result} />
            ))}
          </tbody>
        </table>
      </div>

      {/* 市場共識 */}
      <ConsensusBlock consensus={data.consensus} />

      {/* 說明 */}
      <p className="mt-4 text-xs text-slate-500">
        * 水錢（Vig）越低表示該博彩公司的賠率越接近公平；
        去水機率是移除水錢後的公平機率估計
      </p>
    </div>
  );
}

