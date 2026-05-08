/**
 * PlayerDDTile.tsx — Double-Double (DD) binary tile
 *
 * SPO-20 Phase 3 §4: DD outcome is binary (Yes/No), so it cannot reuse the
 * Over/Under chart in `PlayerHistoryStats`. This component renders the
 * DD-specific shape:
 *
 *   - Yes price (American odds) — from snapshot when wired
 *   - Yes implied probability — derived from price
 *   - Yes fair probability — single-leg de-vigged value, or "vig prior
 *     unavailable" when null (decision §4 step 3 forbids fabrication)
 *   - Historical P(DD = 1) — `prob_dd` from
 *     `csv_player_history.player_dd_history()` when wired
 *   - "ML projection N/A — Phase 2" footer (decision §4 step 4)
 *
 * ⚠ Anti-hallucination guards (binding, see CLAUDE.md):
 *   - NEVER show a `point` value (DD has none)
 *   - NEVER fabricate `yes_fair_prob` when null
 *   - NEVER derive a Phase-1 ML projection (DD is multivariate)
 *
 * Backend wiring status (as of SPO-20):
 *   The DD odds + DD historical paths exist in services
 *   (`odds_snapshot_service._parse_binary_market` and
 *   `csv_player_history.player_dd_history`) but no API endpoint surfaces
 *   them yet. This component renders the contract-correct UI now so it
 *   lights up automatically when the backend endpoint ships. Until then
 *   the data props are null and the UI shows "pending" copy explicitly
 *   (NOT zero or fake numbers).
 */

"use client";

import { Award, Info, Target } from "lucide-react";
import { cn } from "@/lib/utils";

interface PlayerDDTileProps {
  playerName: string;
  /** American odds for the Yes outcome. Null when no bookmaker has posted. */
  yesPrice?: number | null;
  /** Implied probability (vig-laden) of the Yes outcome, derived from yesPrice. */
  yesImpliedProb?: number | null;
  /**
   * Single-leg de-vigged Yes probability. Null when the league-average vig
   * prior cannot be safely applied — DO NOT substitute a number.
   */
  yesFairProb?: number | null;
  /** Historical P(DD = 1) from CSV game logs (`prob_dd`). Null when sample is empty. */
  historicalProbDD?: number | null;
  /** Number of historical games considered. */
  historicalGames?: number | null;
}

function formatAmericanPrice(price: number): string {
  return price > 0 ? `+${price}` : `${price}`;
}

function formatPercent(p: number | null | undefined): string {
  if (p === null || p === undefined || Number.isNaN(p)) return "—";
  return `${(p * 100).toFixed(1)}%`;
}

/**
 * PlayerDDTile — renders the DD-specific binary outcome panel.
 */
