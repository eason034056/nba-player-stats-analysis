// @vitest-environment node
// 💡 這支 util 是純邏輯（無 DOM、無 React），用 node env 跳過 jsdom 載入鏈，
// 避免踩到 repo 既有的 @csstools/css-calc ESM/CJS interop 問題。
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import {
  METRIC_TO_MARKET,
  metricToMarket,
} from "@/lib/metric-to-market";
import { METRIC_DISPLAY_NAMES } from "@/lib/schemas";

// 💡 不從 @/components/MarketSelect import MARKETS——那會把 lucide-react +
// CSS transitive dep 拉進 jsdom，跑到 ESM/CJS interop 雷區。MarketKey 的
// 正確性已經由 `as const satisfies Record<string, MarketKey>` 在編譯時保證。

describe("metricToMarket", () => {
  it("covers every metric exposed via METRIC_DISPLAY_NAMES", () => {
    // 💡 巡迴 schemas.ts 上的 metric 公開名單，而不是硬列 12 個 key——
    // 下次新增 metric 時，只要在 METRIC_DISPLAY_NAMES 加了卻忘記在
    // METRIC_TO_MARKET 加，這個測試會立刻紅燈。
    const exposedMetrics = Object.keys(METRIC_DISPLAY_NAMES);
    const mapped = Object.keys(METRIC_TO_MARKET);
    expect(mapped.sort()).toEqual(exposedMetrics.sort());
  });

  it("returns the correct market for known metrics", () => {
    expect(metricToMarket("points")).toBe("player_points");
    expect(metricToMarket("threes_made")).toBe("player_threes");
    expect(metricToMarket("dd")).toBe("player_double_double");
    expect(metricToMarket("ra")).toBe("player_rebounds_assists");
  });

  describe("unknown metric fallback", () => {
    let warnSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    });

    afterEach(() => {
      warnSpy.mockRestore();
    });

    it("falls back to player_points and warns", () => {
      expect(metricToMarket("nonexistent_metric")).toBe("player_points");
      expect(warnSpy).toHaveBeenCalledOnce();
      expect(warnSpy.mock.calls[0][0]).toContain("nonexistent_metric");
    });

    it("does NOT match prototype keys like 'toString'", () => {
      // ⚠ 用 `in` 而不是 hasOwnProperty 的話，"toString" 會誤命中 Object.prototype
      expect(metricToMarket("toString")).toBe("player_points");
      expect(warnSpy).toHaveBeenCalledOnce();
    });
  });
});
