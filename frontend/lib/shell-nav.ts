/**
 * shell-nav.ts
 *
 * Path helpers for the app shell. The league lives in the URL
 * (`/` versus `/wnba`), not in a provider. Bet Slip and Today follow
 * that path so the two slips never share a badge.
 */

export type LeagueId = "nba" | "wnba";

export type ShellSection = "today" | "picks" | "slip" | "method";

export function isWnbaPath(pathname: string): boolean {
  return pathname === "/wnba" || pathname.startsWith("/wnba/");
}

/**
 * Which shell tab the path belongs to.
 * An event page stays under Today. A player page and any other route
 * do not light a tab.
 */
export function shellSection(pathname: string): ShellSection | null {
  if (pathname === "/about") return "method";

  const rest = isWnbaPath(pathname)
    ? pathname.slice("/wnba".length) || "/"
    : pathname;

  if (rest === "/" || rest === "/event" || rest.startsWith("/event/")) {
    return "today";
  }
  if (rest === "/picks" || rest.startsWith("/picks/")) return "picks";
  if (rest === "/betslip" || rest.startsWith("/betslip/")) return "slip";
  return null;
}

export function hrefForSection(section: ShellSection, league: LeagueId): string {
  if (section === "method") return "/about";
  if (league === "wnba") {
    if (section === "today") return "/wnba";
    if (section === "picks") return "/wnba/picks";
    return "/wnba/betslip";
  }
  if (section === "today") return "/";
  if (section === "picks") return "/picks";
  return "/betslip";
}

/**
 * Where the league switch sends the reader.
 * Today, Picks, and Bet Slip keep their section. Method is one shared
 * page, so leaving it opens that league's Today. A route with no
 * section (a player page, for example) opens that league's Today.
 */
export function leagueSwitchHref(pathname: string, target: LeagueId): string {
  const section = shellSection(pathname);
  if (section === null || section === "method") {
    return target === "wnba" ? "/wnba" : "/";
  }
  return hrefForSection(section, target);
}
