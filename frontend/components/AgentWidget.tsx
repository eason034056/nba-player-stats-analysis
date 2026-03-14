"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  ChevronRight,
  Loader2,
  RefreshCw,
  Send,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";

import { useBetSlip } from "@/contexts/BetSlipContext";
import { useAgentWidget } from "@/contexts/AgentWidgetContext";
import { cn } from "@/lib/utils";
import type { AgentAction, AgentThreadMessage } from "@/lib/agent-chat";

const QUICK_ACTIONS: Array<{
  action: AgentAction;
  label: string;
  prompt: string;
  requiresPick?: boolean;
  requiresSlip?: boolean;
}> = [
  { action: "analyze_pick", label: "Should I bet this?", prompt: "Should I bet this?", requiresPick: true },
  { action: "risk_check", label: "What is the biggest risk?", prompt: "What is the biggest risk?", requiresPick: true },
  { action: "review_slip", label: "Compare with my slip", prompt: "Compare with my slip", requiresSlip: true },
  { action: "line_movement", label: "Summarize line movement", prompt: "Summarize line movement", requiresPick: true },
  { action: "plain_english", label: "Explain in plain English", prompt: "Explain in plain English", requiresPick: true },
];

const formatPct = (value: number | null | undefined) => {
  if (value == null || Number.isNaN(value)) {
    return "N/A";
  }
  return `${(value * 100).toFixed(1)}%`;
};

const VerdictCard = ({ message }: { message: AgentThreadMessage }) => {
  if (!message.verdict) {
    return null;
  }

  const verdictTone =
    message.verdict.decision === "over"
      ? "text-green-300 border-green-400/30 bg-green-400/10"
      : message.verdict.decision === "under"
        ? "text-sky-300 border-sky-400/30 bg-sky-400/10"
        : "text-yellow-200 border-yellow-300/30 bg-yellow-300/10";

  return (
    <div className="rounded-[24px] border border-white/10 bg-white/4 p-4">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-[0.24em] text-light">Verdict</p>
          <h3 className="mt-2 text-lg font-semibold text-dark">{message.verdict.subject}</h3>
        </div>
        <span className={cn("rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em]", verdictTone)}>
          {message.verdict.decision}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-[18px] border border-white/8 bg-white/5 p-3">
          <p className="text-[11px] uppercase tracking-[0.22em] text-light">Confidence</p>
          <p className="mt-2 text-xl font-semibold text-dark">{formatPct(message.verdict.confidence)}</p>
        </div>
        <div className="rounded-[18px] border border-white/8 bg-white/5 p-3">
          <p className="text-[11px] uppercase tracking-[0.22em] text-light">Model</p>
          <p className="mt-2 text-xl font-semibold text-dark">{formatPct(message.verdict.model_probability)}</p>
        </div>
        <div className="rounded-[18px] border border-white/8 bg-white/5 p-3">
          <p className="text-[11px] uppercase tracking-[0.22em] text-light">Market</p>
          <p className="mt-2 text-xl font-semibold text-dark">{formatPct(message.verdict.market_implied_probability)}</p>
        </div>
        <div className="rounded-[18px] border border-white/8 bg-white/5 p-3">
          <p className="text-[11px] uppercase tracking-[0.22em] text-light">EV</p>
          <p className="mt-2 text-xl font-semibold text-dark">{formatPct(message.verdict.expected_value_pct)}</p>
        </div>
      </div>

      {message.verdict.reasons.length > 0 && (
        <div className="mt-4 space-y-2">
          {message.verdict.reasons.map((reason) => (
            <div key={reason} className="rounded-[18px] border border-white/8 bg-white/3 px-3 py-2 text-sm text-dark">
              {reason}
            </div>
          ))}
        </div>
      )}

      {message.verdict.risk_factors.length > 0 && (
        <div className="mt-4 rounded-[18px] border border-red/25 bg-red/10 p-3 text-sm text-dark">
          <div className="mb-2 flex items-center gap-2 text-red">
            <ShieldAlert className="h-4 w-4" />
            <span className="text-[11px] uppercase tracking-[0.22em]">Risk</span>
          </div>
          <p>{message.verdict.risk_factors[0]}</p>
        </div>
      )}
    </div>
  );
};

