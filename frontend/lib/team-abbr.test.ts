import { describe, expect, it } from "vitest";

import { teamAbbr, teamShortName } from "@/lib/team-abbr";

const WNBA_FULL_NAMES: Array<[string, string, string]> = [
  ["Atlanta Dream", "ATL", "Dream"],
  ["Chicago Sky", "CHI", "Sky"],
  ["Connecticut Sun", "CON", "Sun"],
  ["Dallas Wings", "DAL", "Wings"],
  ["Golden State Valkyries", "GSV", "Valkyries"],
  ["Indiana Fever", "IND", "Fever"],
  ["Los Angeles Sparks", "LAS", "Sparks"],
  ["Las Vegas Aces", "LVA", "Aces"],
  ["Minnesota Lynx", "MIN", "Lynx"],
  ["New York Liberty", "NYL", "Liberty"],
  ["Phoenix Mercury", "PHX", "Mercury"],
  ["Seattle Storm", "SEA", "Storm"],
  ["Toronto Tempo", "TOR", "Tempo"],
  ["Washington Mystics", "WAS", "Mystics"],
];

const NBA_FULL_NAMES: Array<[string, string, string]> = [
  ["Atlanta Hawks", "ATL", "Hawks"],
  ["Chicago Bulls", "CHI", "Bulls"],
  ["Dallas Mavericks", "DAL", "Mavericks"],
  ["Golden State Warriors", "GSW", "Warriors"],
  ["Indiana Pacers", "IND", "Pacers"],
  ["Los Angeles Lakers", "LAL", "Lakers"],
  ["Los Angeles Clippers", "LAC", "Clippers"],
  ["Minnesota Timberwolves", "MIN", "Timberwolves"],
  ["New York Knicks", "NYK", "Knicks"],
  ["Phoenix Suns", "PHX", "Suns"],
  ["Toronto Raptors", "TOR", "Raptors"],
  ["Washington Wizards", "WAS", "Wizards"],
];

describe("teamAbbr", () => {
  it("maps every WNBA franchise from the backend alias list", () => {
    for (const [name, code, short] of WNBA_FULL_NAMES) {
      expect(teamAbbr(name, "wnba")).toBe(code);
      expect(teamShortName(name, "wnba")).toBe(short);
    }
    expect(teamAbbr("LA Sparks", "wnba")).toBe("LAS");
    expect(teamAbbr("NY Liberty", "wnba")).toBe("NYL");
    expect(teamAbbr("Sun", "wnba")).toBe("CON");
    expect(teamAbbr("Las Vegas", "wnba")).toBe("LVA");
  });

  it("maps NBA franchises through the existing code table", () => {
    for (const [name, code, short] of NBA_FULL_NAMES) {
      expect(teamAbbr(name, "nba")).toBe(code);
      expect(teamShortName(name, "nba")).toBe(short);
    }
    expect(teamAbbr("Heat", "nba")).toBe("MIA");
    expect(teamAbbr("76ers", "nba")).toBe("PHI");
  });

  it("does not let one league's nickname resolve to the other league's code", () => {
    expect(teamAbbr("Chicago Bulls", "wnba")).toBe("BUL");
    expect(teamAbbr("Bulls", "wnba")).toBe("BUL");
    expect(teamAbbr("Chicago Sky", "nba")).toBe("SKY");
    expect(teamAbbr("Los Angeles Sparks", "nba")).toBe("SPA");
    expect(teamAbbr("Los Angeles Lakers", "wnba")).toBe("LAK");
    expect(teamAbbr("New York Liberty", "nba")).toBe("LIB");
    expect(teamAbbr("New York Knicks", "wnba")).toBe("KNI");
    expect(teamAbbr("Minnesota Lynx", "nba")).toBe("LYN");
    expect(teamAbbr("Lynx", "nba")).toBe("LYNX");
    expect(teamAbbr("Minnesota Timberwolves", "wnba")).toBe("TIM");
    expect(teamAbbr("Phoenix Mercury", "nba")).toBe("MER");
    expect(teamAbbr("Phoenix Suns", "wnba")).toBe("SUN");
    expect(teamAbbr("Golden State Valkyries", "nba")).toBe("VAL");
    expect(teamAbbr("Golden State Warriors", "wnba")).toBe("WAR");
    expect(teamAbbr("Dallas Wings", "nba")).toBe("WIN");
    expect(teamAbbr("Dallas Mavericks", "wnba")).toBe("MAV");
    expect(teamAbbr("Indiana Fever", "nba")).toBe("FEV");
    expect(teamAbbr("Indiana Pacers", "wnba")).toBe("PAC");
    expect(teamAbbr("Washington Mystics", "nba")).toBe("MYS");
    expect(teamAbbr("Washington Wizards", "wnba")).toBe("WIZ");
    expect(teamAbbr("Toronto Tempo", "nba")).toBe("TEM");
    expect(teamAbbr("Toronto Raptors", "wnba")).toBe("RAP");
    expect(teamAbbr("Seattle Storm", "nba")).toBe("STO");
    expect(teamAbbr("Connecticut Sun", "nba")).toBe("SUN");
    expect(teamAbbr("Connecticut", "wnba")).toBe("CON");
    expect(teamAbbr("Connecticut", "nba")).toBe("CONN");
    expect(teamAbbr("Connecticut", "nba")).not.toBe("CON");
  });

  it("returns an empty label for an empty name", () => {
    expect(teamAbbr("", "nba")).toBe("");
    expect(teamAbbr("", "wnba")).toBe("");
    expect(teamShortName("", "nba")).toBe("");
    expect(teamShortName("", "wnba")).toBe("");
  });
});
