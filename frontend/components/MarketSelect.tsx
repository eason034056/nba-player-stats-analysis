/**
 * MarketSelect.tsx - Market Type Selection Component (Minimal Design)
 * 
 * Design Philosophy:
 * - White cards with black borders
 * - Red/dark for selected state
 * - Clean typography
 */

"use client";

import { Activity, Target, Repeat2, Trophy } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Market type definitions
 */
export const MARKETS = [
  {
    key: "player_points",
    name: "Points",
    shortName: "Points",
    icon: Target,
    description: "Player points scored",
  },
  {
    key: "player_assists",
    name: "Assists",
    shortName: "Assists",
    icon: Activity,
    description: "Player assists",
  },
  {
    key: "player_rebounds",
    name: "Rebounds",
    shortName: "Rebounds",
    icon: Repeat2,
    description: "Player rebounds",
  },
  {
    key: "player_points_rebounds_assists",
    name: "Points+Rebounds+Assists",
    shortName: "PRA",
    icon: Trophy,
    description: "Sum of three stats",
  },
] as const;

export type MarketKey = (typeof MARKETS)[number]["key"];

interface MarketSelectProps {
  value: MarketKey;
  onChange: (value: MarketKey) => void;
  disabled?: boolean;
}

/**
 * MarketSelect Component
 */
export function MarketSelect({
  value,
  onChange,
  disabled = false,
}: MarketSelectProps) {
  return (
    <div className="space-y-4">
      {/* Label */}
      <label className="control-label">
        <Activity className="h-4 w-4 text-red" />
        Stat Type
      </label>

      {/* Market selection grid */}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {MARKETS.map((market) => {
          const Icon = market.icon;
          const isSelected = value === market.key;

          return (
            <button
              key={market.key}
              type="button"
              onClick={() => !disabled && onChange(market.key)}
              disabled={disabled}
              aria-pressed={isSelected}
              className={cn(
                isSelected ? "control-tile-active" : "control-tile",
                isSelected
                  ? "ring-1 ring-white/20"
                  : "hover:ring-1 hover:ring-white/10",
                disabled && "cursor-not-allowed opacity-50"
              )}
              title={market.description}
            >
              {/* Icon */}
              <Icon
                className={cn(
                  "mb-3 h-6 w-6",
                  isSelected ? "text-white" : "text-light"
                )}
              />

              {/* Name */}
              <span
                className={cn(
                  "text-sm font-semibold leading-tight md:text-base",
                  isSelected ? "text-white" : "text-dark",
                )}
              >
                {market.name}
              </span>

              {/* Short name */}
              <span
                className={cn(
                  "mt-1 text-[11px] uppercase tracking-[0.22em]",
                  isSelected ? "text-white/72" : "text-light",
                )}
              >
                {market.shortName}
              </span>

              {/* Selected indicator */}
              {isSelected && (
                <div className="absolute right-3 top-3 flex h-6 w-6 items-center justify-center rounded-full border border-white/22 bg-white/12">
                  <div className="h-2.5 w-2.5 rounded-full bg-white" />
                </div>
              )}
            </button>
          );
        })}
      </div>

      {/* Description */}
      <p className="control-hint">
        Select the player stat type to query
      </p>
    </div>
  );
}

/**
 * Get market display name
 */
export function getMarketDisplayName(key: string): string {
  const market = MARKETS.find((m) => m.key === key);
  return market?.name || key;
}