export function PlayerDDTile({
  playerName,
  yesPrice,
  yesImpliedProb,
  yesFairProb,
  historicalProbDD,
  historicalGames,
}: PlayerDDTileProps) {
  const fairProbAvailable =
    yesFairProb !== null && yesFairProb !== undefined && !Number.isNaN(yesFairProb);
  const histAvailable =
    historicalProbDD !== null &&
    historicalProbDD !== undefined &&
    !Number.isNaN(historicalProbDD);

  // Edge bar — show historical P(DD=1) against the fair (or implied) Yes prob,
  // so the user can eyeball whether the book is offering value.
  const referenceProb = fairProbAvailable ? yesFairProb! : yesImpliedProb ?? null;
  const edge =
    histAvailable && referenceProb !== null ? historicalProbDD! - referenceProb : null;

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Title */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-red flex items-center justify-center">
          <Award className="w-4 h-4 text-white" />
        </div>
        <h3 className="text-lg font-bold text-dark">
          {playerName} — Double Double (Yes / No)
        </h3>
      </div>

      {/* Stat row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {/* Yes price */}
        <div className="card">
          <p className="text-sm font-bold text-dark mb-1">Yes Price</p>
          <p className="text-xl font-bold font-mono text-dark">
            {yesPrice === null || yesPrice === undefined
              ? "—"
              : formatAmericanPrice(yesPrice)}
          </p>
          <p className="text-[10px] text-gray mt-0.5">American odds</p>
        </div>

        {/* Yes implied prob */}
        <div className="card">
          <p className="text-sm font-bold text-dark mb-1">Yes Implied</p>
          <p className="text-xl font-bold text-dark">
            {formatPercent(yesImpliedProb)}
          </p>
          <p className="text-[10px] text-gray mt-0.5">vig-laden</p>
        </div>

        {/* Yes fair prob (or "vig prior unavailable") */}
        <div className="card bg-green-50 border-green-300">
          <p className="text-sm font-bold text-green-700 mb-1">Yes Fair</p>
          {fairProbAvailable ? (
            <>
              <p className="text-xl font-bold text-green-600">
                {formatPercent(yesFairProb)}
              </p>
              <p className="text-[10px] text-gray mt-0.5">single-leg de-vigged</p>
            </>
          ) : (
            <>
              <p className="text-sm font-semibold text-gray italic">
                vig prior unavailable
              </p>
              <p className="text-[10px] text-gray mt-0.5">
                fair-prob withheld (not fabricated)
              </p>
            </>
          )}
        </div>

        {/* Historical P(DD=1) */}
        <div className="card bg-blue-50 border-blue-300">
          <div className="flex items-center gap-2 text-blue-700 mb-1">
            <Target className="w-4 h-4" />
            <span className="text-sm font-bold">Historical</span>
          </div>
          <p className="text-xl font-bold text-blue-600">
            {formatPercent(historicalProbDD)}
          </p>
          <p className="text-[10px] text-gray mt-0.5">
            {historicalGames !== null && historicalGames !== undefined
              ? `over ${historicalGames} games`
              : "P(DD = 1) — pending"}
          </p>
        </div>
      </div>

      {/* Edge bar (historical vs reference) */}
      {edge !== null && (
        <div className="card">
          <p className="text-sm font-bold text-dark mb-2">
            Historical edge vs {fairProbAvailable ? "fair" : "implied"} Yes prob
          </p>
          <div className="relative h-3 w-full bg-dark/10 rounded-full overflow-hidden">
            <div
              className={cn(
                "absolute left-0 top-0 h-full",
                edge >= 0 ? "bg-green-500" : "bg-red",
              )}
              style={{ width: `${Math.min(Math.abs(edge) * 100, 100)}%` }}
            />
          </div>
          <p
            className={cn(
              "mt-1 text-xs font-bold",
              edge >= 0 ? "text-green-600" : "text-red",
            )}
          >
            {edge >= 0 ? "+" : ""}
            {(edge * 100).toFixed(1)} pts
          </p>
        </div>
      )}

      {/* ML projection footer (Phase 2 scope) */}
      <div className="card border-dark/20">
        <div className="flex items-start gap-3">
          <Info className="w-5 h-5 text-gray shrink-0 mt-0.5" />
          <div className="text-xs text-gray space-y-1">
            <p>
              📊 Double Double = ≥ 2 of {"{"}PTS, REB, AST, STL, BLK{"}"} ≥ 10 in a
              single game.
            </p>
            <p>
              🤖 <span className="font-semibold">ML projection N/A — Phase 2.</span>{" "}
              DD is a multivariate joint probability that cannot be derived
              from marginal projections without correlation data.
            </p>
            {!histAvailable && (
              <p>
                ℹ️ Historical P(DD=1) wiring is pending — backend ships the
                computation in <code className="text-[11px]">player_dd_history()</code>
                {" "}but no public endpoint exposes it yet (see SPO-20 backend
                gap escalation).
              </p>
            )}
            {yesPrice === null && (
              <p>
                ℹ️ No bookmaker has posted a Yes price for this game yet — odds
                fields will populate on the next snapshot fetch when inventory
                appears.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
