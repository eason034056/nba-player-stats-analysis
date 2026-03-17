"use client";

import type { RefObject } from "react";
import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronUp, Loader2, ShieldAlert } from "lucide-react";

import { cn } from "@/lib/utils";
import type { AgentQuickAction, AgentThreadMessage } from "@/lib/agent-chat";

import { AgentVerdictBreakdown } from "./AgentVerdictBreakdown";
import { formatPct, formatSignedPct } from "./presentation";

const VerdictSummaryCard = ({ message }: { message: AgentThreadMessage }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!message.verdict) {
    return null;
  }

  const marketDelta =
    message.verdict.market_implied_probability == null
      ? null
      : message.verdict.model_probability - message.verdict.market_implied_probability;
  const hasBreakdown =
    (message.verdict.breakdown?.sections.length ?? 0) > 0 ||
    message.verdict.reasons.length > 0 ||
    message.verdict.risk_factors.length > 0;
  const isLineMoved = message.verdict.market_pricing_mode === "line_moved";
  const decisionTone =
    message.verdict.decision === "over"
      ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
      : message.verdict.decision === "under"
        ? "border-sky-400/30 bg-sky-400/10 text-sky-200"
        : "border-yellow-300/30 bg-yellow-300/10 text-yellow-100";

  return (
    <div className="rounded-[22px] border border-white/10 bg-[rgba(255,255,255,0.04)] p-4 shadow-[0_18px_48px_rgba(2,8,20,0.28)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-[0.24em] text-light">Verdict</p>
          <h3 className="mt-2 text-base font-semibold text-dark">
            {message.verdict.subject}
          </h3>
          <p className="mt-2 text-sm text-gray">
            {message.verdict.summary || message.verdict.reasons[0]}
          </p>
        </div>
        <span
          className={cn(
            "rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.22em]",
            decisionTone,
          )}
        >
          {message.verdict.decision}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2 text-sm">
        <div className="rounded-[16px] border border-white/8 bg-white/5 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-light">Confidence</p>
          <p className="mt-1 font-semibold text-dark">{formatPct(message.verdict.confidence)}</p>
        </div>
        <div className="rounded-[16px] border border-white/8 bg-white/5 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-light">EV</p>
          <p className="mt-1 font-semibold text-dark">{formatPct(message.verdict.expected_value_pct)}</p>
        </div>
        <div className="rounded-[16px] border border-white/8 bg-white/5 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-light">Market delta</p>
          <p className="mt-1 font-semibold text-dark">{formatSignedPct(marketDelta)}</p>
        </div>
      </div>

      {isLineMoved ? (
        <div className="mt-4 rounded-[18px] border border-yellow-400/25 bg-yellow-400/10 p-3 text-sm text-dark">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.2em] text-yellow-700">
            <ShieldAlert className="h-4 w-4" />
            <span>Line moved</span>
          </div>
          <p className="mt-2 font-semibold">
            Original {message.verdict.queried_line ?? "N/A"} {"->"} Live {message.verdict.best_line ?? "N/A"}
          </p>
          {message.verdict.available_lines.length > 0 ? (
            <p className="mt-1 text-xs text-gray">
              Available lines: {message.verdict.available_lines.join(", ")}
            </p>
          ) : null}
        </div>
      ) : null}

      {hasBreakdown ? (
        <div className="mt-4">
          <button
            type="button"
            onClick={() => setIsExpanded((current) => !current)}
            className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-dark transition-colors hover:bg-white/10"
          >
            {isExpanded ? "Hide breakdown" : "Show breakdown"}
            {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>

          {isExpanded ? (
            <div className="mt-3 space-y-3">
              {(message.verdict.breakdown?.sections.length ?? 0) > 0 ? (
                <AgentVerdictBreakdown
                  breakdown={message.verdict.breakdown}
                  columns="two"
                  emptyMessage="Breakdown is unavailable for this verdict."
                />
              ) : message.verdict.reasons.length > 0 ? (
                <div className="space-y-2">
                  {message.verdict.reasons.map((reason) => (
                    <div
                      key={reason}
                      className="rounded-[16px] border border-white/8 bg-white/4 px-3 py-2 text-sm text-dark"
                    >
                      {reason}
                    </div>
                  ))}
                </div>
              ) : null}

              {message.verdict.risk_factors.length > 0 ? (
                <div className="rounded-[18px] border border-red/25 bg-red/10 p-3 text-sm text-dark">
                  <div className="mb-2 flex items-center gap-2 text-red">
                    <ShieldAlert className="h-4 w-4" />
                    <span className="text-[10px] uppercase tracking-[0.2em]">
                      Risk note
                    </span>
                  </div>
                  <p>{message.verdict.risk_factors[0]}</p>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};

const SlipReviewCard = ({ message }: { message: AgentThreadMessage }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!message.slip_review) {
    return null;
  }

  return (
    <div className="rounded-[22px] border border-white/10 bg-[rgba(255,255,255,0.04)] p-4 shadow-[0_18px_48px_rgba(2,8,20,0.28)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-[0.24em] text-light">Slip review</p>
          <h3 className="mt-2 text-base font-semibold text-dark">
            {message.slip_review.summary}
          </h3>
        </div>
        <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[10px] uppercase tracking-[0.22em] text-light">
          {message.slip_review.items.length} legs
        </span>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2 text-sm">
        <div className="rounded-[16px] border border-white/8 bg-white/5 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-light">Keep</p>
          <p className="mt-1 font-semibold text-dark">{message.slip_review.keep_count}</p>
        </div>
        <div className="rounded-[16px] border border-white/8 bg-white/5 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-light">Recheck</p>
          <p className="mt-1 font-semibold text-dark">{message.slip_review.recheck_count}</p>
        </div>
        <div className="rounded-[16px] border border-white/8 bg-white/5 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-light">Remove</p>
          <p className="mt-1 font-semibold text-dark">{message.slip_review.remove_count}</p>
        </div>
      </div>

      <button
        type="button"
        onClick={() => setIsExpanded((current) => !current)}
        className="mt-4 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-dark transition-colors hover:bg-white/10"
      >
        {isExpanded ? "Hide legs" : "Show legs"}
        {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </button>

      {isExpanded ? (
        <div className="mt-3 space-y-2">
          {message.slip_review.items.map((item) => (
            <div
              key={`${item.subject}-${item.recommendation ?? "review"}`}
              className="rounded-[16px] border border-white/8 bg-white/4 px-3 py-2"
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-dark">{item.subject}</p>
                <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[10px] uppercase tracking-[0.2em] text-light">
                  {item.recommendation ?? "review"}
                </span>
              </div>
              <p className="mt-1 text-sm text-gray">{item.summary}</p>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
};

interface AgentWidgetTranscriptProps {
  transcriptRef: RefObject<HTMLDivElement>;
  messages: AgentThreadMessage[];
  starterActions: AgentQuickAction[];
  isPending: boolean;
  error: string | null;
  onAction: (action: AgentQuickAction) => Promise<void>;
  onRetryLastRequest: () => Promise<void>;
}

export const AgentWidgetTranscript = ({
  transcriptRef,
  messages,
  starterActions,
  isPending,
  error,
  onAction,
  onRetryLastRequest,
}: AgentWidgetTranscriptProps) => (
  <div
    ref={transcriptRef}
    role="log"
    aria-label="Betting agent transcript"
    className="app-scrollbar flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5"
  >
    {messages.length === 0 ? (
      <div className="rounded-[22px] border border-white/8 bg-[rgba(255,255,255,0.03)] p-4">
        <p className="text-sm text-gray">
          Start with a direct question about the current pick, then branch into risk,
          pricing, or a plain-English explanation as needed.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          {starterActions.map((action) => (
            <button
              key={action.action}
              type="button"
              onClick={() => void onAction(action)}
              className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-dark transition-colors hover:border-white/20 hover:bg-white/10"
            >
              {action.label}
            </button>
          ))}
        </div>
      </div>
    ) : null}

    {messages.map((message) => (
      <div key={message.id} className="space-y-3">
        <div
          className={cn(
            "rounded-[20px] px-4 py-3 text-sm leading-6 shadow-[0_12px_36px_rgba(2,8,20,0.18)]",
            message.role === "user"
              ? "ml-auto w-fit max-w-[85%] whitespace-pre-wrap break-words border border-red/25 bg-[linear-gradient(180deg,rgba(255,136,108,0.16)_0%,rgba(255,136,108,0.09)_100%)] text-dark"
              : "mr-6 max-w-[calc(100%-1.5rem)] whitespace-pre-wrap break-words border border-white/8 bg-white/4 text-dark",
          )}
        >
          {message.text}
        </div>
        {message.role === "assistant" ? (
          <div className="space-y-3">
            <VerdictSummaryCard message={message} />
            <SlipReviewCard message={message} />
          </div>
        ) : null}
      </div>
    ))}

    {isPending ? (
      <div className="flex items-center gap-2 rounded-full border border-white/8 bg-white/4 px-3 py-2 text-sm text-gray">
        <Loader2 className="h-4 w-4 animate-spin text-red" />
        <span>Checking historical edge, pricing, and context...</span>
      </div>
    ) : null}

    {error ? (
      <div className="rounded-[20px] border border-red/25 bg-red/10 p-4 text-sm text-dark">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 text-red" />
          <div className="flex-1">
            <p>{error}</p>
            <button
              type="button"
              onClick={() => void onRetryLastRequest()}
              className="mt-3 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/8 px-3 py-2 font-medium text-dark transition-colors hover:bg-white/12"
              aria-label="Retry last request"
            >
              Retry last request
            </button>
          </div>
        </div>
      </div>
    ) : null}
  </div>
);
