/**
 * EventDetail — NBA game page.
 *
 * Numbers come from the events, odds, daily-picks, history, and lineup
 * routes. A missing field is a labeled empty state.
 */

"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useAgentWidget } from "@/contexts/AgentWidgetContext";
import { useBetSlip } from "@/contexts/BetSlipContext";
import {
  calculateNoVig,
  getCSVPlayers,
  getDailyPicks,
  getEvents,
  getPlayerDDHistory,
  getPlayerHistory,
  getPlayerSuggestions,
  getTeamLineup,
  useEventBulkProps,
  useEventReads,
} from "@/lib/api";
import { createAgentPickContextFromDailyPick } from "@/lib/agent-chat";
import { AGENT_CHAT_UI_ENABLED } from "@/lib/agent-chat-ui";
import {
  buildOurRead,
  nbaReadsStatus,
  nbaRequestNote,
  chartLine,
  errorText,
  eventClock,
  eventLineupChips,
  eventPlayerRows,
  eventTeammates,
  gameLogChart,
  gameLogTiles,
  marketToMetric,
  NBA_EVENT_TABS,
  postedLine,
  type EventTab,
} from "@/lib/event-page";
import { EventActionBar } from "@/components/event/EventActionBar";
import { EventHeader } from "@/components/event/EventHeader";
import { EventTabs } from "@/components/event/EventTabs";
import { FilterSheet } from "@/components/event/FilterSheet";
import {
  activeFilterCount,
  MoreFilters,
  type FilterState,
  type LogRange,
  type LogRole,
  type MateMode,
} from "@/components/event/GameFilters";
import { NbaGameLog } from "@/components/event/NbaGameLog";
import { OurRead } from "@/components/event/OurRead";
import { PlayerRail } from "@/components/event/PlayerRail";
import { SportsbookPrices } from "@/components/event/SportsbookPrices";
import { StatChips } from "@/components/event/StatChips";
import type { PlayerSuggestFn } from "@/components/PlayerInput";
import { isBinaryMarket, getMarketDisplayName, type MarketKey } from "@/components/MarketSelect";
import {
  calculatorFormSchema,
  type CalculatorFormData,
  type NBAEvent,
  type NoVigRequest,
  type NoVigResponse,
  type PlayerHistoryRequest,
  type PlayerHistoryResponse,
} from "@/lib/schemas";
import { isPlayerOutInGame } from "@/lib/picks-board";
import { teamAbbr, teamShortName } from "@/lib/team-abbr";
import { getLocalDateString, getTodayString, cn } from "@/lib/utils";

interface LeagueEventConfig {
  eventsQueryKey: string;
  picksQueryKey: string;
  getEvents: (date?: string) => Promise<{ date: string; events: NBAEvent[] }>;
  getPicks: (date: string) => Promise<{ picks: import("@/lib/schemas").DailyPick[] }>;
  calculateNoVig: (request: NoVigRequest) => Promise<NoVigResponse>;
  suggestFn: PlayerSuggestFn;
  getLineup: (team: string, date?: string) => Promise<import("@/lib/schemas").TeamLineup>;
  cacheNamespace: "nba";
  getCSVPlayersFn: typeof getCSVPlayers;
  getPlayerHistoryFn: (request: PlayerHistoryRequest) => Promise<PlayerHistoryResponse>;
  getPlayerDDHistoryFn: typeof getPlayerDDHistory;
}

const cfg: LeagueEventConfig = {
  eventsQueryKey: "events",
  picksQueryKey: "daily-picks",
  getEvents,
  getPicks: (date) => getDailyPicks({ date }),
  calculateNoVig,
  suggestFn: getPlayerSuggestions,
  getLineup: getTeamLineup,
  cacheNamespace: "nba",
  getCSVPlayersFn: getCSVPlayers,
  getPlayerHistoryFn: getPlayerHistory,
  getPlayerDDHistoryFn: getPlayerDDHistory,
};

function historyRequest(
  player: string,
  metric: string,
  line: number,
  recent: number,
  role: LogRole,
  opponent: string,
  mates: string[],
  mateMode: MateMode,
  homeTeam: string,
  awayTeam: string,
  asOf: string,
): PlayerHistoryRequest {
  return {
    player,
    metric,
    threshold: line,
    n: recent,
    bins: 15,
    exclude_dnp: true,
    opponent: opponent || undefined,
    is_starter: role === "all" ? undefined : role === "starter",
    teammate_filter: mates.length > 0 && mateMode !== "all" ? mates : undefined,
    teammate_played:
      mates.length === 0 || mateMode === "all" ? undefined : mateMode === "with",
    home_team: homeTeam || undefined,
    away_team: awayTeam || undefined,
    as_of: asOf || undefined,
  };
}

