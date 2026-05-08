/**
 * MarketSelect.tsx - Market Type Selection Component (12-tile grouped)
 *
 * SPO-20 Phase 3: 把 4 個 tiles 擴充成 12 個，分成三組（Single / Combo / Binary）。
 *
 * Design Philosophy:
 * - 直接垂直堆疊三組（不用 tabs），讓使用者一眼看到所有 12 個選項並做跨組比較
 *   （e.g. PTS vs PRA vs DD），同時保留 mobile 上的可讀性
 * - 每組頂部有 group header，內部仍用 grid 顯示 tiles
 * - Single (7) / Combo (4) 走 Over/Under threshold 流程
 * - Binary (1) DD 走 Yes/No 流程（無 O/U threshold）
 */

"use client";

import {
  Activity,
  Target,
  Repeat2,
  Trophy,
  Crosshair,
  Hand,
  HandMetal,
  CircleDot,
  Sparkles,
  Combine,
  Layers,
  Award,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Market type definitions
 *
 * `group` 由 SPO-20 引入，用來把 12 個 tiles 分成 Single / Combo / Binary。
 * 若 backend 之後再增加新 market，只需在這個 list 加一筆並指定 group。
 *
 * Binary markets (group="binary") MUST be dispatched on `marketKey` by
 * downstream components — they have NO `point` threshold. SPO-20 currently
 * only contains DD; do not blindly add Over/Under markets to this group.
 */
export const MARKETS = [
  // ===== Single (7) — Over/Under at threshold =====
  {
    key: "player_points",
    group: "single",
    name: "Points",
    shortName: "PTS",
    icon: Target,
    description: "Player points scored",
  },
  {
    key: "player_rebounds",
    group: "single",
    name: "Rebounds",
    shortName: "REB",
    icon: Repeat2,
    description: "Player rebounds",
  },
  {
    key: "player_assists",
    group: "single",
    name: "Assists",
    shortName: "AST",
    icon: Activity,
    description: "Player assists",
  },
  {
    key: "player_threes",
    group: "single",
    name: "3-Pointers Made",
    shortName: "3PM",
    icon: CircleDot,
    description: "Three-pointers made",
  },
  {
    key: "player_steals",
    group: "single",
    name: "Steals",
    shortName: "STL",
    icon: HandMetal,
    description: "Player steals",
  },
  {
    key: "player_frees_made",
    group: "single",
    name: "Free Throws Made",
    shortName: "FTM",
    icon: Hand,
    description: "Free throws made",
  },
  {
    key: "player_field_goals",
    group: "single",
    name: "Field Goals Made",
    shortName: "FGM",
    icon: Crosshair,
    description: "Field goals made (working hypothesis: FGM)",
  },
  // ===== Combo (4) — native single Over/Under (no client-side derive math) =====
  // ⚠ Backend returns these as native combo lines; do NOT compute them client-side.
  {
    key: "player_points_rebounds_assists",
    group: "combo",
    name: "Points+Rebounds+Assists",
    shortName: "PRA",
    icon: Trophy,
    description: "Sum of three stats",
  },
  {
    key: "player_rebounds_assists",
    group: "combo",
    name: "Rebounds+Assists",
    shortName: "R+A",
    icon: Combine,
    description: "Rebounds + Assists",
  },
  {
    key: "player_points_rebounds",
    group: "combo",
    name: "Points+Rebounds",
    shortName: "P+R",
    icon: Layers,
    description: "Points + Rebounds",
  },
  {
    key: "player_points_assists",
    group: "combo",
    name: "Points+Assists",
    shortName: "P+A",
    icon: Sparkles,
    description: "Points + Assists",
  },
  // ===== Binary (1) — Yes/No, no point threshold =====
  // ⚠ DD has no O/U threshold; downstream components MUST dispatch on `marketKey`.
  {
    key: "player_double_double",
    group: "binary",
    name: "Double Double",
    shortName: "DD",
    icon: Award,
    description: "Player records a double-double (Yes/No)",
  },
] as const;

export type MarketKey = (typeof MARKETS)[number]["key"];
export type MarketGroup = (typeof MARKETS)[number]["group"];

/**
 * Group display configuration
 *
 * 把 group key 對應成中英 header label。垂直堆疊版面下，這個 list 也決定渲染順序。
 */
const MARKET_GROUPS: ReadonlyArray<{
  key: MarketGroup;
  label: string;
  hint: string;
}> = [
  {
    key: "single",
    label: "Single Stats",
    hint: "Over / Under at a threshold",
  },
  {
    key: "combo",
    label: "Combo",
    hint: "Native combo line — no client-side math",
  },
  {
    key: "binary",
    label: "Binary",
    hint: "Yes / No outcome — no threshold",
  },
];

interface MarketSelectProps {
  value: MarketKey;
  onChange: (value: MarketKey) => void;
  disabled?: boolean;
}

/**
 * MarketSelect Component
 *
 * 渲染 12 個 tiles，垂直堆疊三組（Single / Combo / Binary）。
 * `aria-pressed` 保留以維持原 control-readability test 的契約。
 */
export function MarketSelect({
  value,
  onChange,
  disabled = false,
}: MarketSelectProps) {
  return (
    <div className="space-y-6">
      {/* Label */}
      <label className="control-label">
        <Activity className="h-4 w-4 text-red" />
        Stat Type
      </label>

      {MARKET_GROUPS.map((groupCfg) => {
        const groupMarkets = MARKETS.filter((m) => m.group === groupCfg.key);
        if (groupMarkets.length === 0) return null;

        return (
          <div
            key={groupCfg.key}
            data-market-group={groupCfg.key}
            className="space-y-3"
          >
            {/* Group header */}
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="text-xs font-bold uppercase tracking-[0.22em] text-light">
                {groupCfg.label}
              </h3>
              <span className="text-[11px] text-light">{groupCfg.hint}</span>
            </div>

            {/* Market selection grid */}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
              {groupMarkets.map((market) => {
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
                      disabled && "cursor-not-allowed opacity-50",
                    )}
                    title={market.description}
                  >
                    {/* Icon */}
                    <Icon
                      className={cn(
                        "mb-3 h-6 w-6",
                        isSelected ? "text-white" : "text-light",
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
          </div>
        );
      })}

      {/* Description */}
      <p className="control-hint">Select the player stat type to query</p>
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

/**
 * Lookup helpers — kept here so downstream components don't have to walk
 * MARKETS by hand. Group dispatch is the canonical way to tell whether a
 * market is binary (DD) without string-matching the key.
 */
export function getMarketGroup(key: string): MarketGroup | null {
  const market = MARKETS.find((m) => m.key === key);
  return market?.group ?? null;
}

export function isBinaryMarket(key: string): boolean {
  return getMarketGroup(key) === "binary";
}
