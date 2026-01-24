/**
 * MarketSelect.tsx - 市場類型選擇元件
 * 
 * 讓使用者選擇要查詢的統計類型
 * 
 * 功能：
 * - 選擇 Points（得分）
 * - 選擇 Assists（助攻）
 * - 選擇 Rebounds（籃板）
 * - 選擇 Points + Assists + Rebounds（PRA 三雙組合）
 */

"use client";

import { Activity, Target, Repeat2, Trophy } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * 市場類型定義
 * 
 * key: API 使用的識別碼（對應 The Odds API 的 market 參數）
 * name: 顯示名稱
 * shortName: 簡短名稱（用於標籤）
 * icon: 圖示元件
 * description: 描述
 */
export const MARKETS = [
  {
    key: "player_points",
    name: "得分",
    shortName: "Points",
    icon: Target,
    description: "球員得分數",
  },
  {
    key: "player_assists",
    name: "助攻",
    shortName: "Assists",
    icon: Activity,
    description: "球員助攻數",
  },
  {
    key: "player_rebounds",
    name: "籃板",
    shortName: "Rebounds",
    icon: Repeat2,
    description: "球員籃板數",
  },
  {
    key: "player_points_rebounds_assists",
    name: "得分+籃板+助攻",
    shortName: "PRA",
    icon: Trophy,
    description: "三項數據總和",
  },
] as const;

// 市場 key 的類型
export type MarketKey = (typeof MARKETS)[number]["key"];

/**
 * MarketSelect Props
 * 
 * @property value - 當前選中的市場 key
 * @property onChange - 市場改變時的回調函數
 * @property disabled - 是否禁用選擇
 */
interface MarketSelectProps {
  value: MarketKey;
  onChange: (value: MarketKey) => void;
  disabled?: boolean;
}

/**
 * MarketSelect 元件
 * 
 * 市場類型選擇器，使用卡片按鈕樣式
 * 允許使用者選擇要查詢的統計類型（Points/Assists/Rebounds/PRA）
 */
export function MarketSelect({
  value,
  onChange,
  disabled = false,
}: MarketSelectProps) {
  return (
    <div>
      {/* 標籤 */}
      <label className="block text-sm font-medium text-slate-300 mb-2">
        <Activity className="inline w-4 h-4 mr-1.5" />
        統計類型
      </label>

      {/* 市場選擇按鈕網格 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
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
                // 基本樣式
                "relative flex flex-col items-center justify-center",
                "p-3 rounded-lg border transition-all duration-200",
                "focus:outline-none focus:ring-2 focus:ring-blue-500/50",
                // 選中狀態
                isSelected
                  ? "border-blue-500 bg-blue-500/10 text-blue-300"
                  : "border-slate-700 bg-slate-800/50 text-slate-400 hover:border-slate-600 hover:bg-slate-800",
                // 禁用狀態
                disabled && "opacity-50 cursor-not-allowed"
              )}
              title={market.description}
            >
              {/* 圖示 */}
              <Icon
                className={cn(
                  "w-5 h-5 mb-1.5",
                  isSelected ? "text-blue-400" : "text-slate-500"
                )}
              />
              
              {/* 名稱 */}
              <span className={cn(
                "text-sm font-medium",
                isSelected ? "text-blue-300" : "text-slate-300"
              )}>
                {market.name}
              </span>

              {/* 簡短名稱標籤 */}
              <span className="text-xs text-slate-500 mt-0.5">
                {market.shortName}
              </span>

              {/* 選中指示器 */}
              {isSelected && (
                <div className="absolute top-1 right-1 w-2 h-2 bg-blue-500 rounded-full" />
              )}
            </button>
          );
        })}
      </div>

      {/* 說明文字 */}
      <p className="mt-2 text-xs text-slate-500">
        選擇要查詢的球員統計類型
      </p>
    </div>
  );
}

/**
 * 取得市場的顯示名稱
 * 
 * @param key - 市場 key
 * @returns 顯示名稱
 */
export function getMarketDisplayName(key: string): string {
  const market = MARKETS.find((m) => m.key === key);
  return market?.name || key;
}

