/**
 * Navbar.tsx - Minimal Navigation Bar Component
 * 
 * Design Philosophy:
 * - Red background (#E92016) as brand identity
 * - White/cream text for contrast
 * - No shadows, no gradients
 * - Clean geometric shapes
 */

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Info, Target } from "lucide-react";
import { cn } from "@/lib/utils";

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
 */
export function Navbar() {
  const pathname = usePathname();

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 bg-red">
      <div className="max-w-6xl mx-auto px-6">
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
          </div>
        </div>
      </div>
    </nav>
  );
}
