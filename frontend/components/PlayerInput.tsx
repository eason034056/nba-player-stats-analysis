/**
 * PlayerInput.tsx - 球員輸入元件
 * 
 * 帶有 Autocomplete 功能的球員名稱輸入框
 * 
 * 功能：
 * - 文字輸入搜尋
 * - 即時搜尋建議（從 API 取得）
 * - 點擊選擇建議
 * - 鍵盤導航（上下鍵 + Enter）
 * - 在搜尋欄下方顯示所有球員列表，支援點擊選擇
 */

"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, User, Loader2, Users } from "lucide-react";
import { getPlayerSuggestions } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { MarketKey } from "./MarketSelect";

/**
 * PlayerInput Props
 * 
 * @property eventId - 賽事 ID（用於取得該場比賽的球員列表）
 * @property market - 市場類型（用於取得對應市場的球員列表）
 * @property value - 當前輸入值
 * @property onChange - 值改變時的回調
 * @property disabled - 是否禁用
 */
interface PlayerInputProps {
  eventId: string;
  market?: MarketKey;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

/**
 * PlayerInput 元件
 * 
 * 帶 Autocomplete 的球員名稱輸入框
 * 同時在下方顯示所有可選球員列表
 */
export function PlayerInput({
  eventId,
  market = "player_points",
  value,
  onChange,
  disabled = false,
}: PlayerInputProps) {
  // 下拉選單是否顯示
  const [isOpen, setIsOpen] = useState(false);
  
  // 當前高亮的建議項目索引
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  
  // 輸入框的 ref
  const inputRef = useRef<HTMLInputElement>(null);
  
  // 下拉選單的 ref
  const listRef = useRef<HTMLUListElement>(null);

  // 使用 React Query 取得所有球員（用於顯示全部列表）
  // 這個查詢不帶搜尋關鍵字，取得該場比賽的所有球員
  const { data: allPlayers, isLoading: isLoadingAll } = useQuery({
    queryKey: ["allPlayers", eventId, market],
    queryFn: () => getPlayerSuggestions(eventId, "", market),
    enabled: !!eventId,
    staleTime: 60 * 1000, // 60 秒內不重新查詢
  });

  // 使用 React Query 取得搜尋建議
  // useQuery: TanStack Query 的核心 hook
  // - queryKey: 快取的鍵，用於識別這個查詢
  // - queryFn: 實際執行查詢的函數
  // - enabled: 是否啟用查詢（有 eventId 且有輸入時才查詢）
  const { data: suggestions, isLoading: isLoadingSearch } = useQuery({
    queryKey: ["playerSuggestions", eventId, market, value],
    queryFn: () => getPlayerSuggestions(eventId, value, market),
    enabled: !!eventId && value.length >= 1,
    staleTime: 30 * 1000, // 30 秒內不重新查詢
  });

  // 全部球員列表
  const allPlayerList = allPlayers?.players || [];

  // 搜尋結果過濾後的球員列表
  const filteredPlayers = suggestions?.players || [];

  // 處理輸入變化
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = e.target.value;
    onChange(newValue);
    setIsOpen(true);
    setHighlightedIndex(-1);
  };

  // 選擇一個球員
  const selectPlayer = useCallback((playerName: string) => {
    onChange(playerName);
    setIsOpen(false);
    setHighlightedIndex(-1);
    inputRef.current?.blur();
  }, [onChange]);

