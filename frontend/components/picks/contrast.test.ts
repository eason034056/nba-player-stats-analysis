import { describe, expect, it } from "vitest";

/**
 * Ratios for colors added on the picks board, bet slip, method page,
 * and the light agent drawer. Normal text needs 4.5:1. Large text and
 * UI controls need 3:1.
 */

function channel(hex: string, index: number): number {
  const raw = parseInt(hex.replace("#", "").slice(index, index + 2), 16) / 255;
  return raw <= 0.04045 ? raw / 12.92 : ((raw + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  return 0.2126 * channel(hex, 0) + 0.7152 * channel(hex, 2) + 0.0722 * channel(hex, 4);
}

function contrast(foreground: string, background: string): number {
  const lighter = Math.max(luminance(foreground), luminance(background));
  const darker = Math.min(luminance(foreground), luminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

function blend(foreground: string, background: string, alpha: number): string {
  const fg = foreground.replace("#", "");
  const bg = background.replace("#", "");
  const hex = (index: number) =>
    Math.round(
      parseInt(fg.slice(index, index + 2), 16) * alpha +
        parseInt(bg.slice(index, index + 2), 16) * (1 - alpha),
    )
      .toString(16)
      .padStart(2, "0");
  return `#${hex(0)}${hex(2)}${hex(4)}`;
}

const WHITE = "#FFFFFF";
const CANVAS = "#EEEEEE";
const BRAND = "#3E0F8D";
const INK = "#1D1530";
const MUTED = "#625B70";
const ACCENT = "#E4DA72";
const YELLOW_INK = "#5A5310";

const pairs: Array<{ where: string; foreground: string; background: string; minimum: number }> = [
  { where: "DailyPicksBoard.tsx:164 eyebrow", foreground: "#7B4FC4", background: CANVAS, minimum: 4.5 },
  { where: "DailyPicksBoard.tsx:170 body", foreground: MUTED, background: CANVAS, minimum: 4.5 },
  { where: "DailyPicksBoard.tsx:179 strong count, 12px label", foreground: "#2A0A60", background: ACCENT, minimum: 4.5 },
  { where: "DailyPicksBoard.tsx:193 stale badge, text-yellow ink on accent", foreground: YELLOW_INK, background: ACCENT, minimum: 4.5 },
  { where: "DailyPicksBoard.tsx:193 fresh badge", foreground: "#166534", background: "#E5F2EA", minimum: 4.5 },
  { where: "DailyPicksBoard.tsx:404 hit rate, 24px bold", foreground: BRAND, background: WHITE, minimum: 3 },
  { where: "DailyPicksBoard.tsx:410 playable tier", foreground: WHITE, background: BRAND, minimum: 4.5 },
  { where: "DailyPicksBoard.tsx:27 lean tier", foreground: BRAND, background: "#E3DAF3", minimum: 4.5 },
  { where: "DailyPicksBoard.tsx:28 pass tier", foreground: "#4A4458", background: "#E2E2E2", minimum: 4.5 },
  { where: "DailyPicksBoard.tsx:512 tag", foreground: "#4A4458", background: "#F1F0F3", minimum: 4.5 },
  { where: "DailyPicksBoard.tsx:462 Ask", foreground: BRAND, background: "#ECE6F7", minimum: 4.5 },
  { where: "BetSlipScreen.tsx:49 share title, white on brand", foreground: WHITE, background: BRAND, minimum: 4.5 },
  { where: "BetSlipScreen.tsx:58 share stamp, 11px", foreground: ACCENT, background: BRAND, minimum: 4.5 },
  { where: "BetSlipScreen.tsx:75 share prop, 12px", foreground: "#D9CEF0", background: BRAND, minimum: 4.5 },
  { where: "BetSlipScreen.tsx:77 share percent, 16px bold", foreground: ACCENT, background: BRAND, minimum: 4.5 },
  { where: "BetSlipScreen.tsx:82 share footer, 10px", foreground: "#BFAEE3", background: BRAND, minimum: 4.5 },
  { where: "BetSlipScreen.tsx:305 leg percent, 20px bold", foreground: BRAND, background: WHITE, minimum: 3 },
  { where: "BetSlipScreen.tsx:332 Clear all", foreground: "#8E2C50", background: WHITE, minimum: 4.5 },
  { where: "AgentWidget.tsx:329 drawer title, 17px bold", foreground: WHITE, background: BRAND, minimum: 4.5 },
  { where: "AgentWidget.tsx:332 drawer subtitle, 12px", foreground: "#D9CEF0", background: BRAND, minimum: 4.5 },
  { where: "AgentWidget.tsx:42 light summary label", foreground: MUTED, background: WHITE, minimum: 4.5 },
  { where: "AgentWidget.tsx:45 light summary title", foreground: INK, background: WHITE, minimum: 4.5 },
  { where: "AgentWidgetComposer.tsx:124 composer text", foreground: INK, background: "#F7F6F9", minimum: 4.5 },
  { where: "AgentWidgetComposer.tsx:130 Send", foreground: WHITE, background: BRAND, minimum: 4.5 },
  { where: "globals.css:490 light remap of text-on-dark", foreground: INK, background: WHITE, minimum: 4.5 },
  { where: "globals.css:493 light remap of text-on-dark-muted", foreground: MUTED, background: WHITE, minimum: 4.5 },
  { where: "about/page.tsx:51 code block", foreground: "#EDE7F8", background: INK, minimum: 4.5 },
  { where: "about/page.tsx:53 code comment", foreground: "#8F86A3", background: INK, minimum: 4.5 },
  { where: "about/page.tsx:58 vig formula", foreground: ACCENT, background: INK, minimum: 4.5 },
  { where: "about/page.tsx:90 planned note", foreground: YELLOW_INK, background: "#F6F2D2", minimum: 4.5 },
  { where: "PlayerProjectionPanel.tsx:80 Easy, 20px bold", foreground: "#15803D", background: "#F0FDF4", minimum: 4.5 },
  { where: "PlayerProjectionPanel.tsx:83 Avg, 20px bold", foreground: "#A16207", background: "#FEFCE8", minimum: 4.5 },
  { where: "PlayerProjectionPanel.tsx:85 Hard, 20px bold on red/5", foreground: "#8E2C50", background: "#F9F4F6", minimum: 4.5 },
  { where: "PlayerProjectionPanel.tsx:427 Matchup caption on Easy", foreground: MUTED, background: "#F0FDF4", minimum: 4.5 },
  { where: "PlayerProjectionPanel.tsx:427 Matchup caption on Avg", foreground: MUTED, background: "#FEFCE8", minimum: 4.5 },
  { where: "PlayerProjectionPanel.tsx:427 Matchup caption on Hard", foreground: MUTED, background: "#F9F4F6", minimum: 4.5 },
  { where: "PlayerProjectionPanel.tsx:77 missing rank", foreground: MUTED, background: "#EFEFF1", minimum: 4.5 },
];

describe("picks, slip, and agent contrast", () => {
  it("keeps new text at 4.5:1, or 3:1 when the type is large", () => {
    const failures = pairs
      .map((pair) => {
        const ratio = contrast(pair.foreground, pair.background);
        return { ...pair, ratio };
      })
      .filter((pair) => pair.ratio < pair.minimum)
      .map((pair) => `${pair.where}: ${pair.ratio.toFixed(2)}:1`);
    expect(failures).toEqual([]);
  });

  it("pins the light-drawer line-moved label below 4.5:1", () => {
    const wash = blend("#FACC15", WHITE, 0.1);
    const ratio = contrast(ACCENT, wash);
    // AgentWidgetTranscript.tsx:88. text-accent stays #E4DA72 on the pale
    // yellow wash. The light-surface remap does not include text-accent.
    expect(ratio).toBeLessThan(4.5);
    expect(ratio).toBeCloseTo(1.38, 2);
  });
});
