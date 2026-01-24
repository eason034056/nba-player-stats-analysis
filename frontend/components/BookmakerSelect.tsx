/**
 * BookmakerSelect.tsx - 博彩公司多選元件
 * 
 * 讓使用者選擇要查詢的博彩公司
 * 使用 checkbox 多選介面
 * 
 * 功能：
 * - 全選 / 取消全選
 * - 分組顯示（主流、其他）
 * - 個別選擇
 * - 顯示已選數量
 */

"use client";

import { useState } from "react";
import { Check, Building2, ChevronDown, ChevronUp } from "lucide-react";
import { BOOKMAKERS, type BookmakerKey } from "@/lib/schemas";
import { cn } from "@/lib/utils";

// 分組顯示：主流 vs 其他
const FEATURED_BOOKMAKERS = ["draftkings", "fanduel", "betmgm", "caesars", "espnbet", "bet365"];
const featuredBooks = BOOKMAKERS.filter(b => FEATURED_BOOKMAKERS.includes(b.key));
const otherBooks = BOOKMAKERS.filter(b => !FEATURED_BOOKMAKERS.includes(b.key));

/**
 * BookmakerSelect Props
 * 
 * @property value - 已選擇的博彩公司 key 陣列
 * @property onChange - 選擇改變時的回調
 * @property disabled - 是否禁用
 */
interface BookmakerSelectProps {
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
}

/**
 * BookmakerSelect 元件
 * 
 * 博彩公司多選介面（支援分組摺疊）
 */
export function BookmakerSelect({
  value,
  onChange,
  disabled = false,
}: BookmakerSelectProps) {
  // 是否全選
  const isAllSelected = value.length === 0; // 空陣列表示全選（API 會查詢所有）
  
  // 是否展開「其他博彩公司」區塊
  const [showOthers, setShowOthers] = useState(false);

  // 切換全選
  const toggleSelectAll = () => {
    if (isAllSelected) {
      // 取消全選，選擇主流平台
      onChange(featuredBooks.map(b => b.key));
    } else {
      // 全選（清空陣列）
      onChange([]);
    }
  };

  // 切換單個博彩公司
  const toggleBookmaker = (key: string) => {
    if (isAllSelected) {
      // 從全選狀態切換到個別選擇
      // 選擇除了被點擊的之外的所有
      onChange(BOOKMAKERS.filter((b) => b.key !== key).map((b) => b.key));
    } else if (value.includes(key)) {
      // 取消選擇
      const newValue = value.filter((v) => v !== key);
      // 如果取消後剩下所有，則變為全選
      if (newValue.length === BOOKMAKERS.length - 1) {
        onChange([]);
      } else {
        onChange(newValue);
      }
    } else {
      // 新增選擇
      onChange([...value, key]);
    }
  };

  // 檢查某個博彩公司是否被選中
  const isSelected = (key: string) => {
    return isAllSelected || value.includes(key);
  };

  return (
    <div className={cn(disabled && "opacity-50 pointer-events-none")}>
      {/* 標籤 */}
      <label className="block text-sm font-medium text-slate-300 mb-3">
        <Building2 className="inline w-4 h-4 mr-1.5" />
        博彩公司
      </label>

      {/* 全選按鈕 */}
      <button
        type="button"
        onClick={toggleSelectAll}
        className={cn(
          "w-full mb-4 px-4 py-3 rounded-xl",
          "flex items-center justify-between",
          "border transition-all duration-200",
          isAllSelected
            ? "bg-gradient-to-r from-amber-500/15 to-orange-500/15 border-amber-500/40 text-amber-300"
            : "bg-slate-800/60 border-slate-700/50 text-slate-400 hover:border-slate-600 hover:bg-slate-800"
        )}
      >
        <span className="font-semibold">
          {isAllSelected ? "✓ 已選擇全部" : "選擇全部"}
        </span>
        {isAllSelected && <Check className="w-5 h-5" />}
      </button>

      {/* 主流博彩公司 */}
      <div className="mb-4">
        <h4 className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wider">
          主流平台
        </h4>
        <div className="grid grid-cols-2 gap-2">
          {featuredBooks.map((bookmaker) => {
            const selected = isSelected(bookmaker.key);

            return (
              <button
                key={bookmaker.key}
                type="button"
                onClick={() => toggleBookmaker(bookmaker.key)}
                className={cn(
                  "px-3 py-2.5 rounded-xl text-sm font-medium",
                  "flex items-center justify-between",
                  "border transition-all duration-200",
                  selected
                    ? "bg-slate-800/80 border-slate-600/60 text-slate-100"
                    : "bg-slate-900/40 border-slate-800/50 text-slate-500 hover:border-slate-700 hover:text-slate-300"
                )}
              >
                <span className="truncate">{bookmaker.name}</span>
                {selected && (
                  <Check className="w-4 h-4 text-emerald-400 shrink-0 ml-2" />
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* 其他博彩公司（可摺疊） */}
      <div>
        <button
          type="button"
          onClick={() => setShowOthers(!showOthers)}
          className="flex items-center justify-between w-full mb-2 text-xs font-medium text-slate-500 hover:text-slate-400 transition-colors uppercase tracking-wider"
        >
          <span>其他博彩公司 ({otherBooks.length})</span>
          {showOthers ? (
            <ChevronUp className="w-4 h-4" />
          ) : (
            <ChevronDown className="w-4 h-4" />
          )}
        </button>
        
        {showOthers && (
          <div className="grid grid-cols-2 gap-2 animate-fade-in">
            {otherBooks.map((bookmaker) => {
              const selected = isSelected(bookmaker.key);

              return (
                <button
                  key={bookmaker.key}
                  type="button"
                  onClick={() => toggleBookmaker(bookmaker.key)}
                  className={cn(
                    "px-3 py-2 rounded-xl text-xs",
                    "flex items-center justify-between",
                    "border transition-all duration-200",
                    selected
                      ? "bg-slate-800/60 border-slate-600/50 text-slate-200"
                      : "bg-slate-900/30 border-slate-800/40 text-slate-600 hover:border-slate-700 hover:text-slate-400"
                  )}
                >
                  <span className="truncate">{bookmaker.name}</span>
                  {selected && (
                    <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0 ml-1.5" />
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* 已選數量提示 */}
      <p className="mt-4 text-xs text-slate-500">
        {isAllSelected ? (
          <>將查詢所有 {BOOKMAKERS.length} 家博彩公司</>
        ) : (
          <>已選擇 <span className="text-slate-300 font-medium">{value.length}</span> / {BOOKMAKERS.length} 家</>
        )}
      </p>
    </div>
  );
}

