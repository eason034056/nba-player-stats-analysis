/**
 * EventDetail.tsx — league-parametrized Event Detail / No-Vig Calculator body.
 *
 * SPO-83 Phase 0 (epic SPO-82). NBA is the reference design. This component is
 * the single source of truth for the event-detail page across leagues: both
 * `app/event/[eventId]/page.tsx` (NBA) and `app/wnba/event/[eventId]/page.tsx`
 * (WNBA) render it with a `league` prop instead of forking the JSX.
 *
 * Why parametrize instead of fork (decision log Decision 1):
 *   The two pages were forked then drifted (NBA 418 LOC vs WNBA 293). A shared
 *   component driven by a `league` prop makes drift structurally impossible —
 *   there is only one layout. League-specific behavior lives in `LEAGUE_CONFIG`
 *   (which endpoints, which labels) and in two capability flags for the data
 *   gaps WNBA genuinely has today.
 *
 * Data-gap handling (decision log Decision 2):
 *   WNBA has events / no-vig / player-suggest / player-history endpoints, so
 *   those sections are wired for real. WNBA has NO projection endpoint and NO
 *   lineup ingestion yet → those two slots render <SectionUnavailable> in place
 *   rather than being dropped, preserving structural parity.
 *
 * Design Philosophy (unchanged from the NBA original):
 * - Cream background (#FFF2DF) / Red accents (#E92016) / Yellow highlights (#F9DC24)
 */

"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  ArrowLeft,
  Calculator,
  Loader2,
  AlertCircle,
  Calendar,
} from "lucide-react";
import {
  getEvents,
  calculateNoVig,
  getPlayerProjection,
  getTeamLineup,
  getPlayerSuggestions,
  getCSVPlayers,
  getPlayerHistory,
  getWNBAEvents,
  calculateWNBANoVig,
  getWNBAPlayerSuggestions,
  getWNBACSVPlayers,
  getWNBAPlayerHistory,
} from "@/lib/api";
import { TeamLogo } from "@/components/TeamLogo";
import {
  calculatorFormSchema,
  type CalculatorFormData,
  type NoVigResponse,
  type NoVigRequest,
  type EventsResponse,
  type CSVPlayersResponse,
  type PlayerHistoryRequest,
  type PlayerHistoryResponse,
} from "@/lib/schemas";
import { formatFullDate, getLocalDateString } from "@/lib/utils";
import { PlayerInput, type PlayerSuggestFn } from "@/components/PlayerInput";
import { BookmakerSelect } from "@/components/BookmakerSelect";
import { MarketSelect, type MarketKey } from "@/components/MarketSelect";
import { ResultsTable } from "@/components/ResultsTable";
import { PlayerHistoryStats } from "@/components/PlayerHistoryStats";
import { PlayerProjectionPanel } from "@/components/PlayerProjectionPanel";
import { TeamLineupPanel } from "@/components/TeamLineupPanel";
import { SectionUnavailable } from "@/components/SectionUnavailable";
import { getCanonicalTeamCode } from "@/lib/team-logos";

export type League = "nba" | "wnba";

/**
 * Per-league wiring. Everything that differs between NBA and WNBA is a value
 * here — no `if (league === ...)` scattered through the JSX. `supportsLineup` /
 * `supportsProjection` are the only two genuine data gaps (see file header).
 */
interface LeagueEventConfig {
  backLabel: string;
  workspaceEyebrow: string;
  /** Third "how to read" bullet — the only copy that differs between leagues. */
  howToReadStep3: string;
  /** TanStack Query key root for the events list (keeps NBA/WNBA caches apart). */
  eventsQueryKey: string;
  getEvents: (date?: string) => Promise<EventsResponse>;
  calculateNoVig: (request: NoVigRequest) => Promise<NoVigResponse>;
  suggestFn: PlayerSuggestFn;
  cacheNamespace: League;
  getCSVPlayersFn: (query?: string) => Promise<CSVPlayersResponse>;
  getPlayerHistoryFn: (request: PlayerHistoryRequest) => Promise<PlayerHistoryResponse>;
  supportsLineup: boolean;
  supportsProjection: boolean;
}

