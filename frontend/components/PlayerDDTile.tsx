/**
 * PlayerDDTile — Double-double (Yes/No) panel.
 *
 * Data comes from two routes shipped with the 12-metric backend:
 *   - GET /api/{nba|wnba}/player-dd-history
 *     `prob_dd`, `n_games`, `dd_games`, `message`
 *   - POST /api/{nba|wnba}/props/no-vig with market `player_double_double`
 *     per-book `yes_price`, `no_price`, `p_yes_imp`, `p_no_imp`,
 *     `yes_fair_prob`, `no_fair_prob`, plus consensus `p_yes_fair` / `p_no_fair`
 *
 * A missing, null, or empty payload renders an explicit unavailable state.
 * This tile does not display the binary `line` sentinel and does not read
 * `over_*` / `under_*` as a substitute for the Yes/No fields.
 */

"use client";

import { AlertCircle, Award, Info, Loader2, Target } from "lucide-react";

import { SectionUnavailable } from "@/components/SectionUnavailable";
import { ApiError } from "@/lib/api";
import { SINGLE_LEG_PRIOR_LABEL } from "@/lib/no-vig-display";
import {
  formatPercent,
  historicalEdgeVsFairYes,
  referenceFairYes,
  roundHalfAwayFromZero,
  selectDDHistory,
  selectDDOdds,
  staleLineWarning,
  type DDBookQuote,
  type DDHistorySelection,
  type DDOddsSelection,
} from "@/lib/player-dd";
import { BOOKMAKERS } from "@/lib/schemas";
import type {
  NoVigRequest,
  NoVigResponse,
  PlayerDDHistoryRequest,
  PlayerDDHistoryResponse,
} from "@/lib/schemas";
import { cn } from "@/lib/utils";
import {
  usePlayerDDTileData,
  type DDLeague,
} from "@/lib/use-player-dd";

const MISSING_PLAYER_MESSAGE =
  "Enter a player name to load double-double history and Yes/No odds.";
const EMPTY_HISTORY_MESSAGE = "No double-double games are in the sample.";
const EMPTY_ODDS_MESSAGE =
  "No Yes/No double-double prices are posted for this player.";
const NULL_ODDS_MESSAGE =
  "Yes/No prices were not in the response. Over/Under numbers are not shown in their place.";
const NO_EVENT_MESSAGE =
  "Live Yes/No prices need a game. Open this player from an event to load posted odds.";
const UNSUPPORTED_LEAGUE_MESSAGE =
  "Double-double history and live Yes/No odds are not available for this league.";

export interface PlayerDDTileProps {
  playerName: string;
  /**
   * Which league's routes to call. NBA and WNBA both expose the history
   * route and the binary no-vig branch. `null` renders the unavailable
   * state and does not call either API.
   */
  league: DDLeague | null;
  /** Required for live Yes/No prices. History still loads without it. */
  eventId?: string;
  /** Optional season filter forwarded as the `season` query param. */
  season?: string;
  getPlayerDDHistoryFn?: (
    request: PlayerDDHistoryRequest,
  ) => Promise<PlayerDDHistoryResponse>;
  calculateNoVigFn?: (request: NoVigRequest) => Promise<NoVigResponse>;
}

function formatAmericanPrice(price: number): string {
  return price > 0 ? `+${price}` : `${price}`;
}

function bookLabel(key: string): string {
  const known = BOOKMAKERS.find((book) => book.key === key);
  return known?.name ?? key;
}

function errorText(error: unknown): string {
  if (error instanceof ApiError && error.detail) return error.detail;
  if (
    error &&
    typeof error === "object" &&
    "detail" in error &&
    typeof (error as { detail?: unknown }).detail === "string" &&
    (error as { detail: string }).detail.length > 0
  ) {
    return (error as { detail: string }).detail;
  }
  if (error instanceof Error && error.message) return error.message;
  return "Request failed";
}

function FieldValue({
  value,
  kind,
  missingLabel,
  valueClassName = "text-dark",
}: {
  value: number | null;
  kind: "price" | "percent";
  missingLabel: string;
  valueClassName?: string;
}) {
  if (value === null) {
    return (
      <p className="text-sm font-semibold text-gray italic">{missingLabel}</p>
    );
  }
  return (
    <p className={cn("text-xl font-bold font-mono", valueClassName)}>
      {kind === "price" ? formatAmericanPrice(value) : formatPercent(value)}
    </p>
  );
}