export function EventDetail() {
  const params = useParams();
  const eventId = params.eventId as string;
  const searchParams = useSearchParams();
  const routeDate = searchParams.get("date");
  const initialPlayer = searchParams.get("player") || "";
  const initialMarket = (searchParams.get("market") as MarketKey) || "player_points";
  const initialThreshold = searchParams.get("threshold") || "";
  const requestedTab = searchParams.get("tab");
  const requested: EventTab =
    requestedTab === "log" || requestedTab === "filters" || requestedTab === "odds" || requestedTab === "read"
      ? requestedTab
      : "read";
  const startingTab: EventTab = requested === "filters" ? "log" : requested;
  const router = useRouter();
  const slip = useBetSlip();
  const { openWidget, setSelectedPickContext } = useAgentWidget();

  const [tab, setTab] = useState<EventTab>(startingTab);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [selectedMarket, setSelectedMarket] = useState<MarketKey>(initialMarket);
  const [result, setResult] = useState<NoVigResponse | null>(null);
  const [range, setRange] = useState<LogRange>(10);
  const [lineSteps, setLineSteps] = useState(0);
  const [role, setRole] = useState<LogRole>("all");
  const [opponent, setOpponent] = useState("");
  const [mates, setMates] = useState<string[]>([]);
  const [mateMode, setMateMode] = useState<MateMode>("all");
  const [selectedBar, setSelectedBar] = useState<string | null>(null);

  const { control, watch, setValue } = useForm<CalculatorFormData>({
    resolver: zodResolver(calculatorFormSchema),
    defaultValues: { player_name: initialPlayer, bookmakers: [] },
  });
  const playerName = watch("player_name");
  const bookmakers = watch("bookmakers");
  const bookmakerKey = (bookmakers ?? []).join(",");

  const mutation = useMutation({
    mutationFn: cfg.calculateNoVig,
    onSuccess: (data) => setResult(data),
  });

  useEffect(() => {
    setResult(null);
    if (!playerName || playerName.trim().length < 2) return;
    mutation.mutate({
      event_id: eventId,
      player_name: playerName.trim(),
      market: selectedMarket,
      regions: "us",
      bookmakers: bookmakers && bookmakers.length > 0 ? bookmakers : null,
      odds_format: "american",
    });
    // The mutation object is not a trigger. The inputs above are.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playerName, selectedMarket, bookmakerKey, eventId]);

  useEffect(() => {
    setLineSteps(0);
    setOpponent("");
    setMates([]);
    setMateMode("all");
    setRole("all");
    setSelectedBar(null);
  }, [playerName, selectedMarket]);

  const eventsQuery = useQuery({
    queryKey: [cfg.eventsQueryKey, routeDate || "all"],
    queryFn: () => cfg.getEvents(routeDate || undefined),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const currentEvent = eventsQuery.data?.events.find((event) => event.event_id === eventId);
  const gameDate = currentEvent?.commence_time
    ? getLocalDateString(currentEvent.commence_time)
    : undefined;
  const picksDate = routeDate || gameDate || getTodayString();
  const awayAbbr = currentEvent ? teamAbbr(currentEvent.away_team) : "";
  const homeAbbr = currentEvent ? teamAbbr(currentEvent.home_team) : "";
  const eventHome = currentEvent?.home_team ?? "";
  const eventAway = currentEvent?.away_team ?? "";
  const eventAsOf = currentEvent?.commence_time ?? "";

  const readsQuery = useEventReads({
    eventId,
    market: selectedMarket,
    enabled: true,
  });
  const propsQuery = useEventBulkProps({
    eventId,
    market: selectedMarket,
    enabled: true,
  });
  const picksQuery = useQuery({
    queryKey: [cfg.picksQueryKey, picksDate],
    queryFn: () => cfg.getPicks(picksDate),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const suggestQuery = useQuery({
    queryKey: ["player-suggest", cfg.cacheNamespace, eventId, selectedMarket],
    queryFn: () => cfg.suggestFn(eventId, undefined, selectedMarket),
    enabled: Boolean(eventId),
    staleTime: 30 * 1000,
    retry: false,
  });
  const awayLineupQuery = useQuery({
    queryKey: ["teamLineup", cfg.cacheNamespace, awayAbbr, gameDate],
    queryFn: () => cfg.getLineup(awayAbbr, gameDate),
    enabled: Boolean(awayAbbr && gameDate),
    staleTime: 60 * 1000,
    retry: false,
  });
  const homeLineupQuery = useQuery({
    queryKey: ["teamLineup", cfg.cacheNamespace, homeAbbr, gameDate],
    queryFn: () => cfg.getLineup(homeAbbr, gameDate),
    enabled: Boolean(homeAbbr && gameDate),
    staleTime: 60 * 1000,
    retry: false,
  });
  const binary = isBinaryMarket(selectedMarket);
  const metric = marketToMetric(selectedMarket);
  const pick =
    picksQuery.data?.picks.find(
      (item) =>
        item.event_id === eventId &&
        item.metric === metric &&
        item.player_name.trim().toLowerCase() === playerName.trim().toLowerCase(),
    ) ?? null;
  const liveLine = postedLine(result?.results);
  const line = liveLine ?? (pick ? pick.threshold : null);
  const activeLine = chartLine(line, lineSteps);
  const historyEnabled = Boolean(playerName) && activeLine != null && !binary;
  const baseHistoryEnabled = Boolean(playerName) && line != null && !binary;

  const chartQuery = useQuery({
    queryKey: [
      "event-chart",
      cfg.cacheNamespace,
      playerName,
      metric,
      activeLine,
      range,
      role,
      opponent,
      mates,
      mateMode,
      eventHome,
      eventAway,
      eventAsOf,
    ],
    queryFn: () =>
      cfg.getPlayerHistoryFn(
        historyRequest(
          playerName,
          metric,
          activeLine as number,
          range,
          role,
          opponent,
          mates,
          mateMode,
          eventHome,
          eventAway,
          eventAsOf,
        ),
      ),
    enabled: historyEnabled,
    staleTime: 30 * 1000,
    retry: false,
  });
  const sampleQuery = useQuery({
    queryKey: ["event-sample", cfg.cacheNamespace, playerName, metric, line, eventHome, eventAway, eventAsOf],
    queryFn: () =>
      cfg.getPlayerHistoryFn(
        historyRequest(playerName, metric, line as number, 0, "all", "", [], "all", eventHome, eventAway, eventAsOf),
      ),
    enabled: baseHistoryEnabled,
    staleTime: 30 * 1000,
    retry: false,
  });
  const last10Query = useQuery({
    queryKey: ["event-last10", cfg.cacheNamespace, playerName, metric, line, eventHome, eventAway, eventAsOf],
    queryFn: () =>
      cfg.getPlayerHistoryFn(
        historyRequest(playerName, metric, line as number, 10, "all", "", [], "all", eventHome, eventAway, eventAsOf),
      ),
    enabled: baseHistoryEnabled,
    staleTime: 30 * 1000,
    retry: false,
  });

  const rows = eventPlayerRows({
    suggested: suggestQuery.data?.players ?? [],
    picks: picksQuery.data?.picks ?? [],
    metric: selectedMarket,
    eventId,
    selectedName: playerName,
    postedLine: line,
    awayLineup: awayLineupQuery.data ?? null,
    homeLineup: homeLineupQuery.data ?? null,
    awayAbbr,
    homeAbbr,
    league: "nba",
    reads: readsQuery.data?.reads,
    readsStatus: nbaReadsStatus(readsQuery.isLoading, readsQuery.isError),
    bulkPlayers: propsQuery.data?.markets.find((market) => market.market === selectedMarket)?.players,
  });
  const selectedRow = rows.find((row) => row.name === playerName) ?? null;
  const selectedRead =
    readsQuery.data?.reads.find(
      (read) => read.player.trim().toLowerCase() === playerName.trim().toLowerCase(),
    ) ?? null;
  const position = pick?.position?.trim() || selectedRow?.position || null;
  const eventPicks = picksQuery.data?.picks ?? [];
  const listedOut =
    playerName.trim().length > 0 && isPlayerOutInGame(eventPicks, eventId, playerName);
  const model = buildOurRead({
    player: playerName.trim(),
    marketName: getMarketDisplayName(selectedMarket),
    market: selectedMarket,
    binary,
    eventId,
    homeTeam: currentEvent?.home_team ?? "",
    awayTeam: currentEvent?.away_team ?? "",
    commenceTime: currentEvent?.commence_time ?? "",
    team: selectedRow?.team ?? null,
    position,
    line,
    pick,
    consensus: result?.consensus ?? null,
    last10: last10Query.data?.game_logs ?? [],
    history: sampleQuery.data ?? null,
    league: "nba",
    read: selectedRead,
    listedOut,
  });
  const readsNote = nbaRequestNote("reads", nbaReadsStatus(readsQuery.isLoading, readsQuery.isError));
  const propsNote = nbaRequestNote("props", nbaReadsStatus(propsQuery.isLoading, propsQuery.isError));
  const shownModel =
    readsNote && !pick && !model.listedOut ? { ...model, caption: readsNote, tier: null } : model;
  const chart = chartQuery.data ? gameLogChart(chartQuery.data.game_logs ?? [], activeLine) : null;

  const existing = slip.picks.find(
    (item) => item.player_name === model.primary?.player_name && item.metric === model.primary?.metric,
  );
  const addSeed = (seed: NonNullable<typeof model.primary>) => {
    const id = `${seed.player_name}-${seed.metric}`;
    slip.removePick(id);
    slip.addPick(seed);
  };
  const askAgent = () => {
    if (!AGENT_CHAT_UI_ENABLED) return;
    if (pick) setSelectedPickContext(createAgentPickContextFromDailyPick(pick));
    openWidget();
  };

  const chartEmpty = (() => {
    if (binary) return "Game log bars are for Over/Under stats. Double-double history is in the panel below.";
    if (!playerName) return "Choose a player to load the game log.";
    if (line == null && !mutation.isPending) return "No posted line. Over and under are not calculated.";
    if (chartQuery.isError) return null;
    if (chartQuery.data && chartQuery.data.n_games === 0) {
      return chartQuery.data.message?.trim() || "No games match these filters.";
    }
    return null;
  })();

  const show = (id: EventTab | EventTab[]) => {
    const ids = Array.isArray(id) ? id : [id];
    return cn(!ids.includes(tab) && "max-md:hidden");
  };
  const clock = eventClock(currentEvent, "nba");
  const chips = eventLineupChips({
    awayAbbr,
    homeAbbr,
    status: currentEvent?.lineup_status,
    awayLineup: awayLineupQuery.data ?? null,
    homeLineup: homeLineupQuery.data ?? null,
  });
  const mobileLineup = chips
    .filter((chip) => chip.tone === "confirmed" || chip.tone === "projected")
    .map((chip) => `${chip.abbr} ${chip.tone}`)
    .join(" · ");
  const mobileWhen = [clock.mobile, mobileLineup].filter(Boolean).join(" · ");
  const filters: FilterState = {
    range,
    onRange: setRange,
    lineText: activeLine == null ? null : String(activeLine),
    lineChanged: lineSteps !== 0,
    lineDisabled: line == null,
    onMinus: () => setLineSteps((steps) => steps - 1),
    onPlus: () => setLineSteps((steps) => steps + 1),
    onResetLine: () => setLineSteps(0),
    role,
    onRole: setRole,
    opponent,
    opponents: sampleQuery.data?.opponents ?? [],
    onOpponent: setOpponent,
    teammates: eventTeammates({
      player: playerName,
      awayLineup: awayLineupQuery.data ?? null,
      homeLineup: homeLineupQuery.data ?? null,
      historyTeammates: sampleQuery.data?.teammates ?? [],
    }),
    selectedMates: mates,
    onToggleMate: (name) =>
      setMates((current) =>
        current.includes(name) ? current.filter((item) => item !== name) : [...current, name],
      ),
    mateMode,
    onMateMode: setMateMode,
  };
  const activeFilters = activeFilterCount(filters);
  const resetFilters = () => {
    setLineSteps(0);
    setRole("all");
    setOpponent("");
    setMates([]);
    setMateMode("all");
    setSelectedBar(null);
  };
  const logNote = chartQuery.data
    ? `${getMarketDisplayName(selectedMarket)} · ${chartQuery.data.n_games} ${
        chartQuery.data.n_games === 1 ? "game" : "games"
      }`
    : getMarketDisplayName(selectedMarket);
  const chartProps = {
    model: chart,
    selectedKey: selectedBar,
    onSelect: setSelectedBar,
    isLoading: chartQuery.isLoading && historyEnabled,
    isError: chartQuery.isError,
    errorText: errorText(chartQuery.error),
    emptyMessage: chartEmpty,
  };

  return (
    <div className="mx-auto flex w-full min-w-0 max-w-[1200px] flex-col gap-5 px-4 py-6 md:px-8">
      <EventHeader
        awayName={currentEvent ? teamShortName(currentEvent.away_team) : ""}
        homeName={currentEvent ? teamShortName(currentEvent.home_team) : ""}
        awayAbbr={awayAbbr}
        homeAbbr={homeAbbr}
        when={clock.web}
        mobileWhen={mobileWhen}
        chips={chips}
        isLoading={eventsQuery.isLoading}
        isError={eventsQuery.isError || (!eventsQuery.isLoading && !currentEvent)}
        errorText={
          eventsQuery.isError
            ? errorText(eventsQuery.error)
            : "Game information not found"
        }
        onBack={() => router.push("/")}
        onRetry={() => eventsQuery.refetch()}
      />

      <div className="flex flex-col gap-5 md:grid md:grid-cols-[minmax(280px,360px)_minmax(0,1fr)] md:items-start">
        <div className="max-md:contents md:col-start-1 md:flex md:min-w-0 md:flex-col md:gap-5">
          <aside className="order-1 max-md:contents md:flex md:flex-col md:gap-5 md:rounded-[24px] md:border md:border-line md:bg-white md:p-5">
            <StatChips
              value={selectedMarket}
              onChange={setSelectedMarket}
              disabled={mutation.isPending}
            />
            {readsNote ? (
              <div className="flex flex-wrap items-center gap-3">
                <p className="text-sm text-ink">{readsNote}</p>
                {readsQuery.isError ? (
                  <button
                    type="button"
                    onClick={() => readsQuery.refetch()}
                    className="text-sm font-semibold text-brand underline"
                  >
                    Retry reads
                  </button>
                ) : null}
              </div>
            ) : null}
            {propsNote ? (
              <div className="flex flex-wrap items-center gap-3">
                <p className="text-sm text-ink">{propsNote}</p>
                {propsQuery.isError ? (
                  <button
                    type="button"
                    onClick={() => propsQuery.refetch()}
                    className="text-sm font-semibold text-brand underline"
                  >
                    Retry props
                  </button>
                ) : null}
              </div>
            ) : null}
            <PlayerRail
              rows={rows}
              selected={playerName}
              onSelect={(name) => setValue("player_name", name)}
              isLoading={suggestQuery.isLoading && rows.length === 0}
              isError={suggestQuery.isError && rows.length === 0}
              errorText={errorText(suggestQuery.error)}
              onRetry={() => suggestQuery.refetch()}
            />
          </aside>
        </div>

        <div className="max-md:contents md:col-start-2 md:flex md:min-w-0 md:flex-col md:gap-5">
          <div className="order-1 md:hidden">
            <EventTabs value={tab} onChange={setTab} tabs={NBA_EVENT_TABS} />
          </div>

          <div className={cn("order-2 min-w-0", show("read"))}>
            <OurRead
              model={shownModel}
              isLoading={Boolean(playerName) && mutation.isPending && !pick && !result}
              isError={mutation.isError}
              errorText={errorText(mutation.error)}
              primaryInSlip={existing?.direction === model.primary?.direction}
              otherInSlip={existing?.direction === model.other?.direction}
              onAddPrimary={() => model.primary && addSeed(model.primary)}
              onAddOther={() => model.other && addSeed(model.other)}
              onAsk={askAgent}
            />
          </div>

          <NbaGameLog
            className={cn("order-4", show("log"))}
            filters={filters}
            note={logNote}
            tiles={chartQuery.data && chartQuery.data.n_games > 0 ? gameLogTiles(chartQuery.data, activeLine) : null}
            chart={chartProps}
            activeFilters={activeFilters}
            onOpenFilters={() => setFiltersOpen(true)}
            onReset={activeFilters > 0 || lineSteps !== 0 ? resetFilters : null}
          />

          <SportsbookPrices
            className={cn("order-5", show("odds"))}
            data={result}
            isLoading={mutation.isPending}
            isError={mutation.isError}
            errorText={errorText(mutation.error)}
          />
        </div>
      </div>

      <FilterSheet open={filtersOpen} onClose={() => setFiltersOpen(false)}>
        <MoreFilters {...filters} />
      </FilterSheet>

      {playerName && !model.listedOut ? (
        <EventActionBar
          model={model}
          primaryInSlip={existing?.direction === model.primary?.direction}
          otherInSlip={existing?.direction === model.other?.direction}
          onAddPrimary={() => model.primary && addSeed(model.primary)}
          onAddOther={() => model.other && addSeed(model.other)}
          onAsk={askAgent}
        />
      ) : null}
    </div>
  );
}
