"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAgentWidget } from "@/contexts/AgentWidgetContext";
import { useBetSlip } from "@/contexts/BetSlipContext";
import { useWnbaBetSlip } from "@/contexts/WnbaBetSlipContext";
import {
  hrefForSection,
  isWnbaPath,
  leagueSwitchHref,
  shellSection,
  type LeagueId,
  type ShellSection,
} from "@/lib/shell-nav";
import { cn } from "@/lib/utils";

const SECTIONS: { id: ShellSection; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "picks", label: "Picks" },
  { id: "slip", label: "Bet Slip" },
  { id: "method", label: "Method" },
];

function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center bg-brand font-mono font-bold text-accent",
        compact
          ? "h-[30px] w-[30px] rounded-mark-sm text-xs"
          : "h-[34px] w-[34px] rounded-mark text-[13px]",
      )}
    >
      NV
    </span>
  );
}

function LeagueSwitch({ pathname }: { pathname: string }) {
  const onWnba = isWnbaPath(pathname);
  const choice = (league: LeagueId, label: string) => {
    const active = league === "wnba" ? onWnba : !onWnba;
    return (
      <Link
        href={leagueSwitchHref(pathname, league)}
        aria-current={active ? "true" : undefined}
        className={cn(
          "rounded-badge px-[7px] py-[3px] font-mono text-[11px] font-bold leading-none",
          active ? "bg-brand-tint text-brand" : "text-muted hover:text-brand",
        )}
      >
        {label}
      </Link>
    );
  };

  return (
    <div role="group" aria-label="League" className="inline-flex items-center gap-0.5">
      {choice("nba", "NBA")}
      {choice("wnba", "WNBA")}
    </div>
  );
}

function SlipBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1.5 font-mono text-[11px] font-bold text-brand-ink">
      {count > 99 ? "99+" : count}
    </span>
  );
}

function SectionLinks({
  pathname,
  count,
  variant,
}: {
  pathname: string;
  count: number;
  variant: "bar" | "tabs";
}) {
  const league: LeagueId = isWnbaPath(pathname) ? "wnba" : "nba";
  const active = shellSection(pathname);

  return (
    <>
      {SECTIONS.map((section) => {
        const isActive = active === section.id;
        const href = hrefForSection(section.id, league);
        if (variant === "tabs") {
          return (
            <Link
              key={section.id}
              href={href}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                "relative flex min-h-14 flex-1 flex-col items-center gap-1.5 px-1 pb-1 pt-0 text-xs font-semibold",
                isActive ? "text-brand" : "text-muted",
              )}
            >
              <span
                className={cn(
                  "h-[3px] w-7 rounded-b-[3px]",
                  isActive ? "bg-brand" : "bg-transparent",
                )}
              />
              <span className="relative pt-1">
                {section.label}
                {section.id === "slip" && (
                  <span className="absolute -right-5 top-0">
                    <SlipBadge count={count} />
                  </span>
                )}
              </span>
            </Link>
          );
        }
        return (
          <Link
            key={section.id}
            href={href}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold",
              isActive ? "bg-brand-tint text-brand" : "text-ink-2 hover:bg-brand-tint/60",
            )}
          >
            <span>{section.label}</span>
            {section.id === "slip" && <SlipBadge count={count} />}
          </Link>
        );
      })}
    </>
  );
}

function AskAgentButton({ compact = false }: { compact?: boolean }) {
  const { openWidget } = useAgentWidget();
  return (
    <button
      type="button"
      onClick={openWidget}
      className={cn(
        "inline-flex items-center justify-center rounded-full bg-brand font-semibold text-white hover:bg-brand-deep",
        compact ? "min-h-10 px-3.5 text-[13px]" : "px-[18px] py-2.5 text-sm",
      )}
    >
      {compact ? "Ask agent" : "Ask the agent"}
    </button>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  const onWnba = isWnbaPath(pathname);
  const { count: nbaCount } = useBetSlip();
  const { count: wnbaCount } = useWnbaBetSlip();
  const count = onWnba ? wnbaCount : nbaCount;

  return (
    <div className="flex min-h-screen flex-col bg-canvas text-ink">
      <header className="sticky top-0 z-40 border-b border-line bg-white">
        <div
          data-testid="web-header"
          className="hidden h-header w-full grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center px-8 md:grid"
        >
          <div className="flex min-w-0 items-center gap-2.5 justify-self-start">
            <Link href={onWnba ? "/wnba" : "/"} className="flex items-center gap-2.5">
              <BrandMark />
              <span className="text-lg font-bold tracking-[-0.02em]">No-Vig</span>
            </Link>
            <LeagueSwitch pathname={pathname} />
          </div>
          <nav aria-label="Primary" className="flex items-center gap-1 justify-self-center">
            <SectionLinks pathname={pathname} count={count} variant="bar" />
          </nav>
          <div className="justify-self-end">
            <AskAgentButton />
          </div>
        </div>
        <div className="flex items-center justify-between px-4 pb-3 pt-3.5 md:hidden">
          <div className="flex items-center gap-2">
            <Link href={onWnba ? "/wnba" : "/"} className="flex items-center gap-2">
              <BrandMark compact />
              <span className="text-[17px] font-bold tracking-[-0.02em]">No-Vig</span>
            </Link>
            <LeagueSwitch pathname={pathname} />
          </div>
          <AskAgentButton compact />
        </div>
      </header>

      <main className="flex-1 pb-24 md:pb-0">{children}</main>

      <nav
        aria-label="Mobile"
        className="fixed inset-x-0 bottom-0 z-40 flex border-t border-line bg-white px-1.5 pb-2.5 md:hidden"
      >
        <SectionLinks pathname={pathname} count={count} variant="tabs" />
      </nav>
    </div>
  );
}
