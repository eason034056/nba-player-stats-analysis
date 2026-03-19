/**
 * BetSlipContext.tsx - 下注列表全局狀態管理
 * 
 * 用於管理用戶選擇的「下注列表」
 * 
 * 功能：
 * - picks: 已添加的 picks 列表
 * - addPick: 添加 pick 到列表
 * - removePick: 從列表移除 pick
 * - clearAll: 清空列表
 * - isInSlip: 檢查 pick 是否已在列表中
 * - count: 當前列表中的 pick 數量
 * 
 * 持久化：
 * - 自動同步到 localStorage，刷新頁面不會丟失資料
 * 
 * 使用方式：
 * 1. 在 providers.tsx 中包裹 BetSlipProvider
 * 2. 在任意組件中使用 useBetSlip() hook 獲取狀態和方法
 */

"use client";

import React, { 
  createContext, 
  useContext, 
  useState, 
  useCallback, 
  useEffect,
  type ReactNode 
} from "react";

// ==================== 類型定義 ====================

/**
 * BetSlipPick - 下注列表中的單一選擇
 * 
 * 包含顯示和識別所需的所有資訊
 */
export interface BetSlipPick {
  /** 唯一識別碼，格式：player_name-metric */
  id: string;
  /** 球員名稱 */
  player_name: string;
  /** 球員所屬球隊（簡短名稱，如 "Lakers"） */
  player_team: string;
  /** 賽事 ID，用於連結到詳細頁面 */
  event_id: string;
  /** 主場球隊 */
  home_team: string;
  /** 客場球隊 */
  away_team: string;
  /** 比賽開始時間（ISO 8601 格式） */
  commence_time: string;
  /** 統計指標（points/assists/rebounds/pra） */
  metric: string;
  /** 門檻值（例如 28.5） */
  threshold: number;
  /** 方向（over/under） */
  direction: string;
  /** 歷史機率 */
  probability: number;
  /** 樣本場次數 */
  n_games: number;
  /** 添加到列表的時間（ISO 8601 格式） */
  added_at: string;
}

/**
 * BetSlipContextType - Context 提供的值類型
 */
interface BetSlipContextType {
  /** 當前列表中的所有 picks */
  picks: BetSlipPick[];
  /** 添加 pick 到列表 */
  addPick: (pick: Omit<BetSlipPick, "id" | "added_at">) => void;
  /** 從列表移除 pick */
  removePick: (id: string) => void;
  /** 清空所有 picks */
  clearAll: () => void;
  /** 檢查 pick 是否已在列表中 */
  isInSlip: (playerName: string, metric: string) => boolean;
  /** 當前 picks 數量 */
  count: number;
}

// ==================== Context 建立 ====================

/**
 * BetSlipContext
 * 
 * 預設值為 undefined，使用時必須在 Provider 內部
 * 這樣可以在未正確包裹時給出明確的錯誤訊息
 */
const BetSlipContext = createContext<BetSlipContextType | undefined>(undefined);

// localStorage key
const STORAGE_KEY = "betslip_picks";

// ==================== Provider 組件 ====================

/**
 * BetSlipProvider - Context Provider 組件
 * 
 * 包裹應用程式的根組件，提供下注列表狀態給所有子組件
 * 
 * @param children - 子組件
 */
export function BetSlipProvider({ children }: { children: ReactNode }) {
  // 狀態：picks 列表
  const [picks, setPicks] = useState<BetSlipPick[]>([]);
  
  // 標記：是否已從 localStorage 載入（避免 hydration 問題）
  const [isHydrated, setIsHydrated] = useState(false);

  // ==================== localStorage 同步 ====================

  /**
   * 初始化：從 localStorage 載入資料
   * 
   * 使用 useEffect 確保只在客戶端執行
   * 這避免了 SSR/SSG 時的 hydration mismatch 問題
   */
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        // 驗證是否為陣列
        if (Array.isArray(parsed)) {
          setPicks(parsed);
        }
      }
    } catch (error) {
      console.error("Failed to load betslip from localStorage:", error);
    }
    setIsHydrated(true);
  }, []);

  /**
   * 同步：當 picks 變化時儲存到 localStorage
   * 
   * 只在 hydrated 後才執行，避免覆蓋 localStorage 中的資料
   */
  useEffect(() => {
    if (isHydrated) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(picks));
      } catch (error) {
        console.error("Failed to save betslip to localStorage:", error);
      }
    }
  }, [picks, isHydrated]);

  // ==================== 操作方法 ====================

  /**
   * 生成 pick 的唯一 ID
   * 
   * 格式：player_name-metric
   * 這確保同一球員的同一指標只能添加一次
   */
  const generateId = useCallback((playerName: string, metric: string): string => {
    return `${playerName}-${metric}`;
  }, []);

  /**
   * 添加 pick 到列表
   * 
   * 如果已存在（相同球員 + 相同指標）則不會重複添加
   * 
   * @param pickData - pick 資料（不含 id 和 added_at）
   */
  const addPick = useCallback((pickData: Omit<BetSlipPick, "id" | "added_at">) => {
    const id = generateId(pickData.player_name, pickData.metric);
    
    setPicks((prev) => {
      // 檢查是否已存在
      if (prev.some((p) => p.id === id)) {
        return prev; // 已存在，不重複添加
      }
      
      // 建立完整的 pick 物件
      const newPick: BetSlipPick = {
        ...pickData,
        id,
        added_at: new Date().toISOString(),
      };
      
      return [...prev, newPick];
    });
  }, [generateId]);

  /**
   * 從列表移除 pick
   * 
   * @param id - pick 的唯一識別碼
   */
  const removePick = useCallback((id: string) => {
    setPicks((prev) => prev.filter((p) => p.id !== id));
  }, []);

  /**
   * 清空所有 picks
   */
  const clearAll = useCallback(() => {
    setPicks([]);
  }, []);

  /**
   * 檢查 pick 是否已在列表中
   * 
   * @param playerName - 球員名稱
   * @param metric - 統計指標
   * @returns 是否已在列表中
   */
  const isInSlip = useCallback((playerName: string, metric: string): boolean => {
    const id = generateId(playerName, metric);
    return picks.some((p) => p.id === id);
  }, [picks, generateId]);

  // ==================== Context Value ====================

  const value: BetSlipContextType = {
    picks,
    addPick,
    removePick,
    clearAll,
    isInSlip,
    count: picks.length,
  };

  return (
    <BetSlipContext.Provider value={value}>
      {children}
    </BetSlipContext.Provider>
  );
}

// ==================== Hook ====================

/**
 * useBetSlip - 使用下注列表 Context 的 Hook
 * 
 * 必須在 BetSlipProvider 內部使用
 * 
 * @returns BetSlipContextType - 下注列表的狀態和方法
 * @throws Error - 如果在 Provider 外部使用
 * 
 * @example
 * ```tsx
 * function MyComponent() {
 *   const { picks, addPick, removePick, isInSlip, count } = useBetSlip();
 *   
 *   // 添加 pick
 *   addPick({
 *     player_name: "Stephen Curry",
 *     metric: "points",
 *     // ... 其他欄位
 *   });
 *   
 *   // 檢查是否已添加
 *   const isAdded = isInSlip("Stephen Curry", "points");
 * }
 * ```
 */
export function useBetSlip(): BetSlipContextType {
  const context = useContext(BetSlipContext);
  
  if (context === undefined) {
    throw new Error(
      "useBetSlip must be used within a BetSlipProvider. " +
      "Make sure to wrap your app with <BetSlipProvider>."
    );
  }
  
  return context;
}
