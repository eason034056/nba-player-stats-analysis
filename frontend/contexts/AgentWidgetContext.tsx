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
  openWidget: () => void;
  closeWidget: () => void;
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
}

const AgentWidgetContext = createContext<AgentWidgetContextValue | undefined>(
  undefined,
);

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
  const { picks } = useBetSlip();
  const [isOpen, setIsOpen] = useState(false);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<AgentThreadMessage[]>([]);
  const [threadId, setThreadId] = useState("");
  const [pageContext, setPageContextState] = useState<AgentPageContext>({
    route: pathname || "/",
    date: null,
    selected_teams: [],
  });
  const [selectedPickContext, setSelectedPickContextState] =
    useState<AgentPickContext | null>(null);
  const [lastRequest, setLastRequest] = useState<AgentChatRequest | null>(null);

  useEffect(() => {
    const rawState = sessionStorage.getItem(STORAGE_KEY);
    if (!rawState) {
      return;
    }

    try {
      const parsedState = JSON.parse(rawState) as StoredAgentWidgetState;
      setIsOpen(parsedState.isOpen);
      setMessages(parsedState.messages || []);
      setThreadId(parsedState.threadId || "");
      setPageContextState(
        parsedState.pageContext || {
          route: pathname || "/",
          date: null,
          selected_teams: [],
        },
      );
      setSelectedPickContextState(parsedState.selectedPickContext || null);
    } catch {
      sessionStorage.removeItem(STORAGE_KEY);
    }
  }, [pathname]);

  useEffect(() => {
    setPageContextState((current) => ({
      ...current,
      route: pathname || current.route || "/",
    }));
  }, [pathname]);

  useEffect(() => {
    const storedState: StoredAgentWidgetState = {
      isOpen,
      messages,
      threadId,
      pageContext,
      selectedPickContext,
    };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(storedState));
  }, [isOpen, messages, pageContext, selectedPickContext, threadId]);

  const openWidget = useCallback(() => {
    setIsOpen(true);
  }, []);

  const closeWidget = useCallback(() => {
    setIsOpen(false);
  }, []);

  const setPageContext = useCallback(
    (page: Partial<AgentPageContext>) => {
      setPageContextState((current) => ({
        route: page.route ?? pathname ?? current.route,
        date: page.date ?? current.date ?? null,
        selected_teams: page.selected_teams ?? current.selected_teams,
      }));
    },
    [pathname],
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
      } catch (error) {
        setError(getAgentErrorMessage(error));
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
      openWidget,
      closeWidget,
      setPageContext,
      setSelectedPickContext,
      clearSelectedPickContext,
      submitAction,
      retryLastRequest,
    }),
    [
      clearSelectedPickContext,
      closeWidget,
      error,
      isOpen,
      isPending,
      messages,
      openWidget,
      pageContext,
      retryLastRequest,
      selectedPickContext,
      setPageContext,
      setSelectedPickContext,
      submitAction,
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
