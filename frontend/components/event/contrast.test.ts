import { describe, expect, it } from "vitest";

/**
 * Ratios for text colors introduced on the game page.
 * Body text needs 4.5:1. Large text (24px, or 18.66px bold) and UI need 3:1.
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
const pairs: Array<{ where: string; foreground: string; background: string; minimum: number }> = [
  { where: "EventHeader.tsx:65 away abbr, white on brand", foreground: WHITE, background: "#3E0F8D", minimum: 4.5 },
  { where: "EventHeader.tsx:68 home abbr, white on brand-soft", foreground: WHITE, background: "#9564DD", minimum: 4.5 },
  { where: "EventHeader.tsx:73 title, ink on white", foreground: "#1D1530", background: WHITE, minimum: 4.5 },
  { where: "EventHeader.tsx:76 clock, muted on white", foreground: "#625B70", background: WHITE, minimum: 4.5 },
  { where: "EventHeader.tsx:8 projected chip", foreground: "#5A5310", background: "#F6F2D2", minimum: 4.5 },
  { where: "EventHeader.tsx:10 missing chip", foreground: "#4A4458", background: "#E2E2E2", minimum: 4.5 },
  { where: "OurRead.tsx:118 market name, large brand-soft on white", foreground: "#9564DD", background: WHITE, minimum: 3 },
  { where: "OurRead.tsx:56 under label, 14px on white", foreground: "#5B3A99", background: WHITE, minimum: 4.5 },
  { where: "OurRead.tsx:157 ask, brand on tint", foreground: "#3E0F8D", background: "#ECE6F7", minimum: 4.5 },
  { where: "OurRead.tsx:10 pass tier", foreground: "#4A4458", background: "#E2E2E2", minimum: 4.5 },
  { where: "GameLogChart.tsx:44 axis labels", foreground: "#8A8496", background: WHITE, minimum: 4.5 },
  { where: "GameLogChart.tsx:108 opponent labels", foreground: "#8A8496", background: WHITE, minimum: 4.5 },
  { where: "GameLogChart.tsx:95 line tag", foreground: "#2A0A60", background: "#E4DA72", minimum: 4.5 },
  { where: "EventTabs.tsx:27 selected tab", foreground: "#3E0F8D", background: WHITE, minimum: 4.5 },
  { where: "EventTabs.tsx:27 idle tab", foreground: "#4A4458", background: "#F3F1F6", minimum: 4.5 },
  { where: "EventDetail.tsx:658 stat label", foreground: "#4A4458", background: "#F7F6F9", minimum: 4.5 },
  { where: "GameFilters.tsx:139 disabled Home/Away", foreground: "#625B70", background: "#F3F1F6", minimum: 3 },
];

describe("game page text contrast", () => {
  it("keeps new text at 4.5:1, or 3:1 when the type is large", () => {
    const failures = pairs
      .filter((pair) => contrast(pair.foreground, pair.background) < pair.minimum)
      .map((pair) => {
        const ratio = contrast(pair.foreground, pair.background).toFixed(2);
        return `${pair.where}: ${ratio}:1`;
      });
    expect(failures).toEqual([]);
  });

  it("keeps the faded venue control at 3:1 after opacity", () => {
    const card = WHITE;
    const track = blend("#F3F1F6", card, 0.6);
    const label = blend("#625B70", track, 0.6);
    const ratio = contrast(label, track);
    expect(ratio).toBeGreaterThanOrEqual(3);
  });
});
