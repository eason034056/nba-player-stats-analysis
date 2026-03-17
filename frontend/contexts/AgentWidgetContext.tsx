"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { usePathname } from "next/navigation";

import { useBetSlip } from "@/contexts/BetSlipContext";
import { ApiError, sendAgentChat } from "@/lib/api";
import {
  createAgentPickContextFromBetSlip,
  type AgentAction,
  type AgentChatRequest,
  type AgentPageContext,
  type AgentPickContext,
  type AgentRequestContext,
  type AgentThreadMessage,
} from "@/lib/agent-chat";

const STORAGE_KEY = "agent_widget_state";

export type AgentWidgetViewMode = "panel" | "workspace";

interface AgentWidgetSubmitOptions {
  action: AgentAction;
  message: string;
  contextPatch?: Partial<AgentRequestContext>;
}

interface AgentWidgetContextValue {
  isOpen: boolean;
  isPending: boolean;
  error: string | null;
  messages: AgentThreadMessage[];
  pageContext: AgentPageContext;
  selectedPickContext: AgentPickContext | null;
  viewMode: AgentWidgetViewMode;
  isSuggestionsOpen: boolean;
  isAnalysisPanelOpen: boolean;
  openWidget: () => void;
  closeWidget: () => void;
  setViewMode: (viewMode: AgentWidgetViewMode) => void;
  toggleSuggestions: () => void;
  closeSuggestions: () => void;
  toggleAnalysisPanel: () => void;
  closeAnalysisPanel: () => void;
  setPageContext: (page: Partial<AgentPageContext>) => void;
  setSelectedPickContext: (pick: AgentPickContext | null) => void;
  clearSelectedPickContext: () => void;
  submitAction: (options: AgentWidgetSubmitOptions) => Promise<void>;
  retryLastRequest: () => Promise<void>;
}

interface StoredAgentWidgetState {
  isOpen: boolean;
  messages: AgentThreadMessage[];
  threadId: string;
  pageContext: AgentPageContext;
  selectedPickContext: AgentPickContext | null;
  viewMode: AgentWidgetViewMode;
}

const AgentWidgetContext = createContext<AgentWidgetContextValue | undefined>(
  undefined,
);

const DEFAULT_PAGE_CONTEXT = (route: string): AgentPageContext => ({
  route,
  date: null,
  selected_teams: [],
});

const readStoredState = (route: string): StoredAgentWidgetState | null => {
  if (typeof window === "undefined") {
    return null;
  }

  const rawState = sessionStorage.getItem(STORAGE_KEY);
  if (!rawState) {
    return null;
  }

  try {
    const parsedState = JSON.parse(rawState) as StoredAgentWidgetState;
    return {
      isOpen: parsedState.isOpen ?? false,
      messages: parsedState.messages ?? [],
      threadId: parsedState.threadId ?? "",
      pageContext: parsedState.pageContext ?? DEFAULT_PAGE_CONTEXT(route),
      selectedPickContext: parsedState.selectedPickContext ?? null,
      viewMode: parsedState.viewMode ?? "panel",
    };
  } catch {
    sessionStorage.removeItem(STORAGE_KEY);
    return null;
  }
};

