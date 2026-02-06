/**
 * providers.tsx - Context Providers
 * 
 * 包含所有需要在整個應用中使用的 Context Providers
 * 
 * React Query (TanStack Query):
 * - 用於管理伺服器狀態（server state）
 * - 自動快取、背景更新、重試等功能
 * - 比起自己用 useState + useEffect 更方便且強大
 * 
 * BetSlipProvider:
 * - 管理下注列表的全局狀態
 * - 自動同步到 localStorage 持久化
 */

"use client"; // 標記為客戶端元件，因為使用了 state

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useState } from "react";
import { BetSlipProvider } from "@/contexts/BetSlipContext";

/**
 * Providers 元件
 * 
 * 包裹所有需要的 context providers
 * 放在 layout.tsx 中使用
 * 
 * @param children - 子元件
 */
export function Providers({ children }: { children: React.ReactNode }) {
  // 使用 useState 確保每個請求都有獨立的 QueryClient
  // 這對於 SSR (Server-Side Rendering) 很重要
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // staleTime: 資料被視為「過期」的時間（毫秒）
            // 在這段時間內，即使重新渲染也不會重新 fetch
            staleTime: 60 * 1000, // 60 秒
            
            // gcTime (舊名 cacheTime): 快取保留時間
            // 資料不再被使用後，過了這段時間會從快取中移除
            gcTime: 10 * 60 * 1000, // 10 分鐘
            
            // retry: 失敗時重試次數
            retry: 1,
            
            // refetchOnWindowFocus: 視窗獲得焦點時是否重新 fetch
            // 關閉避免太頻繁的 API 呼叫
            refetchOnWindowFocus: false,
          },
          mutations: {
            // mutation 的重試設定
            retry: 1,
          },
        },
      })
  );

  return (
    // QueryClientProvider: React Query 的 context provider
    // 讓所有子元件都能使用 useQuery、useMutation 等 hooks
    <QueryClientProvider client={queryClient}>
      {/* BetSlipProvider: 下注列表的 context provider
          讓所有子元件都能使用 useBetSlip hook 管理下注列表 */}
      <BetSlipProvider>
        {children}
      </BetSlipProvider>
      
      {/* React Query Devtools: 開發工具
          只在開發環境顯示，用於除錯和監控查詢狀態 */}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}

