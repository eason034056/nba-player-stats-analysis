"use client";

import type { RefObject } from "react";
import { Send, Sparkles } from "lucide-react";

import type { AgentQuickAction } from "@/lib/agent-chat";
import { cn } from "@/lib/utils";

interface AgentWidgetComposerProps {
  composerValue: string;
  inputRef: RefObject<HTMLTextAreaElement>;
  isPending: boolean;
  isSuggestionsOpen: boolean;
  primaryActions: AgentQuickAction[];
  templateActions: AgentQuickAction[];
  viewMode: "panel" | "workspace";
  surface?: "light" | "dark";
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
  surface = "dark",
  onComposerChange,
  onSubmit,
  onAction,
  onToggleSuggestions,
}: AgentWidgetComposerProps) => {
  const canSend = composerValue.trim().length > 0 && !isPending;

  const light = surface === "light";

  return (
    <div
      className={cn(
        "border-t px-3.5 py-3",
        light ? "border-[#E3DFE9] bg-white" : "border-white/8 bg-[rgba(5,10,18,0.78)] px-4 backdrop-blur-xl sm:px-5",
      )}
    >
      {isSuggestionsOpen ? (
        <div
          className={cn(
            "mb-3 rounded-[18px] border p-3",
            light ? "border-[#E3DFE9] bg-[#F7F6F9]" : "rounded-[22px] border-white/10 bg-[rgba(255,255,255,0.04)]",
          )}
        >
          <div>
            <p className={cn("text-[10px] uppercase tracking-[0.22em]", light ? "text-muted" : "text-on-dark-muted")}>
              Next actions
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {primaryActions.map((action) => (
                <button
                  key={action.action}
                  type="button"
                  disabled={isPending}
                  onClick={() => void onAction(action)}
                  className={cn(
                    "rounded-full border px-3 py-2 text-sm font-medium transition-colors disabled:opacity-45",
                    light
                      ? "border-[#D3CCDF] bg-white text-brand hover:bg-brand-tint"
                      : "border-white/10 bg-white/5 text-on-dark hover:border-white/20 hover:bg-white/10",
                  )}
                >
                  {action.label}
                </button>
              ))}
            </div>
          </div>

          {templateActions.length > 0 ? (
            <div className={cn("mt-4 border-t pt-4", light ? "border-[#E3DFE9]" : "border-white/8")}>
              <p className={cn("text-[10px] uppercase tracking-[0.22em]", light ? "text-muted" : "text-on-dark-muted")}>
                More prompts
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {templateActions.map((action) => (
                  <button
                    key={action.action}
                    type="button"
                    disabled={isPending}
                    onClick={() => void onAction(action)}
                    className={cn(
                      "rounded-full border px-3 py-2 text-sm font-medium transition-colors disabled:opacity-45",
                      light
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
        </div>
      ) : null}

      {light ? (
        <div className="flex flex-col gap-2.5">
          <div className="flex gap-2">
            <textarea
              ref={inputRef}
              rows={1}
              value={composerValue}
              aria-label="Message betting agent"
              placeholder="Ask about a player, prop or your slip"
              onChange={(event) => onComposerChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void onSubmit();
                }
              }}
              className="min-h-11 w-full flex-1 resize-none rounded-full border border-[#D3CCDF] bg-[#F7F6F9] px-3.5 py-2.5 text-sm leading-6 text-ink outline-none placeholder:text-muted"
            />
            <button
              type="button"
              onClick={() => void onSubmit()}
              disabled={!canSend}
              className="inline-flex min-h-11 items-center rounded-full bg-brand px-[18px] text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-45"
            >
              Send
            </button>
          </div>
          <button
            type="button"
            onClick={onToggleSuggestions}
            className="inline-flex w-fit items-center gap-2 rounded-full border border-[#D3CCDF] bg-white px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-brand"
          >
            <Sparkles className="h-3.5 w-3.5" />
            Suggestions
          </button>
        </div>
      ) : (
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
          className="min-h-[42px] w-full resize-none bg-transparent text-sm leading-6 text-on-dark outline-none placeholder:text-on-dark-muted"
        />

        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onToggleSuggestions}
              className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] font-medium uppercase tracking-[0.16em] text-on-dark-muted transition-colors hover:bg-white/10"
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
                : "inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/90 px-3.5 py-1.5 text-sm font-semibold text-ink transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-45"
            }
          >
            <Send className="h-4 w-4" />
            <span>Send</span>
          </button>
        </div>
      </div>
      )}
    </div>
  );
};
