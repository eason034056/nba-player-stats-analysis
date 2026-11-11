"use client";

import type { LeagueSegment } from "@/lib/event-detail-link";
import { joinMeta, type EventPlayerRow } from "@/lib/event-page";
import { playerLastName } from "@/lib/today-board";
import { cn } from "@/lib/utils";

const TIER_PILL = {
  strong: "bg-accent text-accent-ink",
  playable: "bg-brand text-white",
  lean: "bg-lean text-brand",
} as const;

export function PlayerRail({
  rows,
  selected,
  onSelect,
  isLoading,
  isError,
  errorText,
  onRetry,
  league = "wnba",
}: {
  rows: EventPlayerRow[];
  selected: string;
  onSelect: (name: string) => void;
  isLoading: boolean;
  isError: boolean;
  errorText: string | null;
  onRetry: () => void;
  league?: LeagueSegment;
}) {
  const nba = league === "nba";
  return (
    <div data-testid="player-rail" className="flex flex-col gap-2.5">
      <div className={cn("flex items-center justify-between gap-3", nba && "max-md:hidden")}>
        <div className="text-xs font-bold uppercase tracking-[0.08em] text-muted">2 · Player</div>
        <div className="text-xs text-muted">Line · our lean</div>
      </div>
      {isLoading ? (
        <p className="text-sm text-muted">Loading players.</p>
      ) : isError ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-ink">{errorText ?? "The player list failed."}</p>
          <button type="button" onClick={onRetry} className="text-sm font-semibold text-brand underline">
            Retry
          </button>
        </div>
      ) : rows.length === 0 ? (
        <p className="rounded-2xl bg-[#F7F6F9] px-4 py-6 text-center text-sm text-muted">
          No players are posted for this stat.
        </p>
      ) : (
        <div className="flex gap-2 overflow-x-auto md:flex-col md:overflow-visible">
          {rows.map((row) => {
            const active = row.name === selected;
            const meta = joinMeta(row.position, row.team, " · ");
            const tierName = row.tier && row.tier.name !== "pass" ? row.tier.name : null;
            const pill = nba
              ? tierName
                ? TIER_PILL[tierName]
                : row.hasLean
                  ? "bg-pass text-ink-2"
                  : "bg-seg text-muted"
              : row.hasLean
                ? "bg-[#E2E2E2] text-ink"
                : "bg-[#F3F1F6] text-muted";
            return (
              <button
                key={row.name}
                type="button"
                aria-pressed={active}
                onClick={() => onSelect(row.name)}
                data-testid={`player-row-${row.name}`}
                className={cn(
                  "flex min-w-[118px] shrink-0 flex-col gap-1.5 rounded-2xl border px-3 py-2.5 text-left md:grid md:min-w-0 md:grid-cols-[minmax(0,1fr)_44px_148px] md:items-center md:gap-2.5 md:px-3.5 md:py-3",
                  nba && active && "max-md:order-first",
                  active
                    ? "border-brand bg-brand-tint"
                    : nba
                      ? "border-divider bg-white"
                      : "border-line bg-white",
                )}
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-bold text-ink">
                    <span className="md:hidden">{playerLastName(row.name)}</span>
                    <span className="hidden md:inline">{row.name}</span>
                  </span>
                  {meta ? <span className="hidden text-xs text-muted md:block">{meta}</span> : null}
                </span>
                <span className="font-mono text-xs font-semibold text-muted md:text-right md:text-[13px]">
                  {row.lineText}
                </span>
                <span
                  className={cn(
                    "w-fit whitespace-nowrap rounded-[6px] px-1.5 py-0.5 font-mono text-[11px] font-bold md:w-full md:rounded-lg md:px-1 md:py-1.5 md:text-center md:text-xs",
                    pill,
                  )}
                >
                  {row.leanText}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
