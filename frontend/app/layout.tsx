/**
 * layout.tsx - 根佈局
 * 
 * Next.js App Router 的根佈局檔案
 * 所有頁面都會被這個佈局包裹
 * 
 * 包含：
 * 1. HTML 和 metadata 設定
 * 2. 全域樣式引入
 * 3. 共用的 Provider（如 React Query）
 * 4. 共用的導航欄
 */

import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Navbar } from "@/components/Navbar";

/**
 * Metadata 設定
 * 
 * 定義頁面的 meta 標籤，用於 SEO 和社群分享
 */
export const metadata: Metadata = {
  // 網站標題
  title: {
    default: "No-Vig NBA | 去水機率計算器",
    template: "%s | No-Vig NBA",
  },
  // 網站描述
  description:
    "計算 NBA 球員得分 Props 的去水機率，移除博彩公司水錢，取得公平的市場機率估計",
  // 關鍵字
  keywords: [
    "NBA",
    "去水",
    "no-vig",
    "賠率",
    "機率",
    "球員得分",
    "props",
    "博彩",
  ],
  // 作者
  authors: [{ name: "No-Vig NBA" }],
  // 圖標
  icons: {
    icon: "/favicon.ico",
  },
};

/**
 * 根佈局元件
 * 
 * 所有頁面的共同外框
 * 
 * @param children - 子頁面內容
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // lang="zh-TW": 設定語言為繁體中文
    <html lang="zh-TW">
      <body>
        {/* Providers: 包含 React Query 等 context providers */}
        <Providers>
          {/* 背景裝飾 */}
          <div className="fixed inset-0 -z-10">
            {/* 漸層背景 */}
            <div className="absolute inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950" />
            {/* 網格裝飾 */}
            <div 
              className="absolute inset-0 opacity-[0.03]"
              style={{
                backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='1'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
              }}
            />
            {/* 頂部光暈 */}
            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[600px] bg-blue-500/10 rounded-full blur-3xl" />
          </div>
          
          {/* 導航欄 */}
          <Navbar />
          
          {/* 主要內容區域 */}
          <main className="min-h-screen pt-16">
            {children}
          </main>
          
          {/* 頁尾 */}
          <footer className="border-t border-slate-800 py-8 mt-auto">
            <div className="container mx-auto px-4 text-center text-slate-500 text-sm">
              <p className="mb-2">
                本站為資訊與數據分析用途，不構成投注建議
              </p>
              <p>
                資料可能延遲或缺漏，以外部供應商為準
              </p>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}

