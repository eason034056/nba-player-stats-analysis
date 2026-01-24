/**
 * Navbar.tsx - 導航欄元件
 * 
 * 網站頂部的導航欄，包含：
 * - Logo / 網站名稱
 * - 導航連結
 * 
 * 使用 fixed 定位，讓導航欄固定在頂部
 */

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Info, Zap } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * 導航連結配置
 */
const navLinks = [
  { href: "/", label: "首頁", icon: Activity },
  { href: "/about", label: "關於", icon: Info },
];

/**
 * Navbar 元件
 * 
 * 固定在頁面頂部的導航欄
 */
export function Navbar() {
  // 取得當前路徑，用於高亮當前頁面的導航連結
  const pathname = usePathname();

  return (
    <nav className="fixed top-0 left-0 right-0 z-50">
      {/* 背景層 */}
      <div className="absolute inset-0 bg-slate-950/80 backdrop-blur-xl border-b border-slate-800/50" />
      
      <div className="relative max-w-6xl mx-auto px-6">
        <div className="flex items-center justify-between h-16">
          {/* Logo / 網站名稱 */}
          <Link 
            href="/" 
            className="flex items-center gap-3 group"
          >
            {/* Logo 容器 */}
            <div className="relative">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center shadow-lg shadow-amber-500/20 group-hover:shadow-amber-500/40 transition-shadow">
                <span className="text-xl">🏀</span>
              </div>
              {/* 發光效果 */}
              <div className="absolute inset-0 rounded-xl bg-amber-500/20 blur-lg opacity-0 group-hover:opacity-100 transition-opacity" />
            </div>
            
            {/* 網站名稱 */}
            <div className="flex flex-col">
              <span className="text-xl font-bold text-white group-hover:text-gradient transition-colors">
                No-Vig NBA
              </span>
              <span className="text-[10px] text-slate-500 -mt-0.5 tracking-wider uppercase">
                Fair Odds Calculator
              </span>
            </div>
          </Link>

          {/* 導航連結 */}
          <div className="flex items-center gap-2">
            {navLinks.map((link) => {
              // 判斷是否為當前頁面
              const isActive = pathname === link.href;
              const Icon = link.icon;

              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={cn(
                    // 基礎樣式
                    "flex items-center gap-2 px-4 py-2.5 rounded-xl",
                    "text-sm font-medium transition-all duration-200",
                    // 根據是否為當前頁面切換樣式
                    isActive
                      ? "bg-gradient-to-r from-blue-600/20 to-cyan-600/20 text-blue-400 border border-blue-500/30"
                      : "text-slate-400 hover:text-white hover:bg-slate-800/80"
                  )}
                >
                  <Icon className="w-4 h-4" />
                  <span>{link.label}</span>
                </Link>
              );
            })}
          </div>
        </div>
      </div>
    </nav>
  );
}

