"use client";

import type { ComponentProps } from "react";

import { GameLogChart } from "@/components/event/GameLogChart";
import {
  LineControl,
  OpponentControl,
  RangeControl,
  RoleControl,
  TeammatesControl,
  VenueControl,
  type FilterState,
} from "@/components/event/GameFilters";
import type { GameLogTile, GameLogTileKey } from "@/lib/event-page";
import { cn } from "@/lib/utils";

const TILE_TONE: Record<GameLogTileKey, string> = {
  over: "bg-brand-tint text-brand",
  under: "bg-[#F3F1F6] text-[#5B3A99]",
  average: "bg-[#F7F6F9] text-ink",
  games: "bg-[#F7F6F9] text-ink",
};

export function NbaGameLog({
  filters,
  note,
  tiles,
  chart,
  activeFilters,
  onOpenFilters,
  onReset,
  className,
}: {
  filters: FilterState;
  note: string;
  tiles: GameLogTile[] | null;
  chart: Omit<ComponentProps<typeof GameLogChart>, "note" | "heading">;
  activeFilters: number;
  onOpenFilters: () => void;
  onReset: (() => void) | null;
  className?: string;
}) {
  return (
    <section
      data-testid="game-log"
      className={cn(
        "flex min-w-0 flex-col gap-3.5 rounded-[20px] border border-line bg-white p-4 md:gap-5 md:rounded-[24px] md:p-7",
        className,
      )}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2.5">
        <div className="flex flex-wrap items-baseline gap-2.5">
          <h3 className="text-[17px] font-bold text-ink md:text-lg">Game log</h3>
          <p className="text-xs text-muted md:text-[13px]">{note}</p>
        </div>
        {onReset ? (
          <button
            type="button"
            onClick={onReset}
            className="text-[13px] font-semibold text-brand underline max-md:hidden"
          >
            Reset filters
          </button>
        ) : null}
      </div>

      <div data-testid="game-filters" className="flex flex-col gap-3.5 md:gap-5">
        <div className="grid gap-3.5 md:grid-cols-3 md:gap-4">
          <RangeControl league="nba" value={filters.range} onChange={filters.onRange} labelClassName="max-md:hidden" />
          <div className="flex items-end gap-2 md:block">
            <LineControl {...filters} inlineLabel className="flex-1" />
            <button
              type="button"
              onClick={onOpenFilters}
              className={cn(
                "min-h-11 shrink-0 rounded-control border px-4 text-[13px] font-bold md:hidden",
                activeFilters > 0 ? "border-brand bg-brand text-white" : "border-line-strong bg-white text-ink",
              )}
            >
              {activeFilters > 0 ? `Filters · ${activeFilters}` : "Filters"}
            </button>
          </div>
          <VenueControl className="max-md:hidden" />
          <RoleControl value={filters.role} onChange={filters.onRole} className="max-md:hidden" />
          <OpponentControl
            value={filters.opponent}
            options={filters.opponents}
            onChange={filters.onOpponent}
            className="max-md:hidden"
          />
        </div>
        <TeammatesControl {...filters} className="max-md:hidden" />
      </div>

      {tiles ? (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4 md:gap-2.5">
          {tiles.map((tile) => (
            <div
              key={tile.key}
              data-testid={`log-tile-${tile.key}`}
              className={cn("flex flex-col gap-1 rounded-[14px] p-3 md:rounded-tile md:p-3.5", TILE_TONE[tile.key])}
            >
              <div className="text-[11px] font-semibold text-[#4A4458] md:text-xs">{tile.label}</div>
              <div className="font-mono text-[21px] font-bold leading-tight md:text-2xl">{tile.value}</div>
              {tile.sub ? <div className="text-[11px] text-muted md:text-xs">{tile.sub}</div> : null}
            </div>
          ))}
        </div>
      ) : null}

      <GameLogChart {...chart} note={note} heading={false} />
      {chart.model && !chart.model.empty ? (
        <p className="text-xs text-muted md:hidden">Tap a bar to see that game.</p>
      ) : null}
    </section>
  );
}