  // 處理鍵盤事件
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen || filteredPlayers.length === 0) return;

    switch (e.key) {
      case "ArrowDown":
        // 向下移動高亮
        e.preventDefault();
        setHighlightedIndex((prev) =>
          prev < filteredPlayers.length - 1 ? prev + 1 : prev
        );
        break;

      case "ArrowUp":
        // 向上移動高亮
        e.preventDefault();
        setHighlightedIndex((prev) => (prev > 0 ? prev - 1 : prev));
        break;

      case "Enter":
        // 選擇當前高亮項目
        e.preventDefault();
        if (highlightedIndex >= 0) {
          selectPlayer(filteredPlayers[highlightedIndex]);
        }
        break;

      case "Escape":
        // 關閉下拉選單
        setIsOpen(false);
        break;
    }
  };

  // 點擊外部時關閉下拉選單
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        inputRef.current &&
        !inputRef.current.contains(e.target as Node) &&
        listRef.current &&
        !listRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // 滾動到高亮項目
  useEffect(() => {
    if (highlightedIndex >= 0 && listRef.current) {
      const items = listRef.current.querySelectorAll("li");
      items[highlightedIndex]?.scrollIntoView({ block: "nearest" });
    }
  }, [highlightedIndex]);

  return (
    <div className="space-y-4">
      {/* 搜尋輸入區域 */}
      <div className="relative">
        {/* 標籤 */}
        <label className="block text-sm font-medium text-slate-300 mb-2">
          <Search className="inline w-4 h-4 mr-1.5" />
          搜尋球員
        </label>

        {/* 輸入框容器 */}
        <div className="relative">
          {/* 搜尋圖示 */}
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500" />
          
          {/* 輸入框 */}
          <input
            ref={inputRef}
            type="text"
            value={value}
            onChange={handleInputChange}
            onFocus={() => setIsOpen(true)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            placeholder="輸入球員名稱，如 Stephen Curry"
            className={cn(
              "input pl-10 pr-10",
              disabled && "opacity-50 cursor-not-allowed"
            )}
          />

          {/* 載入中指示器 */}
          {isLoadingSearch && (
            <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500 animate-spin" />
          )}
        </div>

        {/* 下拉搜尋建議列表 */}
        {isOpen && filteredPlayers.length > 0 && (
          <ul
            ref={listRef}
            className={cn(
              "absolute z-50 w-full mt-1",
              "bg-slate-800 border border-slate-700 rounded-lg",
              "max-h-60 overflow-auto",
              "shadow-xl shadow-black/20"
            )}
          >
            {filteredPlayers.map((player, index) => (
              <li
                key={player}
                onClick={() => selectPlayer(player)}
                className={cn(
                  "px-4 py-2.5 cursor-pointer",
                  "flex items-center gap-3",
                  "transition-colors duration-100",
                  // 高亮狀態
                  index === highlightedIndex
                    ? "bg-blue-600/20 text-blue-300"
                    : "text-slate-300 hover:bg-slate-700/50"
                )}
              >
                <User className="w-4 h-4 text-slate-500" />
                <span>{player}</span>
              </li>
            ))}
          </ul>
        )}

        {/* 沒有搜尋結果提示 */}
        {isOpen && value.length >= 2 && !isLoadingSearch && filteredPlayers.length === 0 && (
          <div className="absolute z-50 w-full mt-1 px-4 py-3 bg-slate-800 border border-slate-700 rounded-lg">
            <p className="text-sm text-slate-500">
              找不到符合的球員
            </p>
          </div>
        )}
      </div>

      {/* 所有球員列表區域 */}
      <div>
        {/* 標籤 */}
        <label className="block text-sm font-medium text-slate-300 mb-2">
          <Users className="inline w-4 h-4 mr-1.5" />
          全部球員（點擊選擇）
        </label>

        {/* 球員列表 */}
        {isLoadingAll ? (
          // 載入中骨架屏
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {[...Array(9)].map((_, i) => (
              <div key={i} className="skeleton h-9 rounded-lg" />
            ))}
          </div>
        ) : allPlayerList.length > 0 ? (
          // 球員卡片網格
          <div className="max-h-64 overflow-y-auto rounded-lg border border-slate-700 bg-slate-800/30 p-2">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              {allPlayerList.map((player) => {
                const isSelected = value === player;
                return (
                  <button
                    key={player}
                    type="button"
                    onClick={() => selectPlayer(player)}
                    disabled={disabled}
                    className={cn(
                      "px-3 py-2 rounded-lg text-sm text-left",
                      "flex items-center gap-2",
                      "transition-all duration-150",
                      "focus:outline-none focus:ring-2 focus:ring-blue-500/50",
                      // 選中狀態
                      isSelected
                        ? "bg-blue-600/30 border border-blue-500 text-blue-200"
                        : "bg-slate-800/50 border border-slate-700 text-slate-300 hover:bg-slate-700/50 hover:border-slate-600",
                      // 禁用狀態
                      disabled && "opacity-50 cursor-not-allowed"
                    )}
                  >
                    <User className={cn(
                      "w-3.5 h-3.5 shrink-0",
                      isSelected ? "text-blue-400" : "text-slate-500"
                    )} />
                    <span className="truncate">{player}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          // 無球員資料
          <div className="px-4 py-6 text-center bg-slate-800/30 rounded-lg border border-slate-700">
            <Users className="w-8 h-8 text-slate-600 mx-auto mb-2" />
            <p className="text-sm text-slate-500">
              此場比賽尚無可查詢的球員資料
            </p>
          </div>
        )}

        {/* 球員數量統計 */}
        {allPlayerList.length > 0 && (
          <p className="mt-2 text-xs text-slate-500">
            共 {allPlayerList.length} 位球員有此統計類型的 Props 資料
          </p>
        )}
      </div>
    </div>
  );
}
