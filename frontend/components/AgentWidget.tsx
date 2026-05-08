"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, ChevronRight, Sparkles, X } from "lucide-react";

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
}: {
  eyebrow: string;
  title: string;
  description: string;
  isWorkspace: boolean;
}) => (
  <div
    className={cn(
      "rounded-[20px] border border-white/10 bg-[rgba(255,255,255,0.04)] px-4 py-3 shadow-[0_18px_48px_rgba(2,8,20,0.18)]",
      isWorkspace ? "w-full" : "min-w-0 flex-1",
    )}
  >
    <p className="text-[10px] uppercase tracking-[0.24em] text-light">{eyebrow}</p>
    <p className="mt-1 truncate text-sm font-semibold text-dark">{title}</p>
    <p className="mt-1 truncate text-xs text-gray">{description}</p>
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
    openWidget,
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
          <div className="flex items-center justify-between gap-3 border-b border-white/8 px-4 py-3 sm:px-5">
            <div className="flex items-center gap-3">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] uppercase tracking-[0.22em] text-light">
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
                className="inline-flex items-center rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-dark transition-colors hover:bg-white/10"
              >
                Return to panel
              </button>
              <button
                type="button"
                onClick={toggleAnalysisPanel}
                className="inline-flex items-center rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-dark transition-colors hover:bg-white/10"
              >
                {isAnalysisPanelOpen ? "Hide analysis" : "Show analysis"}
              </button>
              <button
                type="button"
                onClick={closeWidget}
                className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/10 bg-white/5 text-light transition-colors hover:bg-white/10"
                aria-label="Close betting agent"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="border-b border-white/8 px-4 py-3 sm:px-5">
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
    <div className="fixed inset-0 z-50 flex items-end justify-end bg-[rgba(3,6,12,0.4)] px-3 pb-3 pt-20 sm:bg-transparent sm:px-5 sm:pb-5 sm:pt-24">
      <div
        role="dialog"
        aria-label="Betting agent"
        className="relative flex h-[min(82vh,44rem)] w-full max-w-[28rem] flex-col overflow-hidden rounded-[30px] border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.06)_0%,rgba(255,255,255,0.03)_100%),rgba(8,15,26,0.94)] shadow-[0_38px_120px_rgba(2,8,20,0.52)] backdrop-blur-2xl"
      >
        <div className="flex items-center gap-3 border-b border-white/8 px-4 py-3 sm:px-5">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/12 bg-[radial-gradient(circle_at_top,#fff7e5_0%,#ff9f84_100%)] text-dark shadow-[0_12px_36px_rgba(255,136,108,0.3)]">
            <Bot className="h-4 w-4" />
          </div>

          <SummaryRail
            eyebrow={summary.eyebrow}
            title={summary.title}
            description={summary.description}
            isWorkspace={false}
          />

          <button
            type="button"
            onClick={() => setViewMode("workspace")}
            className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-dark transition-colors hover:bg-white/10"
            aria-label="Expand workspace"
          >
            Expand
            <ChevronRight className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={closeWidget}
            className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/10 bg-white/5 text-light transition-colors hover:bg-white/10"
            aria-label="Close betting agent"
          >
            <X className="h-4 w-4" />
          </button>
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
          viewMode="panel"
          onComposerChange={setComposerValue}
          onSubmit={handleSubmit}
          onAction={handleAction}
          onToggleSuggestions={toggleSuggestions}
        />
      </div>
    </div>
  );

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
          {isPending ? (
            <span className="absolute inset-0 animate-ping rounded-full border border-white/35" />
          ) : null}
        </span>
        <span className="hidden min-w-0 flex-col sm:flex">
          <span className="text-[11px] uppercase tracking-[0.26em] text-light">
            Cinematic desk
          </span>
          <span className="text-sm font-semibold text-dark">Ask the Board</span>
        </span>
        <ChevronRight className="hidden h-4 w-4 text-light sm:block" />
      </button>

      {isOpen ? (viewMode === "workspace" ? workspaceContent : panelContent) : null}
    </>
  );
};
