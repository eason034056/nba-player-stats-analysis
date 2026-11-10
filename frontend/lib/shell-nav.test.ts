import { describe, expect, it } from "vitest";

import {
  hrefForSection,
  isWnbaPath,
  leagueSwitchHref,
  shellSection,
} from "@/lib/shell-nav";

describe("shell navigation", () => {
  it("treats only the /wnba tree as the WNBA league", () => {
    expect(isWnbaPath("/wnba")).toBe(true);
    expect(isWnbaPath("/wnba/picks")).toBe(true);
    expect(isWnbaPath("/wnba/event/aces-liberty")).toBe(true);
    expect(isWnbaPath("/")).toBe(false);
    expect(isWnbaPath("/picks")).toBe(false);
    expect(isWnbaPath("/wnbax")).toBe(false);
  });

  it("keeps Today, Picks, and Bet Slip when the league switch flips", () => {
    expect(leagueSwitchHref("/", "wnba")).toBe("/wnba");
    expect(leagueSwitchHref("/wnba", "nba")).toBe("/");
    expect(leagueSwitchHref("/picks", "wnba")).toBe("/wnba/picks");
    expect(leagueSwitchHref("/wnba/picks", "nba")).toBe("/picks");
    expect(leagueSwitchHref("/betslip", "wnba")).toBe("/wnba/betslip");
    expect(leagueSwitchHref("/wnba/betslip", "nba")).toBe("/betslip");
  });

  it("sends Method and a page with no section to that league's Today", () => {
    expect(shellSection("/about")).toBe("method");
    expect(leagueSwitchHref("/about", "wnba")).toBe("/wnba");
    expect(leagueSwitchHref("/about", "nba")).toBe("/");
    expect(shellSection("/wnba/player/A%27ja%20Wilson")).toBeNull();
    expect(leagueSwitchHref("/wnba/player/A%27ja%20Wilson", "nba")).toBe("/");
    expect(leagueSwitchHref("/wnba/player/A%27ja%20Wilson", "wnba")).toBe("/wnba");
  });

  it("keeps an event page under Today and switches to the other league's Today", () => {
    expect(shellSection("/event/heat-bucks")).toBe("today");
    expect(shellSection("/wnba/event/aces-liberty")).toBe("today");
    expect(leagueSwitchHref("/event/heat-bucks", "wnba")).toBe("/wnba");
    expect(leagueSwitchHref("/wnba/event/aces-liberty", "nba")).toBe("/");
  });

  it("builds the four section hrefs for both leagues", () => {
    expect(hrefForSection("today", "nba")).toBe("/");
    expect(hrefForSection("picks", "nba")).toBe("/picks");
    expect(hrefForSection("slip", "nba")).toBe("/betslip");
    expect(hrefForSection("method", "nba")).toBe("/about");
    expect(hrefForSection("today", "wnba")).toBe("/wnba");
    expect(hrefForSection("picks", "wnba")).toBe("/wnba/picks");
    expect(hrefForSection("slip", "wnba")).toBe("/wnba/betslip");
    expect(hrefForSection("method", "wnba")).toBe("/about");
  });
});