function BookQuoteCard({ quote }: { quote: DDBookQuote }) {
  return (
    <article className="card" aria-label={`${bookLabel(quote.bookmaker)} double-double prices`}>
      <p className="text-sm font-bold text-dark mb-3">{bookLabel(quote.bookmaker)}</p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray">Yes price</p>
          <FieldValue value={quote.yesPrice} kind="price" missingLabel="Unavailable" />
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray">No price</p>
          <FieldValue
            value={quote.noPrice}
            kind="price"
            missingLabel="Unavailable"
          />
          {quote.noPrice === null && (
            <p className="text-[10px] text-gray mt-0.5">No leg not posted</p>
          )}
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray">Yes implied</p>
          <FieldValue value={quote.yesImplied} kind="percent" missingLabel="Unavailable" />
          {quote.yesImplied !== null && (
            <p className="text-[10px] text-gray mt-0.5">vig-laden</p>
          )}
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray">No implied</p>
          <FieldValue value={quote.noImplied} kind="percent" missingLabel="Unavailable" />
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray">Yes fair</p>
          <FieldValue
            value={quote.yesFair}
            kind="percent"
            missingLabel="vig prior unavailable"
          />
          {quote.usesSingleLegPrior && quote.yesFair !== null && (
            <p className="text-[10px] text-gray mt-0.5">{SINGLE_LEG_PRIOR_LABEL}</p>
          )}
          {quote.yesFair === null && (
            <p className="text-[10px] text-gray mt-0.5">fair probability withheld</p>
          )}
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray">No fair</p>
          <FieldValue
            value={quote.noFair}
            kind="percent"
            missingLabel="Unavailable"
          />
          {quote.usesSingleLegPrior && quote.noFair !== null && (
            <p className="text-[10px] text-gray mt-0.5">{SINGLE_LEG_PRIOR_LABEL}</p>
          )}
        </div>
      </div>
    </article>
  );
}

function HistoryBlock({
  isLoading,
  isError,
  error,
  selection,
}: {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  selection: DDHistorySelection | null;
}) {
  if (isLoading) {
    return (
      <div className="card" role="status">
        <div className="flex items-center gap-3 text-sm text-gray">
          <Loader2 className="h-4 w-4 animate-spin text-red" />
          Loading double-double history
        </div>
      </div>
    );
  }
  if (isError) {
    return (
      <div className="card border-red" role="alert">
        <div className="flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-red shrink-0" />
          <div>
            <p className="font-bold text-dark">Double-double history unavailable</p>
            <p className="text-sm text-gray">{errorText(error)}</p>
          </div>
        </div>
      </div>
    );
  }
  if (!selection || selection.status === "empty") {
    return (
      <SectionUnavailable
        eyebrow="Historical rate"
        title="Double-double history"
        message={selection?.message || EMPTY_HISTORY_MESSAGE}
      />
    );
  }
  return (
    <div className="card bg-blue-50 border-blue-300" data-testid="dd-history">
      <div className="flex items-center gap-2 text-blue-700 mb-1">
        <Target className="w-4 h-4" />
        <span className="text-sm font-bold">Historical P(DD = 1)</span>
      </div>
      <p className="text-xl font-bold text-blue-600">{formatPercent(selection.probDD)}</p>
      <p className="text-[10px] text-gray mt-0.5">
        {selection.ddGames} of {selection.nGames} games
      </p>
    </div>
  );
}

