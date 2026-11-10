/**
 * team-abbr.ts
 *
 * Short labels for a team name the API already returned.
 * NBA codes come from `getCanonicalTeamCode`. WNBA codes are the
 * RotoWire abbreviations in `backend/app/services/lineup_source_support.py`.
 * The two leagues share several letters (CHI, MIN, TOR, …) and must
 * not share one lookup table.
 */

import type { LeagueSegment } from "./event-detail-link";
import { getCanonicalTeamCode, getShortTeamName } from "./team-logos";

const WNBA_ALIASES: Record<string, readonly string[]> = {
  ATL: ["Atlanta Dream", "Dream", "ATL"],
  CHI: ["Chicago Sky", "Sky", "CHI"],
  CON: ["Connecticut Sun", "Sun", "Connecticut", "CON"],
  DAL: ["Dallas Wings", "Wings", "DAL"],
  GSV: ["Golden State Valkyries", "Valkyries", "GSV"],
  IND: ["Indiana Fever", "Fever", "IND"],
  LAS: ["Los Angeles Sparks", "Sparks", "LA Sparks", "LAS"],
  LVA: ["Las Vegas Aces", "Aces", "Las Vegas", "LVA"],
  MIN: ["Minnesota Lynx", "Lynx", "MIN"],
  NYL: ["New York Liberty", "Liberty", "NY Liberty", "NYL"],
  PHX: ["Phoenix Mercury", "Mercury", "PHX"],
  SEA: ["Seattle Storm", "Storm", "SEA"],
  TOR: ["Toronto Tempo", "Tempo", "TOR"],
  WAS: ["Washington Mystics", "Mystics", "WAS"],
};

function compact(value: string): string {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

const WNBA_LOOKUP: Record<string, string> = {};
for (const [code, aliases] of Object.entries(WNBA_ALIASES)) {
  WNBA_LOOKUP[compact(code)] = code;
  for (const alias of aliases) {
    WNBA_LOOKUP[compact(alias)] = code;
  }
}

function fallbackAbbr(name: string): string {
  const last = name.trim().split(/\s+/).filter(Boolean).pop() ?? name;
  const letters = last.replace(/[^A-Za-z0-9]/g, "");
  return (letters.slice(0, 3) || name.slice(0, 3)).toUpperCase();
}

export function teamAbbr(name: string, league: LeagueSegment): string {
  if (!name) return "";
  if (league === "wnba") {
    return WNBA_LOOKUP[compact(name)] ?? fallbackAbbr(name);
  }
  const code = getCanonicalTeamCode(name);
  if (code && code.length <= 4) return code;
  return fallbackAbbr(name);
}

export function teamShortName(name: string, league: LeagueSegment): string {
  if (!name) return "";
  if (league === "nba") return getShortTeamName(name);
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return parts.length > 1 ? parts[parts.length - 1] : name;
}
