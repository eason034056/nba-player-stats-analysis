/**
 * wnba/betslip/page.tsx — WNBA bet slip (SPO-37 Phase 6).
 *
 * Sister page of `/betslip/page.tsx`. Structurally parallel by design, with
 * three deliberate omissions relative to NBA:
 *
 *   1. No "Review My Slip" agent button. The agent chat endpoint
 *      (`sendAgentChat` in `frontend/lib/api.ts`) is NBA-hardcoded; routing a
 *      WNBA slip through it would produce wrong context. WNBA agent surfacing
 *      is tracked separately — Phase 5c shipped the WNBA chat *endpoint*,
 *      but the widget action layer still defaults to NBA. Out of scope here.
 *
 *   2. No lineup badges. `getLineups` only hits `/api/nba/lineups`. A WNBA
 *      equivalent helper does not exist yet; adding one is a one-line
 *      follow-up but not on the SPO-37 spec.
 *
 *   3. Header copy reads "WNBA" instead of "NBA". Share-image header reads
 *      "My WNBA Picks". This is the only "league discriminator" — a string
 *      label, not state.
 *
 * Everything else (remove / clearAll / share-as-PNG / clipboard copy /
 * Web Share API) mirrors NBA byte-for-byte from the user's perspective.
 *
 * ⚠ This file reads `useWnbaBetSlip`, never `useBetSlip`. Mixing them would
 * defeat the entire point of Phase 6.
 */

"use client";

import { useState, useRef, useCallback } from "react";
import Link from "next/link";
import {
  ClipboardList,
  Trash2,
  X,
  ExternalLink,
  Download,
  Copy,
  Image as ImageIcon,
  Check,
  Flame,
  TrendingUp,
  Share2,
} from "lucide-react";
import {
  useWnbaBetSlip,
  type BetSlipPick,
} from "@/contexts/WnbaBetSlipContext";
import { buildEventDetailHref } from "@/lib/event-detail-link";
import { metricToMarket } from "@/lib/metric-to-market";
import { TeamLogo } from "@/components/TeamLogo";
import { getShortTeamName } from "@/lib/team-logos";
import {
  METRIC_DISPLAY_NAMES,
  DIRECTION_DISPLAY_NAMES,
} from "@/lib/schemas";
import { formatProbability } from "@/lib/utils";

// 💡 Reused inline constants from NBA betslip page. Kept duplicated (rather
// than exported from the NBA file) because these are *visual* constants for a
// PNG export template — neither file should drag the other along when the
// design changes.
const SHARE_FONT_SANS =
  "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";
const SHARE_FONT_MONO =
  "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace";

function getProbabilityLevel(probability: number): "high" | "medium" {
  // 0.70 cutoff aligned with NBA so the green/yellow signal reads
  // consistently across leagues (per SPO-35 Phase 3 rationale).
  return probability >= 0.7 ? "high" : "medium";
}

