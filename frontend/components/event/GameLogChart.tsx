"use client";

import type { ChartBar, ChartModel } from "@/lib/event-page";
import { cn } from "@/lib/utils";

type GameResult = "over" | "under" | "push" | "none";

const RESULT_PILL: Record<GameResult, { label: string; className: string }> = {
  over: { label: "Over", className: "bg-brand text-white" },
  under: { label: "Under", className: "bg-[#C9B4EE] text-brand-ink" },
  push: { label: "Push", className: "bg-accent text-brand-ink" },
  none: { label: "No line", className: "bg-[#E2E2E2] text-[#4A4458]" },
};

function gameResult(bar: ChartBar, lineText: string | null): GameResult {
  if (bar.over === null) return "none";
  if (bar.over) return "over";
  return bar.value === Number(lineText) ? "push" : "under";
}

export function GameLogChart({
  model,
  note,
  selectedKey,
  onSelect,
  isLoading,
  isError,
  errorText,
  emptyMessage,
  heading = true,
}: {
  model: ChartModel | null;
  note: string;
  selectedKey: string | null;
  onSelect: (key: string) => void;
  isLoading: boolean;
  isError: boolean;
  errorText: string | null;
  emptyMessage: string | null;
  heading?: boolean;
}) {
  const selected = model?.bars.find((bar) => bar.key === selectedKey) ?? model?.bars.at(-1) ?? null;
  const pill = selected ? RESULT_PILL[gameResult(selected, model?.lineText ?? null)] : null;
  return (
    <div data-testid="game-log-chart" className="flex flex-col gap-4">
      {heading ? (
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-lg font-bold text-ink">Game log</h3>
          <p className="text-[13px] text-muted">{note}</p>
        </div>
      ) : null}
      {isLoading ? <p className="text-sm text-muted">Loading the game log.</p> : null}
      {isError ? <p className="text-sm font-semibold text-red">{errorText ?? "The game log failed."}</p> : null}
      {emptyMessage ? (
        <p className="rounded-[14px] bg-[#F7F6F9] px-4 py-9 text-center text-sm text-muted">{emptyMessage}</p>
      ) : null}
      {model && !model.empty ? (
        <>
          <div className="grid grid-cols-[34px_minmax(0,1fr)] gap-2">
            <div className="relative h-[220px]">
              {model.ticks.map((tick) => (
                <div
                  key={tick.pos}
                  className="absolute right-0 translate-y-1/2 font-mono text-[10px] font-semibold text-muted"
                  style={{ bottom: tick.pos }}
                >
                  {tick.label}
                </div>
              ))}
            </div>
            <div className="relative h-[220px] border-b border-[#D3CCDF]">
              {model.ticks.map((tick) => (
                <div
                  key={`grid-${tick.pos}`}
                  className="absolute left-0 right-0 border-t border-[#F1EEF4]"
                  style={{ bottom: tick.pos }}
                />
              ))}
              <div className="absolute inset-0 flex gap-1">
                {model.bars.map((bar) => {
                  const active = selected?.key === bar.key;
                  return (
                    <button
                      key={bar.key}
                      type="button"
                      onClick={() => onSelect(bar.key)}
                      aria-label={`${bar.date} ${bar.opponent} ${bar.valueText}`}
                      className="relative h-full min-w-0 flex-1"
                    >
                      <span
                        className={cn(
                          "absolute bottom-0 left-0 right-0 mx-auto max-w-[30px] rounded-t-[5px]",
                          bar.over === false ? "bg-[#C9B4EE]" : "bg-brand",
                          active && "ring-2 ring-accent",
                        )}
                        style={{ height: `${bar.heightPct}%` }}
                      />
                      <span
                        className="absolute left-0 right-0 text-center font-mono text-[11px] font-semibold text-ink"
                        style={{ bottom: `calc(${bar.heightPct}% + 4px)` }}
                      >
                        {bar.valueText}
                      </span>
                    </button>
                  );
                })}
              </div>
              {model.linePct != null && model.lineText ? (
                <>
                  <div
                    className="pointer-events-none absolute left-0 right-0 border-t-2 border-dashed border-[#B3A63A]"
                    style={{ bottom: `${model.linePct}%` }}
                  />
                  <div
                    className="absolute -left-9 w-9 translate-y-1/2 rounded bg-accent text-center font-mono text-[10px] font-bold text-brand-ink"
                    style={{ bottom: `${model.linePct}%` }}
                  >
                    {model.lineText}
                  </div>
                </>
              ) : null}
            </div>
            <div />
            <div className="flex gap-1">
              {model.bars.map((bar) => (
                <div
                  key={`${bar.key}-opp`}
                  className="min-w-0 flex-1 truncate text-center font-mono text-[10px] font-semibold text-muted"
                >
                  {bar.opponent}
                </div>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            {selected && pill ? (
              <div
                data-testid="selected-game"
                className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[14px] bg-[#F7F6F9] px-3.5 py-2.5 text-[13px]"
              >
                <span className="font-bold text-ink">
                  {selected.dateLabel}
                  {selected.opponent ? ` vs ${selected.opponent}` : ""}
                </span>
                <span className="font-mono text-[15px] font-bold text-ink">{selected.valueText}</span>
                <span className={cn("rounded-full px-2 py-[3px] text-[11px] font-bold", pill.className)}>
                  {pill.label}
                </span>
              </div>
            ) : null}
            <div className="flex flex-wrap gap-3.5 text-xs text-muted">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-[3px] bg-brand" /> Over
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-[3px] bg-[#C9B4EE]" /> Under
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="w-3.5 border-t-2 border-dashed border-[#B3A63A]" /> Line
              </span>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
