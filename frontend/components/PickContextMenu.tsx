/**
 * PickContextMenu.tsx - 右鍵選單組件
 * 
 * 為 Pick 卡片提供右鍵選單功能
 * 用戶可以通過右鍵快速添加或移除下注列表中的選擇
 * 
 * 功能：
 * - 右鍵點擊顯示選單
 * - 添加到下注列表 / 從列表移除（根據狀態切換）
 * - 查看詳細數據（導航到 event 頁面）
 * - 點擊其他地方或按 ESC 關閉選單
 * 
 * 使用方式：
 * ```tsx
 * <PickContextMenu pick={pickData}>
 *   <PickCard pick={pickData} />
 * </PickContextMenu>
 * ```
 */

"use client";

import React, { useState, useRef, useEffect, useCallback, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { Plus, Minus, ExternalLink, ClipboardList, ArrowLeftRight } from "lucide-react";
import { useBetSlip, type BetSlipPick } from "@/contexts/BetSlipContext";
import { type DailyPick } from "@/lib/schemas";

// ==================== 類型定義 ====================

interface PickContextMenuProps {
  /** 子組件（要包裹的卡片） */
  children: ReactNode;
  /** Pick 資料 */
  pick: DailyPick;
}

interface MenuPosition {
  x: number;
  y: number;
}

// ==================== 輔助函數 ====================

/**
 * metric → market 轉換
 * 
 * 將簡短的 metric key 轉換為 API 使用的 market key
 */
function metricToMarket(metric: string): string {
  switch (metric) {
    case "points": return "player_points";
    case "rebounds": return "player_rebounds";
    case "assists": return "player_assists";
    case "pra": return "player_points_rebounds_assists";
    default: return "player_points";
  }
}

// ==================== 組件 ====================

/**
 * PickContextMenu - 右鍵選單組件
 * 
 * 包裹任意子組件，提供右鍵選單功能
 */
export function PickContextMenu({ children, pick }: PickContextMenuProps) {
  const router = useRouter();
  const { picks, addPick, removePick, isInSlip } = useBetSlip();
  
  // 選單狀態
  const [isOpen, setIsOpen] = useState(false);
  const [position, setPosition] = useState<MenuPosition>({ x: 0, y: 0 });
  
  // Refs
  const menuRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  
  // 檢查是否已在下注列表中
  const isAdded = isInSlip(pick.player_name, pick.metric);

  // ==================== 反向下注資訊 ====================

  /**
   * reverseDirection - 反向方向
   * 
   * 如果原始方向是 "over"，反向就是 "under"，反之亦然
   * 這讓用戶可以根據當天狀況逆向下注
   */
  const reverseDirection = pick.direction === "over" ? "under" : "over";

  /**
   * reverseProbability - 反向機率
   * 
   * 反向機率 = 1 - 原始機率
   * 例如原始 Over 90% → 反向 Under 10%
   */
  const reverseProbability = 1 - pick.probability;

  /**
   * reverseDirectionLabel - 反向方向的顯示名稱
   * 
   * "over" → "Over", "under" → "Under"
   */
  const reverseDirectionLabel = reverseDirection === "over" ? "Over" : "Under";

  /**
   * existingPick - 在 betslip 中已存在的相同 player+metric 的 pick
   * 
   * 用來判斷 betslip 裡的 pick 是原始方向還是反向
   */
  const existingPick = picks.find(
    (p) => p.player_name === pick.player_name && p.metric === pick.metric
  );

  /**
   * isReversedInSlip - 反向下注是否已在列表中
   * 
   * 當 existingPick 的 direction 與反向方向一致時為 true
   * 用來在選單中顯示不同狀態（已添加/未添加）
   */
  const isReversedInSlip = existingPick?.direction === reverseDirection;

  // ==================== 事件處理 ====================

  /**
   * 處理右鍵點擊
   * 
   * 顯示選單並定位到滑鼠位置
   */
  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    // 計算選單位置，確保不超出視窗邊界
    const x = e.clientX;
    const y = e.clientY;
    
    // 獲取視窗尺寸
    const windowWidth = window.innerWidth;
    const windowHeight = window.innerHeight;
    
    // 選單預估尺寸（加入反向下注選項後高度增加）
    const menuWidth = 220;
    const menuHeight = 200;
    
    // 調整位置避免超出邊界
    const adjustedX = x + menuWidth > windowWidth ? windowWidth - menuWidth - 10 : x;
    const adjustedY = y + menuHeight > windowHeight ? windowHeight - menuHeight - 10 : y;
    
    setPosition({ x: adjustedX, y: adjustedY });
    setIsOpen(true);
  }, []);

  /**
   * 關閉選單
   */
  const closeMenu = useCallback(() => {
    setIsOpen(false);
  }, []);

  /**
   * 處理添加/移除下注列表
   */
  const handleToggleBetSlip = useCallback(() => {
    if (isAdded) {
      // 移除
      removePick(`${pick.player_name}-${pick.metric}`);
    } else {
      // 添加
      const betSlipPick: Omit<BetSlipPick, "id" | "added_at"> = {
        player_name: pick.player_name,
        player_team: pick.player_team || "",
        event_id: pick.event_id,
        home_team: pick.home_team,
        away_team: pick.away_team,
        commence_time: pick.commence_time,
        metric: pick.metric,
        threshold: pick.threshold,
        direction: pick.direction,
        probability: pick.probability,
        n_games: pick.n_games,
      };
      addPick(betSlipPick);
    }
    closeMenu();
  }, [isAdded, pick, addPick, removePick, closeMenu]);

  /**
   * 處理添加反向下注
   * 
   * handleAddReverseBet - 將 pick 以相反方向添加到下注列表
   * 
   * 使用方式：
   * - 如果數據顯示 90% Under，但用戶認為今天情況不同想下 Over
   * - 右鍵 → 點擊「Bet Reverse: Over X.X」即可添加反向下注
   * 
   * 邏輯：
   * 1. 先移除已存在的同一 player+metric 的 pick（無論哪個方向）
   * 2. 添加新的 pick，direction 反轉，probability 取 (1 - 原始)
   * 
   * 為什麼要先 removePick 再 addPick？
   * - 因為 pick ID 是 `player_name-metric`，不包含方向
   * - 所以同一球員同一指標只能有一個方向的 pick
   * - removePick 使用 functional update (setPicks(prev => ...))
   * - addPick 也使用 functional update，React 會依序套用
   * - 所以 addPick 看到的 state 已經是移除後的結果，不會衝突
   */
  const handleAddReverseBet = useCallback(() => {
    const id = `${pick.player_name}-${pick.metric}`;

    // 先移除已存在的 pick（如果有的話）
    removePick(id);

    // 添加反向 pick
    const betSlipPick: Omit<BetSlipPick, "id" | "added_at"> = {
      player_name: pick.player_name,
      player_team: pick.player_team || "",
      event_id: pick.event_id,
      home_team: pick.home_team,
      away_team: pick.away_team,
      commence_time: pick.commence_time,
      metric: pick.metric,
      threshold: pick.threshold,
      direction: reverseDirection,           // 反向方向
      probability: reverseProbability,       // 反向機率
      n_games: pick.n_games,
    };
    addPick(betSlipPick);
    closeMenu();
  }, [pick, reverseDirection, reverseProbability, addPick, removePick, closeMenu]);

  /**
   * 處理查看詳細數據
   * 
   * 導航到 event 詳細頁面
   */
  const handleViewDetails = useCallback(() => {
    const marketKey = metricToMarket(pick.metric);
    const href = `/event/${pick.event_id}?player=${encodeURIComponent(pick.player_name)}&market=${marketKey}&threshold=${pick.threshold}`;
    router.push(href);
    closeMenu();
  }, [pick, router, closeMenu]);

  // ==================== 副作用 ====================

  /**
   * 點擊外部關閉選單
   */
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        closeMenu();
      }
    };

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        closeMenu();
      }
    };

    // 延遲添加事件監聽，避免立即觸發
    const timeoutId = setTimeout(() => {
      document.addEventListener("click", handleClickOutside);
      document.addEventListener("keydown", handleEscape);
    }, 0);

    return () => {
      clearTimeout(timeoutId);
      document.removeEventListener("click", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [isOpen, closeMenu]);

  /**
   * 滾動時關閉選單
   */
  useEffect(() => {
    if (!isOpen) return;

    const handleScroll = () => {
      closeMenu();
    };

    window.addEventListener("scroll", handleScroll, true);
    return () => window.removeEventListener("scroll", handleScroll, true);
  }, [isOpen, closeMenu]);

  // ==================== 渲染 ====================

  // 選單內容（使用 Portal 渲染到 body）
  const menuContent = isOpen && (
    <div
      ref={menuRef}
      className="fixed min-w-[200px] py-2 bg-white rounded-lg shadow-xl border-2 border-dark/10 animate-fade-in"
      style={{
        left: position.x,
        top: position.y,
        zIndex: 9999, // 使用非常高的 z-index 確保在最上層
      }}
    >
      {/* 選單標題 */}
      <div className="px-4 py-2 border-b border-dark/10">
        <p className="text-sm font-bold text-dark truncate">
          {pick.player_name}
        </p>
        <p className="text-xs text-gray">
          {pick.metric.charAt(0).toUpperCase() + pick.metric.slice(1)} {pick.direction} {pick.threshold}
        </p>
      </div>

      {/* 選單項目 */}
      <div className="py-1">
        {/* 添加/移除下注列表 */}
        <button
          onClick={handleToggleBetSlip}
          className={`
            w-full flex items-center gap-3 px-4 py-2.5 text-sm font-medium
            transition-colors duration-150
            ${isAdded
              ? "text-red hover:bg-red/10"
              : "text-dark hover:bg-dark/5"
            }
          `}
        >
          {isAdded ? (
            <>
              <Minus className="w-4 h-4" />
              <span>Remove from Bet Slip</span>
            </>
          ) : (
            <>
              <Plus className="w-4 h-4" />
              <span>Add to Bet Slip</span>
            </>
          )}
        </button>

        {/* 分隔線 */}
        <div className="mx-3 my-1 border-t border-dark/10" />

        {/* 反向下注 */}
        <button
          onClick={handleAddReverseBet}
          className={`
            w-full flex items-center gap-3 px-4 py-2.5 text-sm font-medium
            transition-colors duration-150
            ${isReversedInSlip
              ? "text-orange-600 hover:bg-orange-50"
              : "text-dark hover:bg-dark/5"
            }
          `}
        >
          <ArrowLeftRight className="w-4 h-4" />
          <span className="flex-1 text-left">
            {isReversedInSlip
              ? `Reversed in Slip`
              : `Bet Reverse: ${reverseDirectionLabel} ${pick.threshold}`
            }
          </span>
          {/* 反向機率提示（小字顯示） */}
          <span className="text-xs text-gray opacity-70">
            {(reverseProbability * 100).toFixed(0)}%
          </span>
        </button>

        {/* 分隔線 */}
        <div className="mx-3 my-1 border-t border-dark/10" />

        {/* 查看詳細數據 */}
        <button
          onClick={handleViewDetails}
          className="w-full flex items-center gap-3 px-4 py-2.5 text-sm font-medium text-dark hover:bg-dark/5 transition-colors duration-150"
        >
          <ExternalLink className="w-4 h-4" />
          <span>View Details</span>
        </button>
      </div>

      {/* 已添加提示 */}
      {isAdded && (
        <div className="px-4 py-2 border-t border-dark/10">
          <p className={`text-xs flex items-center gap-1.5 ${isReversedInSlip ? "text-orange-600" : "text-green-600"}`}>
            {isReversedInSlip ? (
              <>
                <ArrowLeftRight className="w-3 h-3" />
                Reversed bet in slip ({reverseDirectionLabel} {pick.threshold})
              </>
            ) : (
              <>
                <ClipboardList className="w-3 h-3" />
                In your bet slip
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );

  return (
    <div ref={containerRef} onContextMenu={handleContextMenu} className="relative">
      {/* 子組件（被包裹的卡片） */}
      {children}

      {/* 右鍵選單 - 使用 Portal 渲染到 document.body，避免被其他元素遮擋 */}
      {typeof window !== "undefined" && menuContent && createPortal(menuContent, document.body)}
    </div>
  );
}