function formatGameTime(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

// ----------------------------------------------------------------- card -----

function WnbaBetSlipCard({
  pick,
  onRemove,
}: {
  pick: BetSlipPick;
  onRemove: () => void;
}) {
  const level = getProbabilityLevel(pick.probability);
  const metricName = METRIC_DISPLAY_NAMES[pick.metric] || pick.metric;
  const directionName =
    DIRECTION_DISPLAY_NAMES[pick.direction] || pick.direction;

  const marketKey = metricToMarket(pick.metric);
  const detailHref = buildEventDetailHref({
    eventId: pick.event_id,
    commenceTime: pick.commence_time,
    player: pick.player_name,
    market: marketKey,
    threshold: pick.threshold,
    // 💡 Critical: route detail link to the WNBA event page, not the NBA one.
    // The shared `buildEventDetailHref` accepts a league flag for this reason
    // (see SPO-35 task summary).
    league: "wnba",
  });

  return (
    <div className="card group animate-fade-in">
      <div className="flex items-start gap-4">
        <TeamLogo
          teamName={pick.player_team || pick.home_team}
          size={48}
          className="shrink-0"
        />

        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between mb-2">
            <div>
              <h3 className="text-lg font-semibold text-dark">
                {pick.player_name}
              </h3>
              <p className="text-sm text-gray">
                {pick.player_team && (
                  <span className="font-medium">
                    {getShortTeamName(pick.player_team)} ·{" "}
                  </span>
                )}
                {pick.away_team} @ {pick.home_team}
              </p>
            </div>

            <button
              onClick={onRemove}
              className="p-2 rounded-full text-gray hover:text-red hover:bg-red/10 transition-colors"
              title="Remove from bet slip"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="flex items-center justify-between mb-3">
            <div
              className={`
                px-3 py-1.5 rounded-lg text-sm font-bold
                ${pick.direction === "over"
                  ? "bg-green-500/10 text-green-600 border border-green-500/30"
                  : "bg-blue-500/10 text-blue-600 border border-blue-500/30"
                }
              `}
            >
              {metricName} {directionName} {pick.threshold}
            </div>

            <div className="flex items-center gap-2">
              {level === "high" && (
                <Flame className="w-4 h-4 text-green-500" />
              )}
              <span
                className={`
                  text-2xl font-mono font-bold
                  ${level === "high" ? "text-green-500" : "text-yellow"}
                `}
              >
                {formatProbability(pick.probability)}
              </span>
            </div>
          </div>

          <div className="flex items-center justify-between text-sm">
            <span className="text-gray">
              {formatGameTime(pick.commence_time)}
            </span>
            <Link
              href={detailHref}
              className="flex items-center gap-1 text-red hover:underline font-medium"
            >
              <span>View Details</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="card text-center py-16">
      <div className="w-20 h-20 mx-auto mb-6 rounded-full border border-white/10 bg-white/4 flex items-center justify-center">
        <ClipboardList className="w-10 h-10 text-gray" />
      </div>
      <h3 className="text-2xl font-semibold text-dark mb-3">
        Your WNBA Bet Slip is Empty
      </h3>
      <p className="text-gray mb-8 max-w-md mx-auto">
        Right-click on any pick in the WNBA Daily Picks page to add it to your
        WNBA bet slip.
      </p>
      <Link
        href="/wnba/picks"
        className="btn-primary inline-flex items-center gap-2"
      >
        <TrendingUp className="w-4 h-4" />
        Browse WNBA Daily Picks
      </Link>
    </div>
  );
}

// --------------------------------------------------------------- share -----

/**
 * Share-image template — captured by html-to-image into a PNG. Hard-coded
 * pixel sizes and inline styles guarantee deterministic export, independent
 * of the live Tailwind cascade.
 */
function ShareImageTemplate({
  picks,
  forwardedRef,
}: {
  picks: BetSlipPick[];
  forwardedRef: React.RefObject<HTMLDivElement>;
}) {
  const today = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });

  return (
    <div
      ref={forwardedRef}
      style={{
        width: 600,
        padding: 32,
        background: "#FFF2DF",
        fontFamily: SHARE_FONT_SANS,
        fontSize: 16,
        boxSizing: "border-box",
        fontSynthesis: "none",
        textRendering: "geometricPrecision",
      }}
    >
      <div
        style={{
          marginBottom: 24,
          padding: 20,
          background: "#E92016",
          borderRadius: 12,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            marginBottom: 4,
          }}
        >
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: 8,
              background: "#FFF2DF",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <span style={{ fontSize: 24, lineHeight: "24px" }}>🏀</span>
          </div>
          <div
            style={{
              fontSize: 24,
              fontWeight: 800,
              color: "#FFF2DF",
              margin: 0,
              lineHeight: 1.15,
            }}
          >
            My WNBA Picks
          </div>
        </div>
        <div
          style={{
            fontSize: 14,
            color: "rgba(255,242,223,0.8)",
            margin: 0,
            marginLeft: 52,
            lineHeight: 1.35,
          }}
        >
          {today}
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {picks.map((pick) => {
          const level = getProbabilityLevel(pick.probability);
          const metricName =
            METRIC_DISPLAY_NAMES[pick.metric] || pick.metric;
          const directionName =
            DIRECTION_DISPLAY_NAMES[pick.direction] || pick.direction;

          return (
            <div
              key={pick.id}
              style={{
                background: "#FFFFFF",
                borderRadius: 12,
                padding: 16,
                border: "2px solid #1a1a1a",
                position: "relative" as const,
              }}
            >
              {level === "high" && (
                <div
                  style={{
                    position: "absolute" as const,
                    top: 12,
                    right: 12,
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    padding: "4px 10px",
                    borderRadius: 999,
                    background: "#22c55e",
                    color: "#fff",
                    fontSize: 11,
                    fontWeight: 700,
                    lineHeight: 1,
                  }}
                >
                  🔥 HOT
                </div>
              )}

              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 12,
                  marginBottom: 12,
                }}
              >
                <div
                  style={{ flex: 1, paddingRight: level === "high" ? 70 : 0 }}
                >
                  <div
                    style={{
                      fontSize: 18,
                      fontWeight: 700,
                      color: "#1a1a1a",
                      margin: 0,
                      marginBottom: 4,
                      lineHeight: 1.2,
                    }}
                  >
                    {pick.player_name}
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      color: "#666",
                      margin: 0,
                      lineHeight: 1.35,
                    }}
                  >
                    {pick.player_team && (
                      <span style={{ fontWeight: 500 }}>
                        {getShortTeamName(pick.player_team)} ·{" "}
                      </span>
                    )}
                    {pick.away_team} @ {pick.home_team}
                  </div>
                </div>
              </div>

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <div
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "8px 16px",
                    borderRadius: 8,
                    fontSize: 14,
                    fontWeight: 700,
                    lineHeight: 1.2,
                    background:
                      pick.direction === "over"
                        ? "rgba(34, 197, 94, 0.1)"
                        : "rgba(59, 130, 246, 0.1)",
                    color: pick.direction === "over" ? "#16a34a" : "#2563eb",
                    border:
                      pick.direction === "over"
                        ? "2px solid rgba(34, 197, 94, 0.3)"
                        : "2px solid rgba(59, 130, 246, 0.3)",
                  }}
                >
                  {metricName} {directionName} {pick.threshold}
                </div>

                <div
                  style={{
                    fontSize: 32,
                    fontWeight: 700,
                    fontFamily: SHARE_FONT_MONO,
                    color: level === "high" ? "#22c55e" : "#eab308",
                    minWidth: 100,
                    textAlign: "right" as const,
                    lineHeight: 1,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "flex-end",
                  }}
                >
                  {formatProbability(pick.probability)}
                </div>
              </div>

              <div
                style={{
                  marginTop: 12,
                  height: 6,
                  background: "rgba(0,0,0,0.1)",
                  borderRadius: 999,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    width: `${pick.probability * 100}%`,
                    background: level === "high" ? "#22c55e" : "#eab308",
                    borderRadius: 999,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>

      <div
        style={{
          marginTop: 24,
          paddingTop: 16,
          borderTop: "2px solid rgba(0,0,0,0.1)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div
          style={{
            fontSize: 13,
            color: "#666",
            margin: 0,
            fontWeight: 500,
            lineHeight: 1.35,
          }}
        >
          Generated by No-Vig WNBA
        </div>
        <div
          style={{
            fontSize: 13,
            color: "#666",
            margin: 0,
            fontWeight: 600,
            lineHeight: 1.35,
          }}
        >
          {picks.length} pick{picks.length !== 1 ? "s" : ""}
        </div>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------- page -----

export default function WnbaBetSlipPage() {
  const { picks, removePick, clearAll, count } = useWnbaBetSlip();
  const [showPreview, setShowPreview] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);
  const shareImageRef = useRef<HTMLDivElement>(null);

  /**
   * generateCanvas — render the share template into a canvas.
   *
   * Uses html-to-image's `toCanvas` (SVG foreignObject path) which preserves
   * CSS fidelity better than html2canvas. The post-step manually fills the
   * background to avoid transparent PNGs.
   */
  const generateCanvas = useCallback(async () => {
    if (!shareImageRef.current || picks.length === 0) return null;

    const { toCanvas } = await import("html-to-image");
    const element = shareImageRef.current;

    if ("fonts" in document) {
      await document.fonts.ready;
    }

    const rawCanvas = await toCanvas(element, {
      pixelRatio: 2,
      backgroundColor: "#FFF2DF",
      filter: () => true,
    });

    const canvas = document.createElement("canvas");
    canvas.width = rawCanvas.width;
    canvas.height = rawCanvas.height;

    const ctx = canvas.getContext("2d");
    if (!ctx) return rawCanvas;
    ctx.fillStyle = "#FFF2DF";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(rawCanvas, 0, 0);
    return canvas;
  }, [picks]);

  const handleDownload = useCallback(async () => {
    if (picks.length === 0) return;
    setIsGenerating(true);
    try {
      const canvas = await generateCanvas();
      if (!canvas) return;
      const url = canvas.toDataURL("image/png");
      const link = document.createElement("a");
      link.href = url;
      const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
      link.download = `wnba-picks-${timestamp}.png`;
      link.click();
    } catch (error) {
      console.error("Failed to generate WNBA share image:", error);
    } finally {
      setIsGenerating(false);
    }
  }, [picks, generateCanvas]);

  const handleCopyToClipboard = useCallback(async () => {
    if (picks.length === 0) return;
    setIsGenerating(true);
    try {
      const canvas = await generateCanvas();
      if (!canvas) return;
      const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob((b) => {
          if (b) resolve(b);
          else reject(new Error("Failed to create blob"));
        }, "image/png");
      });
      await navigator.clipboard.write([
        new ClipboardItem({ "image/png": blob }),
      ]);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (error) {
      console.error("Failed to copy WNBA share image:", error);
      alert(
        "Your browser may not support copying images. Please try downloading instead.",
      );
    } finally {
      setIsGenerating(false);
    }
  }, [picks, generateCanvas]);

  const handleShare = useCallback(async () => {
    if (picks.length === 0) return;
    if (!navigator.share) {
      handleDownload();
      return;
    }
    setIsGenerating(true);
    try {
      const canvas = await generateCanvas();
      if (!canvas) return;
      const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob((b) => {
          if (b) resolve(b);
          else reject(new Error("Failed to create blob"));
        }, "image/png");
      });
      const file = new File([blob], "wnba-picks.png", {
        type: "image/png",
      });
      await navigator.share({
        files: [file],
        title: "My WNBA Picks",
        text: `Check out my ${picks.length} WNBA pick${
          picks.length !== 1 ? "s" : ""
        } for today!`,
      });
    } catch (error) {
      // ⚠ Web Share API throws AbortError when the user dismisses the share
      // sheet — that's a normal cancellation, not a bug worth logging.
      if ((error as Error).name !== "AbortError") {
        console.error("Failed to share WNBA picks:", error);
      }
    } finally {
      setIsGenerating(false);
    }
  }, [picks, generateCanvas, handleDownload]);

  return (
    <div className="min-h-screen page-enter">
      <div className="mx-auto max-w-6xl px-6 py-10">
        <section className="grid gap-6 md:grid-cols-[1.15fr_0.85fr] mb-8">
          <div className="card">
            <div className="section-eyebrow">
              <ClipboardList className="mr-2 h-3.5 w-3.5" />
              My WNBA selections
            </div>

            <h1 className="hero-title mb-4">
              WNBA bet slip,
              <span className="text-gradient block">
                saved as a curated board.
              </span>
            </h1>

            <div className="accent-line mb-6" />

            <p className="max-w-2xl text-lg leading-8 text-gray">
              A separate slip for WNBA picks — adding a WNBA leg here never
              touches your NBA slip. Refine the board before tip-off, then
              export it as a shareable image.
            </p>
          </div>

          <div className="card">
            <p className="text-xs uppercase tracking-[0.22em] text-light mb-3">
              Slip status
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-light">
                  Saved picks
                </p>
                <p className="mt-2 text-3xl font-semibold text-dark">{count}</p>
              </div>
              <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-light">
                  Share mode
                </p>
                <p className="mt-2 text-sm font-semibold text-dark">
                  {showPreview ? "Previewing" : "Ready"}
                </p>
                <p className="text-xs text-gray">PNG / clipboard / web share</p>
              </div>
            </div>
          </div>
        </section>

        {count === 0 && <EmptyState />}

        {count > 0 && (
          <>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-8">
              <div className="flex items-center gap-3">
                <h2 className="text-xl font-semibold text-dark">Your Picks</h2>
                <span className="badge-neutral">
                  {count} {count === 1 ? "pick" : "picks"}
                </span>
              </div>

              <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                <button
                  onClick={() => setShowPreview(!showPreview)}
                  className="btn-refresh"
                >
                  <ImageIcon className="w-4 h-4" />
                  <span className="hidden sm:inline">
                    {showPreview ? "Hide Preview" : "Preview Image"}
                  </span>
                  <span className="sm:hidden">
                    {showPreview ? "Hide" : "Preview"}
                  </span>
                </button>

                <button
                  onClick={clearAll}
                  className="flex items-center gap-2 px-4 py-2 rounded-full text-sm font-bold text-red hover:bg-red/10 transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                  <span>Clear All</span>
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 mb-8">
              {picks.map((pick) => (
                <WnbaBetSlipCard
                  key={pick.id}
                  pick={pick}
                  onRemove={() => removePick(pick.id)}
                />
              ))}
            </div>

            {showPreview && (
              <div className="mb-8">
                <h3 className="text-lg font-semibold text-dark mb-4">
                  Share Image Preview
                </h3>
                <div className="overflow-x-auto pb-4">
                  <div className="inline-block rounded-[28px] overflow-hidden shadow-panel">
                    <ShareImageTemplate
                      picks={picks}
                      forwardedRef={shareImageRef}
                    />
                  </div>
                </div>
              </div>
            )}

            {!showPreview && (
              <div
                style={{
                  position: "fixed",
                  left: 0,
                  top: 0,
                  opacity: 0,
                  pointerEvents: "none",
                  zIndex: -1,
                }}
                aria-hidden="true"
              >
                <ShareImageTemplate
                  picks={picks}
                  forwardedRef={shareImageRef}
                />
              </div>
            )}

            <div className="card">
              <h3 className="text-lg font-semibold text-dark mb-4">
                Share Your WNBA Picks
              </h3>
              <p className="text-gray text-sm mb-6">
                Generate an image of your WNBA picks to share with friends on
                social media or messaging apps.
              </p>

              <div className="flex flex-wrap gap-3">
                <button
                  onClick={handleDownload}
                  disabled={isGenerating}
                  className="btn-primary flex items-center gap-2"
                >
                  <Download
                    className={`w-4 h-4 ${isGenerating ? "animate-pulse" : ""}`}
                  />
                  <span>{isGenerating ? "Generating..." : "Download PNG"}</span>
                </button>

                <button
                  onClick={handleCopyToClipboard}
                  disabled={isGenerating}
                  className="btn-refresh flex items-center gap-2"
                >
                  {copySuccess ? (
                    <>
                      <Check className="w-4 h-4 text-green-500" />
                      <span className="text-green-500">Copied!</span>
                    </>
                  ) : (
                    <>
                      <Copy
                        className={`w-4 h-4 ${isGenerating ? "animate-pulse" : ""}`}
                      />
                      <span>Copy to Clipboard</span>
                    </>
                  )}
                </button>

                <button
                  onClick={handleShare}
                  disabled={isGenerating}
                  className="btn-refresh flex items-center gap-2"
                >
                  <Share2
                    className={`w-4 h-4 ${isGenerating ? "animate-pulse" : ""}`}
                  />
                  <span>Share</span>
                </button>
              </div>
            </div>
          </>
        )}

        <div className="mt-16 text-center">
          <div className="divider-light mb-8" />
          <p className="text-sm text-gray max-w-lg mx-auto">
            Right-click on any pick in the WNBA Daily Picks page to quickly add
            or remove it from your WNBA bet slip. Selections are saved locally
            and persist across refreshes — independent from your NBA slip.
          </p>
        </div>
      </div>
    </div>
  );
}
