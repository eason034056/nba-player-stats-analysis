"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { DatePicker } from "@/components/DatePicker";
import { LineupStatusBadge } from "@/components/LineupStatusBadge";
import { PickContextMenu } from "@/components/PickContextMenu";
import type { LeagueSegment } from "@/lib/event-detail-link";
import { boardRate } from "@/lib/nba-card";
import {
  CONFIDENCE_FILTERS,
  buildPickRows,
  countStrong,
  marketChipList,
  matchesConfidence,
  picksEyebrow,
  sortPicks,
  type ConfidenceFilter,
} from "@/lib/picks-board";
import type { DailyPick, TeamLineup } from "@/lib/schemas";
import { metricShort } from "@/lib/today-board";
import { cn } from "@/lib/utils";

const TIER_CLASS = {
  strong: "bg-accent text-brand-ink",
  playable: "bg-brand text-white",
  lean: "bg-[#E3DAF3] text-brand",
  pass: "bg-[#E2E2E2] text-[#4A4458]",
} as const;

export interface DailyPicksBoardProps {
  league: LeagueSegment;
  selectedDate: string;
  onDateChange: (date: string) => void;
  analyzedAt?: string | null;
  isStale: boolean;
  picks: DailyPick[];
  isLoading: boolean;
  isError: boolean;
  errorMessage: string | null;
  onRetry: () => void;
  onReanalyze: () => void;
  isReanalyzing: boolean;
  emptyMessage: string | null;
  minProbability: number;
  teams: string[];
  selectedTeams: Set<string>;
  onToggleTeam: (team: string) => void;
  onClearTeams: () => void;
  teamFilterEmpty: boolean;
  lineupFor?: (pick: DailyPick) => TeamLineup | null | undefined;
  showLineup: boolean;
  isLineupLoading: boolean;
  isLineupError: boolean;
  slipDirection: (pick: DailyPick) => string | null;
  onToggleSlip: (pick: DailyPick) => void;
  onAddReverse?: (pick: DailyPick) => void;
  slipCaption?: (pick: DailyPick) => string | null;
  onAsk?: (pick: DailyPick) => void;
  onReviewBoard?: () => void;
}

function Chip({
  active,
  onClick,
  children,
  mono = false,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
  mono?: boolean;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "min-h-[38px] shrink-0 rounded-full border px-3.5 py-2",
        mono ? "font-mono text-xs font-bold" : "text-[13px] font-semibold",
        active ? "border-brand bg-brand text-white" : "border-muted bg-white text-ink",
      )}
    >
      {children}
    </button>
  );
}

function PickSkeleton() {
  return (
    <div className="flex items-center gap-4 rounded-[20px] border border-line bg-white px-[18px] py-4">
      <div className="h-10 w-10 animate-pulse rounded-full bg-[#EEEBF2]" />
      <div className="flex-1 space-y-2">
        <div className="h-4 w-40 animate-pulse rounded bg-[#EEEBF2]" />
        <div className="h-3 w-56 animate-pulse rounded bg-[#EEEBF2]" />
      </div>
      <div className="h-7 w-16 animate-pulse rounded bg-[#EEEBF2]" />
    </div>
  );
}

