import { postedLine } from "@/lib/event-page";
import {
  MISSING_QUOTE,
  consensusPriorCaption,
  fairYesValue,
  hideLine,
  noPriceText,
  responseIsBinary,
  usesSingleLegPrior,
  yesPriceText,
} from "@/lib/no-vig-display";
import { formatPercent } from "@/lib/player-dd";
import type { NoVigResponse } from "@/lib/schemas";
import { formatVig, getBookmakerDisplayName } from "@/lib/utils";

export interface PriceRow {
  bookmaker: string;
  book: string;
  vig: string;
  line: string | null;
  offLine: boolean;
  yes: string;
  no: string;
  fair: string;
  prior: boolean;
}

export interface SportsbookPrices {
  binary: boolean;
  yesLabel: "Over" | "Yes";
  noLabel: "Under" | "No";
  postedLine: string | null;
  consensus: string | null;
  priorCaption: string | null;
  updated: string | null;
  rows: PriceRow[];
}

export function updatedLabel(ageSeconds: number | null | undefined): string | null {
  if (typeof ageSeconds !== "number" || !Number.isFinite(ageSeconds) || ageSeconds < 0) return null;
  if (ageSeconds < 120) return `Updated ${Math.round(ageSeconds)} s ago`;
  if (ageSeconds < 7200) return `Updated ${Math.floor(ageSeconds / 60)} min ago`;
  return `Updated ${Math.floor(ageSeconds / 3600)} h ago`;
}

export function sportsbookPrices(data: NoVigResponse): SportsbookPrices {
  const binary = responseIsBinary(data);
  const posted = binary ? null : postedLine(data.results);
  const consensus = data.consensus
    ? binary
      ? data.consensus.p_yes_fair ?? data.consensus.p_over_fair
      : data.consensus.p_over_fair
    : null;
  return {
    binary,
    yesLabel: binary ? "Yes" : "Over",
    noLabel: binary ? "No" : "Under",
    postedLine: posted == null ? null : String(posted),
    consensus: consensus == null ? null : formatPercent(consensus),
    priorCaption: consensusPriorCaption(data),
    updated: updatedLabel(data.data_age_seconds),
    rows: data.results.map((row) => {
      const hidden = hideLine(row, data.market);
      const fair = fairYesValue(row);
      return {
        bookmaker: row.bookmaker,
        book: getBookmakerDisplayName(row.bookmaker),
        vig: formatVig(row.vig),
        line: hidden ? null : String(row.line),
        offLine: !hidden && posted != null && Math.round(row.line * 10) / 10 !== posted,
        yes: yesPriceText(row),
        no: noPriceText(row, binary),
        fair: fair == null ? MISSING_QUOTE : formatPercent(fair),
        prior: binary && usesSingleLegPrior(row),
      };
    }),
  };
}