const SlipReview = ({ message }: { message: AgentThreadMessage }) => {
  if (!message.slip_review) {
    return null;
  }

  return (
    <div className="rounded-[24px] border border-white/10 bg-white/4 p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-[0.24em] text-light">Slip Review</p>
          <p className="mt-2 text-lg font-semibold text-dark">{message.slip_review.summary}</p>
        </div>
        <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-[0.22em] text-light">
          {message.slip_review.items.length} legs
        </div>
      </div>

      <div className="space-y-3">
        {message.slip_review.items.map((item) => (
          <div key={`${item.subject}-${item.recommendation ?? "none"}`} className="rounded-[20px] border border-white/8 bg-white/4 p-3">
            <div className="flex items-center justify-between gap-3">
              <p className="font-semibold text-dark">{item.subject}</p>
              <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-[0.22em] text-light">
                {item.recommendation ?? "review"}
              </span>
            </div>
            <p className="mt-2 text-sm text-gray">{item.summary}</p>
          </div>
        ))}
      </div>
    </div>
  );
};

export const AgentWidget = () => {
  const { count } = useBetSlip();
  const {
    closeWidget,
    error,
    isOpen,
    isPending,
    messages,
    openWidget,
    pageContext,
    retryLastRequest,
    selectedPickContext,
    submitAction,
  } = useAgentWidget();
  const [composerValue, setComposerValue] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);

  const quickActions = useMemo(
    () =>
      QUICK_ACTIONS.map((item) => ({
        ...item,
        disabled:
          (item.requiresPick && !selectedPickContext) ||
          (item.requiresSlip && count === 0),
      })),
    [count, selectedPickContext],
  );

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeWidget();
      }
    };

    window.addEventListener("keydown", handleKeydown);
    inputRef.current?.focus();

    return () => {
      window.removeEventListener("keydown", handleKeydown);
    };
  }, [closeWidget, isOpen]);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (!transcript || typeof transcript.scrollTo !== "function") {
      return;
    }

    transcript.scrollTo({
      top: transcript.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, error, isPending]);

  const handleSubmit = async (action: AgentAction, message: string) => {
    if (!message.trim() || isPending) {
      return;
    }

    await submitAction({ action, message: message.trim() });
    if (action === "general") {
      setComposerValue("");
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={openWidget}
        className="fixed bottom-5 right-5 z-50 inline-flex items-center gap-3 rounded-full border border-white/15 bg-[rgba(8,16,29,0.86)] px-4 py-3 text-left shadow-[0_24px_70px_rgba(2,8,20,0.48)] backdrop-blur-xl transition-all duration-200 hover:-translate-y-1 hover:border-white/25"
        aria-label="Ask the Board"
      >
        <span className="relative flex h-11 w-11 items-center justify-center rounded-full border border-white/12 bg-[radial-gradient(circle_at_top,#fff7e5_0%,#ff9f84_100%)] text-dark shadow-[0_12px_36px_rgba(255,136,108,0.3)]">
          <Bot className="h-5 w-5" />
          {isPending && <span className="absolute inset-0 animate-ping rounded-full border border-white/35" />}
        </span>
        <span className="hidden min-w-0 flex-col sm:flex">
          <span className="text-[11px] uppercase tracking-[0.26em] text-light">Cinematic Desk</span>
          <span className="text-sm font-semibold text-dark">Ask the Board</span>
        </span>
        <ChevronRight className="hidden h-4 w-4 text-light sm:block" />
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-end justify-end bg-[rgba(3,6,12,0.4)] px-3 pb-3 pt-20 sm:bg-transparent sm:px-5 sm:pb-5 sm:pt-24">
          <div
            role="dialog"
            aria-label="Betting agent"
            className="relative flex h-[min(82vh,46rem)] w-full max-w-[26rem] flex-col overflow-hidden rounded-[30px] border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.08)_0%,rgba(255,255,255,0.03)_100%),rgba(8,16,29,0.92)] shadow-[0_38px_120px_rgba(2,8,20,0.52)] backdrop-blur-2xl"
          >
            <div className="border-b border-white/8 px-5 py-4">
              <div className="mb-4 flex items-start justify-between gap-4">
                <div>
                  <div className="section-eyebrow mb-3">
                    <Sparkles className="mr-2 h-3.5 w-3.5" />
                    Analyst console
                  </div>
                  <h2 className="text-2xl font-semibold text-dark">Betting agent</h2>
                  <p className="mt-2 text-sm text-gray">
                    Route {pageContext.route}
                    {pageContext.date ? ` · ${pageContext.date}` : ""}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={closeWidget}
                  className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/10 bg-white/5 text-light transition-colors hover:bg-white/10"
                  aria-label="Close betting agent"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="flex flex-wrap gap-2">
                {quickActions.map((item) => (
                  <button
                    key={item.action}
                    type="button"
                    disabled={item.disabled || isPending}
                    onClick={() => handleSubmit(item.action, item.prompt)}
                    className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-dark transition-colors hover:border-white/20 hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>

            <div ref={transcriptRef} className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
              {messages.length === 0 && (
                <div className="rounded-[24px] border border-white/8 bg-white/4 p-4 text-sm text-gray">
                  Start with a pick-specific question or review the current slip. The widget already carries your route, date filters, and saved picks.
                </div>
              )}

              {messages.map((message) => (
                <div key={message.id} className="space-y-3">
                  <div
                    className={cn(
                      "rounded-[24px] px-4 py-3 text-sm leading-7",
                      message.role === "user"
                        ? "ml-10 border border-red/20 bg-red/12 text-dark"
                        : "mr-4 border border-white/8 bg-white/4 text-dark",
                    )}
                  >
                    {message.text}
                  </div>
                  {message.role === "assistant" && (
                    <>
                      <VerdictCard message={message} />
                      <SlipReview message={message} />
                    </>
                  )}
                </div>
              ))}

              {isPending && (
                <div className="rounded-[24px] border border-white/10 bg-white/4 px-4 py-3 text-sm text-dark">
                  <div className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin text-red" />
                    <span>Checking historical edge, market pricing, and slip context...</span>
                  </div>
                </div>
              )}

              {error && (
                <div className="rounded-[24px] border border-red/25 bg-red/10 p-4 text-sm text-dark">
                  <p>{error}</p>
                  <button
                    type="button"
                    onClick={retryLastRequest}
                    className="mt-3 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/8 px-3 py-2 font-medium text-dark transition-colors hover:bg-white/12"
                    aria-label="Retry last request"
                  >
                    <RefreshCw className="h-4 w-4" />
                    <span>Retry last request</span>
                  </button>
                </div>
              )}
            </div>

            <div className="border-t border-white/8 px-5 py-4">
              <div className="rounded-[24px] border border-white/10 bg-white/4 p-3">
                <textarea
                  ref={inputRef}
                  value={composerValue}
                  onChange={(event) => setComposerValue(event.target.value)}
                  placeholder="Ask for a verdict, a risk check, or a slip review..."
                  className="min-h-[88px] w-full resize-none bg-transparent text-sm text-dark outline-none placeholder:text-light"
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void handleSubmit("general", composerValue);
                    }
                  }}
                />
                <div className="mt-3 flex items-center justify-between gap-3">
                  <p className="text-[11px] uppercase tracking-[0.22em] text-light">
                    Verdict-first, English-first
                  </p>
                  <button
                    type="button"
                    onClick={() => void handleSubmit("general", composerValue)}
                    disabled={!composerValue.trim() || isPending}
                    className="btn-primary px-4 py-2 disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    <Send className="h-4 w-4" />
                    <span>Send</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
