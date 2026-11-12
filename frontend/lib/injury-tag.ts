/**
 * injury-tag.ts
 *
 * The BDL injury word shown on a card. `injury_status` stays the stored
 * status (Doubtful still arrives there as Questionable). The tag text is
 * the raw word when it has a non-blank value, otherwise the stored status.
 * Out exclusion does not read this module.
 */

export interface InjuryPaint {
  tone: "out" | "doubtful" | "questionable" | "day-to-day" | "probable";
  label: string;
  fg: string;
  bg: string;
  chip: string;
}

export const INJURY_WORDS = [
  {
    tone: "out",
    label: "Out",
    fg: "#FFFFFF",
    bg: "#6E1E34",
    chip: "border border-solid border-transparent bg-[#6E1E34] text-white",
  },
  {
    tone: "doubtful",
    label: "Doubtful",
    fg: "#6E1E34",
    bg: "#F6E3EA",
    chip: "border border-solid border-[#6E1E34] bg-[#F6E3EA] text-[#6E1E34]",
  },
  {
    tone: "questionable",
    label: "Questionable",
    fg: "#5A5310",
    bg: "#F6F2D2",
    chip: "border border-solid border-[#5A5310] bg-[#F6F2D2] text-[#5A5310]",
  },
  {
    tone: "day-to-day",
    label: "Day-To-Day",
    fg: "#1D1530",
    bg: "#F1F0F3",
    chip: "border border-dashed border-[#4A4458] bg-[#F1F0F3] text-[#1D1530]",
  },
  {
    tone: "probable",
    label: "Probable",
    fg: "#12355B",
    bg: "#E7F2FB",
    chip: "border border-dotted border-[#12355B] bg-[#E7F2FB] text-[#12355B]",
  },
] satisfies readonly InjuryPaint[];

export type KnownInjuryTone = (typeof INJURY_WORDS)[number]["tone"];

export const NEUTRAL_PAINT = {
  fg: "#4A4458",
  bg: "#F1F0F3",
  chip: "border border-solid border-transparent bg-[#F1F0F3] text-[#4A4458]",
} as const;

export type InjuryTone = KnownInjuryTone | "neutral";

export interface InjuryTag {
  text: string;
  tone: InjuryTone;
}

/**
 * Fold a status the way the backend compares the five known words.
 * Trim, lowercase, treat "-" and "_" as spaces, then collapse whitespace.
 * `isOutPick` uses this on `injury_status` only, and only the exact key "out" blocks.
 */
export function injuryKey(status: string | null | undefined): string {
  const folded = (status ?? "").trim().toLowerCase().replace(/[-_]+/g, " ");
  return folded.replace(/\s+/g, " ").trim();
}

function presentWord(value: string | null | undefined): string | null {
  if (typeof value !== "string") return null;
  if (value.trim() === "") return null;
  return value;
}

export function injuryPaint(tone: InjuryTone): { fg: string; bg: string; chip: string } {
  if (tone === "neutral") return NEUTRAL_PAINT;
  const word = INJURY_WORDS.find((item) => item.tone === tone);
  if (!word) throw new Error(`Missing injury paint for ${tone}`);
  return { fg: word.fg, bg: word.bg, chip: word.chip };
}

export function canonicalInjuryTag(tone: KnownInjuryTone): InjuryTag {
  const word = INJURY_WORDS.find((item) => item.tone === tone);
  if (!word) throw new Error(`Missing injury word for ${tone}`);
  return { text: word.label, tone: word.tone };
}

export function injurySeverity(tag: InjuryTag): number {
  const index = INJURY_WORDS.findIndex((word) => word.tone === tag.tone);
  return index < 0 ? INJURY_WORDS.length : index;
}

/**
 * Tag for the raw word, or the stored status when raw is null or blank.
 * Null, a blank value with a null status, and Active draw nothing.
 * The five known words use the canonical label. `Day To Day`, `day_to_day`,
 * and `day-to-day` are Day-To-Day. Any other word is shown trimmed, in the
 * casing BDL sent, on the neutral chip.
 */
export function injuryTag(
  raw: string | null | undefined,
  status: string | null | undefined,
): InjuryTag | null {
  const display = presentWord(raw) ?? presentWord(status);
  if (display == null) return null;
  const key = injuryKey(display);
  if (key === "" || key === "active") return null;
  const known = INJURY_WORDS.find((word) => injuryKey(word.label) === key);
  if (known) return { text: known.label, tone: known.tone };
  return { text: display.trim(), tone: "neutral" };
}
