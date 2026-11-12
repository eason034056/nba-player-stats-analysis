/**
 * EventDetail — NBA and WNBA game page.
 *
 * One layout for both leagues. Numbers come from the events, odds,
 * daily-picks, history, and lineup routes. A missing field
 * is a labeled empty state.
 */

"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useAgentWidget } from "@/contexts/AgentWidgetContext";
import { useBetSlip } from "@/contexts/BetSlipContext";
import { useWnbaBetSlip } from "@/contexts/WnbaBetSlipContext";
import {
  calculateNoVig,
  calculateWNBANoVig,
  getCSVPlayers,
  getDailyPicks,
  getEvents,
  getPlayerDDHistory,
  getPlayerHistory,
  getPlayerSuggestions,
  getTeamLineup,
  getWNBACSVPlayers,
  getWNBAEvents,
  getWNBAPlayerDDHistory,
  getWNBAPlayerHistory,
  getWNBAPlayerSuggestions,
  getWNBATeamLineup,
  getWnbaDailyPicks,
  useEventBulkProps,
  useEventReads,
} from "@/lib/api";
import { createAgentPickContextFromDailyPick } from "@/lib/agent-chat";
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
  GameFilters,
  MoreFilters,
  type FilterState,
  type LogRange,
  type LogRole,
  type MateMode,
} from "@/components/event/GameFilters";
import { GameLogChart } from "@/components/event/GameLogChart";
import { NbaGameLog } from "@/components/event/NbaGameLog";
import { OurRead } from "@/components/event/OurRead";
import { PlayerRail } from "@/components/event/PlayerRail";
import { SportsbookPrices } from "@/components/event/SportsbookPrices";
import { StatChips } from "@/components/event/StatChips";
import { BookmakerSelect } from "@/components/BookmakerSelect";
import { PlayerHistoryStats } from "@/components/PlayerHistoryStats";
import { PlayerInput, type PlayerSuggestFn } from "@/components/PlayerInput";
import { ResultsTable } from "@/components/ResultsTable";
import { SectionUnavailable } from "@/components/SectionUnavailable";
import { TeamLineupPanel } from "@/components/TeamLineupPanel";
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
import { formatPercent } from "@/lib/player-dd";
import { teamAbbr, teamShortName } from "@/lib/team-abbr";
import { getLocalDateString, getTodayString, cn } from "@/lib/utils";

export type League = "nba" | "wnba";

interface LeagueEventConfig {
  eventsQueryKey: string;
  picksQueryKey: string;
  getEvents: (date?: string) => Promise<{ date: string; events: NBAEvent[] }>;
  getPicks: (date: string) => Promise<{ picks: import("@/lib/schemas").DailyPick[] }>;
  calculateNoVig: (request: NoVigRequest) => Promise<NoVigResponse>;
  suggestFn: PlayerSuggestFn;
  getLineup: (team: string, date?: string) => Promise<import("@/lib/schemas").TeamLineup>;
  cacheNamespace: League;
  getCSVPlayersFn: typeof getCSVPlayers;
  getPlayerHistoryFn: (request: PlayerHistoryRequest) => Promise<PlayerHistoryResponse>;
  getPlayerDDHistoryFn: typeof getPlayerDDHistory;
}

