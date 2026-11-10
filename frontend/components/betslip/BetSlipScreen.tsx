"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { LineupStatusBadge } from "@/components/LineupStatusBadge";
import { useAgentWidget } from "@/contexts/AgentWidgetContext";
import { useBetSlip, type BetSlipPick } from "@/contexts/BetSlipContext";
import { createAgentPickContextFromBetSlip } from "@/lib/agent-chat";
import { getLineups } from "@/lib/api";
import {
  slipDetailHref,
  slipMatchup,
  slipPropText,
  slipSummary,
  slipTeamCode,
  slipTierLabel,
} from "@/lib/bet-slip-board";
import { formatPercent } from "@/lib/player-dd";
import { getCanonicalTeamCode } from "@/lib/team-logos";
import { getLocalDateString } from "@/lib/utils";

const SHARE_FONT_SANS = "Instrument Sans, system-ui, sans-serif";
const SHARE_FONT_MONO = "JetBrains Mono, ui-monospace, monospace";

function ShareCard({
  picks,
  forwardedRef,
}: {
  picks: BetSlipPick[];
  forwardedRef: React.RefObject<HTMLDivElement>;
}) {
  const stamp = picks[0]?.commence_time
    ? new Date(picks[0].commence_time).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      })
    : "";
  const title = "My NBA Picks";

  return (
    <div
      ref={forwardedRef}
      style={{
        background: "#3E0F8D",
        borderRadius: 24,
        padding: 22,
        color: "#FFFFFF",
        fontFamily: SHARE_FONT_SANS,
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ fontWeight: 700, fontSize: 18 }}>{title}</div>
        <div style={{ fontFamily: SHARE_FONT_MONO, fontWeight: 600, fontSize: 11, color: "#E4DA72" }}>
          {stamp.toUpperCase()}
        </div>
      </div>
      {picks.map((pick) => (
        <div
          key={pick.id}
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 10,
            padding: "10px 0",
            borderTop: "1px solid rgba(255,255,255,0.16)",
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 700, fontSize: 14 }}>{pick.player_name}</div>
            <div style={{ fontSize: 12, color: "#D9CEF0" }}>{slipPropText(pick)}</div>
          </div>
          <div style={{ fontFamily: SHARE_FONT_MONO, fontWeight: 700, fontSize: 16, color: "#E4DA72" }}>
            {formatPercent(pick.probability)}
          </div>
        </div>
      ))}
      <div style={{ fontFamily: SHARE_FONT_MONO, fontWeight: 500, fontSize: 10, color: "#BFAEE3" }}>
        novig · for research only
      </div>
    </div>
  );
}

