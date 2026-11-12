import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// jsdom has no layout, so these read the class lists the PR changed.
// The contract: every layout utility added for mobile is either max-md:
// or moved behind md:, so desktop (md and up) computes the same classes.

function classesOf(file: string, testId: string): string[] {
  const src = readFileSync(path.join(__dirname, file), "utf8");
  const at = src.indexOf(`data-testid="${testId}"`);
  expect(at, `${testId} in ${file}`).toBeGreaterThan(-1);
  const cls = src.slice(at).match(/className="([^"]+)"/);
  return cls ? cls[1].split(/\s+/) : [];
}

const unprefixedFlexSize = /^(flex-1|flex-\[.*\]|basis-.*)$/;

describe("QA: Picks card flex sizing is md-only", () => {
  it.each(["pick-player", "pick-prop", "pick-rate"])("%s has no unprefixed flex-1 / basis", (id) => {
    const classes = classesOf("picks/DailyPicksBoard.tsx", id);
    expect(classes.filter((c) => unprefixedFlexSize.test(c))).toEqual([]);
  });

});

describe("QA: WNBA signal rows keep basis-60 at every width", () => {
  it("the non-verdict branch is the unprefixed basis-60", () => {
    const src = readFileSync(path.join(__dirname, "event/OurRead.tsx"), "utf8");
    expect(src).toMatch(/showVerdict \? "md:basis-60" : "basis-60"/);
  });
});

describe("QA: odds table scroll is mobile-only", () => {
  it("the min width that forces the scroll is max-md only", () => {
    const src = readFileSync(path.join(__dirname, "ResultsTable.tsx"), "utf8");
    const scroll = src.slice(src.indexOf('data-testid="odds-table-scroll"'));
    expect(scroll.length).toBeGreaterThan(0);
    const table = scroll.match(/<table className="([^"]+)"/)![1].split(/\s+/);
    expect(table.filter((c) => c.startsWith("min-w-"))).toEqual([]);
    expect(table).toContain("max-md:min-w-[760px]");
  });
});
