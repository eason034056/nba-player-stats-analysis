/**
 * Pure readers for the SPO-26 double-double payloads.
 *
 * The tile must display `PlayerDDHistoryResponse` and the binary
 * `yes_*` / `no_*` fields. It must not invent a rate from `dd_games`,
 * and it must not treat legacy `over_*` / `under_*` values as Yes/No.
 * Those legacy fields stay on the row so older Over/Under screens keep
 * parsing, including the `line = 0.5` sentinel and the single-leg case
 * where `under_odds` is copied from the Yes price.
 */

import type {
  BookmakerResult,
  NoVigResponse,
  PlayerDDHistoryResponse,
} from "@/lib/schemas";

/** American odds of 0 are not a posted price. The route drops that leg. */
export function isPostedAmericanPrice(
  value: number | null | undefined,
): value is number {
  return typeof value === "number" && Number.isFinite(value) && value !== 0;
}

export function isProbability(
  value: number | null | undefined,
): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export interface DDBookQuote {
  bookmaker: string;
  yesPrice: number;
  noPrice: number | null;
  yesImplied: number | null;
  noImplied: number | null;
  yesFair: number | null;
  noFair: number | null;
}

export type DDOddsSelection =
  | {
      status: "ready";
      books: DDBookQuote[];
      consensusYesFair: number | null;
      consensusNoFair: number | null;
      message: string | null;
    }
  | {
      status: "unavailable";
      reason: "empty" | "null-fields";
      message: string | null;
    };

function explanatoryMessage(message: string | null | undefined): string | null {
  if (typeof message !== "string") return null;
  const trimmed = message.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * Keep a book only when `yes_price` is a real posted price.
 * `over_odds` is intentionally unread: on a binary row it is a positional
 * alias, and on a row whose explicit Yes fields are null it must not leak
 * into the tile.
 */
function quoteFromRow(row: BookmakerResult): DDBookQuote | null {
  if (!isPostedAmericanPrice(row.yes_price)) return null;
  return {
    bookmaker: row.bookmaker,
    yesPrice: row.yes_price,
    noPrice: isPostedAmericanPrice(row.no_price) ? row.no_price : null,
    yesImplied: isProbability(row.p_yes_imp) ? row.p_yes_imp : null,
    noImplied: isProbability(row.p_no_imp) ? row.p_no_imp : null,
    yesFair: isProbability(row.yes_fair_prob) ? row.yes_fair_prob : null,
    noFair: isProbability(row.no_fair_prob) ? row.no_fair_prob : null,
  };
}

export function selectDDOdds(response: NoVigResponse): DDOddsSelection {
  const message = explanatoryMessage(response.message);
  const books = response.results
    .map(quoteFromRow)
    .filter((row): row is DDBookQuote => row !== null);

  if (books.length === 0) {
    return {
      status: "unavailable",
      reason: response.results.length === 0 ? "empty" : "null-fields",
      message,
    };
  }

  const consensus = response.consensus;
  return {
    status: "ready",
    books,
    consensusYesFair: isProbability(consensus?.p_yes_fair)
      ? consensus.p_yes_fair
      : null,
    consensusNoFair: isProbability(consensus?.p_no_fair)
      ? consensus.p_no_fair
      : null,
    message,
  };
}

export type DDHistorySelection =
  | {
      status: "ready";
      player: string;
      probDD: number;
      nGames: number;
      ddGames: number;
    }
  | {
      status: "empty";
      player: string;
      message: string | null;
    };

/**
 * A historical rate is shown only when the route returned `prob_dd` and a
 * positive `n_games`. An empty sample is HTTP 200 with `prob_dd: null`;
 * dividing `dd_games / n_games` here would hide that.
 */
export function selectDDHistory(
  response: PlayerDDHistoryResponse,
): DDHistorySelection {
  const message = explanatoryMessage(response.message);
  const nGames = response.n_games;
  const ddGames = response.dd_games;
  if (
    !isProbability(response.prob_dd) ||
    typeof nGames !== "number" ||
    !Number.isFinite(nGames) ||
    nGames <= 0 ||
    typeof ddGames !== "number" ||
    !Number.isFinite(ddGames)
  ) {
    return { status: "empty", player: response.player, message };
  }
  return {
    status: "ready",
    player: response.player,
    probDD: response.prob_dd,
    nGames,
    ddGames,
  };
}

/**
 * Fair Yes probability used for the historical-edge bar.
 * Consensus wins when the route sent `p_yes_fair`. A single posted book
 * can stand on its own `yes_fair_prob`. Several books and no consensus
 * is not averaged on the client.
 */
export function referenceFairYes(
  selection: Extract<DDOddsSelection, { status: "ready" }>,
): number | null {
  if (isProbability(selection.consensusYesFair)) return selection.consensusYesFair;
  if (selection.books.length === 1) return selection.books[0]?.yesFair ?? null;
  return null;
}

export function historicalEdgeVsFairYes(
  probDD: number | null,
  fairYes: number | null,
): number | null {
  if (!isProbability(probDD) || !isProbability(fairYes)) return null;
  return probDD - fairYes;
}
