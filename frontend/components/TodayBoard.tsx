"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { useAgentWidget } from "@/contexts/AgentWidgetContext";
import {
  getDailyPicks,
  getEvents,
  getWNBAEvents,
  getWnbaDailyPicks,
} from "@/lib/api";
import type { LeagueSegment } from "@/lib/event-detail-link";
import {
  slateEyebrow,
  todayGames,
  todayReads,
  type TodayGameCard,
  type TodayReadCard,
} from "@/lib/today-board";
import { getTodayString } from "@/lib/utils";
import { cn } from "@/lib/utils";

const TIER_CLASS = {
  strong: "bg-accent text-brand-ink",
  playable: "bg-brand text-white",
  lean: "bg-lean text-brand",
  pass: "bg-pass text-ink-2",
} as const;

function errorText(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "The request failed.";
}

function ReadFace({
  read,
  tone,
}: {
  read: TodayReadCard;
  tone: "overlay" | "flat";
}) {
  return (
    <Link
      href={read.href}
      className={cn(
        "flex flex-col gap-3.5 rounded-card text-white",
        tone === "overlay"
          ? "border border-white/[0.16] bg-white/[0.08] p-[18px] hover:bg-white/[0.14]"
          : "bg-brand p-4",
      )}
    >
      <div className="flex items-center justify-between gap-2.5">
        <span className="font-mono text-[11px] font-bold text-accent">#{read.rank}</span>
        {read.tier ? (
          <span
            className={cn(
              "rounded-full px-[9px] py-1 text-[11px] font-bold",
              TIER_CLASS[read.tier.name],
            )}
          >
            {read.tier.label}
          </span>
        ) : null}
      </div>
      <div>
        <div className="text-[17px] font-bold tracking-[-0.01em]">{read.player}</div>
        <div className={cn("mt-0.5 text-gray-light", tone === "flat" ? "text-xs" : "text-[13px]")}>
          {read.matchup}
        </div>
      </div>
      <div className="flex items-end justify-between gap-2.5">
        <div className="text-[15px] font-semibold">{read.propText}</div>
        <div className="font-mono text-prob font-bold text-accent">
          {read.probabilityText}
        </div>
      </div>
    </Link>
  );
}

function GameTopRead({ game }: { game: TodayGameCard }) {
  return (
    <>
      <div className="min-w-0">
        <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
          Top read
        </div>
        <div className="mt-1 text-sm font-semibold text-ink">
          {game.topText ?? "No read on this game"}
        </div>
      </div>
      {game.showProbability && game.topProbabilityText ? (
        <div
          className={cn(
            "shrink-0 rounded-mark px-2.5 py-1.5 font-mono text-sm font-bold",
            game.tier ? TIER_CLASS[game.tier.name] : "bg-pass text-ink-2",
          )}
        >
          {game.topProbabilityText}
        </div>
      ) : null}
    </>
  );
}

function WebBoard({
  eyebrow,
  reads,
  games,
  picksHref,
  picksCount,
  picksLabel,
  blurb,
  onAsk,
}: {
  eyebrow: string;
  reads: TodayReadCard[];
  games: TodayGameCard[];
  picksHref: string;
  picksCount: number | null | undefined;
  picksLabel: string | null;
  blurb: string;
  onAsk: () => void;
}) {
  const countText =
    picksCount == null ? "All picks →" : `All ${picksCount} picks →`;
  return (
    <div data-testid="today-web" className="hidden flex-col gap-[clamp(20px,3cqi,32px)] md:flex">
      <section className="flex flex-col gap-7 rounded-hero bg-brand p-[clamp(22px,4cqi,44px)] text-white">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div className="flex max-w-[620px] flex-col gap-3">
            <div
              data-testid="today-hero-eyebrow"
              className="font-mono text-[12px] font-semibold uppercase leading-[1.2] tracking-[0.12em] text-accent"
            >
              {eyebrow}
            </div>
            <h1 className="font-bold text-hero text-white">
              Tonight&apos;s best reads
            </h1>
            <p className="text-[17px] leading-[1.55] text-brand-mist">
              {blurb}
            </p>
          </div>
          <div className="flex flex-wrap gap-2.5">
            <Link
              href={picksHref}
              className="inline-flex min-h-11 items-center rounded-full bg-accent px-5 text-sm font-bold text-brand-ink"
            >
              {countText}
            </Link>
            <button
              type="button"
              onClick={onAsk}
              className="inline-flex min-h-11 items-center rounded-full border border-white/40 px-5 text-sm font-semibold text-white"
            >
              Ask the agent
            </button>
          </div>
        </div>
        {picksLabel && (
          <p className="text-sm text-brand-mist">{picksLabel}</p>
        )}
        {reads.length > 0 ? (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,260px),1fr))] gap-3">
            {reads.map((read) => (
              <ReadFace key={read.key} read={read} tone="overlay" />
            ))}
          </div>
        ) : (
          !picksLabel && (
            <p className="rounded-card border border-white/[0.16] bg-white/[0.08] px-5 py-6 text-sm text-brand-mist">
              No reads on tonight&apos;s board.
            </p>
          )
        )}
      </section>
      <GamesBlock games={games} hint="Tap a game to check any player prop" />
    </div>
  );
}

