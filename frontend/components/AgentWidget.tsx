"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, Sparkles, X } from "lucide-react";

import { useBetSlip } from "@/contexts/BetSlipContext";
import { useAgentWidget } from "@/contexts/AgentWidgetContext";
import type { AgentQuickAction } from "@/lib/agent-chat";
import { cn } from "@/lib/utils";

import { AgentWidgetAnalysisPanel } from "./agent-widget/AgentWidgetAnalysisPanel";
import { AgentWidgetComposer } from "./agent-widget/AgentWidgetComposer";
import { AgentWidgetTranscript } from "./agent-widget/AgentWidgetTranscript";
import {
  getContextSummary,
  getLastAssistantMessage,
  getSuggestionSets,
} from "./agent-widget/presentation";
import { useDesktopMode } from "./agent-widget/useDesktopMode";

const SummaryRail = ({
  eyebrow,
  title,
  description,
  isWorkspace,
  tone = "dark",
}: {
  eyebrow: string;
  title: string;
  description: string;
  isWorkspace: boolean;
  tone?: "light" | "dark";
}) => (
  <div
    className={cn(
      tone === "light"
        ? "rounded-2xl border border-[#E3DFE9] bg-white px-3.5 py-2.5"
        : "rounded-[20px] border border-white/10 bg-[rgba(255,255,255,0.04)] px-4 py-3 shadow-[0_18px_48px_rgba(2,8,20,0.18)]",
      isWorkspace ? "w-full" : "min-w-0 flex-1",
    )}
  >
    <p className={cn("text-[10px] uppercase tracking-[0.16em]", tone === "light" ? "text-muted" : "tracking-[0.24em] text-on-dark-muted")}>
      {eyebrow}
    </p>
    <p className={cn("mt-1 truncate text-sm font-semibold", tone === "light" ? "text-ink" : "text-on-dark")}>
      {title}
    </p>
    <p className={cn("mt-1 truncate text-xs", tone === "light" ? "text-muted" : "text-on-dark-muted")}>
      {description}
    </p>
  </div>
);

