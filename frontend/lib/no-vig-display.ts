/**
 * Display helpers for /props/no-vig rows.
 *
 * Double-double is Yes/No. The 0.5 line is a placeholder. A one-sided
 * quote has no posted No price: SPO-104 sends `under_odds: null` and
 * `no_price: null`. Older responses still copy the Yes price into
 * `under_odds` and leave `no_price` null. Either null means the fair
 * No number came from the 4.5% single-leg prior.
 *
 * `uses_prior` and `consensus_uses_prior` are provisional names. When
 * a boolean is present it wins. When it is absent, a null No price on
 * any row is still the prior signal.
 */

import type { BookmakerResult, NoVigResponse } from "@/lib/schemas";
import { formatAmericanOdds, formatProbability } from "@/lib/utils";

export const MISSING_QUOTE = "—";
export const SINGLE_LEG_PRIOR_LABEL = "4.5% single-leg prior";

const DOUBLE_DOUBLE_MARKETS = new Set(["player_double_double", "dd"]);

export function isDoubleDoubleMarket(market: string | null | undefined): boolean {
  return typeof market === "string" && DOUBLE_DOUBLE_MARKETS.has(market);
}

/**
 * `uses_prior` wins when the backend sent a boolean. Otherwise a null
 * No price is the prior signal. `undefined` (the field was not on an
 * Over/Under row) is not.
 */
export function usesSingleLegPrior(row: {
  uses_prior?: boolean | null;
  under_odds?: number | null;
  no_price?: number | null;
}): boolean {
  if (typeof row.uses_prior === "boolean") return row.uses_prior;
  return row.under_odds === null || row.no_price === null;
}

export interface ConsensusPriorSource {
  consensus?: {
    consensus_uses_prior?: boolean | null;
    consensus_prior_book_count?: number | null;
  } | null;
  consensus_uses_prior?: boolean | null;
  consensus_prior_book_count?: number | null;
  results: Array<{
    uses_prior?: boolean | null;
    under_odds?: number | null;
    no_price?: number | null;
  }>;
}

function finiteCount(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** True when the consensus includes at least one 4.5% prior book. */
export function consensusUsesPrior(data: ConsensusPriorSource): boolean {
  const onConsensus = data.consensus?.consensus_uses_prior;
  if (typeof onConsensus === "boolean") return onConsensus;
  if (typeof data.consensus_uses_prior === "boolean") return data.consensus_uses_prior;
  return data.results.some((row) => usesSingleLegPrior(row));
}

export function consensusPriorBookCount(data: ConsensusPriorSource): number | null {
  const onConsensus = finiteCount(data.consensus?.consensus_prior_book_count);
  if (onConsensus !== null) return onConsensus;
  return finiteCount(data.consensus_prior_book_count);
}

/**
 * Caption under consensus fair values. A count, when the payload has one,
 * says how many books in that consensus used the prior.
 */
export function consensusPriorCaption(data: ConsensusPriorSource): string | null {
  if (!consensusUsesPrior(data)) return null;
  const count = consensusPriorBookCount(data);
  if (count === null) return SINGLE_LEG_PRIOR_LABEL;
  const noun = count === 1 ? "book" : "books";
  return `includes ${count} ${noun} on the ${SINGLE_LEG_PRIOR_LABEL}`;
}

export function responseIsBinary(data: Pick<NoVigResponse, "market" | "results">): boolean {
  if (isDoubleDoubleMarket(data.market)) return true;
  return data.results.some(
    (row) => row.line_is_synthetic === true || row.market_kind === "binary",
  );
}

/**
 * Hide the numeric line when the backend says it is synthetic.
 * When that flag is absent, a binary market_kind or a DD market is the fallback.
 * An explicit `line_is_synthetic: false` keeps the number.
 */
export function hideLine(
  row: Pick<BookmakerResult, "line_is_synthetic" | "market_kind">,
  market?: string | null,
): boolean {
  if (row.line_is_synthetic === true) return true;
  if (row.line_is_synthetic === false) return false;
  if (row.market_kind === "binary") return true;
  if (row.market_kind === "over_under") return false;
  return isDoubleDoubleMarket(market);
}

function formatPrice(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return MISSING_QUOTE;
  return formatAmericanOdds(value);
}

function formatImplied(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return MISSING_QUOTE;
  return formatProbability(value);
}

export function lineText(
  row: BookmakerResult,
  market?: string | null,
): string {
  if (hideLine(row, market)) return "Yes/No";
  return String(row.line);
}

export function yesPriceText(row: BookmakerResult): string {
  if (typeof row.yes_price === "number") return formatAmericanOdds(row.yes_price);
  return formatPrice(row.over_odds);
}

export function noPriceText(row: BookmakerResult, binary: boolean): string {
  if (binary && usesSingleLegPrior(row)) return MISSING_QUOTE;
  if (typeof row.no_price === "number") return formatAmericanOdds(row.no_price);
  return formatPrice(row.under_odds);
}

export function yesImpliedText(row: BookmakerResult): string {
  if (typeof row.p_yes_imp === "number") return formatProbability(row.p_yes_imp);
  return formatImplied(row.p_over_imp);
}

export function noImpliedText(row: BookmakerResult, binary: boolean): string {
  if (binary && usesSingleLegPrior(row)) return MISSING_QUOTE;
  if (typeof row.p_no_imp === "number") return formatProbability(row.p_no_imp);
  return formatImplied(row.p_under_imp);
}

export function fairYesValue(row: BookmakerResult): number | null {
  if (typeof row.yes_fair_prob === "number") return row.yes_fair_prob;
  return typeof row.p_over_fair === "number" ? row.p_over_fair : null;
}

export function fairNoValue(row: BookmakerResult): number | null {
  if (typeof row.no_fair_prob === "number") return row.no_fair_prob;
  return typeof row.p_under_fair === "number" ? row.p_under_fair : null;
}

export function oddsAgeLabel(
  data: Pick<NoVigResponse, "fetched_at" | "data_age_seconds">,
): string | null {
  const fetched = data.fetched_at;
  const hasFetched = typeof fetched === "string" && fetched.length > 0;
  const age = data.data_age_seconds;
  if (typeof age === "number" && Number.isFinite(age)) {
    return hasFetched
      ? `Odds response is ${age} seconds old. Fetched at ${fetched}.`
      : `Odds response is ${age} seconds old.`;
  }
  if (hasFetched) return `Odds fetched at ${fetched}.`;
  return null;
}
