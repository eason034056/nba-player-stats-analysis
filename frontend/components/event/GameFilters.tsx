"use client";

import { cn } from "@/lib/utils";

export type LogRange = 10 | 20 | 0;
export type LogRole = "all" | "starter" | "bench";
export type MateMode = "all" | "with" | "without";

function Segment<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: ReadonlyArray<{ value: T; label: string }>;
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="text-xs font-bold uppercase tracking-[0.08em] text-muted">{label}</div>
      <div className="flex gap-0.5 rounded-xl bg-[#F3F1F6] p-[3px]">
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <button
              key={String(option.value)}
              type="button"
              aria-pressed={selected}
              onClick={() => onChange(option.value)}
              className={cn(
                "min-h-9 flex-1 rounded-[9px] px-2 text-[13px] font-semibold",
                selected ? "bg-white text-brand" : "text-ink",
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

export function GameFilters({
  range,
  onRange,
  lineText,
  lineChanged,
  lineDisabled,
  onMinus,
  onPlus,
  onResetLine,
  role,
  onRole,
  opponent,
  opponents,
  onOpponent,
  teammates,
  selectedMates,
  onToggleMate,
  mateMode,
  onMateMode,
  gameCount,
}: {
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
  gameCount: number | null;
}) {
  return (
    <div data-testid="game-filters" className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-lg font-bold text-ink">Filter games</h3>
        <p className="text-[13px] text-muted">
          {gameCount == null ? "Line not posted" : `${gameCount} ${gameCount === 1 ? "game" : "games"}`}
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Segment
          label="Range"
          value={range}
          onChange={onRange}
          options={[
            { value: 10, label: "Last 10" },
            { value: 20, label: "Last 20" },
            { value: 0, label: "All" },
          ]}
        />
        <div className="flex min-w-0 flex-col gap-2">
          <div className="text-xs font-bold uppercase tracking-[0.08em] text-muted">Line</div>
          <div className="grid grid-cols-[42px_minmax(0,1fr)_42px] gap-0.5 rounded-xl bg-[#F3F1F6] p-[3px]">
            <button
              type="button"
              aria-label="Lower line"
              disabled={lineDisabled}
              onClick={onMinus}
              className="min-h-9 rounded-[9px] bg-white text-base font-semibold text-brand disabled:opacity-40"
            >
              −
            </button>
            <div className="flex items-center justify-center gap-2 font-mono text-sm font-bold">
              {lineText ?? "—"}
              {lineChanged ? (
                <button type="button" onClick={onResetLine} className="font-sans text-[11px] font-semibold text-brand underline">
                  reset
                </button>
              ) : null}
            </div>
            <button
              type="button"
              aria-label="Raise line"
              disabled={lineDisabled}
              onClick={onPlus}
              className="min-h-9 rounded-[9px] bg-white text-base font-semibold text-brand disabled:opacity-40"
            >
              +
            </button>
          </div>
        </div>
        <div className="flex min-w-0 flex-col gap-2">
          <div className="text-xs font-bold uppercase tracking-[0.08em] text-muted">Venue</div>
          <div className="flex gap-0.5 rounded-xl bg-[#F3F1F6] p-[3px]" aria-disabled="true">
            {["All", "Home", "Away"].map((label) => (
              <button
                key={label}
                type="button"
                disabled
                aria-disabled="true"
                aria-pressed={label === "All"}
                className={cn(
                  "min-h-9 flex-1 rounded-[9px] text-[13px] font-semibold",
                  label === "All" ? "bg-brand text-white" : "text-muted",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted">Home and away are not on the game log.</p>
        </div>
        <Segment
          label="Role"
          value={role}
          onChange={onRole}
          options={[
            { value: "all", label: "All" },
            { value: "starter", label: "Starter" },
            { value: "bench", label: "Bench" },
          ]}
        />
      </div>
      <div className="flex flex-col gap-2">
        <div className="text-xs font-bold uppercase tracking-[0.08em] text-muted">Opponent</div>
        <select
          aria-label="Opponent"
          value={opponent}
          onChange={(event) => onOpponent(event.target.value)}
          className="min-h-11 rounded-xl bg-[#F3F1F6] px-3 text-sm font-semibold text-ink"
        >
          <option value="">All opponents</option>
          {opponents.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-2 border-t border-[#EEEBF2] pt-4">
        <div className="flex items-baseline justify-between gap-3">
          <div className="text-xs font-bold uppercase tracking-[0.08em] text-muted">Teammates</div>
          <p className="text-xs text-muted">Names only. Games missed are not on this response.</p>
        </div>
        {teammates.length === 0 ? (
          <p className="text-sm text-muted">No teammates on this history response.</p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {teammates.map((name) => {
              const selected = selectedMates.includes(name);
              return (
                <button
                  key={name}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => onToggleMate(name)}
                  className={cn(
                    "min-h-[38px] rounded-full border px-3 text-[13px] font-semibold",
                    selected ? "border-brand bg-brand-tint text-brand" : "border-line bg-white text-ink",
                  )}
                >
                  {name}
                </button>
              );
            })}
          </div>
        )}
        <div className={cn(selectedMates.length === 0 && "pointer-events-none opacity-40")}>
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
