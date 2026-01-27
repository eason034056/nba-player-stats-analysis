/**
 * layout.tsx - 根佈局（極簡風版本）
 * 
 * Next.js App Router 的根佈局檔案
 * 
 * 設計理念：
 * - 純米色背景 (#FFF2DF)
 * - 無裝飾元素
 * - 簡潔的結構
 */

import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Navbar } from "@/components/Navbar";

/**
 * Metadata 設定
 */
export const metadata: Metadata = {
  title: {
    default: "No-Vig NBA | 去水機率計算器",
    template: "%s | No-Vig NBA",
  },
  description:
    "計算 NBA 球員得分 Props 的去水機率，移除博彩公司水錢，取得公平的市場機率估計",
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
  authors: [{ name: "No-Vig NBA" }],
  icons: {
    icon: "/favicon.ico",
  },
};

/**
 * 根佈局元件
 * 
 * 極簡設計：純色背景、無裝飾
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-TW">
      <body>
        <Providers>
          {/* 導航欄 */}
          <Navbar />
          
          {/* 主要內容區域 */}
          <main className="min-h-screen pt-20">
            {children}
          </main>
          
          {/* 頁尾 - 極簡風格 */}
          <footer className="footer">
            <div className="max-w-4xl mx-auto px-6">
              <p className="text-sm mb-1">
                本站為資訊與數據分析用途，不構成投注建議
              </p>
              <p className="text-xs text-light">
                資料可能延遲或缺漏，以外部供應商為準
              </p>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
