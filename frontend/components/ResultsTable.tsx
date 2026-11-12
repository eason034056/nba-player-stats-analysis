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
import {
  MISSING_QUOTE,
  SINGLE_LEG_PRIOR_LABEL,
  consensusPriorCaption,
  fairNoValue,
  fairYesValue,
  lineText,
  noImpliedText,
  noPriceText,
  oddsAgeLabel,
  responseIsBinary,
  usesSingleLegPrior,
  yesImpliedText,
  yesPriceText,
} from "@/lib/no-vig-display";
import { formatPercent } from "@/lib/player-dd";
import { type NoVigResponse, type BookmakerResult } from "@/lib/schemas";
import {
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
function priceClass(text: string): string {
  if (text === MISSING_QUOTE) return "text-gray";
  return text.startsWith("-") ? "text-red" : "text-green-800";
}

function ResultRow({
  result,
  market,
  binary,
}: {
  result: BookmakerResult;
  market: string;
  binary: boolean;
}) {
  // Color the badge from the same one-decimal percent `formatVig` prints.
  // 0.06 and 0.06004 both read "6.0%", so both stay in the middle band.
  const vigLabel = formatVig(result.vig);
  const vigShown = Number(vigLabel.replace("%", ""));
  const isHighVig = Number.isFinite(vigShown) && vigShown > 6;
  const isLowVig = Number.isFinite(vigShown) && vigShown < 4;
  const prior = binary && usesSingleLegPrior(result);
  const yesFair = fairYesValue(result);
  const noFair = fairNoValue(result);
  const yesOdds = yesPriceText(result);
  const noOdds = noPriceText(result, binary);

  return (
    <tr
      className="group hover:bg-cream transition-colors"
      data-testid={`result-row-${result.bookmaker}`}
    >
      <td className="font-semibold text-dark">
        {getBookmakerDisplayName(result.bookmaker)}
      </td>

      <td className="font-mono text-lg text-red font-bold" data-testid="result-line">
        {lineText(result, market)}
      </td>

      <td className="font-mono font-semibold" data-testid="result-yes-price">
        <span className={priceClass(yesOdds)}>{yesOdds}</span>
      </td>

      <td className="font-mono font-semibold" data-testid="result-no-price">
        <span className={priceClass(noOdds)}>{noOdds}</span>
      </td>

      <td>
        <span className={cn(
          "inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold",
          isHighVig && "bg-red text-white",
          isLowVig && "bg-green-800 text-white",
          !isHighVig && !isLowVig && "bg-yellow text-dark"
        )}>
          {vigLabel}
        </span>
      </td>

      <td data-testid="result-yes-fair">
        <div className="flex items-center gap-2">
          <span className="font-mono text-blue-600 font-bold w-16">
            {yesFair === null ? MISSING_QUOTE : formatPercent(yesFair)}
          </span>
          {yesFair !== null && (
            <ProbabilityBar probability={yesFair} color="blue" />
          )}
        </div>
        {binary && (
          <p className="text-[10px] text-gray mt-1" data-testid="result-yes-implied">
            {yesImpliedText(result)}
          </p>
        )}
        {prior && yesFair !== null && (
          <p className="text-[10px] text-gray">{SINGLE_LEG_PRIOR_LABEL}</p>
        )}
      </td>

      <td data-testid="result-no-fair">
        <div className="flex items-center gap-2">
          <span className="font-mono text-yellow font-bold w-16">
            {noFair === null ? MISSING_QUOTE : formatPercent(noFair)}
          </span>
          {noFair !== null && (
            <ProbabilityBar probability={noFair} color="amber" />
          )}
        </div>
        {binary && (
          <p className="text-[10px] text-gray mt-1" data-testid="result-no-implied">
            {noImpliedText(result, binary)}
          </p>
        )}
        {prior && noFair !== null && (
          <p className="text-[10px] text-gray">{SINGLE_LEG_PRIOR_LABEL}</p>
        )}
      </td>
    </tr>
  );
}

/**
 * Consensus Block
 */
function ConsensusBlock({
  consensus,
  binary,
  priorCaption,
}: {
  consensus: NoVigResponse["consensus"];
  binary: boolean;
  priorCaption: string | null;
}) {
  if (!consensus) return null;

  const yesFair =
    typeof consensus.p_yes_fair === "number"
      ? consensus.p_yes_fair
      : consensus.p_over_fair;
  const noFair =
    typeof consensus.p_no_fair === "number"
      ? consensus.p_no_fair
      : consensus.p_under_fair;
  const yesLabel = binary ? "Yes" : "Over";
  const noLabel = binary ? "No" : "Under";

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
        <div className="bg-blue-50 rounded-lg p-4 border-2 border-blue-200">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-4 h-4 text-blue-600" />
            <span className="text-sm text-blue-600 font-semibold">{yesLabel}</span>
          </div>
          <p className="text-3xl font-mono font-bold text-blue-600">
            {formatPercent(yesFair)}
          </p>
          {priorCaption && (
            <p className="text-[10px] text-gray mt-1" data-testid="consensus-prior">
              {priorCaption}
            </p>
          )}
          <div className="mt-2 w-full bg-blue-200 rounded-full h-2">
            <div
              className="bg-blue-600 h-full rounded-full transition-all duration-500"
              style={{ width: `${yesFair * 100}%` }}
            />
          </div>
        </div>

        <div className="bg-yellow/20 rounded-lg p-4 border-2 border-yellow">
          <div className="flex items-center gap-2 mb-2">
            <TrendingDown className="w-4 h-4 text-dark" />
            <span className="text-sm text-dark font-semibold">{noLabel}</span>
          </div>
          <p className="text-3xl font-mono font-bold text-dark">
            {formatPercent(noFair)}
          </p>
          {priorCaption && (
            <p className="text-[10px] text-gray mt-1" data-testid="consensus-prior">
              {priorCaption}
            </p>
          )}
          <div className="mt-2 w-full bg-yellow/50 rounded-full h-2">
            <div
              className="bg-yellow h-full rounded-full transition-all duration-500"
              style={{ width: `${noFair * 100}%` }}
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

  // Empty-bookmakers UX (SPO-20 §3): some markets like FTM / FGM are schema-
  // valid but currently have no bookmaker inventory. The backend returns
  // `results: []` (and possibly a "Player not found" message because the
  // player-name list is built off bookmaker outcomes). Surface this as a
  // graceful empty state — NOT as an error, NEVER as a fabricated `point`.
  if (data.results.length === 0) {
    return (
      <div className="card border-yellow">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-lg bg-yellow flex items-center justify-center shrink-0">
            <AlertCircle className="w-5 h-5 text-dark" />
          </div>
          <div>
            <h3 className="font-bold text-dark mb-1">
              No bookmaker line right now
            </h3>
            <p className="text-gray text-sm">
              No bookmaker has posted{" "}
              <span className="font-semibold">
                {getMarketDisplayName(data.market)}
              </span>{" "}
              for this game. The game log on this page stays available. The odds
              tile lights up automatically on the next snapshot fetch when
              inventory appears.
            </p>
            {data.message && (
              <p className="text-gray text-xs mt-2 italic">
                Backend note: {data.message}
              </p>
            )}
          </div>
        </div>
      </div>
    );
  }

  const binary = responseIsBinary(data);
  const priorCaption = consensusPriorCaption(data);
  const ageLabel = oddsAgeLabel(data);

  return (
    <div className="animate-fade-in">
      <div className="flex items-center gap-3 mb-4">
        <h2 className="text-xl font-bold text-dark">
          {data.player_name}
        </h2>
        <span className="badge-neutral">
          {getMarketDisplayName(data.market)}
        </span>
      </div>

      {ageLabel && (
        <p className="mb-4 text-xs text-gray" data-testid="odds-age">
          {ageLabel}
        </p>
      )}

      <div data-testid="odds-table-scroll" className="table-container overflow-hint max-w-full overflow-x-auto">
        <table className="table max-md:min-w-[760px]">
          <thead>
            <tr>
              <th>Bookmaker</th>
              <th>{binary ? "Market" : "Line"}</th>
              <th>{binary ? "Yes Odds" : "Over Odds"}</th>
              <th>{binary ? "No Odds" : "Under Odds"}</th>
              <th>Vig</th>
              <th>{binary ? "Yes Probability" : "Over Probability"}</th>
              <th>{binary ? "No Probability" : "Under Probability"}</th>
            </tr>
          </thead>
          <tbody>
            {data.results.map((result) => (
              <ResultRow
                key={result.bookmaker}
                result={result}
                market={data.market}
                binary={binary}
              />
            ))}
          </tbody>
        </table>
      </div>

      <ConsensusBlock
        consensus={data.consensus}
        binary={binary}
        priorCaption={priorCaption}
      />

      <p className="mt-4 text-xs text-gray">
        * Lower vig indicates the bookmaker&apos;s odds are closer to fair;
        No-vig probability is the fair probability estimate after removing vig
      </p>
    </div>
  );
}
