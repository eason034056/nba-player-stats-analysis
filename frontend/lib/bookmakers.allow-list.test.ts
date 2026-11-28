import { describe, expect, it } from "vitest";

import { BOOKMAKERS, type BookmakerKey } from "@/lib/schemas";
import { getBookmakerDisplayName } from "@/lib/utils";

const BDL_BOOKS: ReadonlyArray<{ key: BookmakerKey; name: string }> = [
  { key: "draftkings", name: "DraftKings" },
  { key: "fanduel", name: "FanDuel" },
  { key: "betmgm", name: "BetMGM" },
  { key: "caesars", name: "Caesars" },
  { key: "betrivers", name: "BetRivers" },
  { key: "fanatics", name: "Fanatics" },
  { key: "betparx", name: "BetPARX" },
  { key: "ballybet", name: "Bally Bet" },
  { key: "betway", name: "Betway" },
  { key: "rebet", name: "Rebet" },
];

describe("BOOKMAKERS allow-list", () => {
  it("is the ten BALLDONTLIE books in vendor order", () => {
    expect(BOOKMAKERS).toHaveLength(10);
    expect(BOOKMAKERS.map((book) => book.key)).toEqual(BDL_BOOKS.map((book) => book.key));
    expect(BOOKMAKERS.map((book) => book.name)).toEqual(BDL_BOOKS.map((book) => book.name));
    expect(BOOKMAKERS.map((book) => book.key)).not.toContain("bally_bet");
  });

  it("maps the display alias bally_bet onto the same name as ballybet", () => {
    expect(getBookmakerDisplayName("ballybet")).toBe("Bally Bet");
    expect(getBookmakerDisplayName("bally_bet")).toBe("Bally Bet");
    expect(getBookmakerDisplayName("bally_bet")).toBe(getBookmakerDisplayName("ballybet"));
  });
});
