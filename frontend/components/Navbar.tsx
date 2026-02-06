/**
 * Navbar.tsx - Minimal Navigation Bar Component
 * 
 * Design Philosophy:
 * - Red background (#E92016) as brand identity
 * - White/cream text for contrast
 * - No shadows, no gradients
 * - Clean geometric shapes
 * 
 * 功能：
 * - 導航連結
 * - 下注列表入口（顯示當前數量 badge）
 */

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Info, Target, ClipboardList } from "lucide-react";
import { cn } from "@/lib/utils";
import { useBetSlip } from "@/contexts/BetSlipContext";

/**
 * Navigation links configuration
 */
const navLinks = [
  { href: "/", label: "Home", icon: Activity },
  { href: "/picks", label: "Daily Picks", icon: Target },
  { href: "/about", label: "About", icon: Info },
];

/**
 * Navbar component
 * 
 * Minimal design: red background, white text, no decoration
 * 包含下注列表入口按鈕，顯示當前已選數量
 */
export function Navbar() {
  const pathname = usePathname();
  const { count } = useBetSlip();
  const isBetSlipActive = pathname === "/betslip";

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 bg-red">
      <div className="max-w-4xl mx-auto px-6">
        <div className="flex items-center justify-between h-16">
          {/* Logo / Site name */}
          <Link 
            href="/" 
            className="flex items-center gap-3 group"
          >
            {/* Logo - 極簡圓形 */}
            <div className="w-10 h-10 rounded-lg bg-cream flex items-center justify-center">
              <span className="text-2xl">🏀</span>
            </div>
            
            {/* 網站名稱 */}
            <div className="flex flex-col">
              <span className="text-xl font-extrabold text-cream tracking-tight">
                No-Vig NBA
              </span>
              <span className="text-[10px] text-cream/70 -mt-0.5 tracking-wider uppercase font-medium">
                Fair Odds Calculator
              </span>
            </div>
          </Link>

          {/* Navigation links */}
          <div className="flex items-center gap-1">
            {navLinks.map((link) => {
              const isActive = pathname === link.href;
              const Icon = link.icon;

              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 rounded-lg",
                    "text-sm font-bold transition-all duration-150",
                    isActive
                      ? "bg-cream text-red"
                      : "text-cream/80 hover:text-cream hover:bg-white/10"
                  )}
                >
                  <Icon className="w-4 h-4" />
                  <span>{link.label}</span>
                </Link>
              );
            })}

            {/* Bet Slip 入口按鈕 */}
            <Link
              href="/betslip"
              className={cn(
                "relative flex items-center gap-2 px-4 py-2 rounded-lg ml-2",
                "text-sm font-bold transition-all duration-150",
                isBetSlipActive
                  ? "bg-cream text-red"
                  : "text-cream/80 hover:text-cream hover:bg-white/10"
              )}
            >
              <div className="relative">
                <ClipboardList className="w-4 h-4" />
                {/* 數量 badge */}
                {count > 0 && (
                  <span className={cn(
                    "absolute -top-2 -right-2.5",
                    "min-w-[18px] h-[18px] px-1",
                    "flex items-center justify-center",
                    "text-[10px] font-bold rounded-full",
                    isBetSlipActive
                      ? "bg-red text-white"
                      : "bg-cream text-red"
                  )}>
                    {count > 99 ? "99+" : count}
                  </span>
                )}
              </div>
              <span>Bet Slip</span>
            </Link>
          </div>
        </div>
      </div>
    </nav>
  );
}
