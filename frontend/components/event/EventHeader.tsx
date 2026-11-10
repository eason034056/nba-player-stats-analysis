"use client";

import type { LeagueSegment } from "@/lib/event-detail-link";
import type { LineupChipModel } from "@/lib/event-page";
import { cn } from "@/lib/utils";

const CHIP_CLASS: Record<LineupChipModel["tone"], string> = {
  confirmed: "bg-brand-tint text-brand",
  projected: "bg-yellow-light text-yellow-dark",
  partial: "bg-[#E3DAF3] text-brand",
  unavailable: "bg-[#E2E2E2] text-[#4A4458]",
  missing: "bg-[#E2E2E2] text-[#4A4458]",
};

export function EventHeader({
  awayName,
  homeName,
  awayAbbr,
  homeAbbr,
  when,
  chips,
  isLoading,
  isError,
  errorText,
  onBack,
  onRetry,
  league = "wnba",
  mobileWhen = null,
}: {
  awayName: string;
  homeName: string;
  awayAbbr: string;
  homeAbbr: string;
  when: string | null;
  chips: LineupChipModel[];
  isLoading: boolean;
  isError: boolean;
  errorText: string | null;
  onBack: () => void;
  onRetry: () => void;
  league?: LeagueSegment;
  mobileWhen?: string | null;
}) {
  const nba = league === "nba" && !isLoading && !isError;
  const matchup = `${awayName} @ ${homeName}`;
  return (
    <div className="flex flex-col gap-4">
      {nba ? (
        <div data-testid="event-mobile-header" className="flex items-center gap-3 md:hidden">
          <button
            type="button"
            onClick={onBack}
            aria-label="All games"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-line-strong bg-white text-lg text-ink"
          >
            ←
          </button>
          <div className="min-w-0">
            <h1 className="truncate text-[19px] font-bold leading-tight tracking-[-0.02em] text-ink">
              {matchup}
            </h1>
            <p className="truncate text-xs text-muted">{mobileWhen || when || "Start time unavailable"}</p>
          </div>
        </div>
      ) : null}
      <div className={cn("flex flex-col gap-4", nba && "hidden md:flex")}>
      <button
        type="button"
        onClick={onBack}
        className="self-start py-1.5 text-sm font-semibold text-muted hover:text-brand"
      >
        ← All games
      </button>
      <section
        data-testid="event-header"
        className="flex flex-wrap items-center justify-between gap-4 rounded-[24px] border border-line bg-white px-5 py-5 md:px-7"
      >
        {isLoading ? (
          <p className="text-sm text-muted">Loading this game.</p>
        ) : isError ? (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-sm font-semibold text-ink">{errorText ?? "This game could not be loaded."}</p>
            <button type="button" onClick={onRetry} className="text-sm font-semibold text-brand underline">
              Retry
            </button>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-3.5">
              <div className="flex">
                <div className="flex h-12 w-12 items-center justify-center rounded-full border-[3px] border-white bg-brand font-mono text-[13px] font-bold text-white">
                  {awayAbbr || "—"}
                </div>
                <div
                  className={cn(
                    "-ml-2.5 flex h-12 w-12 items-center justify-center rounded-full border-[3px] border-white font-mono text-[13px] font-bold text-white",
                    league === "nba" ? "bg-brand-soft" : "bg-brand",
                  )}
                >
                  {homeAbbr || "—"}
                </div>
              </div>
              <div>
                <h1
                  className={cn(
                    "font-bold leading-none tracking-[-0.03em] text-ink",
                    league === "nba" ? "text-[clamp(24px,3.6cqi,36px)]" : "text-2xl md:text-4xl",
                  )}
                >
                  {matchup}
                </h1>
                <p className="mt-1 text-sm text-muted">{when ?? "Start time unavailable"}</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {chips.map((chip) => (
                <span
                  key={chip.label}
                  data-testid={`lineup-chip-${chip.abbr || "team"}`}
                  className={cn(
                    "rounded-full px-3 py-1.5 text-xs font-semibold",
                    CHIP_CLASS[chip.tone],
                  )}
                >
                  {chip.label}
                </span>
              ))}
            </div>
          </>
        )}
      </section>
      </div>
    </div>
  );
}
