"use client";

import type { RefObject } from "react";
import { CornerDownLeft, Send, Sparkles } from "lucide-react";

import type { AgentQuickAction } from "@/lib/agent-chat";

interface AgentWidgetComposerProps {
  composerValue: string;
  inputRef: RefObject<HTMLTextAreaElement>;
  isPending: boolean;
  isSuggestionsOpen: boolean;
  primaryActions: AgentQuickAction[];
  templateActions: AgentQuickAction[];
  viewMode: "panel" | "workspace";
  onComposerChange: (value: string) => void;
  onSubmit: () => Promise<void>;
  onAction: (action: AgentQuickAction) => Promise<void>;
  onToggleSuggestions: () => void;
}

export const AgentWidgetComposer = ({
  composerValue,
  inputRef,
  isPending,
  isSuggestionsOpen,
  primaryActions,
  templateActions,
  viewMode,
  onComposerChange,
  onSubmit,
  onAction,
  onToggleSuggestions,
}: AgentWidgetComposerProps) => {
  const canSend = composerValue.trim().length > 0 && !isPending;

  return (
    <div className="border-t border-white/8 bg-[rgba(5,10,18,0.78)] px-4 py-3 backdrop-blur-xl sm:px-5">
      {isSuggestionsOpen ? (
        <div className="mb-3 rounded-[22px] border border-white/10 bg-[rgba(255,255,255,0.04)] p-3">
          <div>
            <p className="text-[10px] uppercase tracking-[0.22em] text-light">
              Next actions
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {primaryActions.map((action) => (
                <button
                  key={action.action}
                  type="button"
                  disabled={isPending}
                  onClick={() => void onAction(action)}
                  className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-dark transition-colors hover:border-white/20 hover:bg-white/10 disabled:opacity-45"
                >
                  {action.label}
                </button>
              ))}
            </div>
          </div>

          {templateActions.length > 0 ? (
            <div className="mt-4 border-t border-white/8 pt-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-light">
                More prompts
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {templateActions.map((action) => (
                  <button
                    key={action.action}
                    type="button"
                    disabled={isPending}
                    onClick={() => void onAction(action)}
                    className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium text-dark transition-colors hover:border-white/20 hover:bg-white/10 disabled:opacity-45"
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="rounded-[24px] border border-white/10 bg-[rgba(255,255,255,0.04)] px-3 py-2.5 shadow-[0_20px_48px_rgba(2,8,20,0.22)] sm:px-3.5 sm:py-3">
        <textarea
          ref={inputRef}
          rows={1}
          value={composerValue}
          aria-label="Message betting agent"
          placeholder="Ask about this pick, or open suggestions."
          onChange={(event) => onComposerChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void onSubmit();
            }
          }}
          className="min-h-[42px] w-full resize-none bg-transparent text-sm leading-6 text-dark outline-none placeholder:text-light"
        />

        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onToggleSuggestions}
              className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] font-medium uppercase tracking-[0.16em] text-light transition-colors hover:bg-white/10"
            >
              <Sparkles className="h-3.5 w-3.5" />
              Suggestions
            </button>
          </div>

          <button
            type="button"
            onClick={() => void onSubmit()}
            disabled={!canSend}
            className={
              viewMode === "workspace"
                ? "btn-primary px-4 py-2 disabled:cursor-not-allowed disabled:opacity-45"
                : "inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/90 px-3.5 py-1.5 text-sm font-semibold text-dark transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-45"
            }
          >
            <Send className="h-4 w-4" />
            <span>Send</span>
          </button>
        </div>
      </div>
    </div>
  );
};