const LEAGUE_CONFIG: Record<League, LeagueEventConfig> = {
  nba: {
    backLabel: "Back to Events",
    workspaceEyebrow: "Event workspace",
    howToReadStep3:
      "Compare the result with projection data and historical performance before saving a stance.",
    eventsQueryKey: "events",
    getEvents,
    calculateNoVig,
    suggestFn: getPlayerSuggestions,
    cacheNamespace: "nba",
    getCSVPlayersFn: getCSVPlayers,
    getPlayerHistoryFn: getPlayerHistory,
    supportsLineup: true,
    supportsProjection: true,
  },
  wnba: {
    backLabel: "Back to WNBA",
    workspaceEyebrow: "WNBA event workspace",
    howToReadStep3:
      "Compare the result with historical performance before saving a stance. Projection and lineup panels arrive when the WNBA data layers ship.",
    eventsQueryKey: "wnba-events",
    getEvents: getWNBAEvents,
    calculateNoVig: calculateWNBANoVig,
    suggestFn: getWNBAPlayerSuggestions,
    cacheNamespace: "wnba",
    getCSVPlayersFn: getWNBACSVPlayers,
    getPlayerHistoryFn: getWNBAPlayerHistory,
    // No WNBA projection endpoint and no WNBA lineup ingestion yet → empty states.
    supportsLineup: false,
    supportsProjection: false,
  },
};

interface EventDetailProps {
  league: League;
}

