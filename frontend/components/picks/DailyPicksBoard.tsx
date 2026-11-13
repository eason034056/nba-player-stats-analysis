"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { InjuryStatusTag } from "@/components/InjuryStatusTag";
import { LineupStatusBadge } from "@/components/LineupStatusBadge";
import { PickContextMenu } from "@/components/PickContextMenu";
import { BoardChip } from "@/components/picks/BoardChip";
import { PicksDateRow } from "@/components/picks/PicksDateRow";
import type { LeagueSegment } from "@/lib/event-detail-link";
import { boardRate } from "@/lib/nba-card";
import {
  CONFIDENCE_FILTERS,
  buildPickRows,
  countStrong,
  isOutPick,
  marketChipList,
  matchesConfidence,
  picksEyebrow,
  sortPicks,
  type ConfidenceFilter,
  type PickTag,
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
  slipCaption?: (pick: DailyPick) => string | null;
  onReviewBoard?: () => void;
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
  slipCaption,
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
        picks.filter((pick) => {
          if (market !== "ALL" && metricShort(pick.metric) !== market) return false;
          if (isOutPick(pick)) return confidence === "all";
          return matchesConfidence(boardRate(pick, league), confidence);
        }),
        league,
      ),
    [confidence, league, market, picks],
  );
  const rows = useMemo(
    () => buildPickRows(visiblePicks, league, selectedDate),
    [league, selectedDate, visiblePicks],
  );
  const strongCount = countStrong(visiblePicks, league);
  const pickCount = visiblePicks.filter((pick) => !isOutPick(pick)).length;
  const floor = Math.round(minProbability * 100);
  const eyebrow = picksEyebrow(selectedDate, analyzedAt);

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-[22px] px-4 py-6 md:px-8 md:py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex max-w-[640px] flex-col gap-2">
          <div className="font-mono text-xs font-semibold tracking-[0.12em] text-[#7B4FC4]">
            {eyebrow}
          </div>
          <h1 className="text-[30px] font-bold leading-none tracking-[-0.03em] md:text-[52px] md:tracking-[-0.035em]">
            Daily Picks
          </h1>
          <p className="text-[15px] leading-relaxed text-muted max-md:hidden">
            {league === "nba"
              ? `Props whose combined probability is ${floor}% or more.`
              : `Props whose historical hit rate is ${floor}% or more, ranked by that rate.`}
          </p>
          <p className="text-[13px] text-muted md:hidden">
            {pickCount} props at {floor}%+ · {strongCount} strong
          </p>
        </div>
        <div className="flex gap-2.5 max-md:hidden">
          <div className="rounded-2xl border border-line bg-white px-4 py-2.5">
            <div className="font-mono text-[22px] font-bold leading-none">{pickCount}</div>
            <div className="mt-1 text-xs text-muted">picks</div>
          </div>
          <div className="rounded-2xl bg-accent px-4 py-2.5 text-brand-ink">
            <div className="font-mono text-[22px] font-bold leading-none">{strongCount}</div>
            <div className="mt-1 text-xs">strong</div>
          </div>
        </div>
      </div>

      <PicksDateRow
        selectedDate={selectedDate}
        onDateChange={onDateChange}
        analyzedAt={analyzedAt}
        isStale={isStale}
        onReanalyze={onReanalyze}
        isReanalyzing={isReanalyzing}
        onReviewBoard={onReviewBoard}
      />

      <div className="flex flex-col gap-3 md:flex-row md:flex-wrap md:items-center md:gap-x-6">
        <div
          role="group"
          aria-label="Confidence"
          className="-mx-4 flex gap-1.5 overflow-x-auto px-4 md:mx-0 md:flex-wrap md:overflow-visible md:px-0"
        >
          {CONFIDENCE_FILTERS.map((filter) => (
            <BoardChip
              key={filter.id}
              active={confidence === filter.id}
              onClick={() => setConfidence(filter.id)}
            >
              {filter.label}
            </BoardChip>
          ))}
        </div>
        <div
          role="group"
          aria-label="Market"
          className="-mx-4 flex gap-1.5 overflow-x-auto px-4 md:mx-0 md:flex-wrap md:overflow-visible md:px-0"
        >
          {markets.map((label) => (
            <BoardChip key={label} mono active={market === label} onClick={() => setMarket(label)}>
              {label}
            </BoardChip>
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
          <div className="-mx-4 flex gap-2 overflow-x-auto px-4 md:mx-0 md:flex-wrap md:overflow-visible md:px-0">
            {teams.map((team) => {
              const selected = selectedTeams.has(team);
              return (
                <button
                  key={team}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => onToggleTeam(team)}
                  className={cn(
                    "min-h-10 shrink-0 rounded-full border px-3 py-2 font-mono text-xs font-bold",
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
            const inSlip = storedDirection != null;
            const sameSide = inSlip && storedDirection === pick.direction;
            const caption = slipCaption?.(pick) ?? null;
            const dim = row.dimmed && "opacity-60";
            const article = (
              <article
                className={cn(
                  "relative grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-2.5 rounded-[18px] border bg-white p-3.5 transition-colors hover:border-brand-soft",
                  "md:grid-cols-[22px_40px_minmax(0,1.1fr)_minmax(0,1fr)_150px_auto] md:items-center md:gap-x-4 md:gap-y-2 md:rounded-[20px] md:px-[18px] md:py-4",
                  sameSide ? "border-brand" : "border-line",
                )}
              >
                <div data-testid="pick-player" className="contents">
                  <div className={cn("hidden font-mono text-[13px] font-bold text-muted md:col-start-1 md:row-span-2 md:row-start-1 md:block", dim)}>
                    {row.rank}
                  </div>
                  <div
                    className={cn(
                      "hidden h-10 w-10 items-center justify-center rounded-full border border-line font-mono text-[11px] font-bold text-brand md:col-start-2 md:row-span-2 md:row-start-1 md:flex",
                      dim,
                    )}
                  >
                    {row.team || "—"}
                  </div>
                  <div className={cn("col-start-1 row-start-1 flex min-w-0 flex-col md:col-start-3 md:row-span-2 md:row-start-1", dim)}>
                    <div className="order-first truncate text-xs text-muted md:order-last md:mt-0.5 md:text-[13px]">
                      <span className="md:hidden">{row.rank} · </span>
                      {row.matchup}
                    </div>
                    <Link
                      href={row.href}
                      className="mt-0.5 truncate text-base font-bold after:absolute after:inset-0 after:rounded-[18px] hover:text-brand focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-brand md:mt-0 md:after:rounded-[20px]"
                    >
                      {row.player}
                    </Link>
                  </div>
                </div>

                <div data-testid="pick-prop" className="contents">
                  <div
                    className={cn(
                      "col-start-1 row-start-2 text-sm font-semibold text-brand md:col-start-4 md:row-start-1 md:self-end md:text-[15px] md:font-bold md:text-ink",
                      dim,
                    )}
                  >
                    {row.propText}
                  </div>
                  <div className="col-start-1 row-start-3 flex min-w-0 flex-col gap-1.5 md:col-start-4 md:row-start-2 md:self-start">
                    {caption ? <p className="text-xs leading-5 text-muted">{caption}</p> : null}
                    <TagList
                      tags={row.tags}
                      pick={pick}
                      lineupFor={lineupFor}
                      showLineup={showLineup && !row.dimmed}
                      isLineupLoading={isLineupLoading}
                      isLineupError={isLineupError}
                    />
                  </div>
                </div>

                {row.dimmed ? null : (
                  <div
                    data-testid="pick-rate"
                    className="col-start-2 row-span-2 row-start-1 flex flex-col items-end gap-1 md:col-start-5 md:items-stretch md:gap-1.5"
                  >
                    <div className="flex flex-col items-end gap-1 md:flex-row md:items-baseline md:justify-between md:gap-2">
                      <div className="font-mono text-2xl font-bold leading-none text-brand">{row.probabilityText}</div>
                      {row.tierShort && row.tierName ? (
                        <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-bold", TIER_CLASS[row.tierName])}>
                          {row.tierShort}
                        </span>
                      ) : null}
                    </div>
                    <div className="hidden h-1.5 overflow-hidden rounded-full bg-[#EEEBF2] md:block">
                      <div className="h-full rounded-full bg-brand" style={{ width: `${row.barPercent}%` }} />
                    </div>
                  </div>
                )}

                <div className="relative z-10 col-start-2 row-start-3 flex justify-end self-center md:col-start-6 md:row-span-2 md:row-start-1">
                  {row.dimmed ? (
                    inSlip ? (
                      <button
                        type="button"
                        aria-label={`Remove ${pick.player_name}`}
                        onClick={() => onToggleSlip(pick)}
                        className="min-h-10 rounded-full border border-line bg-white px-4 text-[13px] font-bold text-ink md:min-h-11"
                      >
                        Remove
                      </button>
                    ) : null
                  ) : (
                    <button
                      type="button"
                      aria-label={sameSide ? "Added to Bet Slip" : "Add to Bet Slip"}
                      onClick={() => onToggleSlip(pick)}
                      className={cn(
                        "min-h-10 whitespace-nowrap rounded-full border px-3.5 text-[13px] font-bold md:min-h-11 md:px-4",
                        sameSide ? "border-accent bg-accent text-brand-ink" : "border-muted bg-white text-brand",
                      )}
                    >
                      {sameSide ? "✓ In slip" : "+ Slip"}
                    </button>
                  )}
                </div>
              </article>
            );
            if (row.dimmed) return <div key={row.key}>{article}</div>;
            return (
              <PickContextMenu key={row.key} pick={pick} league={league}>
                {article}
              </PickContextMenu>
            );
          })}
        </div>
      ) : null}

      <p className="text-[13px] leading-6 text-muted">
        The line is the most common line across books.{" "}
        {league === "nba"
          ? "The percent is the combined probability. Opponent rank appears only when the response includes it. Tap a pick to see every signal behind it."
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
  tags: PickTag[];
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
      {tags.map((tag) =>
        tag.injury ? (
          <InjuryStatusTag key={tag.text} tag={tag.injury} />
        ) : (
          <span
            key={tag.text}
            className="rounded-md bg-[#F1F0F3] px-2 py-0.5 text-[11px] font-semibold text-[#4A4458]"
          >
            {tag.text}
          </span>
        ),
      )}
    </div>
  );
}
