/**
 * injury-tag.ts
 *
 * The BDL injury word shown on a card. `injury_status` stays the stored
 * status (Doubtful still arrives there as Questionable). The tag text is
 * `injury_status_raw` when that field is present, otherwise `injury_status`.
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
    fg: "#166534",
    bg: "#E5F2EA",
    chip: "border border-solid border-[#166534] bg-[#E5F2EA] text-[#166534]",
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

export function injuryKey(status: string | null | undefined): string {
  return status?.trim().toLowerCase() ?? "";
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
 * Tag for `raw ?? status`.
 * Null, a blank string, and Active draw nothing.
 * The five known words use the canonical label. Any other word is shown
 * trimmed, in the casing BDL sent, on the neutral chip.
 */
export function injuryTag(
  raw: string | null | undefined,
  status: string | null | undefined,
): InjuryTag | null {
  const display = raw ?? status;
  if (typeof display !== "string") return null;
  const key = injuryKey(display);
  if (key === "" || key === "active") return null;
  const known = INJURY_WORDS.find((word) => injuryKey(word.label) === key);
  if (known) return { text: known.label, tone: known.tone };
  return { text: display.trim(), tone: "neutral" };
}
