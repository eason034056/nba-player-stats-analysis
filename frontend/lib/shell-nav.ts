/**
 * shell-nav.ts
 *
 * Path helpers for the app shell. Today, Picks, Bet Slip, and Method
 * are the four sections. An event page stays under Today.
 */

export type ShellSection = "today" | "picks" | "slip" | "method";

/**
 * Which shell tab the path belongs to.
 * An event page stays under Today. Any other route does not light a tab.
 */
export function shellSection(pathname: string): ShellSection | null {
  if (pathname === "/about") return "method";
  if (pathname === "/" || pathname === "/event" || pathname.startsWith("/event/")) {
    return "today";
  }
  if (pathname === "/picks" || pathname.startsWith("/picks/")) return "picks";
  if (pathname === "/betslip" || pathname.startsWith("/betslip/")) return "slip";
  return null;
}

export function hrefForSection(section: ShellSection): string {
  if (section === "method") return "/about";
  if (section === "today") return "/";
  if (section === "picks") return "/picks";
  return "/betslip";
}