export function BetSlipScreen() {
  const { picks, removePick, clearAll, count } = useBetSlip();
  const { setPageContext, submitAction } = useAgentWidget();
  const [isGenerating, setIsGenerating] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);
  const shareImageRef = useRef<HTMLDivElement>(null);
  const picksHref = "/picks";
  const summary = useMemo(
    () => slipSummary(picks.map((pick) => pick.probability)),
    [picks],
  );

  const lineupDates = useMemo(() => {
    return Array.from(
      new Set(
        picks
          .map((pick) => getLocalDateString(pick.commence_time))
          .filter((value): value is string => Boolean(value)),
      ),
    ).sort();
  }, [picks]);

  const {
    data: lineupResponses,
    isLoading: isLineupsLoading,
    isError: isLineupsError,
  } = useQuery({
    queryKey: ["lineups", "betslip", lineupDates],
    queryFn: async () => Promise.all(lineupDates.map((date) => getLineups(date))),
    enabled: lineupDates.length > 0,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const lineupsByDateAndTeam = useMemo(() => {
    return new Map(
      (lineupResponses ?? []).flatMap((response) =>
        response.lineups.map((lineup) => [
          `${response.date}:${getCanonicalTeamCode(lineup.team)}`,
          lineup,
        ] as const),
      ),
    );
  }, [lineupResponses]);

  useEffect(() => {
    setPageContext({
      route: "/betslip",
    });
  }, [setPageContext]);

  const generateCanvas = useCallback(async () => {
    if (!shareImageRef.current || picks.length === 0) return null;
    const { toCanvas } = await import("html-to-image");
    if ("fonts" in document) {
      await document.fonts.ready;
    }
    const rawCanvas = await toCanvas(shareImageRef.current, {
      pixelRatio: 2,
      backgroundColor: "#3E0F8D",
    });
    const canvas = document.createElement("canvas");
    canvas.width = rawCanvas.width;
    canvas.height = rawCanvas.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return rawCanvas;
    ctx.fillStyle = "#3E0F8D";
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
      link.download = `nba-picks-${timestamp}.png`;
      link.click();
    } catch (downloadError) {
      console.error("Failed to generate image:", downloadError);
    } finally {
      setIsGenerating(false);
    }
  }, [generateCanvas, picks.length]);

  const handleCopyToClipboard = useCallback(async () => {
    if (picks.length === 0) return;
    setIsGenerating(true);
    try {
      const canvas = await generateCanvas();
      if (!canvas) return;
      const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob((next) => {
          if (next) resolve(next);
          else reject(new Error("Failed to create blob"));
        }, "image/png");
      });
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (copyError) {
      console.error("Failed to copy image:", copyError);
      alert("Your browser may not support copying images. Please try downloading instead.");
    } finally {
      setIsGenerating(false);
    }
  }, [generateCanvas, picks.length]);

  const handleShare = useCallback(async () => {
    if (picks.length === 0) return;
    if (!navigator.share) {
      await handleDownload();
      return;
    }
    setIsGenerating(true);
    try {
      const canvas = await generateCanvas();
      if (!canvas) return;
      const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob((next) => {
          if (next) resolve(next);
          else reject(new Error("Failed to create blob"));
        }, "image/png");
      });
      const file = new File([blob], "nba-picks.png", { type: "image/png" });
      const title = "My NBA Picks";
      await navigator.share({
        files: [file],
        title,
        text: `${title}: ${picks.length} saved ${picks.length === 1 ? "pick" : "picks"}.`,
      });
    } catch (shareError) {
      if ((shareError as Error).name !== "AbortError") {
        console.error("Failed to share:", shareError);
      }
    } finally {
      setIsGenerating(false);
    }
  }, [generateCanvas, handleDownload, picks]);

  const handleReviewSlip = useCallback(async () => {
    await submitAction({
      action: "review_slip",
      message: "Compare with my slip",
      contextPatch: {
        bet_slip: picks.map((pick) => createAgentPickContextFromBetSlip(pick)),
      },
    });
  }, [picks, submitAction]);

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-[22px] px-4 py-6 md:px-8 md:py-8">
      <div className="flex flex-col gap-2">
        <h1 className="text-[32px] font-bold leading-none tracking-[-0.035em] md:text-[52px]">
          Bet Slip
        </h1>
        <p className="text-[15px] text-muted">Your saved picks.</p>
      </div>

      {count === 0 ? (
        <div className="flex flex-col items-center gap-3.5 rounded-3xl border border-line bg-white px-6 py-12 text-center">
          <h2 className="text-xl font-bold">Nothing saved yet</h2>
          <p className="max-w-[360px] text-sm leading-6 text-muted">
            Add picks from Daily Picks or any game page. They collect here for review and sharing.
          </p>
          <Link
            href={picksHref}
            className="inline-flex min-h-11 items-center rounded-full bg-brand px-5 text-sm font-bold text-white"
          >
            Browse Daily Picks
          </Link>
        </div>
      ) : (
        <div className="flex flex-wrap items-start gap-5">
          <div className="flex min-w-0 flex-[3_1_420px] flex-col gap-2.5">
            <h2 className="sr-only">Your picks</h2>
            {picks.map((pick) => {
              const tier = slipTierLabel(pick.probability);
              const lineup =
                lineupsByDateAndTeam.get(
                  `${getLocalDateString(pick.commence_time)}:${getCanonicalTeamCode(pick.player_team)}`,
                ) ?? null;
              return (
                <article
                  key={pick.id}
                  className="flex items-center gap-3.5 rounded-[20px] border border-line bg-white px-4 py-4 md:px-[18px]"
                >
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-line font-mono text-[11px] font-bold text-brand">
                    {slipTeamCode(pick, "nba")}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-[15px] font-bold">{pick.player_name}</div>
                    <div className="mt-0.5 text-sm font-semibold text-brand">{slipPropText(pick)}</div>
                    <div className="mt-0.5 text-xs text-muted">
                      {slipMatchup(pick, "nba")}
                      {" · "}
                      <Link href={slipDetailHref(pick, "nba")} className="font-semibold text-brand underline">
                        Details
                      </Link>
                    </div>
                    <div className="mt-2">
                      <LineupStatusBadge
                        lineup={lineup}
                        playerName={pick.player_name}
                        isLoading={isLineupsLoading}
                        isError={isLineupsError}
                      />
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-mono text-xl font-bold text-brand">
                      {formatPercent(pick.probability)}
                    </div>
                    {tier ? <div className="text-[11px] font-semibold text-muted">{tier}</div> : null}
                  </div>
                  <button
                    type="button"
                    aria-label={`Remove ${pick.player_name}`}
                    onClick={() => removePick(pick.id)}
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-line bg-white text-base text-muted hover:border-red hover:text-red"
                  >
                    ×
                  </button>
                </article>
              );
            })}
            <div className="mt-1.5 flex flex-wrap gap-2.5">
              <button
                type="button"
                onClick={() => void handleReviewSlip()}
                className="min-h-11 rounded-full bg-brand-tint px-[18px] text-sm font-semibold text-brand"
              >
                Review with agent
              </button>
              <button
                type="button"
                onClick={clearAll}
                className="min-h-11 rounded-full px-[18px] text-sm font-semibold text-red"
              >
                Clear all
              </button>
            </div>
          </div>

          <div className="flex min-w-0 flex-[2_1_300px] flex-col gap-3.5">
            <div className="grid grid-cols-3 gap-2.5 rounded-[20px] border border-line bg-white p-[18px]">
              <div>
                <div className="font-mono text-[22px] font-bold">{summary.count}</div>
                <div className="text-xs text-muted">picks</div>
              </div>
              <div>
                <div className="font-mono text-[22px] font-bold">{summary.averageText}</div>
                <div className="text-xs text-muted">avg. probability</div>
              </div>
              <div>
                <div className="font-mono text-[22px] font-bold text-brand">{summary.allHitText}</div>
                <div className="text-xs text-muted">all hit</div>
              </div>
            </div>
            <p className="text-xs leading-5 text-muted">
              All hit is the product of the stored rates. It is not a joint probability from the API.
            </p>
            <ShareCard picks={picks} forwardedRef={shareImageRef} />
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void handleDownload()}
                disabled={isGenerating}
                className="min-h-11 flex-1 rounded-full bg-brand px-3.5 text-[13px] font-bold text-white disabled:opacity-50"
              >
                {isGenerating ? "Generating..." : "Download PNG"}
              </button>
              <button
                type="button"
                onClick={() => void handleCopyToClipboard()}
                disabled={isGenerating}
                className="min-h-11 flex-1 rounded-full border border-[#D3CCDF] bg-white px-3.5 text-[13px] font-semibold text-ink disabled:opacity-50"
              >
                {copySuccess ? "Copied!" : "Copy image"}
              </button>
              <button
                type="button"
                onClick={() => void handleShare()}
                disabled={isGenerating}
                className="min-h-11 flex-1 rounded-full border border-[#D3CCDF] bg-white px-3.5 text-[13px] font-semibold text-ink disabled:opacity-50"
              >
                Share
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