export function DailyPicksBoard({
  league,
  selectedDate,
  onDateChange,
  analyzedAt,
  isStale,
  picks,
  isLoading,
  isError,
  errorMessage,
  onRetry,
  onReanalyze,
  isReanalyzing,
  emptyMessage,
  minProbability,
  teams,
  selectedTeams,
  onToggleTeam,
  onClearTeams,
  teamFilterEmpty,
  lineupFor,
  showLineup,
  isLineupLoading,
  isLineupError,
  slipDirection,
  onToggleSlip,
  onAddReverse,
  slipCaption,
  onAsk,
  onReviewBoard,
}: DailyPicksBoardProps) {
  const [confidence, setConfidence] = useState<ConfidenceFilter>("all");
  const [market, setMarket] = useState("ALL");

  useEffect(() => {
    setConfidence("all");
    setMarket("ALL");
  }, [selectedDate]);

  const markets = useMemo(() => marketChipList(picks), [picks]);
  const visiblePicks = useMemo(
    () =>
      sortPicks(
        picks.filter(
          (pick) =>
            matchesConfidence(boardRate(pick, league), confidence) &&
            (market === "ALL" || metricShort(pick.metric) === market),
        ),
        league,
      ),
    [confidence, league, market, picks],
  );
  const rows = useMemo(
    () => buildPickRows(visiblePicks, league, selectedDate),
    [league, selectedDate, visiblePicks],
  );
  const strongCount = countStrong(visiblePicks, league);
  const floor = Math.round(minProbability * 100);
  const eyebrow = picksEyebrow(selectedDate, analyzedAt);

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-[22px] px-4 py-6 md:px-8 md:py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex max-w-[640px] flex-col gap-2">
          <div className="font-mono text-xs font-semibold tracking-[0.12em] text-[#7B4FC4]">
            {eyebrow}
          </div>
          <h1 className="text-[32px] font-bold leading-none tracking-[-0.035em] md:text-[52px]">
            Daily Picks
          </h1>
          <p className="text-[15px] leading-relaxed text-muted">
            {league === "nba"
              ? `Props whose combined probability is ${floor}% or more.`
              : `Props whose historical hit rate is ${floor}% or more, ranked by that rate.`}
          </p>
        </div>
        <div className="flex gap-2.5">
          <div className="rounded-2xl border border-line bg-white px-4 py-2.5">
            <div className="font-mono text-[22px] font-bold leading-none">{visiblePicks.length}</div>
            <div className="mt-1 text-xs text-muted">picks</div>
          </div>
          <div className="rounded-2xl bg-accent px-4 py-2.5 text-brand-ink">
            <div className="font-mono text-[22px] font-bold leading-none">{strongCount}</div>
            <div className="mt-1 text-xs">strong</div>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-3 rounded-[20px] border border-line bg-white px-4 py-4 md:px-5">
        <DatePicker value={selectedDate} onChange={onDateChange} />
        <div className="flex flex-wrap items-center gap-2">
          {analyzedAt ? (
            <span
              className={cn(
                "rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-[0.08em]",
                isStale ? "bg-accent text-yellow" : "bg-[#E5F2EA] text-green-800",
              )}
            >
              {isStale ? "Stale board" : "Fresh board"}
            </span>
          ) : null}
          <button
            type="button"
            onClick={onReanalyze}
            disabled={isReanalyzing}
            className="min-h-10 rounded-full border border-muted bg-white px-4 text-sm font-semibold text-ink disabled:opacity-50"
          >
            {isReanalyzing ? "Analyzing..." : "Re-analyze"}
          </button>
          {onReviewBoard ? (
            <button
              type="button"
              onClick={onReviewBoard}
              className="min-h-10 rounded-full bg-brand-tint px-4 text-sm font-semibold text-brand"
            >
              Review board
            </button>
          ) : null}
        </div>
      </div>

      <div className="flex flex-col gap-3 md:flex-row md:flex-wrap md:items-center md:gap-x-6">
        <div
          role="group"
          aria-label="Confidence"
          className="-mx-4 flex gap-1.5 overflow-x-auto px-4 md:mx-0 md:flex-wrap md:overflow-visible md:px-0"
        >
          {CONFIDENCE_FILTERS.map((filter) => (
            <Chip
              key={filter.id}
              active={confidence === filter.id}
              onClick={() => setConfidence(filter.id)}
            >
              {filter.label}
            </Chip>
          ))}
        </div>
        <div
          role="group"
          aria-label="Market"
          className="-mx-4 flex gap-1.5 overflow-x-auto px-4 md:mx-0 md:flex-wrap md:overflow-visible md:px-0"
        >
          {markets.map((label) => (
            <Chip key={label} mono active={market === label} onClick={() => setMarket(label)}>
              {label}
            </Chip>
          ))}
        </div>
      </div>

      {teams.length > 0 ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-semibold text-ink">
              Teams
              {selectedTeams.size > 0 ? (
                <span className="ml-2 font-mono text-xs font-bold text-muted">
                  {selectedTeams.size} selected
                </span>
              ) : null}
            </p>
            {selectedTeams.size > 0 ? (
              <button
                type="button"
                onClick={onClearTeams}
                className="text-sm font-semibold text-muted hover:text-brand"
              >
                Clear all
              </button>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            {teams.map((team) => {
              const selected = selectedTeams.has(team);
              return (
                <button
                  key={team}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => onToggleTeam(team)}
                  className={cn(
                    "min-h-10 rounded-full border px-3 py-2 font-mono text-xs font-bold",
                    selected
                      ? "border-brand bg-brand text-white"
                      : "border-muted bg-white text-ink",
                  )}
                >
                  {team}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}

      {isLoading ? (
        <div className="flex flex-col gap-2.5" aria-busy="true" aria-label="Loading picks">
          {Array.from({ length: 4 }, (_, index) => (
            <PickSkeleton key={index} />
          ))}
        </div>
      ) : null}

      {isError ? (
        <div className="rounded-[20px] border border-red bg-white px-5 py-6">
          <h2 className="text-lg font-bold">Load failed</h2>
          <p className="mt-2 text-sm text-muted">
            {errorMessage || "Unable to fetch analysis data, please try again later"}
          </p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-4 text-sm font-bold text-brand hover:underline"
          >
            Click to retry
          </button>
        </div>
      ) : null}

      {!isLoading && !isError && picks.length === 0 && !teamFilterEmpty ? (
        <div className="rounded-[20px] border border-line bg-white px-6 py-12 text-center">
          <h2 className="text-xl font-bold">No high-probability picks</h2>
          <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-muted">
            {emptyMessage ||
              `No betting options at or above ${floor}% were found for ${selectedDate}.`}
          </p>
          <button
            type="button"
            onClick={onReanalyze}
            disabled={isReanalyzing}
            className="mt-6 min-h-11 rounded-full bg-brand px-5 text-sm font-bold text-white disabled:opacity-50"
          >
            {isReanalyzing ? "Analyzing..." : "Analyze now"}
          </button>
        </div>
      ) : null}

      {!isLoading && !isError && teamFilterEmpty ? (
        <div className="rounded-[20px] border border-line bg-white px-6 py-12 text-center">
          <h2 className="text-xl font-bold">No picks match current filters</h2>
          <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-muted">
            Picks are available for {selectedDate}, but none match the selected teams.
          </p>
          <button
            type="button"
            onClick={onClearTeams}
            className="mt-6 min-h-11 rounded-full bg-brand px-5 text-sm font-bold text-white"
          >
            Clear filters
          </button>
        </div>
      ) : null}

      {!isLoading && !isError && picks.length > 0 && !teamFilterEmpty && rows.length === 0 ? (
        <div className="rounded-[20px] border border-line bg-white px-5 py-10 text-center text-sm text-muted">
          No picks match these filters.
        </div>
      ) : null}

      {!isLoading && !isError && rows.length > 0 ? (
        <div className="flex flex-col gap-2.5">
          {rows.map((row, index) => {
            const pick = visiblePicks[index];
            if (!pick) return null;
            const storedDirection = slipDirection(pick);
            const reverse = pick.direction === "over" ? "under" : "over";
            const inSlip = storedDirection != null;
            const reversed = storedDirection === reverse;
            const sameSide = inSlip && !reversed;
            return (
              <PickContextMenu key={row.key} pick={pick} league={league}>
                <article
                  className={cn(
                    "flex flex-col gap-3 rounded-[18px] border bg-white px-3.5 py-3.5 md:flex-row md:flex-wrap md:items-center md:gap-x-5 md:rounded-[20px] md:px-[18px] md:py-4",
                    sameSide ? "border-brand" : "border-line",
                  )}
                >
                  <div className="flex min-w-0 flex-1 items-center gap-3 md:basis-[240px]">
                    <div className="w-[22px] shrink-0 font-mono text-[13px] font-bold text-muted">
                      {row.rank}
                    </div>
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-line font-mono text-[11px] font-bold text-brand">
                      {row.team}
                    </div>
                    <div className="min-w-0 flex-1">
                      <Link href={row.href} className="block font-bold hover:text-brand">
                        {row.player}
                      </Link>
                      <div className="mt-0.5 text-[13px] text-muted">{row.matchup}</div>
                    </div>
                  </div>

                  <div className="flex min-w-0 flex-1 basis-[220px] flex-col gap-2">
                    <div className="text-[15px] font-bold">{row.propText}</div>
                    {slipCaption?.(pick) ? (
                      <p className="text-xs leading-5 text-muted">{slipCaption(pick)}</p>
                    ) : null}
                    <TagList
                      tags={row.tags}
                      pick={pick}
                      lineupFor={lineupFor}
                      showLineup={showLineup}
                      isLineupLoading={isLineupLoading}
                      isLineupError={isLineupError}
                    />
                  </div>

                  <div className="flex min-w-[120px] flex-[0_1_150px] flex-col gap-1.5">
                    <div className="flex items-baseline justify-between gap-2">
                      <div className="font-mono text-2xl font-bold text-brand">{row.probabilityText}</div>
                      {row.tierShort && row.tierName ? (
                        <span
                          className={cn(
                            "rounded-full px-2 py-0.5 text-[11px] font-bold",
                            TIER_CLASS[row.tierName],
                          )}
                        >
                          {row.tierShort}
                        </span>
                      ) : null}
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-[#EEEBF2]">
                      <div
                        className="h-full rounded-full bg-brand"
                        style={{ width: `${row.barPercent}%` }}
                      />
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-wrap justify-end gap-2">
                      <button
                        type="button"
                        aria-label={sameSide ? "Added to Bet Slip" : "Add to Bet Slip"}
                        onClick={() => onToggleSlip(pick)}
                        className={cn(
                          "min-h-11 rounded-full border px-4 text-[13px] font-bold",
                          sameSide
                            ? "border-accent bg-accent text-brand-ink"
                            : "border-muted bg-white text-brand",
                        )}
                      >
                        {sameSide ? "✓ In slip" : "+ Slip"}
                      </button>
                      {onAddReverse ? (
                        <button
                          type="button"
                          aria-label={
                            reversed
                              ? `Reverse added (${reverse})`
                              : `Add ${reverse === "over" ? "Over" : "Under"}`
                          }
                          onClick={() => onAddReverse(pick)}
                          className={cn(
                            "min-h-11 rounded-full border px-3 text-[13px] font-semibold",
                            reversed
                              ? "border-brand bg-brand text-white"
                              : "border-muted bg-white text-ink",
                          )}
                        >
                          {reversed ? "Reverse added" : `Add ${reverse === "over" ? "Over" : "Under"}`}
                        </button>
                      ) : null}
                      {onAsk ? (
                        <button
                          type="button"
                          aria-label={`Ask Agent about ${pick.player_name}`}
                          onClick={() => onAsk(pick)}
                          className="min-h-11 rounded-full bg-brand-tint px-3 text-[13px] font-bold text-brand"
                        >
                          Ask
                        </button>
                      ) : null}
                    </div>
                </article>
              </PickContextMenu>
            );
          })}
        </div>
      ) : null}

      <p className="text-[13px] leading-6 text-muted">
        The line is the most common line across books.{" "}
        {league === "nba"
          ? "The percent is the combined probability. Projection, edge, minutes, and opponent rank appear only when the response includes them."
          : "The percent is the historical hit rate over the stored sample. Projection, edge, minutes, and opponent rank appear only when the response includes them. A blended probability is not on this board."}
      </p>
    </div>
  );
}

function TagList({
  tags,
  pick,
  lineupFor,
  showLineup,
  isLineupLoading,
  isLineupError,
}: {
  tags: { text: string }[];
  pick: DailyPick;
  lineupFor?: (pick: DailyPick) => TeamLineup | null | undefined;
  showLineup: boolean;
  isLineupLoading: boolean;
  isLineupError: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {showLineup ? (
        <LineupStatusBadge
          lineup={lineupFor?.(pick)}
          playerName={pick.player_name}
          isLoading={isLineupLoading}
          isError={isLineupError}
        />
      ) : null}
      {tags.map((tag) => (
        <span
          key={tag.text}
          className="rounded-md bg-[#F1F0F3] px-2 py-0.5 text-[11px] font-semibold text-[#4A4458]"
        >
          {tag.text}
        </span>
      ))}
    </div>
  );
}
