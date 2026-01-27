/**
 * ResultsTable.tsx - Results Table Component (Minimal Design)
 * 
 * Design Philosophy:
 * - White table with black borders
 * - Red/yellow accents for data highlights
 * - Clean, easy-to-read layout
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

interface ResultsTableProps {
  data: NoVigResponse | null;
  isLoading?: boolean;
}

/**
 * Probability Bar
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
    <div className="relative w-24 h-2 bg-dark/10 rounded-full overflow-hidden">
      <div
        className={cn(
          "absolute left-0 top-0 h-full rounded-full transition-all duration-500",
          color === "blue" ? "bg-blue-500" : "bg-yellow"
        )}
        style={{ width: `${percentage}%` }}
      />
    </div>
  );
}

/**
 * Single Result Row
 */
function ResultRow({ result }: { result: BookmakerResult }) {
  const isHighVig = result.vig > 0.06;
  const isLowVig = result.vig < 0.04;

  return (
    <tr className="group hover:bg-cream transition-colors">
      {/* Bookmaker name */}
      <td className="font-semibold text-dark">
        {getBookmakerDisplayName(result.bookmaker)}
      </td>

      {/* Line */}
      <td className="font-mono text-lg text-red font-bold">
        {result.line}
      </td>

      {/* Over odds */}
      <td className="font-mono font-semibold">
        <span className={cn(
          result.over_odds < 0 ? "text-red" : "text-green-600"
        )}>
          {formatAmericanOdds(result.over_odds)}
        </span>
      </td>

      {/* Under odds */}
      <td className="font-mono font-semibold">
        <span className={cn(
          result.under_odds < 0 ? "text-red" : "text-green-600"
        )}>
          {formatAmericanOdds(result.under_odds)}
        </span>
      </td>

      {/* Vig */}
      <td>
        <span className={cn(
          "inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold",
          isHighVig && "bg-red text-white",
          isLowVig && "bg-green-500 text-white",
          !isHighVig && !isLowVig && "bg-yellow text-dark"
        )}>
          {formatVig(result.vig)}
        </span>
      </td>

      {/* Over probability */}
      <td>
        <div className="flex items-center gap-2">
          <span className="font-mono text-blue-600 font-bold w-16">
            {formatProbability(result.p_over_fair)}
          </span>
          <ProbabilityBar probability={result.p_over_fair} color="blue" />
        </div>
      </td>

      {/* Under probability */}
      <td>
        <div className="flex items-center gap-2">
          <span className="font-mono text-yellow font-bold w-16">
            {formatProbability(result.p_under_fair)}
          </span>
          <ProbabilityBar probability={result.p_under_fair} color="amber" />
        </div>
      </td>
    </tr>
  );
}

/**
 * Consensus Block
 */
function ConsensusBlock({ 
  consensus 
}: { 
  consensus: NoVigResponse["consensus"];
}) {
  if (!consensus) return null;

  return (
    <div className="card mt-6 border-red">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-8 h-8 rounded-lg bg-red flex items-center justify-center">
          <Calculator className="w-4 h-4 text-white" />
        </div>
        <h3 className="text-lg font-bold text-dark">
          Market Consensus
        </h3>
        <span className="text-xs text-gray font-medium">
          ({consensus.method === "mean" ? "Mean Method" : "Weighted Method"})
        </span>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Over */}
        <div className="bg-blue-50 rounded-lg p-4 border-2 border-blue-200">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-4 h-4 text-blue-600" />
            <span className="text-sm text-blue-600 font-semibold">Over</span>
          </div>
          <p className="text-3xl font-mono font-bold text-blue-600">
            {formatProbability(consensus.p_over_fair)}
          </p>
          <div className="mt-2 w-full bg-blue-200 rounded-full h-2">
            <div
              className="bg-blue-600 h-full rounded-full transition-all duration-500"
              style={{ width: `${consensus.p_over_fair * 100}%` }}
            />
          </div>
        </div>

        {/* Under */}
        <div className="bg-yellow/20 rounded-lg p-4 border-2 border-yellow">
          <div className="flex items-center gap-2 mb-2">
            <TrendingDown className="w-4 h-4 text-dark" />
            <span className="text-sm text-dark font-semibold">Under</span>
          </div>
          <p className="text-3xl font-mono font-bold text-dark">
            {formatProbability(consensus.p_under_fair)}
          </p>
          <div className="mt-2 w-full bg-yellow/50 rounded-full h-2">
            <div
              className="bg-yellow h-full rounded-full transition-all duration-500"
              style={{ width: `${consensus.p_under_fair * 100}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Loading Skeleton
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
 * ResultsTable Component
 */
export function ResultsTable({ data, isLoading }: ResultsTableProps) {
  if (isLoading) {
    return <TableSkeleton />;
  }

  if (!data) {
    return null;
  }

  if (data.message && data.results.length === 0) {
    return (
      <div className="card border-yellow">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-lg bg-yellow flex items-center justify-center shrink-0">
            <AlertCircle className="w-5 h-5 text-dark" />
          </div>
          <div>
            <h3 className="font-bold text-dark mb-1">
              No Data Found
            </h3>
            <p className="text-gray text-sm">
              {data.message}
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      {/* Title */}
      <div className="flex items-center gap-3 mb-4">
        <h2 className="text-xl font-bold text-dark">
          {data.player_name}
        </h2>
        <span className="badge-neutral">
          {getMarketDisplayName(data.market)}
        </span>
      </div>

      {/* Table */}
      <div className="table-container">
        <table className="table">
          <thead>
            <tr>
              <th>Bookmaker</th>
              <th>Line</th>
              <th>Over Odds</th>
              <th>Under Odds</th>
              <th>Vig</th>
              <th>Over Probability</th>
              <th>Under Probability</th>
            </tr>
          </thead>
          <tbody>
            {data.results.map((result) => (
              <ResultRow key={result.bookmaker} result={result} />
            ))}
          </tbody>
        </table>
      </div>

      {/* Consensus */}
      <ConsensusBlock consensus={data.consensus} />

      {/* Note */}
      <p className="mt-4 text-xs text-gray">
        * Lower vig indicates the bookmaker's odds are closer to fair;
        No-vig probability is the fair probability estimate after removing vig
      </p>
    </div>
  );
}