const LEAGUE_CONFIG: Record<League, LeagueEventConfig> = {
  nba: {
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
  },
  wnba: {
    eventsQueryKey: "wnba-events",
    picksQueryKey: "wnba-daily-picks",
    getEvents: getWNBAEvents,
    getPicks: (date) => getWnbaDailyPicks({ date }),
    calculateNoVig: calculateWNBANoVig,
    suggestFn: getWNBAPlayerSuggestions,
    getLineup: getWNBATeamLineup,
    cacheNamespace: "wnba",
    getCSVPlayersFn: getWNBACSVPlayers,
    getPlayerHistoryFn: getWNBAPlayerHistory,
    getPlayerDDHistoryFn: getWNBAPlayerDDHistory,
  },
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

export function EventDetail({ league }: { league: League }) {
  const cfg = LEAGUE_CONFIG[league];
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
  const startingTab: EventTab = league === "nba" && requested === "filters" ? "log" : requested;
  const router = useRouter();
  const nbaSlip = useBetSlip();
  const wnbaSlip = useWnbaBetSlip();
  const slip = league === "wnba" ? wnbaSlip : nbaSlip;
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
  const awayAbbr = currentEvent ? teamAbbr(currentEvent.away_team, league) : "";
  const homeAbbr = currentEvent ? teamAbbr(currentEvent.home_team, league) : "";
  const eventHome = currentEvent?.home_team ?? "";
  const eventAway = currentEvent?.away_team ?? "";
  const eventAsOf = currentEvent?.commence_time ?? "";

  const readsQuery = useEventReads({
    eventId,
    market: selectedMarket,
    enabled: league === "nba",
  });
  const propsQuery = useEventBulkProps({
    eventId,
    market: selectedMarket,
    enabled: league === "nba",
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
    league,
    reads: readsQuery.data?.reads,
    readsStatus: league === "nba" ? nbaReadsStatus(readsQuery.isLoading, readsQuery.isError) : "ready",
    bulkPlayers: propsQuery.data?.markets.find((market) => market.market === selectedMarket)?.players,
  });
  const selectedRow = rows.find((row) => row.name === playerName) ?? null;
  const selectedRead =
    league === "nba"
      ? readsQuery.data?.reads.find(
          (read) => read.player.trim().toLowerCase() === playerName.trim().toLowerCase(),
        ) ?? null
      : null;
  const position =
    league === "nba" ? pick?.position?.trim() || selectedRow?.position || null : null;
  const eventPicks = picksQuery.data?.picks ?? [];
  const listedOut =
    league === "nba" &&
    playerName.trim().length > 0 &&
    isPlayerOutInGame(eventPicks, eventId, playerName);
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
    league,
    read: selectedRead,
    listedOut,
  });
  const readsNote =
    league === "nba" ? nbaRequestNote("reads", nbaReadsStatus(readsQuery.isLoading, readsQuery.isError)) : null;
  const propsNote =
    league === "nba" ? nbaRequestNote("props", nbaReadsStatus(propsQuery.isLoading, propsQuery.isError)) : null;
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
  const nba = league === "nba";
  const clock = eventClock(currentEvent, league);
  const chips = eventLineupChips({
    league,
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
        league={league}
        awayName={
          nba && currentEvent ? teamShortName(currentEvent.away_team, league) : currentEvent?.away_team ?? ""
        }
        homeName={
          nba && currentEvent ? teamShortName(currentEvent.home_team, league) : currentEvent?.home_team ?? ""
        }
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
        onBack={() => router.push(league === "wnba" ? "/wnba" : "/")}
        onRetry={() => eventsQuery.refetch()}
      />

      {nba ? null : <EventTabs value={tab} onChange={setTab} />}

      <div className="flex flex-col gap-5 md:grid md:grid-cols-[minmax(280px,360px)_minmax(0,1fr)] md:items-start">
        {!nba && currentEvent ? (
          <details
            className={cn(
              "order-last rounded-[20px] border border-line bg-white px-4 py-3 md:order-first md:col-span-2",
              tab !== "read" && "max-md:hidden",
            )}
          >
            <summary className="cursor-pointer text-sm font-semibold text-ink">Starters</summary>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <TeamLineupPanel
                lineup={awayLineupQuery.data ?? null}
                isLoading={awayLineupQuery.isLoading}
                title={`${awayAbbr} lineup`}
              />
              <TeamLineupPanel
                lineup={homeLineupQuery.data ?? null}
                isLoading={homeLineupQuery.isLoading}
                title={`${homeAbbr} lineup`}
              />
            </div>
          </details>
        ) : null}

        <aside
          className={cn(
            nba
              ? "order-1 max-md:contents md:col-start-1 md:flex md:flex-col md:gap-5 md:rounded-[24px] md:border md:border-line md:bg-white md:p-5"
              : "order-1 flex flex-col gap-5 rounded-[24px] border border-line bg-white p-4 md:col-start-1 md:p-5",
            !nba && tab !== "read" && "max-md:hidden",
          )}
        >
          <StatChips
            league={league}
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
            league={league}
            rows={rows}
            selected={playerName}
            onSelect={(name) => setValue("player_name", name)}
            isLoading={suggestQuery.isLoading && rows.length === 0}
            isError={suggestQuery.isError && rows.length === 0}
            errorText={errorText(suggestQuery.error)}
            onRetry={() => suggestQuery.refetch()}
          />
        </aside>

        {nba ? (
          <div className="order-1 md:hidden">
            <EventTabs value={tab} onChange={setTab} tabs={NBA_EVENT_TABS} />
          </div>
        ) : null}

        <div className={cn("order-2 min-w-0 md:col-start-2", show("read"))}>
            <OurRead
              league={league}
              model={shownModel}
              isLoading={Boolean(playerName) && mutation.isPending && !pick && !result}
              isError={mutation.isError}
              errorText={errorText(mutation.error)}
              primaryInSlip={existing?.direction === model.primary?.direction}
              otherInSlip={existing?.direction === model.other?.direction}
              onAddPrimary={() => model.primary && addSeed(model.primary)}
              onAddOther={() => model.other && addSeed(model.other)}
              onAsk={() => {
                if (pick) setSelectedPickContext(createAgentPickContextFromDailyPick(pick));
                openWidget();
              }}
            />
          </div>

          {!nba ? (
          <div
            className={cn(
              "order-3 rounded-[24px] border border-line bg-white p-4 md:col-start-1 md:p-5",
              tab !== "read" && "max-md:hidden",
            )}
          >
            <Controller
              name="player_name"
              control={control}
              render={({ field }) => (
                <PlayerInput
                  eventId={eventId}
                  market={selectedMarket}
                  value={field.value}
                  onChange={field.onChange}
                  disabled={mutation.isPending}
                  suggestFn={cfg.suggestFn}
                  cacheNamespace={cfg.cacheNamespace}
                />
              )}
            />
          </div>
          ) : null}

          {nba ? (
            <NbaGameLog
              className={cn("order-4 md:col-start-2", show("log"))}
              filters={filters}
              note={logNote}
              tiles={chartQuery.data && chartQuery.data.n_games > 0 ? gameLogTiles(chartQuery.data, activeLine) : null}
              chart={chartProps}
              activeFilters={activeFilters}
              onOpenFilters={() => setFiltersOpen(true)}
              onReset={activeFilters > 0 || lineSteps !== 0 ? resetFilters : null}
            />
          ) : (
            <section className={cn("order-4 flex flex-col gap-5 rounded-[24px] border border-line bg-white p-4 md:col-start-2 md:p-7", show(["log", "filters"]))}>
              <div className={show("log")}>
                <GameLogChart {...chartProps} note={logNote} />
                {chartQuery.data && chartQuery.data.n_games > 0 ? (
                  <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
                    <StatTile label="Over" value={formatPercent(chartQuery.data.p_over)} />
                    <StatTile label="Under" value={formatPercent(chartQuery.data.p_under)} />
                    <StatTile label="Average" value={chartQuery.data.mean == null ? "—" : chartQuery.data.mean.toFixed(1)} />
                    <StatTile label="Games" value={String(chartQuery.data.n_games)} />
                  </div>
                ) : null}
              </div>
              <div className={show("filters")}>
                <GameFilters {...filters} league={league} gameCount={chartQuery.data?.n_games ?? null} />
              </div>
            </section>
          )}

          {nba ? (
            <SportsbookPrices
              className={cn("order-5 md:col-start-2", show("odds"))}
              data={result}
              isLoading={mutation.isPending}
              isError={mutation.isError}
              errorText={errorText(mutation.error)}
            />
          ) : (
            <section
              data-testid="odds-panel"
              className={cn(
                "order-5 min-w-0 max-w-full rounded-[24px] border border-line bg-white p-4 md:col-start-2 md:p-7",
                show("odds"),
              )}
            >
              <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-lg font-bold text-ink">Sportsbook prices</h3>
                <p className="text-[13px] text-muted">
                  {result?.consensus
                    ? `No-vig consensus ${binary ? "yes" : "over"} ${formatPercent(
                        binary ? result.consensus.p_yes_fair : result.consensus.p_over_fair,
                      )}`
                    : "No-vig consensus is not on this response."}
                </p>
              </div>
              <Controller
                name="bookmakers"
                control={control}
                render={({ field }) => (
                  <BookmakerSelect value={field.value} onChange={field.onChange} disabled={mutation.isPending} />
                )}
              />
              <div className="mt-4">
                <ResultsTable data={result} isLoading={mutation.isPending} />
              </div>
            </section>
          )}

          {!nba ? (
          <div className={cn("order-6 md:col-start-2", show("log"))}>
            <PlayerHistoryStats
              eventId={eventId}
              initialPlayer={playerName}
              initialMarket={selectedMarket}
              initialThreshold={line == null ? initialThreshold : String(line)}
              onPlayerSelect={(name) => setValue("player_name", name)}
              getCSVPlayersFn={cfg.getCSVPlayersFn}
              getPlayerHistoryFn={cfg.getPlayerHistoryFn}
              getPlayerDDHistoryFn={cfg.getPlayerDDHistoryFn}
              calculateNoVigFn={cfg.calculateNoVig}
              eventHome={eventHome}
              eventAway={eventAway}
              eventAsOf={eventAsOf}
              cacheNamespace={cfg.cacheNamespace}
            />
          </div>
          ) : null}

          {league === "wnba" && playerName ? (
            <div className={cn("order-7 md:col-start-2", show("read"))}>
              <SectionUnavailable
                eyebrow="Today's Projection"
                title="Player projection"
                message="Projection modeling is not available for WNBA yet. This panel will populate once the WNBA projection source ships."
              />
            </div>
          ) : null}
      </div>

      {nba ? (
        <FilterSheet open={filtersOpen} onClose={() => setFiltersOpen(false)}>
          <MoreFilters {...filters} />
        </FilterSheet>
      ) : null}

      {playerName && !model.listedOut ? (
        <EventActionBar
          league={league}
          model={model}
          primaryInSlip={existing?.direction === model.primary?.direction}
          otherInSlip={existing?.direction === model.other?.direction}
          onAddPrimary={() => model.primary && addSeed(model.primary)}
          onAddOther={() => model.other && addSeed(model.other)}
          onAsk={() => {
            if (pick) setSelectedPickContext(createAgentPickContextFromDailyPick(pick));
            openWidget();
          }}
        />
      ) : null}
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-[#F7F6F9] px-3.5 py-3">
      <div className="text-xs font-semibold text-[#4A4458]">{label}</div>
      <div className="font-mono text-2xl font-bold leading-tight text-ink">{value}</div>
    </div>
  );
}
