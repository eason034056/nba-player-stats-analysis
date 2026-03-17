"use client";

import { useEffect } from "react";
import { X } from "lucide-react";

import type { AgentPageContext, AgentPickContext, AgentThreadMessage } from "@/lib/agent-chat";

import { AgentVerdictBreakdown } from "./AgentVerdictBreakdown";
import { formatPct } from "./presentation";

interface AgentWidgetAnalysisPanelProps {
  pageContext: AgentPageContext;
  selectedPickContext: AgentPickContext | null;
  lastAssistantMessage?: AgentThreadMessage;
  slipCount: number;
  isDesktop: boolean;
  onClose: () => void;
}

const AnalysisContent = ({
  pageContext,
  selectedPickContext,
  lastAssistantMessage,
  slipCount,
}: Omit<AgentWidgetAnalysisPanelProps, "isDesktop" | "onClose">) => {
  const verdict = lastAssistantMessage?.verdict;
  const riskNote = verdict?.risk_factors[0];
  const isLineMoved = verdict?.market_pricing_mode === "line_moved";
  const lineupContext = verdict?.lineup_context;

  useEffect(() => {
    if (lastAssistantMessage?.status !== "line_moved" || !verdict) {
      return;
    }

    console.debug("line_moved", {
      subject: verdict.subject,
      queried_line: verdict.queried_line,
      best_line: verdict.best_line,
    });
  }, [lastAssistantMessage?.status, verdict]);

  return (
    <div className="space-y-4">
      <div>
        <p className="text-[10px] uppercase tracking-[0.22em] text-light">
          Market snapshot
        </p>
        {verdict ? (
          <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
            <div className="rounded-[16px] border border-white/8 bg-white/5 px-3 py-2">
              <p className="text-[10px] uppercase tracking-[0.18em] text-light">Model</p>
              <p className="mt-1 font-semibold text-dark">
                {formatPct(verdict.model_probability)}
              </p>
            </div>
            <div className="rounded-[16px] border border-white/8 bg-white/5 px-3 py-2">
              <p className="text-[10px] uppercase tracking-[0.18em] text-light">Market</p>
              <p className="mt-1 font-semibold text-dark">
                {formatPct(verdict.market_implied_probability)}
              </p>
            </div>
            <div className="rounded-[16px] border border-white/8 bg-white/5 px-3 py-2">
              <p className="text-[10px] uppercase tracking-[0.18em] text-light">EV</p>
              <p className="mt-1 font-semibold text-dark">
                {formatPct(verdict.expected_value_pct)}
              </p>
            </div>
            <div className="rounded-[16px] border border-white/8 bg-white/5 px-3 py-2">
              <p className="text-[10px] uppercase tracking-[0.18em] text-light">Decision</p>
              <p className="mt-1 font-semibold uppercase text-dark">{verdict.decision}</p>
            </div>
            {isLineMoved ? (
              <div className="col-span-2 rounded-[16px] border border-yellow-400/25 bg-yellow-400/10 px-3 py-2">
                <p className="text-[10px] uppercase tracking-[0.18em] text-yellow-700">Line moved</p>
                <p className="mt-1 font-semibold text-dark">
                  Original {verdict.queried_line ?? "N/A"} {"->"} Live {verdict.best_line ?? "N/A"}
                </p>
                {verdict.available_lines.length > 0 ? (
                  <p className="mt-1 text-xs text-gray">
                    Available lines: {verdict.available_lines.join(", ")}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="mt-3 rounded-[18px] border border-white/8 bg-white/5 px-3 py-3 text-sm text-gray">
            Ask for a verdict to populate the market snapshot.
          </div>
        )}
      </div>

      <div>
        <p className="text-[10px] uppercase tracking-[0.22em] text-light">Context</p>
        <div className="mt-3 space-y-2">
          {selectedPickContext ? (
            <div className="rounded-[18px] border border-white/8 bg-white/5 px-3 py-3">
              <p className="text-sm font-semibold text-dark">
                {selectedPickContext.player_name} {selectedPickContext.metric}{" "}
                {selectedPickContext.direction} {selectedPickContext.threshold}
              </p>
              <p className="mt-1 text-sm text-gray">
                {selectedPickContext.away_team} at {selectedPickContext.home_team}
              </p>
            </div>
          ) : null}
          <div className="rounded-[18px] border border-white/8 bg-white/5 px-3 py-3">
            <p className="text-sm font-semibold text-dark">
              {pageContext.date ? `Board for ${pageContext.date}` : "Current board"}
            </p>
            <p className="mt-1 text-sm text-gray">
              {pageContext.selected_teams.length > 0
                ? `${pageContext.selected_teams.length} team filter${pageContext.selected_teams.length > 1 ? "s" : ""}`
                : "No active team filters"}
            </p>
          </div>
          <div className="rounded-[18px] border border-white/8 bg-white/5 px-3 py-3">
            <p className="text-sm font-semibold text-dark">Slip status</p>
            <p className="mt-1 text-sm text-gray">
              {slipCount > 0 ? `${slipCount} saved picks` : "No saved picks yet"}
            </p>
          </div>
        </div>
      </div>

      <div>
        <p className="text-[10px] uppercase tracking-[0.22em] text-light">Risk note</p>
        <div className="mt-3 rounded-[18px] border border-white/8 bg-white/5 px-3 py-3 text-sm text-gray">
          {riskNote ?? "Open analysis after a verdict to see the highest-risk note here."}
        </div>
      </div>

      <div>
        <p className="text-[10px] uppercase tracking-[0.22em] text-light">Breakdown</p>
        <div className="mt-3">
          <AgentVerdictBreakdown
            breakdown={verdict?.breakdown}
            columns="one"
            emptyMessage="Open analysis after a verdict to see the full evidence breakdown."
          />
        </div>
      </div>

      <div>
        <p className="text-[10px] uppercase tracking-[0.22em] text-light">Lineup Context</p>
        <div className="mt-3 space-y-2">
          {lineupContext ? (
            <>
              <div className="rounded-[18px] border border-white/8 bg-white/5 px-3 py-3 text-sm text-gray">
                {lineupContext.summary || "Lineup context is unavailable."}
              </div>
              <div className="grid grid-cols-1 gap-2">
                {lineupContext.player_team ? (
                  <div className="rounded-[18px] border border-white/8 bg-white/5 px-3 py-3">
                    <p className="text-sm font-semibold text-dark">Player team</p>
                    <p className="mt-1 text-sm text-gray">
                      {lineupContext.player_team.team} · {lineupContext.player_team.confidence ?? "n/a"} confidence
                    </p>
                    <p className="mt-1 text-xs text-gray">
                      {lineupContext.player_team.player_is_projected_starter
                        ? "Player remains in the projected starting five."
                        : "Player is not locked into the projected starting five."}
                    </p>
                  </div>
                ) : null}
                {lineupContext.opponent_team ? (
                  <div className="rounded-[18px] border border-white/8 bg-white/5 px-3 py-3">
                    <p className="text-sm font-semibold text-dark">Opponent team</p>
                    <p className="mt-1 text-sm text-gray">
                      {lineupContext.opponent_team.team} · {lineupContext.opponent_team.confidence ?? "n/a"} confidence
                    </p>
                    <p className="mt-1 text-xs text-gray">
                      {lineupContext.opponent_team.source_disagreement
                        ? "Lineup context still moving."
                        : "Sources are aligned for the opponent lineup."}
                    </p>
                  </div>
                ) : null}
              </div>
            </>
          ) : (
            <div className="rounded-[18px] border border-white/8 bg-white/5 px-3 py-3 text-sm text-gray">
              Open analysis after a verdict to see lineup context here.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export const AgentWidgetAnalysisPanel = ({
  pageContext,
  selectedPickContext,
  lastAssistantMessage,
  slipCount,
  isDesktop,
  onClose,
}: AgentWidgetAnalysisPanelProps) => {
  const content = (
    <AnalysisContent
      pageContext={pageContext}
      selectedPickContext={selectedPickContext}
      lastAssistantMessage={lastAssistantMessage}
      slipCount={slipCount}
    />
  );

  if (isDesktop) {
    return (
      <aside className="w-[20rem] border-l border-white/8 bg-[rgba(7,13,24,0.7)] p-5 backdrop-blur-xl">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-[0.24em] text-light">
              Analysis
            </p>
            <h3 className="mt-2 text-lg font-semibold text-dark">Market snapshot</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-white/10 bg-white/5 text-light transition-colors hover:bg-white/10"
            aria-label="Close analysis"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {content}
      </aside>
    );
  }

  return (
    <div
      role="dialog"
      aria-label="Betting agent analysis"
      className="fixed inset-x-3 bottom-3 z-[60] rounded-[28px] border border-white/10 bg-[rgba(7,13,24,0.94)] p-5 shadow-[0_28px_90px_rgba(2,8,20,0.48)] backdrop-blur-2xl lg:hidden"
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-[0.24em] text-light">Analysis</p>
          <h3 className="mt-2 text-lg font-semibold text-dark">Market snapshot</h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-white/10 bg-white/5 text-light transition-colors hover:bg-white/10"
          aria-label="Close analysis"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      {content}
    </div>
  );
};
