import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SportsbookPrices } from "@/components/event/SportsbookPrices";
import { noVigResponseSchema } from "@/lib/schemas";
import bam from "@/test/fixtures/event/nba-no-vig-bam.json";
import ddOneSided from "@/test/fixtures/props-no-vig/player-double-double-one-sided.json";

const parse = (raw: unknown) => noVigResponseSchema.parse(raw);

function renderPrices(props: Partial<Parameters<typeof SportsbookPrices>[0]>) {
  return render(
    <SportsbookPrices data={null} isLoading={false} isError={false} errorText={null} {...props} />,
  );
}

describe("SportsbookPrices", () => {
  it("lists each book with its line, prices, and fair over percent", () => {
    renderPrices({ data: parse(bam) });

    const headers = screen.getAllByRole("columnheader").map((cell) => cell.textContent);
    expect(headers).toEqual(["Book", "Line", "Over", "Under", "Fair over"]);
    const draftkings = within(screen.getByTestId("price-row-draftkings")).getAllByRole("cell");
    expect(draftkings.map((cell) => cell.textContent)).toEqual([
      "DraftKingsvig 4.2%",
      "18.5",
      "-118",
      "-102",
      "54%",
    ]);
    expect(screen.getByText("No-vig consensus 54% over")).toBeInTheDocument();
    expect(screen.getByText("Line 18.5")).toBeInTheDocument();
    expect(screen.getByText("Updated 90 s ago")).toBeInTheDocument();
  });

  it("names the off-line book's line under the book on mobile", () => {
    renderPrices({ data: parse(bam) });

    const betmgm = within(screen.getByTestId("price-row-betmgm")).getAllByRole("cell")[0];
    expect(betmgm).toHaveTextContent("vig 4.8% · line 19.5");
    expect(within(screen.getByTestId("price-row-draftkings")).getAllByRole("cell")[0]).not.toHaveTextContent("line");
  });

  it("drops the line column and labels Yes/No on a double-double", () => {
    renderPrices({ data: parse(ddOneSided) });

    const headers = screen.getAllByRole("columnheader").map((cell) => cell.textContent);
    expect(headers).toEqual(["Book", "Yes", "No", "Fair yes"]);
    expect(screen.getByTestId("price-row-fanduel")).toHaveTextContent("4.5% single-leg prior");
    expect(screen.getByTestId("consensus-prior")).toBeInTheDocument();
  });

  it("says no book posted the market when the response has no rows", () => {
    renderPrices({ data: parse({ ...bam, results: [], consensus: null, message: "Player not found" }) });

    expect(screen.getByText("No bookmaker line right now")).toBeInTheDocument();
    expect(screen.getByText("Backend note: Player not found")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows a loading state and no stale table while the request runs", () => {
    renderPrices({ data: parse(bam), isLoading: true });

    expect(screen.getByLabelText("Loading prices")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("prints the request error", () => {
    renderPrices({ isError: true, errorText: "Odds request failed" });
    expect(screen.getByText("Odds request failed")).toBeInTheDocument();
  });
});
