import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { z } from "zod";

import * as schemas from "@/lib/schemas";
import metricsFixture from "@/test/fixtures/metrics/bdl-rate-null.json";

const FRONTEND_ROOT = path.resolve(__dirname, "..");
const SOURCE_DIRS = ["app", "components", "contexts", "lib"];

function sourceFiles(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    const info = statSync(full);
    if (info.isDirectory()) {
      if (entry === "node_modules" || entry === "fixtures" || entry.startsWith(".")) continue;
      found.push(...sourceFiles(full));
      continue;
    }
    if (!/\.(ts|tsx|js|jsx)$/.test(entry)) continue;
    if (/\.(test|qa\.test)\.(ts|tsx)$/.test(entry)) continue;
    found.push(full);
  }
  return found;
}

describe("metrics payload from backend PR 127", () => {
  it("loads a payload with bdl_rate null and no odds_api_quota", () => {
    expect(metricsFixture).toMatchObject({ bdl_rate: null });
    expect(metricsFixture).not.toHaveProperty("odds_api_quota");
  });

  it("has no frontend reader and no schema key for quota fields", () => {
    const hits: string[] = [];
    for (const file of SOURCE_DIRS.flatMap((dir) => sourceFiles(path.join(FRONTEND_ROOT, dir)))) {
      const text = readFileSync(file, "utf8");
      if (/odds_api_quota|bdl_rate|\/metrics|the-odds-api|theoddsapi/.test(text)) {
        hits.push(path.relative(FRONTEND_ROOT, file));
      }
    }
    expect(hits).toEqual([]);

    for (const value of Object.values(schemas)) {
      if (!(value instanceof z.ZodObject)) continue;
      const shape = value.shape as Record<string, z.ZodTypeAny>;
      expect(shape).not.toHaveProperty("odds_api_quota");
      if ("bdl_rate" in shape) {
        expect(shape.bdl_rate.safeParse(null).success).toBe(true);
      }
      const parsed = value.safeParse(metricsFixture);
      if (!parsed.success) {
        for (const issue of parsed.error.issues) {
          expect(issue.path.join(".")).not.toBe("odds_api_quota");
          expect(issue.path.join(".")).not.toBe("bdl_rate");
        }
      }
    }
  });
});
