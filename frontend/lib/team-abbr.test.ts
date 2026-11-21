import { describe, expect, it } from "vitest";

import { teamAbbr, teamShortName } from "@/lib/team-abbr";

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
  it("maps NBA franchises through the existing code table", () => {
    for (const [name, code, short] of NBA_FULL_NAMES) {
      expect(teamAbbr(name)).toBe(code);
      expect(teamShortName(name)).toBe(short);
    }
    expect(teamAbbr("Heat")).toBe("MIA");
    expect(teamAbbr("76ers")).toBe("PHI");
  });

  it("returns an empty label for an empty name", () => {
    expect(teamAbbr("")).toBe("");
    expect(teamShortName("")).toBe("");
  });
});