export const AgentWidget = () => {
  const { count } = useBetSlip();
  const {
    closeAnalysisPanel,
    closeSuggestions,
    closeWidget,
    error,
    isAnalysisPanelOpen,
    isOpen,
    isPending,
    isSuggestionsOpen,
    messages,
    pageContext,
    retryLastRequest,
    selectedPickContext,
    setViewMode,
    submitAction,
    toggleAnalysisPanel,
    toggleSuggestions,
    viewMode,
  } = useAgentWidget();
  const isDesktop = useDesktopMode();
  const [composerValue, setComposerValue] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const lastAssistantMessage = useMemo(
    () => getLastAssistantMessage(messages),
    [messages],
  );
  const summary = useMemo(
    () =>
      getContextSummary(
        pageContext,
        selectedPickContext,
        count,
        lastAssistantMessage,
      ),
    [count, lastAssistantMessage, pageContext, selectedPickContext],
  );
  const suggestions = useMemo(
    () =>
      getSuggestionSets({
        selectedPickContext,
        slipCount: count,
        messages,
      }),
    [count, messages, selectedPickContext],
  );

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const textarea = inputRef.current;
    textarea?.focus();
  }, [isOpen, viewMode]);

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

  useEffect(() => {
    const textarea = inputRef.current;
    if (!textarea) {
      return;
    }

    textarea.style.height = "0px";
    const maxHeight = viewMode === "workspace" ? 156 : 88;
    const nextHeight = Math.min(textarea.scrollHeight, maxHeight);
    textarea.style.height = `${Math.max(nextHeight, 42)}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [composerValue, viewMode]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const { body, documentElement } = document;
    const previousBodyOverflow = body.style.overflow;
    const previousHtmlOverflow = documentElement.style.overflow;

    body.style.overflow = "hidden";
    documentElement.style.overflow = "hidden";

    return () => {
      body.style.overflow = previousBodyOverflow;
      documentElement.style.overflow = previousHtmlOverflow;
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }

      if (isAnalysisPanelOpen) {
        closeAnalysisPanel();
        return;
      }

      if (isSuggestionsOpen) {
        closeSuggestions();
        return;
      }

      if (viewMode === "workspace" && isDesktop) {
        setViewMode("panel");
        return;
      }

      closeWidget();
    };

    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [
    closeAnalysisPanel,
    closeSuggestions,
    closeWidget,
    isAnalysisPanelOpen,
    isDesktop,
    isOpen,
    isSuggestionsOpen,
    setViewMode,
    viewMode,
  ]);

  const handleAction = async (action: AgentQuickAction) => {
    closeSuggestions();
    await submitAction({ action: action.action, message: action.prompt });
  };

  const handleSubmit = async () => {
    if (!composerValue.trim() || isPending) {
      return;
    }

    closeSuggestions();
    await submitAction({
      action: "general",
      message: composerValue.trim(),
    });
    setComposerValue("");
  };

  const workspaceContent = (
    <div className="fixed inset-0 z-50 bg-[rgba(3,6,12,0.74)] backdrop-blur-md">
      <div
        role="dialog"
        aria-label="Betting agent"
        className="mx-auto flex h-full w-full max-w-6xl overflow-hidden bg-[linear-gradient(180deg,rgba(255,255,255,0.05)_0%,rgba(255,255,255,0.02)_100%),rgba(6,11,20,0.96)] lg:my-3 lg:h-[calc(100%-1.5rem)] lg:rounded-[32px] lg:border lg:border-white/10 lg:shadow-[0_42px_120px_rgba(2,8,20,0.54)]"
      >
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between gap-3 border-b border-white/10 px-4 py-3 sm:px-5">
            <div className="flex items-center gap-3">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] uppercase tracking-[0.22em] text-on-dark-muted">
                <Sparkles className="h-3.5 w-3.5" />
                Analyst console
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  closeAnalysisPanel();
                  setViewMode("panel");
                }}
                className="inline-flex items-center rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-on-dark transition-colors hover:bg-white/10"
              >
                Return to panel
              </button>
              <button
                type="button"
                onClick={toggleAnalysisPanel}
                className="inline-flex items-center rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-on-dark transition-colors hover:bg-white/10"
              >
                {isAnalysisPanelOpen ? "Hide analysis" : "Show analysis"}
              </button>
              <button
                type="button"
                onClick={closeWidget}
                className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/10 bg-white/5 text-on-dark-muted transition-colors hover:bg-white/10"
                aria-label="Close betting agent"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="border-b border-white/10 px-4 py-3 sm:px-5">
            <SummaryRail
              eyebrow={summary.eyebrow}
              title={summary.title}
              description={summary.description}
              isWorkspace
            />
          </div>

          <AgentWidgetTranscript
            transcriptRef={transcriptRef}
            messages={messages}
            starterActions={suggestions.starterActions}
            isPending={isPending}
            error={error}
            onAction={handleAction}
            onRetryLastRequest={retryLastRequest}
          />

          <AgentWidgetComposer
            composerValue={composerValue}
            inputRef={inputRef}
            isPending={isPending}
            isSuggestionsOpen={isSuggestionsOpen}
            primaryActions={suggestions.primaryActions}
            templateActions={suggestions.templateActions}
            viewMode="workspace"
            onComposerChange={setComposerValue}
            onSubmit={handleSubmit}
            onAction={handleAction}
            onToggleSuggestions={toggleSuggestions}
          />
        </div>

        {isAnalysisPanelOpen && isDesktop ? (
          <AgentWidgetAnalysisPanel
            pageContext={pageContext}
            selectedPickContext={selectedPickContext}
            lastAssistantMessage={lastAssistantMessage}
            slipCount={count}
            isDesktop
            onClose={closeAnalysisPanel}
          />
        ) : null}
      </div>

      {isAnalysisPanelOpen && !isDesktop ? (
        <AgentWidgetAnalysisPanel
          pageContext={pageContext}
          selectedPickContext={selectedPickContext}
          lastAssistantMessage={lastAssistantMessage}
          slipCount={count}
          isDesktop={false}
          onClose={closeAnalysisPanel}
        />
      ) : null}
    </div>
  );

  const panelContent = (
    <div className="fixed inset-0 z-50 bg-[rgba(29,21,48,0.32)]">
      <div
        role="dialog"
        aria-label="Betting agent"
        data-layout={isDesktop ? "drawer" : "full"}
        className={cn(
          "absolute flex flex-col overflow-hidden bg-[#F7F6F9] shadow-[-20px_0_60px_rgba(29,21,48,0.18)]",
          isDesktop ? "inset-y-0 right-0 w-[min(440px,100%)]" : "inset-0",
        )}
      >
        <div className="flex items-center justify-between gap-3 bg-brand px-[18px] py-4 text-white">
          <div className="min-w-0">
            <div className="text-[17px] font-bold">Betting agent</div>
            <div className="text-xs text-on-dark-muted">Checks market, form, projection and matchup</div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => setViewMode("workspace")}
              className="inline-flex min-h-10 items-center gap-1 rounded-full border border-white/30 px-3 text-sm font-semibold text-white"
              aria-label="Expand workspace"
            >
              Expand
              <ChevronRight className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={closeWidget}
              className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/30 text-lg text-white"
              aria-label="Close betting agent"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="border-b border-[#E3DFE9] px-4 py-3">
          <SummaryRail
            eyebrow={summary.eyebrow}
            title={summary.title}
            description={summary.description}
            isWorkspace={false}
            tone="light"
          />
        </div>

        <AgentWidgetTranscript
          transcriptRef={transcriptRef}
          messages={messages}
          starterActions={suggestions.starterActions}
          isPending={isPending}
          error={error}
          onAction={handleAction}
          onRetryLastRequest={retryLastRequest}
          surface="light"
        />

        <AgentWidgetComposer
          composerValue={composerValue}
          inputRef={inputRef}
          isPending={isPending}
          isSuggestionsOpen={isSuggestionsOpen}
          primaryActions={suggestions.primaryActions}
          templateActions={suggestions.templateActions}
          viewMode="panel"
          surface="light"
          onComposerChange={setComposerValue}
          onSubmit={handleSubmit}
          onAction={handleAction}
          onToggleSuggestions={toggleSuggestions}
        />
      </div>
    </div>
  );

  return isOpen ? (viewMode === "workspace" ? workspaceContent : panelContent) : null;
};