function OddsBlock({
  hasEvent,
  isLoading,
  isError,
  error,
  selection,
}: {
  hasEvent: boolean;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  selection: DDOddsSelection | null;
}) {
  if (!hasEvent) {
    return (
      <SectionUnavailable
        eyebrow="Yes / No odds"
        title="Double-double odds"
        message={NO_EVENT_MESSAGE}
      />
    );
  }
  if (isLoading) {
    return (
      <div className="card" role="status">
        <div className="flex items-center gap-3 text-sm text-gray">
          <Loader2 className="h-4 w-4 animate-spin text-red" />
          Loading double-double odds
        </div>
      </div>
    );
  }
  if (isError) {
    return (
      <div className="card border-red" role="alert">
        <div className="flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-red shrink-0" />
          <div>
            <p className="font-bold text-dark">Double-double odds unavailable</p>
            <p className="text-sm text-gray">{errorText(error)}</p>
          </div>
        </div>
      </div>
    );
  }
  if (!selection || selection.status === "unavailable") {
    const message =
      selection?.reason === "null-fields"
        ? [NULL_ODDS_MESSAGE, selection.message].filter(Boolean).join(" ")
        : selection?.message || EMPTY_ODDS_MESSAGE;
    return (
      <SectionUnavailable
        eyebrow="Yes / No odds"
        title="Double-double odds"
        message={message}
      />
    );
  }

  const priorOnly =
    selection.books.length > 0 &&
    selection.books.every((book) => book.usesSingleLegPrior);

  return (
    <div className="space-y-4" data-testid="dd-odds">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {selection.books.map((quote) => (
          <BookQuoteCard key={quote.bookmaker} quote={quote} />
        ))}
      </div>
      {selection.consensusYesFair !== null || selection.consensusNoFair !== null ? (
        <div className="card bg-green-50 border-green-300">
          <p className="text-sm font-bold text-green-700 mb-2">Consensus fair probability</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-[10px] uppercase tracking-wide text-gray">Yes fair</p>
              <FieldValue
                value={selection.consensusYesFair}
                kind="percent"
                missingLabel="Unavailable"
                valueClassName="text-green-800"
              />
              {priorOnly && selection.consensusYesFair !== null && (
                <p className="text-[10px] text-gray mt-0.5">{SINGLE_LEG_PRIOR_LABEL}</p>
              )}
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-gray">No fair</p>
              <FieldValue
                value={selection.consensusNoFair}
                kind="percent"
                missingLabel="Unavailable"
                valueClassName="text-green-800"
              />
              {priorOnly && selection.consensusNoFair !== null && (
                <p className="text-[10px] text-gray mt-0.5">{SINGLE_LEG_PRIOR_LABEL}</p>
              )}
            </div>
          </div>
        </div>
      ) : selection.books.length > 1 ? (
        <SectionUnavailable
          eyebrow="Consensus"
          title="Consensus fair probability"
          message="No consensus Yes/No probability was returned. Book-level prices are shown above and are not averaged here."
        />
      ) : null}
      {selection.message && (
        <p className="text-xs text-gray">{selection.message}</p>
      )}
      {staleLineWarning(selection) && (
        <p className="text-sm font-semibold text-red" role="status">
          {staleLineWarning(selection)}
        </p>
      )}
    </div>
  );
}

export function PlayerDDTile({
  playerName,
  league,
  eventId,
  season,
  getPlayerDDHistoryFn,
  calculateNoVigFn,
}: PlayerDDTileProps) {
  const { historyQuery, oddsQuery, leagueSupported, canQueryHistory, canQueryOdds } =
    usePlayerDDTileData({
      playerName,
      league,
      eventId,
      season,
      getPlayerDDHistoryFn,
      calculateNoVigFn,
    });

  const historySelection =
    historyQuery.data !== undefined ? selectDDHistory(historyQuery.data) : null;
  const oddsSelection =
    oddsQuery.data !== undefined ? selectDDOdds(oddsQuery.data) : null;
  const fairYes =
    oddsSelection?.status === "ready" ? referenceFairYes(oddsSelection) : null;
  const edge =
    historySelection?.status === "ready"
      ? historicalEdgeVsFairYes(historySelection.probDD, fairYes)
      : null;
  const headingName =
    historySelection?.player && historySelection.player.length > 0
      ? historySelection.player
      : playerName;

  return (
    <div className="space-y-4 animate-fade-in" data-testid="player-dd-tile">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-red flex items-center justify-center">
          <Award className="w-4 h-4 text-white" />
        </div>
        <h3 className="text-lg font-bold text-dark">
          {headingName} — Double Double (Yes / No)
        </h3>
      </div>

      {!leagueSupported ? (
        <SectionUnavailable
          eyebrow="Double double"
          title="Double-double"
          message={UNSUPPORTED_LEAGUE_MESSAGE}
        />
      ) : !canQueryHistory ? (
        <SectionUnavailable
          eyebrow="Double double"
          title="Double-double"
          message={MISSING_PLAYER_MESSAGE}
        />
      ) : (
        <>
          <HistoryBlock
            isLoading={
              historyQuery.isFetching && historyQuery.data === undefined
            }
            isError={historyQuery.isError}
            error={historyQuery.error}
            selection={historySelection}
          />
          <OddsBlock
            hasEvent={Boolean(eventId)}
            isLoading={
              canQueryOdds && oddsQuery.isFetching && oddsQuery.data === undefined
            }
            isError={oddsQuery.isError}
            error={oddsQuery.error}
            selection={oddsSelection}
          />
          {edge !== null && (
            <div className="card" data-testid="dd-edge">
              <p className="text-sm font-bold text-dark mb-2">
                Historical edge vs fair Yes probability
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
                {roundHalfAwayFromZero(edge * 100, 1).toFixed(1)} pts
              </p>
            </div>
          )}
        </>
      )}

      <div className="card border-dark/20">
        <div className="flex items-start gap-3">
          <Info className="w-5 h-5 text-gray shrink-0 mt-0.5" />
          <div className="text-xs text-gray space-y-1">
            <p>
              Double-double means at least 2 of points, rebounds, assists, steals,
              and blocks are 10 or more in the same game.
            </p>
            <p>
              <span className="font-semibold">ML projection is not available.</span>{" "}
              A double-double is a joint outcome. This tile does not derive one
              from separate stat projections.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
