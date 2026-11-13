"use client";

import { addDays, format, subDays } from "date-fns";
import { enUS } from "date-fns/locale";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { BoardChip } from "@/components/picks/BoardChip";
import { cn, isToday, isTomorrow } from "@/lib/utils";

const isoDate = (date: Date) => format(date, "yyyy-MM-dd");

const STEP_BUTTON =
  "flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-full border border-muted bg-white text-ink";
const ACTION_BUTTON = "min-h-[34px] whitespace-nowrap rounded-full px-3.5 text-[13px] font-semibold disabled:opacity-50";

export function PicksDateRow({
  selectedDate,
  onDateChange,
  analyzedAt,
  isStale,
  onReanalyze,
  isReanalyzing,
  onReviewBoard,
}: {
  selectedDate: string;
  onDateChange: (date: string) => void;
  analyzedAt?: string | null;
  isStale: boolean;
  onReanalyze: () => void;
  isReanalyzing: boolean;
  onReviewBoard?: () => void;
}) {
  const current = new Date(`${selectedDate}T00:00:00`);
  return (
    <div className="flex flex-col gap-2.5 md:flex-row md:items-center md:justify-between md:gap-4">
      <div
        role="group"
        aria-label="Board date"
        className="-mx-4 flex items-center gap-1.5 overflow-x-auto px-4 [scrollbar-width:none] md:mx-0 md:px-0"
      >
        <button
          type="button"
          aria-label="Previous day"
          onClick={() => onDateChange(isoDate(subDays(current, 1)))}
          className={STEP_BUTTON}
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <label className="relative flex min-h-[38px] shrink-0 cursor-pointer items-center rounded-full border border-brand bg-brand-tint px-3.5 font-mono text-xs font-bold text-brand">
          {format(current, "MMM d · EEE", { locale: enUS })}
          <input
            type="date"
            aria-label="Pick a date"
            value={selectedDate}
            onChange={(event) => event.target.value && onDateChange(event.target.value)}
            className="absolute inset-0 cursor-pointer opacity-0"
          />
        </label>
        <button
          type="button"
          aria-label="Next day"
          onClick={() => onDateChange(isoDate(addDays(current, 1)))}
          className={STEP_BUTTON}
        >
          <ChevronRight className="h-4 w-4" />
        </button>
        <BoardChip active={isToday(selectedDate)} onClick={() => onDateChange(isoDate(new Date()))}>
          Today
        </BoardChip>
        <BoardChip active={isTomorrow(selectedDate)} onClick={() => onDateChange(isoDate(addDays(new Date(), 1)))}>
          Tomorrow
        </BoardChip>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
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
          className={cn(ACTION_BUTTON, "border border-muted bg-white text-ink")}
        >
          {isReanalyzing ? "Analyzing..." : "Re-analyze"}
        </button>
        {onReviewBoard ? (
          <button type="button" onClick={onReviewBoard} className={cn(ACTION_BUTTON, "bg-brand-tint text-brand")}>
            Review board
          </button>
        ) : null}
      </div>
    </div>
  );
}
