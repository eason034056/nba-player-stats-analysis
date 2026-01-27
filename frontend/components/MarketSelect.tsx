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
    <div>
      {/* Label */}
      <label className="block text-sm font-bold text-dark mb-3">
        <Activity className="inline w-4 h-4 mr-1.5" />
        Stat Type
      </label>

      {/* Market selection grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {MARKETS.map((market) => {
          const Icon = market.icon;
          const isSelected = value === market.key;

          return (
            <button
              key={market.key}
              type="button"
              onClick={() => !disabled && onChange(market.key)}
              disabled={disabled}
              className={cn(
                "relative flex flex-col items-center justify-center",
                "p-4 rounded-lg border-2 transition-all duration-150",
                "focus:outline-none",
                isSelected
                  ? "border-red bg-red text-white"
                  : "border-dark/20 bg-white text-dark hover:border-dark",
                disabled && "opacity-50 cursor-not-allowed"
              )}
              title={market.description}
            >
              {/* Icon */}
              <Icon
                className={cn(
                  "w-6 h-6 mb-2",
                  isSelected ? "text-white" : "text-gray"
                )}
              />
              
              {/* Name */}
              <span className={cn(
                "text-sm font-bold",
                isSelected ? "text-white" : "text-dark"
              )}>
                {market.name}
              </span>

              {/* Short name */}
              <span className={cn(
                "text-xs mt-0.5",
                isSelected ? "text-white/70" : "text-gray"
              )}>
                {market.shortName}
              </span>

              {/* Selected indicator */}
              {isSelected && (
                <div className="absolute top-2 right-2 w-2 h-2 bg-white rounded-full" />
              )}
            </button>
          );
        })}
      </div>

      {/* Description */}
      <p className="mt-3 text-xs text-gray">
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
