"use client";

import type { League } from "@/components/EventDetail";
import { cn } from "@/lib/utils";

export type LogRange = 5 | 10 | 20 | 0;
export type LogRole = "all" | "starter" | "bench";
export type MateMode = "all" | "with" | "without";

export const RANGE_OPTIONS: Record<League, ReadonlyArray<{ value: LogRange; label: string }>> = {
  nba: [
    { value: 5, label: "L5" },
    { value: 10, label: "L10" },
    { value: 20, label: "L20" },
    { value: 0, label: "All" },
  ],
  wnba: [
    { value: 10, label: "Last 10" },
    { value: 20, label: "Last 20" },
    { value: 0, label: "All" },
  ],
};

export interface FilterState {
  range: LogRange;
  onRange: (range: LogRange) => void;
  lineText: string | null;
  lineChanged: boolean;
  lineDisabled: boolean;
  onMinus: () => void;
  onPlus: () => void;
  onResetLine: () => void;
  role: LogRole;
  onRole: (role: LogRole) => void;
  opponent: string;
  opponents: string[];
  onOpponent: (opponent: string) => void;
  teammates: string[];
  selectedMates: string[];
  onToggleMate: (name: string) => void;
  mateMode: MateMode;
  onMateMode: (mode: MateMode) => void;
}

export function activeFilterCount(filters: Pick<FilterState, "role" | "opponent" | "selectedMates" | "mateMode">): number {
  return [
    filters.role !== "all",
    filters.opponent !== "",
    filters.selectedMates.length > 0 && filters.mateMode !== "all",
  ].filter(Boolean).length;
}

function FilterLabel({ children, className }: { children: string; className?: string }) {
  return <div className={cn("text-xs font-bold uppercase tracking-[0.08em] text-muted", className)}>{children}</div>;
}

function Segment<T extends string | number>({
  label,
  value,
  options,
  onChange,
  className,
  labelClassName,
}: {
  label: string;
  value: T;
  options: ReadonlyArray<{ value: T; label: string }>;
  onChange: (value: T) => void;
  className?: string;
  labelClassName?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)}>
      <FilterLabel className={labelClassName}>{label}</FilterLabel>
      <div className="flex gap-0.5 rounded-control bg-[#F3F1F6] p-[3px]">
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <button
              key={String(option.value)}
              type="button"
              aria-pressed={selected}
              onClick={() => onChange(option.value)}
              className={cn(
                "min-h-9 flex-1 rounded-mark-sm px-2 text-[13px] font-semibold",
                selected ? "bg-brand text-white" : "text-[#4A4458]",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function RangeControl({
  league,
  value,
  onChange,
  className,
  labelClassName,
}: {
  league: League;
  value: LogRange;
  onChange: (range: LogRange) => void;
  className?: string;
  labelClassName?: string;
}) {
  return (
    <Segment
      label="Range"
      value={value}
      onChange={onChange}
      options={RANGE_OPTIONS[league]}
      className={className}
      labelClassName={labelClassName}
    />
  );
}

export function LineControl({
  lineText,
  lineChanged,
  lineDisabled,
  onMinus,
  onPlus,
  onResetLine,
  inlineLabel = false,
  className,
}: Pick<FilterState, "lineText" | "lineChanged" | "lineDisabled" | "onMinus" | "onPlus" | "onResetLine"> & {
  inlineLabel?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)}>
      <FilterLabel className={cn(inlineLabel && "max-md:hidden")}>Line</FilterLabel>
      <div className="grid grid-cols-[42px_minmax(0,1fr)_42px] gap-0.5 rounded-control bg-[#F3F1F6] p-[3px]">
        <button
          type="button"
          aria-label="Lower line"
          disabled={lineDisabled}
          onClick={onMinus}
          className="min-h-9 rounded-mark-sm bg-white text-base font-semibold text-brand disabled:opacity-40"
        >
          −
        </button>
        <div className="flex flex-col items-center justify-center">
          {inlineLabel ? (
            <span aria-hidden="true" className="text-[10px] font-semibold uppercase text-muted md:hidden">
              Line
            </span>
          ) : null}
          <div className="flex items-center gap-2 font-mono text-sm font-bold">
            {lineText ?? "—"}
            {lineChanged ? (
              <button type="button" onClick={onResetLine} className="font-sans text-[11px] font-semibold text-brand underline">
                reset
              </button>
            ) : null}
          </div>
        </div>
        <button
          type="button"
          aria-label="Raise line"
          disabled={lineDisabled}
          onClick={onPlus}
          className="min-h-9 rounded-mark-sm bg-white text-base font-semibold text-brand disabled:opacity-40"
        >
          +
        </button>
      </div>
    </div>
  );
}

