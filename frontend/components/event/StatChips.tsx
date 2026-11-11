"use client";

import { MARKETS, type MarketKey } from "@/components/MarketSelect";
import type { LeagueSegment } from "@/lib/event-detail-link";
import { cn } from "@/lib/utils";

const ORDER: MarketKey[] = [
  "player_points",
  "player_rebounds",
  "player_assists",
  "player_threes",
  "player_points_rebounds_assists",
  "player_steals",
  "player_frees_made",
  "player_field_goals",
  "player_rebounds_assists",
  "player_points_rebounds",
  "player_points_assists",
  "player_double_double",
];

export function StatChips({
  value,
  onChange,
  disabled = false,
  league = "wnba",
}: {
  value: MarketKey;
  onChange: (market: MarketKey) => void;
  disabled?: boolean;
  league?: LeagueSegment;
}) {
  const nba = league === "nba";
  const chips = ORDER.map((key) => MARKETS.find((market) => market.key === key)).filter(
    (market): market is (typeof MARKETS)[number] => Boolean(market),
  );
  return (
    <div data-testid="stat-chips" className="flex flex-col gap-2.5">
      <div className={cn("text-xs font-bold uppercase tracking-[0.08em] text-muted", nba && "max-md:hidden")}>
        1 · Stat
      </div>
      <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 md:grid md:grid-cols-5 md:overflow-visible">
        {chips.map((market) => {
          const selected = market.key === value;
          return (
            <button
              key={market.key}
              type="button"
              aria-pressed={selected}
              disabled={disabled}
              onClick={() => onChange(market.key)}
              className={cn(
                "min-h-10 shrink-0 border px-3.5 font-mono text-[13px] font-bold md:px-0",
                nba ? "rounded-full md:rounded-control" : "rounded-xl",
                selected
                  ? "border-brand bg-brand text-white"
                  : nba
                    ? "border-line-strong bg-white text-ink"
                    : "border-line bg-white text-ink",
                disabled && "cursor-not-allowed opacity-50",
              )}
            >
              {market.shortName}
            </button>
          );
        })}
      </div>
    </div>
  );
}
