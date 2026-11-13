import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { brotliDecompressSync } from "node:zlib";
import { describe, expect, it } from "vitest";

const FONT_DIR = join(process.cwd(), "app/fonts");

const KNOWN_TAGS = [
  "cmap", "head", "hhea", "hmtx", "maxp", "name", "OS/2", "post", "cvt ", "fpgm", "glyf", "loca",
  "prep", "CFF ", "VORG", "EBDT", "EBLC", "gasp", "hdmx", "kern", "LTSH", "PCLT", "VDMX", "vhea",
  "vmtx", "BASE", "GDEF", "GPOS", "GSUB", "EBSC", "JSTF", "MATH", "CBDT", "CBLC", "COLR", "CPAL",
  "SVG ", "sbix", "acnt", "avar", "bdat", "bloc", "bsln", "cvar", "fdsc", "feat", "fmtx", "fvar",
  "gvar", "hsty", "just", "lcar", "mort", "morx", "opbd", "prop", "trak", "Zapf", "Silf", "Glat",
  "Gloc", "Feat", "Sill",
];

function base128(view: DataView, offset: number): [number, number] {
  let value = 0;
  for (let i = 0; i < 5; i += 1) {
    const byte = view.getUint8(offset + i);
    value = value * 128 + (byte & 0x7f);
    if ((byte & 0x80) === 0) return [value, offset + i + 1];
  }
  throw new Error("bad UIntBase128");
}

/** Code points in the cmap of a WOFF2 file. */
function woff2CodePoints(file: string): Set<number> {
  const bytes = readFileSync(join(FONT_DIR, file));
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (view.getUint32(0) !== 0x774f4632) throw new Error(`${file} is not WOFF2`);
  const numTables = view.getUint16(12);
  let offset = 48;
  const tables: { tag: string; length: number }[] = [];
  for (let i = 0; i < numTables; i += 1) {
    const flags = view.getUint8(offset);
    offset += 1;
    let tag: string;
    if ((flags & 0x3f) === 0x3f) {
      tag = String.fromCharCode(...Array.from(bytes.subarray(offset, offset + 4)));
      offset += 4;
    } else {
      tag = KNOWN_TAGS[flags & 0x3f];
    }
    const version = flags >> 6;
    let origLength: number;
    [origLength, offset] = base128(view, offset);
    let length = origLength;
    const transformed = tag === "glyf" || tag === "loca" ? version === 0 : version !== 0;
    if (transformed) [length, offset] = base128(view, offset);
    tables.push({ tag, length });
  }
  const data = brotliDecompressSync(bytes.subarray(offset));
  let cursor = 0;
  let cmap: Buffer | null = null;
  for (const table of tables) {
    if (table.tag === "cmap") cmap = data.subarray(cursor, cursor + table.length);
    cursor += table.length;
  }
  if (!cmap) throw new Error(`${file} has no cmap`);
  const cv = new DataView(cmap.buffer, cmap.byteOffset, cmap.byteLength);
  const points = new Set<number>();
  const subtables = cv.getUint16(2);
  for (let i = 0; i < subtables; i += 1) {
    const sub = cv.getUint32(4 + i * 8 + 4);
    const format = cv.getUint16(sub);
    if (format === 4) {
      const segX2 = cv.getUint16(sub + 6);
      const ends = sub + 14;
      const starts = ends + segX2 + 2;
      const deltas = starts + segX2;
      const ranges = deltas + segX2;
      for (let s = 0; s < segX2; s += 2) {
        const end = cv.getUint16(ends + s);
        const start = cv.getUint16(starts + s);
        const delta = cv.getInt16(deltas + s);
        const rangeOffset = cv.getUint16(ranges + s);
        for (let c = start; c <= end && c !== 0xffff; c += 1) {
          let glyph: number;
          if (rangeOffset === 0) glyph = (c + delta) & 0xffff;
          else {
            const at = ranges + s + rangeOffset + (c - start) * 2;
            glyph = cv.getUint16(at);
            if (glyph !== 0) glyph = (glyph + delta) & 0xffff;
          }
          if (glyph !== 0) points.add(c);
        }
      }
    } else if (format === 12) {
      const groups = cv.getUint32(sub + 12);
      for (let g = 0; g < groups; g += 1) {
        const base = sub + 16 + g * 12;
        const start = cv.getUint32(base);
        const end = cv.getUint32(base + 4);
        for (let c = start; c <= end; c += 1) points.add(c);
      }
    }
  }
  return points;
}

const sans = woff2CodePoints("InstrumentSans[wght].woff2");
const mono = woff2CodePoints("JetBrainsMono[wght].woff2");

// Glyphs neither original font had. They already painted from the fallback face.
const FALLBACK_BEFORE_SUBSET = new Set(Array.from("≥≈μσ⚠✓⏱⭐\uFE0F"));

function isCjkOrEmoji(cp: number): boolean {
  return (
    (cp >= 0x2e80 && cp <= 0x9fff) ||
    (cp >= 0x3000 && cp <= 0x303f) ||
    (cp >= 0xff00 && cp <= 0xffef) ||
    cp >= 0x1f000
  );
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(tsx?|css)$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}

/** Non-ASCII characters in UI source lines, with comment lines left out. */
function renderedCharacters(): Map<string, string> {
  const found = new Map<string, string>();
  for (const dir of ["app", "components", "lib", "contexts"]) {
    for (const file of sourceFiles(join(process.cwd(), dir))) {
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, index) => {
          const trimmed = line.trim();
          if (trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("/*")) return;
          const code = line.replace(/\s\/\/\s.*$/, "");
          for (const ch of Array.from(code)) {
            const cp = ch.codePointAt(0) ?? 0;
            if (cp > 0x7f && !isCjkOrEmoji(cp) && !found.has(ch)) {
              found.set(ch, `${file.replace(process.cwd() + "/", "")}:${index + 1}`);
            }
          }
        });
    }
  }
  return found;
}

describe("Latin font subsets", () => {
  it("keep printable ASCII in both faces", () => {
    for (let cp = 0x20; cp <= 0x7e; cp += 1) {
      expect(sans.has(cp), `sans U+${cp.toString(16)}`).toBe(true);
      expect(mono.has(cp), `mono U+${cp.toString(16)}`).toBe(true);
    }
  });

  it("cover every non-ASCII character the UI source renders, apart from the old fallback glyphs", () => {
    const missing = Array.from(renderedCharacters())
      .filter(([ch]) => !FALLBACK_BEFORE_SUBSET.has(ch))
      .filter(([ch]) => {
        const cp = ch.codePointAt(0) ?? 0;
        return !sans.has(cp) && !mono.has(cp);
      })
      .map(([ch, where]) => `${ch} U+${(ch.codePointAt(0) ?? 0).toString(16)} at ${where}`);
    expect(missing).toEqual([]);
  });

  it("keep the punctuation and name letters the cards print in the sans face", () => {
    for (const ch of Array.from("·×–—‘’“”…•°›←→−§éćñüö")) {
      expect(sans.has(ch.codePointAt(0) ?? 0), ch).toBe(true);
    }
  });

  it("keep the percent and line glyphs in the mono face", () => {
    for (const ch of Array.from("0123456789.%+−–—·≥")) {
      expect(mono.has(ch.codePointAt(0) ?? 0), ch).toBe(true);
    }
  });
});