export function VenueControl({ className }: { className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)}>
      <FilterLabel>Venue</FilterLabel>
      <div className="flex gap-0.5 rounded-control bg-[#F3F1F6] p-[3px]" aria-disabled="true">
        {["All", "Home", "Away"].map((label) => (
          <button
            key={label}
            type="button"
            disabled
            aria-disabled="true"
            aria-pressed={label === "All"}
            className={cn(
              "min-h-9 flex-1 rounded-mark-sm text-[13px] font-semibold",
              label === "All" ? "bg-brand text-white" : "text-muted",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="text-xs text-muted">Home and away are not on the game log.</p>
    </div>
  );
}

export function RoleControl({
  value,
  onChange,
  className,
}: {
  value: LogRole;
  onChange: (role: LogRole) => void;
  className?: string;
}) {
  return (
    <Segment
      label="Role"
      value={value}
      onChange={onChange}
      className={className}
      options={[
        { value: "all", label: "All" },
        { value: "starter", label: "Starter" },
        { value: "bench", label: "Bench" },
      ]}
    />
  );
}

export function OpponentControl({
  value,
  options,
  onChange,
  className,
}: {
  value: string;
  options: string[];
  onChange: (opponent: string) => void;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)}>
      <FilterLabel>Opponent</FilterLabel>
      <select
        aria-label="Opponent"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-11 rounded-control bg-[#F3F1F6] px-3 text-sm font-semibold text-ink"
      >
        <option value="">All opponents</option>
        {options.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
    </div>
  );
}

export function TeammatesControl({
  teammates,
  selectedMates,
  onToggleMate,
  mateMode,
  onMateMode,
  className,
}: Pick<FilterState, "teammates" | "selectedMates" | "onToggleMate" | "mateMode" | "onMateMode"> & {
  className?: string;
}) {
  const addable = teammates.filter((name) => !selectedMates.includes(name));
  return (
    <div className={cn("flex flex-col gap-3 border-t border-[#EEEBF2] pt-4", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <FilterLabel>Teammates</FilterLabel>
        <p className="text-xs text-muted">Names only. Games missed are not on this response.</p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        {teammates.length === 0 ? (
          <p className="min-w-0 flex-[1_1_320px] text-sm text-muted">No teammates on this history response.</p>
        ) : (
          <div className="flex min-w-0 flex-[1_1_320px] flex-wrap items-center gap-1.5">
            <select
              aria-label="Add a teammate"
              value=""
              disabled={addable.length === 0}
              onChange={(event) => {
                if (event.target.value) onToggleMate(event.target.value);
              }}
              className="min-h-11 min-w-0 max-w-full rounded-control bg-[#F3F1F6] px-3 text-sm font-semibold text-ink disabled:text-muted"
            >
              <option value="">{addable.length === 0 ? "Every teammate added" : "Add a teammate"}</option>
              {addable.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            {selectedMates.map((name) => (
              <button
                key={name}
                type="button"
                aria-label={`Remove ${name}`}
                onClick={() => onToggleMate(name)}
                className="inline-flex min-h-[38px] items-center gap-1.5 rounded-full bg-brand pl-3 pr-2.5 text-[13px] font-semibold text-white"
              >
                {name}
                <span aria-hidden="true" className="text-base leading-none text-white/70">
                  ×
                </span>
              </button>
            ))}
          </div>
        )}
        <div className={cn("min-w-[240px] flex-[0_1_300px]", selectedMates.length === 0 && "pointer-events-none opacity-40")}>
          <Segment
            label="With teammates"
            value={mateMode}
            onChange={onMateMode}
            options={[
              { value: "all", label: "All" },
              { value: "with", label: "With" },
              { value: "without", label: "Without" },
            ]}
          />
        </div>
      </div>
    </div>
  );
}

export function MoreFilters(filters: FilterState) {
  return (
    <div data-testid="more-filters" className="flex flex-col gap-4">
      <VenueControl />
      <RoleControl value={filters.role} onChange={filters.onRole} />
      <OpponentControl value={filters.opponent} options={filters.opponents} onChange={filters.onOpponent} />
      <TeammatesControl {...filters} />
    </div>
  );
}

export function GameFilters({
  league,
  gameCount,
  ...filters
}: FilterState & { league: League; gameCount: number | null }) {
  return (
    <div data-testid="game-filters" className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-lg font-bold text-ink">Filter games</h3>
        <p className="text-[13px] text-muted">
          {gameCount == null ? "Line not posted" : `${gameCount} ${gameCount === 1 ? "game" : "games"}`}
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <RangeControl league={league} value={filters.range} onChange={filters.onRange} />
        <LineControl {...filters} />
        <VenueControl />
        <RoleControl value={filters.role} onChange={filters.onRole} />
      </div>
      <OpponentControl value={filters.opponent} options={filters.opponents} onChange={filters.onOpponent} />
      <TeammatesControl {...filters} />
    </div>
  );
}