function MobileBoard({
  eyebrow,
  reads,
  games,
  picksHref,
  picksCount,
  picksLabel,
}: {
  eyebrow: string;
  reads: TodayReadCard[];
  games: TodayGameCard[];
  picksHref: string;
  picksCount: number | null | undefined;
  picksLabel: string | null;
}) {
  const countText =
    picksCount == null ? "See all picks →" : `See all ${picksCount} picks →`;
  return (
    <div data-testid="today-mobile" className="flex flex-col gap-6 md:hidden">
      <section className="flex flex-col gap-3.5">
        <div className="flex flex-col gap-1.5">
          <div className="font-mono text-eyebrow-mobile font-semibold uppercase text-eyebrow">
            {eyebrow}
          </div>
          <h1 className="font-bold text-hero-mobile text-ink">
            Tonight&apos;s best reads
          </h1>
        </div>
        {picksLabel && <p className="text-sm text-muted">{picksLabel}</p>}
        {reads.length > 0 ? (
          <div className="today-snap">
            {reads.map((read) => (
              <ReadFace key={read.key} read={read} tone="flat" />
            ))}
          </div>
        ) : (
          !picksLabel && (
            <p className="rounded-[20px] border border-line bg-white px-4 py-5 text-sm text-muted">
              No reads on tonight&apos;s board.
            </p>
          )
        )}
        <Link
          href={picksHref}
          className="inline-flex min-h-12 items-center justify-center rounded-md border border-line-strong bg-white text-sm font-bold text-brand"
        >
          {countText}
        </Link>
      </section>
      <GamesBlock games={games} stacked />
    </div>
  );
}