export function EventDetail({ league }: EventDetailProps) {
  const cfg = LEAGUE_CONFIG[league];

  const params = useParams();
  const eventId = params.eventId as string;

  const searchParams = useSearchParams();
  const routeDate = searchParams.get("date");
  const initialPlayer = searchParams.get("player") || "";
  const initialMarket = (searchParams.get("market") as MarketKey) || "player_points";
  const initialThreshold = searchParams.get("threshold") || "";

  const router = useRouter();

  const [result, setResult] = useState<NoVigResponse | null>(null);
  const [selectedMarket, setSelectedMarket] = useState<MarketKey>(initialMarket);

  const {
    control,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<CalculatorFormData>({
    resolver: zodResolver(calculatorFormSchema),
    defaultValues: {
      player_name: initialPlayer,
      bookmakers: [],
    },
  });

  const playerName = watch("player_name");

  const mutation = useMutation({
    mutationFn: cfg.calculateNoVig,
    onSuccess: (data) => {
      setResult(data);
    },
    onError: (error) => {
      console.error("Calculation failed:", error);
    },
  });

  // Auto-run when arriving with prefilled query params (deep-link from a picks page).
  useEffect(() => {
    if (initialPlayer && initialMarket) {
      mutation.mutate({
        event_id: eventId,
        player_name: initialPlayer,
        market: initialMarket,
        regions: "us",
        bookmakers: null,
        odds_format: "american",
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { data: eventsData, isLoading: isEventsLoading } = useQuery({
    queryKey: [cfg.eventsQueryKey, routeDate || "all"],
    queryFn: () => cfg.getEvents(routeDate || undefined),
    staleTime: 5 * 60 * 1000,
  });

  const currentEvent = eventsData?.events.find((e) => e.event_id === eventId);

  // 從比賽時間取得日期（YYYY-MM-DD），用於投影 / lineup API 查詢。
  // commence_time 是 ISO 8601 格式，需轉成本地日期避免 UTC 換日造成錯位。
  const gameDate = currentEvent?.commence_time
    ? getLocalDateString(currentEvent.commence_time)
    : undefined;
  const awayTeamCode = currentEvent ? getCanonicalTeamCode(currentEvent.away_team) : "";
  const homeTeamCode = currentEvent ? getCanonicalTeamCode(currentEvent.home_team) : "";

  // ==================== 投影資料查詢 ====================
  // Gated on cfg.supportsProjection: WNBA has no projection endpoint, so the
  // query never fires for it and the panel slot renders <SectionUnavailable>.
  const {
    data: projectionData,
    isLoading: isProjectionLoading,
  } = useQuery({
    queryKey: ["playerProjection", cfg.cacheNamespace, playerName, gameDate],
    queryFn: () => getPlayerProjection(playerName, gameDate),
    enabled: cfg.supportsProjection && !!playerName && !!gameDate,
    staleTime: 5 * 60 * 1000,
    retry: false, // 404（球員無投影）不需重試
  });

  // ==================== Lineup 查詢 ====================
  // Gated on cfg.supportsLineup for the same reason as projection.
  const {
    data: awayLineup,
    isLoading: isAwayLineupLoading,
  } = useQuery({
    queryKey: ["teamLineup", cfg.cacheNamespace, awayTeamCode, gameDate],
    queryFn: () => getTeamLineup(awayTeamCode, gameDate),
    enabled: cfg.supportsLineup && Boolean(awayTeamCode && gameDate),
    staleTime: 60 * 1000,
    retry: false,
  });

  const {
    data: homeLineup,
    isLoading: isHomeLineupLoading,
  } = useQuery({
    queryKey: ["teamLineup", cfg.cacheNamespace, homeTeamCode, gameDate],
    queryFn: () => getTeamLineup(homeTeamCode, gameDate),
    enabled: cfg.supportsLineup && Boolean(homeTeamCode && gameDate),
    staleTime: 60 * 1000,
    retry: false,
  });

  // marketToProjectionMetric: 把 MarketKey 轉成投影面板用的 metric key。
  // 見 NBA 原始註解（SPO-20 12-tile expansion note）— 新 tile 落到最近的單一 stat。
  const projectionMetric = (() => {
    switch (selectedMarket) {
      case "player_points":
      case "player_threes":
      case "player_steals":
      case "player_frees_made":
      case "player_field_goals":
        return "points" as const;
      case "player_rebounds":
        return "rebounds" as const;
      case "player_assists":
        return "assists" as const;
      case "player_points_rebounds_assists":
      case "player_rebounds_assists":
      case "player_points_rebounds":
      case "player_points_assists":
      case "player_double_double":
        return "pra" as const;
      default:
        return "points" as const;
    }
  })();

  // 從計算結果取出 threshold（盤口線）— 取第一家盤口的 line。
  const currentThreshold = result?.results?.[0]?.line ?? null;

  const handleMarketChange = (market: MarketKey) => {
    setSelectedMarket(market);
    setResult(null);
    setValue("player_name", "");
  };

  const onSubmit = (data: CalculatorFormData) => {
    setResult(null);
    mutation.mutate({
      event_id: eventId,
      player_name: data.player_name,
      market: selectedMarket,
      regions: "us",
      bookmakers: data.bookmakers.length > 0 ? data.bookmakers : null,
      odds_format: "american",
    });
  };

  return (
    <div className="mx-auto max-w-6xl px-6 py-10 page-enter">
      <button
        onClick={() => router.back()}
        className="mb-6 flex items-center gap-2 text-gray transition-colors duration-150 hover:text-dark font-semibold"
      >
        <ArrowLeft className="w-5 h-5" />
        <span>{cfg.backLabel}</span>
      </button>

      <section className="grid gap-6 md:grid-cols-[1.1fr_0.9fr] mb-8">
        <div className="card">
          <div className="section-eyebrow">{cfg.workspaceEyebrow}</div>
          {isEventsLoading ? (
            <div className="animate-pulse">
              <div className="skeleton h-8 w-64 mb-4" />
              <div className="skeleton h-4 w-48" />
            </div>
          ) : currentEvent ? (
            <>
              <h1 className="hero-title mb-5">
                {currentEvent.away_team}
                <span className="text-gradient block">@ {currentEvent.home_team}</span>
              </h1>
              <div className="accent-line mb-6" />
              <div className="flex flex-wrap items-center gap-3 text-gray">
                <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/4 px-3 py-1.5">
                  <Calendar className="w-4 h-4 text-red" />
                  {formatFullDate(currentEvent.commence_time)}
                </span>
                <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/4 px-3 py-1.5">
                  <TeamLogo teamName={currentEvent.away_team} size={20} />
                  <span>{currentEvent.away_team}</span>
                </span>
                <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/4 px-3 py-1.5">
                  <TeamLogo teamName={currentEvent.home_team} size={20} />
                  <span>{currentEvent.home_team}</span>
                </span>
              </div>
            </>
          ) : (
            <div className="flex items-center gap-3 text-red">
              <AlertCircle className="w-6 h-6" />
              <span className="font-semibold">Game information not found</span>
            </div>
          )}
        </div>

        <div className="card">
          <p className="text-xs uppercase tracking-[0.22em] text-light mb-3">How to read this page</p>
          <div className="space-y-4 text-sm leading-7 text-gray">
            <p>1. Pick a market, then choose a player and optional bookmakers.</p>
            <p>2. Run the no-vig calculation to inspect fairer over/under pricing.</p>
            <p>3. {cfg.howToReadStep3}</p>
          </div>
        </div>
      </section>

      {/* Lineup Status — real panels for NBA; labeled empty state for WNBA. */}
      {currentEvent ? (
        <section className="mb-8">
          <div className="mb-4">
            <p className="section-eyebrow">Lineup Status</p>
            <h2 className="mt-2 text-2xl font-semibold text-dark">Projected starters and confidence</h2>
          </div>
          {cfg.supportsLineup ? (
            <div className="grid gap-6 md:grid-cols-2">
              <TeamLineupPanel
                lineup={awayLineup ?? null}
                isLoading={isAwayLineupLoading}
                title={`${awayTeamCode} lineup status`}
              />
              <TeamLineupPanel
                lineup={homeLineup ?? null}
                isLoading={isHomeLineupLoading}
                title={`${homeTeamCode} lineup status`}
              />
            </div>
          ) : (
            <SectionUnavailable
              eyebrow="Lineup Status"
              title="Projected starters and confidence"
              message="Lineup and injury data is not available for WNBA yet. This panel will populate once WNBA lineup ingestion ships."
            />
          )}
        </section>
      ) : null}

      <form onSubmit={handleSubmit(onSubmit)}>
        <div className="card mb-6">
          <MarketSelect
            value={selectedMarket}
            onChange={handleMarketChange}
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          <div className="card">
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
            {errors.player_name && (
              <p className="mt-2 text-sm text-red font-medium">
                {errors.player_name.message}
              </p>
            )}
          </div>

          <div className="card">
            <Controller
              name="bookmakers"
              control={control}
              render={({ field }) => (
                <BookmakerSelect
                  value={field.value}
                  onChange={field.onChange}
                  disabled={mutation.isPending}
                />
              )}
            />
          </div>
        </div>

        <div className="flex justify-center">
          <button
            type="submit"
            disabled={mutation.isPending || !playerName}
            className="btn-primary flex items-center gap-2 px-6 sm:px-10 py-4 text-base sm:text-lg
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>Calculating...</span>
              </>
            ) : (
              <>
                <Calculator className="w-5 h-5" />
                <span>Calculate No-Vig Probability</span>
              </>
            )}
          </button>
        </div>
      </form>

      {mutation.isError && (
        <div className="card mt-6 border-red">
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-lg bg-red flex items-center justify-center shrink-0">
              <AlertCircle className="w-5 h-5 text-white" />
            </div>
            <div>
              <h3 className="font-bold text-dark mb-1">Calculation Failed</h3>
              <p className="text-gray text-sm">
                {mutation.error instanceof Error
                  ? mutation.error.message
                  : "Unable to calculate no-vig probability, please try again later"}
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="mt-8">
        <ResultsTable
          data={result}
          isLoading={mutation.isPending}
        />
      </div>

      {!result && !mutation.isPending && (
        <div className="mt-8 card">
          <h3 className="text-sm font-semibold text-dark mb-2">
            📊 What is No-Vig Probability?
          </h3>
          <p className="text-sm text-gray leading-relaxed">
            Bookmaker odds include &quot;vig&quot; (vig/juice), causing the sum of Over and Under
            implied probabilities to exceed 100%. No-vig probability normalizes these
            implied probabilities to derive a fair probability estimate closer to reality.
            Bookmakers with lower vig have odds closer to true probability.
          </p>
        </div>
      )}

      {/* Player projection — real panel for NBA; labeled empty state for WNBA. */}
      {playerName && (
        <div className="mt-8">
          {cfg.supportsProjection ? (
            <PlayerProjectionPanel
              projection={projectionData ?? null}
              metric={projectionMetric}
              threshold={currentThreshold}
              isLoading={isProjectionLoading}
            />
          ) : (
            <SectionUnavailable
              eyebrow="Today's Projection"
              title="Player projection"
              message="Projection modeling is not available for WNBA yet. This panel will populate once the WNBA projection source ships."
            />
          )}
        </div>
      )}

      <div className="mt-12 pt-8 border-t-2 border-dark/10">
        <div className="card">
          <PlayerHistoryStats
            eventId={eventId}
            initialPlayer={playerName}
            initialMarket={selectedMarket}
            initialThreshold={initialThreshold}
            onPlayerSelect={(name) => setValue("player_name", name)}
            projection={projectionData ?? undefined}
            getCSVPlayersFn={cfg.getCSVPlayersFn}
            getPlayerHistoryFn={cfg.getPlayerHistoryFn}
            calculateNoVigFn={cfg.calculateNoVig}
            cacheNamespace={cfg.cacheNamespace}
          />
        </div>
      </div>
    </div>
  );
}
