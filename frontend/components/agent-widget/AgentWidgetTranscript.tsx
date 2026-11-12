"use client";

import type { RefObject } from "react";
import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronUp, Loader2, ShieldAlert } from "lucide-react";

import { cn } from "@/lib/utils";
import type { AgentQuickAction, AgentThreadMessage } from "@/lib/agent-chat";

import { AgentVerdictBreakdown } from "./AgentVerdictBreakdown";
import { formatPct, formatSignedPct } from "./presentation";

const VerdictSummaryCard = ({
  message,
  surface,
}: {
  message: AgentThreadMessage;
  surface: "light" | "dark";
}) => {
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
    <div
      className={cn(
        "rounded-[22px] border p-4",
        surface === "light"
          ? "border-[#E3DFE9] bg-white"
          : "border-white/10 bg-[rgba(255,255,255,0.04)] shadow-[0_18px_48px_rgba(2,8,20,0.28)]",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-[0.24em] text-on-dark-muted">Verdict</p>
          <h3 className="mt-2 text-base font-semibold text-on-dark">
            {message.verdict.subject}
          </h3>
          <p className="mt-2 text-sm text-on-dark-muted">
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
        <div className="rounded-[16px] border border-white/10 bg-white/5 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-on-dark-muted">Confidence</p>
          <p className="mt-1 font-semibold text-on-dark">{formatPct(message.verdict.confidence)}</p>
        </div>
        <div className="rounded-[16px] border border-white/10 bg-white/5 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-on-dark-muted">EV</p>
          <p className="mt-1 font-semibold text-on-dark">{formatSignedPct(message.verdict.expected_value_pct)}</p>
        </div>
        <div className="rounded-[16px] border border-white/10 bg-white/5 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-on-dark-muted">Market delta</p>
          <p className="mt-1 font-semibold text-on-dark">{formatSignedPct(marketDelta)}</p>
        </div>
      </div>

      {isLineMoved ? (
        <div
          className={cn(
            "mt-4 rounded-[18px] border p-3 text-sm text-on-dark",
            surface === "light"
              ? "border-accent bg-accent"
              : "border-yellow-400/25 bg-yellow-400/10",
          )}
        >
          <div
            className={cn(
              "flex items-center gap-2 text-[10px] uppercase tracking-[0.2em]",
              surface === "light" ? "text-yellow" : "text-accent",
            )}
          >
            <ShieldAlert className="h-4 w-4" />
            <span>Line moved</span>
          </div>
          <p className="mt-2 font-semibold">
            Original {message.verdict.queried_line ?? "N/A"} {"->"} Live {message.verdict.best_line ?? "N/A"}
          </p>
          {message.verdict.available_lines.length > 0 ? (
            <p className="mt-1 text-xs text-on-dark-muted">
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
            className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-on-dark transition-colors hover:bg-white/10"
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
                      className="rounded-[16px] border border-white/10 bg-white/5 px-3 py-2 text-sm text-on-dark"
                    >
                      {reason}
                    </div>
                  ))}
                </div>
              ) : null}

              {message.verdict.risk_factors.length > 0 ? (
                <div className="rounded-[18px] border border-red/25 bg-red/10 p-3 text-sm text-on-dark">
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

const SlipReviewCard = ({
  message,
  surface,
}: {
  message: AgentThreadMessage;
  surface: "light" | "dark";
}) => {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!message.slip_review) {
    return null;
  }

  return (
    <div
      className={cn(
        "rounded-[22px] border p-4",
        surface === "light"
          ? "border-[#E3DFE9] bg-white"
          : "border-white/10 bg-[rgba(255,255,255,0.04)] shadow-[0_18px_48px_rgba(2,8,20,0.28)]",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-[0.24em] text-on-dark-muted">Slip review</p>
          <h3 className="mt-2 text-base font-semibold text-on-dark">
            {message.slip_review.summary}
          </h3>
        </div>
        <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[10px] uppercase tracking-[0.22em] text-on-dark-muted">
          {message.slip_review.items.length} legs
        </span>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2 text-sm">
        <div className="rounded-[16px] border border-white/10 bg-white/5 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-on-dark-muted">Keep</p>
          <p className="mt-1 font-semibold text-on-dark">{message.slip_review.keep_count}</p>
        </div>
        <div className="rounded-[16px] border border-white/10 bg-white/5 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-on-dark-muted">Recheck</p>
          <p className="mt-1 font-semibold text-on-dark">{message.slip_review.recheck_count}</p>
        </div>
        <div className="rounded-[16px] border border-white/10 bg-white/5 px-3 py-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-on-dark-muted">Remove</p>
          <p className="mt-1 font-semibold text-on-dark">{message.slip_review.remove_count}</p>
        </div>
      </div>

      <button
        type="button"
        onClick={() => setIsExpanded((current) => !current)}
        className="mt-4 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-on-dark transition-colors hover:bg-white/10"
      >
        {isExpanded ? "Hide legs" : "Show legs"}
        {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </button>

      {isExpanded ? (
        <div className="mt-3 space-y-2">
          {message.slip_review.items.map((item) => (
            <div
              key={`${item.subject}-${item.recommendation ?? "review"}`}
              className="rounded-[16px] border border-white/10 bg-white/5 px-3 py-2"
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-on-dark">{item.subject}</p>
                <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[10px] uppercase tracking-[0.2em] text-on-dark-muted">
                  {item.recommendation ?? "review"}
                </span>
              </div>
              <p className="mt-1 text-sm text-on-dark-muted">{item.summary}</p>
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
  surface?: "light" | "dark";
}

export const AgentWidgetTranscript = ({
  transcriptRef,
  messages,
  starterActions,
  isPending,
  error,
  onAction,
  onRetryLastRequest,
  surface = "dark",
}: AgentWidgetTranscriptProps) => (
  <div
    ref={transcriptRef}
    role="log"
    aria-label="Betting agent transcript"
    className={cn(
      "app-scrollbar flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5",
      surface === "light" && "agent-surface-light",
    )}
  >
    {messages.length === 0 ? (
      <div
        className={cn(
          "rounded-[18px] border p-3.5",
          surface === "light"
            ? "rounded-bl-[4px] border-[#E3DFE9] bg-white"
            : "rounded-[22px] border-white/10 bg-[rgba(255,255,255,0.03)]",
        )}
      >
        <p className={cn("text-sm leading-relaxed", surface === "light" ? "text-ink" : "text-on-dark-muted")}>
          {surface === "light"
            ? "I check any prop against market price, recent form, matchup, defense rank, and rest. What do you want to look at?"
            : "Start with a direct question about the current pick, then branch into risk, pricing, or a plain-English explanation as needed."}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          {starterActions.map((action) => (
            <button
              key={action.action}
              type="button"
              onClick={() => void onAction(action)}
              className={cn(
                "rounded-full border px-3 py-2 text-sm font-medium transition-colors",
                surface === "light"
                  ? "border-[#D3CCDF] bg-white text-brand hover:bg-brand-tint"
                  : "border-white/10 bg-white/5 text-on-dark hover:border-white/20 hover:bg-white/10",
              )}
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
            "rounded-[18px] px-3.5 py-2.5 text-sm leading-6",
            message.role === "user"
              ? "ml-auto w-fit max-w-[85%] whitespace-pre-wrap break-words rounded-[18px_18px_4px_18px] bg-brand text-white"
              : surface === "light"
                ? "mr-6 max-w-[94%] whitespace-pre-wrap break-words rounded-[18px_18px_18px_4px] border border-[#E3DFE9] bg-white text-ink"
                : "mr-6 max-w-[calc(100%-1.5rem)] whitespace-pre-wrap break-words border border-white/10 bg-white/5 text-on-dark",
          )}
        >
          {message.text}
        </div>
        {message.role === "assistant" ? (
          <div className="space-y-3">
            <VerdictSummaryCard message={message} surface={surface} />
            <SlipReviewCard message={message} surface={surface} />
          </div>
        ) : null}
      </div>
    ))}

    {isPending ? (
      <div
        className={cn(
          "flex items-center gap-2 rounded-[18px] px-4 py-3 text-sm",
          surface === "light"
            ? "border border-[#E3DFE9] bg-white text-muted"
            : "rounded-full border border-white/10 bg-white/5 text-on-dark-muted",
        )}
      >
        <Loader2 className={cn("h-4 w-4 animate-spin", surface === "light" ? "text-brand" : "text-red")} />
        <span>Checking market, form and matchup…</span>
      </div>
    ) : null}

    {error ? (
      <div
        className={cn(
          "rounded-[20px] border p-4 text-sm",
          surface === "light" ? "border-red/30 bg-red-light text-ink" : "border-red/25 bg-red/10 text-on-dark",
        )}
      >
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 text-red" />
          <div className="flex-1">
            <p>{error}</p>
            <button
              type="button"
              onClick={() => void onRetryLastRequest()}
              className={cn(
                "mt-3 inline-flex items-center gap-2 rounded-full border px-3 py-2 font-medium transition-colors",
                surface === "light"
                  ? "border-[#D3CCDF] bg-white text-ink hover:bg-[#F7F6F9]"
                  : "border-white/10 bg-white/10 text-on-dark hover:bg-white/10",
              )}
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
