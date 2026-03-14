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

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  ClipboardList,
  Info,
  Menu,
  Target,
  X,
} from "lucide-react";
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

function NavItem({
  href,
  label,
  icon: Icon,
  isActive,
  badge,
  onNavigate,
}: {
  href: string;
  label: string;
  icon: typeof Activity;
  isActive: boolean;
  badge?: number;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      aria-current={isActive ? "page" : undefined}
      onClick={onNavigate}
      className={cn(
        "group relative flex items-center gap-2.5 rounded-full px-4 py-2.5",
        "text-sm font-semibold tracking-[0.02em] transition-all duration-200",
        isActive
          ? "bg-white text-slate-950 shadow-[0_12px_40px_rgba(255,255,255,0.16)]"
          : "text-white/72 hover:bg-white/10 hover:text-white"
      )}
    >
      <span className="relative">
        <Icon className="h-4 w-4" />
        {typeof badge === "number" && badge > 0 && (
          <span
            className={cn(
              "absolute -right-2.5 -top-2 flex min-w-[18px] items-center justify-center rounded-full px-1 text-[10px] font-bold",
              isActive ? "bg-slate-950 text-white" : "bg-white text-slate-950"
            )}
          >
            {badge > 99 ? "99+" : badge}
          </span>
        )}
      </span>
      <span>{label}</span>
    </Link>
  );
}

/**
 * Navbar component
 * 
 * Minimal design: red background, white text, no decoration
 * 包含下注列表入口按鈕，顯示當前已選數量
 */
export function Navbar() {
  const pathname = usePathname();
  const { count } = useBetSlip();
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const isBetSlipActive = pathname === "/betslip";

  return (
    <nav className="fixed left-0 right-0 top-0 z-50 px-4 pt-4 sm:px-6">
      <div className="mx-auto max-w-6xl">
        <div className="rounded-[28px] border border-white/12 bg-[rgba(7,12,24,0.75)] px-4 py-3 shadow-[0_20px_70px_rgba(3,8,20,0.45)] backdrop-blur-xl sm:px-6">
          <div className="flex items-center justify-between gap-4">
            <Link
              href="/"
              className="group flex items-center gap-3"
              onClick={() => setIsMobileMenuOpen(false)}
            >
              <div className="flex h-11 w-11 items-center justify-center rounded-[18px] border border-white/12 bg-[radial-gradient(circle_at_top,#fff8e6_0%,#d9c7a0_100%)] text-xl shadow-[inset_0_1px_0_rgba(255,255,255,0.55)]">
                🏀
              </div>

              <div className="flex min-w-0 flex-col">
                <span className="truncate text-lg font-semibold tracking-[0.02em] text-white">
                  No-Vig NBA
                </span>
                <span className="truncate text-[10px] uppercase tracking-[0.34em] text-white/45">
                  Cinematic Data Atelier
                </span>
              </div>
            </Link>

            <div className="hidden items-center gap-2 md:flex">
              {navLinks.map((link) => (
                <NavItem
                  key={link.href}
                  href={link.href}
                  label={link.label}
                  icon={link.icon}
                  isActive={pathname === link.href}
                />
              ))}

              <NavItem
                href="/betslip"
                label="Bet Slip"
                icon={ClipboardList}
                isActive={isBetSlipActive}
                badge={count}
              />
            </div>

            <button
              type="button"
              aria-label={isMobileMenuOpen ? "Close navigation menu" : "Open navigation menu"}
              aria-expanded={isMobileMenuOpen}
              onClick={() => setIsMobileMenuOpen((open) => !open)}
              className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-white/12 bg-white/6 text-white transition-colors hover:bg-white/12 md:hidden"
            >
              {isMobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>

          {isMobileMenuOpen && (
            <div
              role="dialog"
              aria-label="Mobile navigation"
              className="mt-4 rounded-[24px] border border-white/10 bg-white/6 p-3 md:hidden"
            >
              <div className="grid gap-2">
                {navLinks.map((link) => (
                  <NavItem
                    key={link.href}
                    href={link.href}
                    label={link.label}
                    icon={link.icon}
                    isActive={pathname === link.href}
                    onNavigate={() => setIsMobileMenuOpen(false)}
                  />
                ))}

                <NavItem
                  href="/betslip"
                  label="Bet Slip"
                  icon={ClipboardList}
                  isActive={isBetSlipActive}
                  badge={count}
                  onNavigate={() => setIsMobileMenuOpen(false)}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
}