function GamesBlock({
  games,
  hint,
  stacked = false,
}: {
  games: TodayGameCard[];
  hint?: string;
  stacked?: boolean;
}) {
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className={cn("font-bold tracking-[-0.02em] text-ink", stacked ? "text-xl" : "text-2xl")}>
          Games
        </h2>
        {hint && <p className="text-[13px] text-muted">{hint}</p>}
      </div>
      {games.length === 0 ? (
        <p className="rounded-[22px] border border-line bg-white px-5 py-8 text-sm text-muted">
          No games on this date.
        </p>
      ) : stacked ? (
        <div className="overflow-hidden rounded-card border border-line bg-list-gap">
          {games.map((game) => (
            <Link
              key={game.eventId}
              href={game.href}
              className="flex min-h-16 items-center gap-3 border-b border-list-gap bg-white py-3.5 pl-4 pr-3.5 last:border-b-0"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="w-9 font-mono text-xs font-bold text-brand">{game.awayAbbr}</span>
                  <span className="truncate text-[15px] font-bold">{game.awayName}</span>
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <span className="w-9 font-mono text-xs font-bold text-brand">{game.homeAbbr}</span>
                  <span className="truncate text-[15px] font-bold">{game.homeName}</span>
                </div>
                <div className="mt-1 truncate text-xs text-muted">
                  {game.topText ? `Top read · ${game.topText}` : "Top read · No read on this game"}
                </div>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-2">
                {game.time && (
                  <div className="font-mono text-xs font-semibold text-muted">{game.time}</div>
                )}
                {game.showProbability && game.topProbabilityText ? (
                  <div
                    className={cn(
                      "rounded-mark-sm px-2 py-1 font-mono text-[13px] font-bold",
                      game.tier ? TIER_CLASS[game.tier.name] : "bg-pass text-ink-2",
                    )}
                  >
                    {game.topProbabilityText}
                  </div>
                ) : null}
              </div>
              <span className="text-xl text-muted" aria-hidden>
                ›
              </span>
            </Link>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,330px),1fr))] gap-3.5">
          {games.map((game) => (
            <Link
              key={game.eventId}
              href={game.href}
              className="flex flex-col gap-[18px] rounded-game border border-line bg-white p-5 hover:border-brand-soft"
            >
              <div className="flex items-center justify-between gap-3">
                <TeamSide abbr={game.awayAbbr} name={game.awayName} role="Away" />
                {game.time && (
                  <div className="rounded-full bg-seg px-2.5 py-1.5 font-mono text-xs font-semibold text-muted">
                    {game.time}
                  </div>
                )}
                <TeamSide abbr={game.homeAbbr} name={game.homeName} role="Home" align="end" />
              </div>
              <div className="flex items-center justify-between gap-3 border-t border-divider pt-3.5">
                <GameTopRead game={game} />
              </div>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}

function TeamSide({
  abbr,
  name,
  role,
  align = "start",
}: {
  abbr: string;
  name: string;
  role: string;
  align?: "start" | "end";
}) {
  const text = (
    <div className={cn("min-w-0", align === "end" && "text-right")}>
      <div className="truncate text-[15px] font-bold text-ink">{name}</div>
      <div className="text-xs text-muted">{role}</div>
    </div>
  );
  const badge = (
    <div className="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-full border border-line font-mono text-xs font-bold text-brand">
      {abbr}
    </div>
  );
  return (
    <div
      className={cn(
        "flex min-w-0 flex-1 items-center gap-2.5",
        align === "end" && "justify-end",
      )}
    >
      {align === "end" ? (
        <>
          {text}
          {badge}
        </>
      ) : (
        <>
          {badge}
          {text}
        </>
      )}
    </div>
  );
}

export function TodayBoard({ league }: { league: LeagueSegment }) {
  const todayString = getTodayString();
  const [selectedDate, setSelectedDate] = useState(todayString);
  const [initialDate, setInitialDate] = useState(todayString);

  const checkAndUpdateDate = useCallback(() => {
    const currentToday = getTodayString();
    if (currentToday !== initialDate) {
      if (selectedDate === initialDate) setSelectedDate(currentToday);
      setInitialDate(currentToday);
    }
  }, [initialDate, selectedDate]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") checkAndUpdateDate();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", checkAndUpdateDate);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", checkAndUpdateDate);
    };
  }, [checkAndUpdateDate]);

  const eventsQuery = useQuery({
    queryKey: [league === "wnba" ? "wnba-events" : "events", selectedDate],
    queryFn: () =>
      league === "wnba" ? getWNBAEvents(selectedDate) : getEvents(selectedDate),
    staleTime: 60 * 1000,
  });

  const picksQuery = useQuery({
    queryKey: [
      league === "wnba" ? "wnba-daily-picks" : "daily-picks",
      selectedDate,
    ],
    queryFn: () =>
      league === "wnba"
        ? getWnbaDailyPicks({ date: selectedDate })
        : getDailyPicks({ date: selectedDate }),
    staleTime: 5 * 60 * 1000,
  });

  const { openWidget } = useAgentWidget();

  if (eventsQuery.isLoading) {
    return (
      <div data-testid="today-loading" aria-busy="true" className="page-frame">
        <div className="page-wrap flex flex-col gap-4">
          <div className="skeleton h-8 w-40" />
          <div className="skeleton h-48 w-full rounded-hero" />
          <p className="text-sm text-muted">Loading tonight&apos;s board</p>
        </div>
      </div>
    );
  }

  if (eventsQuery.isError) {
    return (
      <div role="alert" className="page-frame">
        <div className="page-wrap">
          <h1 className="text-3xl font-bold tracking-[-0.03em] text-ink">
            Tonight&apos;s best reads
          </h1>
          <p className="mt-3 text-base text-ink">Could not load games.</p>
          <p className="mt-1 text-sm text-muted">{errorText(eventsQuery.error)}</p>
          <button
            type="button"
            onClick={() => eventsQuery.refetch()}
            className="mt-4 inline-flex min-h-11 items-center rounded-full bg-brand px-5 text-sm font-bold text-white"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const events = eventsQuery.data?.events ?? [];
  const slateDate = eventsQuery.data?.date || selectedDate;
  const picks = picksQuery.data?.picks ?? [];
  const reads = picksQuery.isSuccess ? todayReads(picks, league, slateDate, 3, events) : [];
  const games = todayGames(
    events,
    picksQuery.isSuccess ? picks : [],
    league,
    slateDate,
  );
  const picksHref = league === "wnba" ? "/wnba/picks" : "/picks";
  const picksCount = picksQuery.isSuccess ? picksQuery.data.total_picks : null;
  const picksLabel = picksQuery.isLoading
    ? "Loading reads"
    : picksQuery.isError
      ? `Reads unavailable. ${errorText(picksQuery.error)}`
      : null;

  const boardProps = {
    eyebrow: slateEyebrow(slateDate, events.length),
    reads,
    games: games.map((game) => {
      if (game.topSource === "event") return game;
      if (picksQuery.isLoading) {
        return { ...game, topText: "Loading the top read", topProbabilityText: null, showProbability: false, tier: null };
      }
      if (picksQuery.isError) {
        return { ...game, topText: "Top read unavailable", topProbabilityText: null, showProbability: false, tier: null };
      }
      return game;
    }),
    picksHref,
    picksCount,
    picksLabel,
    blurb:
      league === "nba"
        ? "Each prop gets one probability, built from market prices, recent form, projection and matchup. Start with the strongest calls, or open any game."
        : "Each card is a historical hit rate from tonight's board. Start with the strongest calls, or open any game.",
  };

  return (
    <div className="page-frame">
      <div className="page-wrap flex flex-col">
        <WebBoard {...boardProps} onAsk={openWidget} />
        <MobileBoard
          eyebrow={boardProps.eyebrow}
          reads={boardProps.reads}
          games={boardProps.games}
          picksHref={boardProps.picksHref}
          picksCount={boardProps.picksCount}
          picksLabel={boardProps.picksLabel}
        />
      </div>
    </div>
  );
}
