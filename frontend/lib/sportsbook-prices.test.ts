// @vitest-environment node
import { describe, expect, it } from "vitest";

import bam from "@/test/fixtures/event/nba-no-vig-bam.json";
import ddOneSided from "@/test/fixtures/props-no-vig/player-double-double-one-sided.json";
import dd from "@/test/fixtures/props-no-vig/player-double-double.json";
import { noVigResponseSchema } from "@/lib/schemas";
import { sportsbookPrices, updatedLabel } from "@/lib/sportsbook-prices";

const parse = (raw: unknown) => noVigResponseSchema.parse(raw);

describe("sportsbookPrices", () => {
  it("builds one row per book with the posted line and the over consensus", () => {
    const model = sportsbookPrices(parse(bam));

    expect(model.binary).toBe(false);
    expect([model.yesLabel, model.noLabel]).toEqual(["Over", "Under"]);
    expect(model.postedLine).toBe("18.5");
    expect(model.consensus).toBe("54%");
    expect(model.updated).toBe("Updated 90 s ago");
    expect(model.rows.map((row) => row.book)).toEqual(["DraftKings", "FanDuel", "BetMGM"]);
    expect(model.rows[0]).toEqual({
      bookmaker: "draftkings",
      book: "DraftKings",
      vig: "4.2%",
      line: "18.5",
      offLine: false,
      yes: "-118",
      no: "-102",
      fair: "54%",
      prior: false,
    });
  });

  it("flags a book that posts a different line than the posted one", () => {
    const rows = sportsbookPrices(parse(bam)).rows;
    expect(rows.find((row) => row.bookmaker === "betmgm")).toMatchObject({ line: "19.5", offLine: true });
    expect(rows.filter((row) => row.offLine)).toHaveLength(1);
  });

  it("uses Yes/No, hides the synthetic line, and reads the yes consensus on a double-double", () => {
    const model = sportsbookPrices(parse(dd));

    expect(model.binary).toBe(true);
    expect([model.yesLabel, model.noLabel]).toEqual(["Yes", "No"]);
    expect(model.postedLine).toBeNull();
    expect(model.consensus).toBe("68%");
    expect(model.rows[0]).toMatchObject({ line: null, offLine: false, yes: "-250", no: "+200", fair: "68%" });
  });

  it("marks a one-sided book as prior-based and prints no No price for it", () => {
    const model = sportsbookPrices(parse(ddOneSided));
    const fanduel = model.rows.find((row) => row.bookmaker === "fanduel");

    expect(fanduel).toMatchObject({ prior: true, no: "—" });
    expect(model.rows.find((row) => row.bookmaker === "draftkings")?.prior).toBe(false);
    expect(model.priorCaption).not.toBeNull();
  });

  it("has no consensus when the response carries none", () => {
    const model = sportsbookPrices(parse({ ...bam, consensus: null }));
    expect(model.consensus).toBeNull();
  });
});

describe("updatedLabel", () => {
  it.each([
    [12, "Updated 12 s ago"],
    [119, "Updated 119 s ago"],
    [120, "Updated 2 min ago"],
    [7199, "Updated 119 min ago"],
    [7200, "Updated 2 h ago"],
  ])("prints %s seconds as %s", (age, label) => {
    expect(updatedLabel(age)).toBe(label);
  });

  it.each([null, undefined, Number.NaN, -1])("is null for %s", (age) => {
    expect(updatedLabel(age)).toBeNull();
  });
});
