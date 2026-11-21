import { describe, expect, it } from "vitest";

import { hrefForSection, shellSection } from "@/lib/shell-nav";

describe("shell navigation", () => {
  it("builds the four section hrefs", () => {
    expect(hrefForSection("today")).toBe("/");
    expect(hrefForSection("picks")).toBe("/picks");
    expect(hrefForSection("slip")).toBe("/betslip");
    expect(hrefForSection("method")).toBe("/about");
  });

  it("keeps Today, Picks, Bet Slip, and Method on their own paths", () => {
    expect(shellSection("/")).toBe("today");
    expect(shellSection("/picks")).toBe("picks");
    expect(shellSection("/betslip")).toBe("slip");
    expect(shellSection("/about")).toBe("method");
  });

  it("keeps an event page under Today", () => {
    expect(shellSection("/event/heat-bucks")).toBe("today");
  });

  it("does not light a tab for a path outside the four sections", () => {
    expect(shellSection("/player/Stephen%20Curry")).toBeNull();
    expect(shellSection("/wnba")).toBeNull();
    expect(shellSection("/wnba/picks")).toBeNull();
  });
});