const createLocalId = () => {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

const createUserMessage = (
  action: AgentAction,
  text: string,
): AgentThreadMessage => ({
  id: createLocalId(),
  role: "user",
  text,
  action,
});

const createAssistantMessage = (
  response: Awaited<ReturnType<typeof sendAgentChat>>,
): AgentThreadMessage => ({
  id: createLocalId(),
  role: "assistant",
  text: response.reply,
  action: response.action,
  status: response.status,
  quick_actions: response.quick_actions,
  verdict: response.verdict ?? null,
  slip_review: response.slip_review ?? null,
});

const DEFAULT_AGENT_ERROR_MESSAGE =
  "Could not reach the betting agent. Try the last request again.";

const getAgentErrorMessage = (error: unknown) => {
  if (error instanceof ApiError && error.detail?.trim()) {
    return error.detail.trim();
  }

  return DEFAULT_AGENT_ERROR_MESSAGE;
};

export const AgentWidgetProvider = ({ children }: { children: ReactNode }) => {
  const pathname = usePathname();
  const route = pathname || "/";
  const storedState = readStoredState(route);
  const { picks } = useBetSlip();
  const [isOpen, setIsOpen] = useState(storedState?.isOpen ?? false);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<AgentThreadMessage[]>(
    storedState?.messages ?? [],
  );
  const [threadId, setThreadId] = useState(storedState?.threadId ?? "");
  const [pageContext, setPageContextState] = useState<AgentPageContext>(
    storedState?.pageContext ?? DEFAULT_PAGE_CONTEXT(route),
  );
  const [selectedPickContext, setSelectedPickContextState] =
    useState<AgentPickContext | null>(storedState?.selectedPickContext ?? null);
  const [lastRequest, setLastRequest] = useState<AgentChatRequest | null>(null);
  const [viewMode, setViewModeState] = useState<AgentWidgetViewMode>(
    storedState?.viewMode ?? "panel",
  );
  const [isSuggestionsOpen, setIsSuggestionsOpen] = useState(false);
  const [isAnalysisPanelOpen, setIsAnalysisPanelOpen] = useState(false);

  useEffect(() => {
    setPageContextState((current) => ({
      ...current,
      route: route || current.route || "/",
    }));
  }, [route]);

  useEffect(() => {
    const storedState: StoredAgentWidgetState = {
      isOpen,
      messages,
      threadId,
      pageContext,
      selectedPickContext,
      viewMode,
    };

    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(storedState));
  }, [isOpen, messages, pageContext, selectedPickContext, threadId, viewMode]);

  const closeTransientChrome = useCallback(() => {
    setIsSuggestionsOpen(false);
    setIsAnalysisPanelOpen(false);
  }, []);

  const openWidget = useCallback(() => {
    setIsOpen(true);
  }, []);

  const closeWidget = useCallback(() => {
    setIsOpen(false);
    closeTransientChrome();
  }, [closeTransientChrome]);

  const setViewMode = useCallback((nextViewMode: AgentWidgetViewMode) => {
    setViewModeState(nextViewMode);
    if (nextViewMode === "panel") {
      setIsAnalysisPanelOpen(false);
    }
  }, []);

  const toggleSuggestions = useCallback(() => {
    setIsSuggestionsOpen((current) => !current);
  }, []);

  const closeSuggestions = useCallback(() => {
    setIsSuggestionsOpen(false);
  }, []);

  const toggleAnalysisPanel = useCallback(() => {
    setIsAnalysisPanelOpen((current) => !current);
  }, []);

  const closeAnalysisPanel = useCallback(() => {
    setIsAnalysisPanelOpen(false);
  }, []);

  const setPageContext = useCallback(
    (page: Partial<AgentPageContext>) => {
      setPageContextState((current) => ({
        route: page.route ?? route ?? current.route,
        date: page.date ?? current.date ?? null,
        selected_teams: page.selected_teams ?? current.selected_teams,
      }));
    },
    [route],
  );

  const setSelectedPickContext = useCallback((pick: AgentPickContext | null) => {
    setSelectedPickContextState(pick);
  }, []);

  const clearSelectedPickContext = useCallback(() => {
    setSelectedPickContextState(null);
  }, []);

  const buildRequestContext = useCallback(
    (contextPatch?: Partial<AgentRequestContext>): AgentRequestContext => ({
      page: {
        ...pageContext,
        ...(contextPatch?.page ?? {}),
      },
      selected_pick:
        contextPatch?.selected_pick === undefined
          ? selectedPickContext
          : contextPatch.selected_pick ?? null,
      visible_picks: contextPatch?.visible_picks ?? [],
      bet_slip:
        contextPatch?.bet_slip ??
        picks.map((pick) => createAgentPickContextFromBetSlip(pick)),
    }),
    [pageContext, picks, selectedPickContext],
  );

  const runRequest = useCallback(
    async (request: AgentChatRequest, appendUserMessage: boolean) => {
      if (appendUserMessage) {
        setMessages((current) => [
          ...current,
          createUserMessage(request.action, request.message),
        ]);
      }

      setError(null);
      setIsPending(true);
      setLastRequest(request);
      setIsOpen(true);

      try {
        const response = await sendAgentChat(request);
        setThreadId(response.thread || request.thread);
        setMessages((current) => [...current, createAssistantMessage(response)]);
      } catch (requestError) {
        setError(getAgentErrorMessage(requestError));
      } finally {
        setIsPending(false);
      }
    },
    [],
  );

  const submitAction = useCallback(
    async ({ action, message, contextPatch }: AgentWidgetSubmitOptions) => {
      const nextThreadId = threadId || createLocalId();
      const request: AgentChatRequest = {
        thread: nextThreadId,
        action,
        message,
        context: buildRequestContext(contextPatch),
      };

      setThreadId(nextThreadId);
      await runRequest(request, true);
    },
    [buildRequestContext, runRequest, threadId],
  );

  const retryLastRequest = useCallback(async () => {
    if (!lastRequest) {
      return;
    }

    await runRequest(lastRequest, false);
  }, [lastRequest, runRequest]);

  const value = useMemo<AgentWidgetContextValue>(
    () => ({
      isOpen,
      isPending,
      error,
      messages,
      pageContext,
      selectedPickContext,
      viewMode,
      isSuggestionsOpen,
      isAnalysisPanelOpen,
      openWidget,
      closeWidget,
      setViewMode,
      toggleSuggestions,
      closeSuggestions,
      toggleAnalysisPanel,
      closeAnalysisPanel,
      setPageContext,
      setSelectedPickContext,
      clearSelectedPickContext,
      submitAction,
      retryLastRequest,
    }),
    [
      clearSelectedPickContext,
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
      setPageContext,
      setSelectedPickContext,
      setViewMode,
      submitAction,
      toggleAnalysisPanel,
      toggleSuggestions,
      viewMode,
    ],
  );

  return (
    <AgentWidgetContext.Provider value={value}>
      {children}
    </AgentWidgetContext.Provider>
  );
};

export const useAgentWidget = () => {
  const context = useContext(AgentWidgetContext);
  if (!context) {
    throw new Error("useAgentWidget must be used within AgentWidgetProvider");
  }

  return context;
};
