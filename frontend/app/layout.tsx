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
import { Cormorant_Garamond, Manrope } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { Navbar } from "@/components/Navbar";

const sans = Manrope({
  subsets: ["latin"],
  variable: "--font-sans",
});

const display = Cormorant_Garamond({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-display",
});

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
      <body className={`${sans.variable} ${display.variable}`}>
        <Providers>
          <Navbar />

          <main className="page-shell min-h-screen pt-28">
            {children}
          </main>

          <footer className="footer">
            <div className="mx-auto max-w-6xl px-6">
              <div className="rounded-[28px] border border-white/8 bg-white/4 px-6 py-6 backdrop-blur-xl">
                <p className="text-sm text-dark mb-2">
                  No-Vig NBA 將賽程、機率、projection 與歷史表現整理成更可讀的分析體驗。
                </p>
                <p className="text-xs text-light">
                  本站內容僅供資訊與研究用途，不構成投注建議；即時賠率與資料可能延遲或缺漏，請以官方來源為準。
                </p>
              </div>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
