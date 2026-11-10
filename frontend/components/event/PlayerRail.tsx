"use client";

import { playerLastName } from "@/lib/today-board";
import type { EventPlayerRow } from "@/lib/event-page";
import { cn } from "@/lib/utils";

export function PlayerRail({
  rows,
  selected,
  onSelect,
  isLoading,
  isError,
  errorText,
  onRetry,
}: {
  rows: EventPlayerRow[];
  selected: string;
  onSelect: (name: string) => void;
  isLoading: boolean;
  isError: boolean;
  errorText: string | null;
  onRetry: () => void;
}) {
  return (
    <div data-testid="player-rail" className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between gap-3">
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
            return (
              <button
                key={row.name}
                type="button"
                aria-pressed={active}
                onClick={() => onSelect(row.name)}
                data-testid={`player-row-${row.name}`}
                className={cn(
                  "flex min-w-[118px] shrink-0 flex-col gap-1.5 rounded-2xl border px-3 py-2.5 text-left md:grid md:min-w-0 md:grid-cols-[minmax(0,1fr)_44px_76px] md:items-center md:gap-2.5 md:px-3.5 md:py-3",
                  active ? "border-brand bg-brand-tint" : "border-line bg-white",
                )}
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-bold text-ink">
                    <span className="md:hidden">{playerLastName(row.name)}</span>
                    <span className="hidden md:inline">{row.name}</span>
                  </span>
                  {row.team ? (
                    <span className="hidden text-xs text-muted md:block">{row.team}</span>
                  ) : null}
                </span>
                <span className="font-mono text-xs font-semibold text-muted md:text-right md:text-[13px]">
                  {row.lineText}
                </span>
                <span
                  className={cn(
                    "w-fit rounded-md px-1.5 py-0.5 font-mono text-[11px] font-bold md:w-full md:px-0 md:py-1.5 md:text-center md:text-xs",
                    row.hasLean ? "bg-[#E2E2E2] text-ink" : "bg-[#F3F1F6] text-muted",
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
