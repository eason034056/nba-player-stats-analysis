import { describe, expect, it } from "vitest";

import { BOOKMAKERS, type BookmakerKey } from "@/lib/schemas";
import { getBookmakerDisplayName } from "@/lib/utils";

const BDL_BOOK_KEYS = [
  "draftkings",
  "fanduel",
  "betmgm",
  "caesars",
  "betrivers",
  "fanatics",
  "betparx",
  "ballybet",
  "betway",
  "rebet",
] as const satisfies readonly BookmakerKey[];

describe("BALLDONTLIE bookmakers", () => {
  it("lists the vendor keys in allow-list order", () => {
    expect(BOOKMAKERS.map((book) => book.key)).toEqual([...BDL_BOOK_KEYS]);
    expect(BOOKMAKERS).toHaveLength(10);
    expect(BOOKMAKERS.map((book) => book.key)).not.toContain("bally_bet");
    for (const retired of ["bovada", "betonlineag", "espnbet", "williamhill_us"]) {
      expect(BOOKMAKERS.map((book) => book.key)).not.toContain(retired);
    }
  });

  it("names the new books and keeps bally_bet as a display alias", () => {
    expect(getBookmakerDisplayName("fanatics")).toBe("Fanatics");
    expect(getBookmakerDisplayName("rebet")).toBe("Rebet");
    expect(getBookmakerDisplayName("ballybet")).toBe("Bally Bet");
    expect(getBookmakerDisplayName("bally_bet")).toBe("Bally Bet");
    expect(getBookmakerDisplayName("draftkings")).toBe("DraftKings");
  });

  it("passes an unknown key through unchanged", () => {
    expect(getBookmakerDisplayName("bovada")).toBe("bovada");
    expect(getBookmakerDisplayName("betonlineag")).toBe("betonlineag");
    expect(getBookmakerDisplayName("espnbet")).toBe("espnbet");
    expect(getBookmakerDisplayName("williamhill_us")).toBe("williamhill_us");
    expect(getBookmakerDisplayName("not-a-book")).toBe("not-a-book");
  });
});
