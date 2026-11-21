/**
 * team-abbr.ts
 *
 * Short labels for a team name the API already returned.
 * Codes come from `getCanonicalTeamCode`.
 */

import { getCanonicalTeamCode, getShortTeamName } from "./team-logos";

function fallbackAbbr(name: string): string {
  const last = name.trim().split(/\s+/).filter(Boolean).pop() ?? name;
  const letters = last.replace(/[^A-Za-z0-9]/g, "");
  return (letters.slice(0, 3) || name.slice(0, 3)).toUpperCase();
}

export function teamAbbr(name: string): string {
  if (!name) return "";
  const code = getCanonicalTeamCode(name);
  if (code && code.length <= 4) return code;
  return fallbackAbbr(name);
}

export function teamShortName(name: string): string {
  if (!name) return "";
  return getShortTeamName(name);
}
