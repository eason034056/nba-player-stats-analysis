/**
 * event/[eventId]/page.tsx - Event Detail / Calculator Page (Minimal Design)
 * 
 * Design Philosophy:
 * - Cream background (#FFF2DF)
 * - Red accents (#E92016)
 * - Yellow highlights (#F9DC24)
 * - Clean typography and clear hierarchy
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
import { getEvents, calculateNoVig, getPlayerProjection, getTeamLineup } from "@/lib/api";
import { TeamLogo } from "@/components/TeamLogo";
import {
  calculatorFormSchema,
  type CalculatorFormData,
  type NoVigResponse,
} from "@/lib/schemas";
import { formatFullDate, getLocalDateString } from "@/lib/utils";
import { PlayerInput } from "@/components/PlayerInput";
import { BookmakerSelect } from "@/components/BookmakerSelect";
import { MarketSelect, type MarketKey } from "@/components/MarketSelect";
import { ResultsTable } from "@/components/ResultsTable";
import { PlayerHistoryStats } from "@/components/PlayerHistoryStats";
import { PlayerProjectionPanel } from "@/components/PlayerProjectionPanel";
import { TeamLineupPanel } from "@/components/TeamLineupPanel";
import { getCanonicalTeamCode } from "@/lib/team-logos";

/**
 * Event Page Component
 */
export default function EventPage() {
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

  const playerName = watch("player_name");

  const { data: eventsData, isLoading: isEventsLoading } = useQuery({
    queryKey: ["events", routeDate || "all"],
    queryFn: () => getEvents(routeDate || undefined),
    staleTime: 5 * 60 * 1000,
  });

  const currentEvent = eventsData?.events.find(
    (e) => e.event_id === eventId
  );

  // 從比賽時間取得日期（YYYY-MM-DD），用於投影 API 查詢
  // commence_time 是 ISO 8601 格式，需轉成本地日期避免 UTC 換日造成錯位
  const gameDate = currentEvent?.commence_time
    ? getLocalDateString(currentEvent.commence_time)
    : undefined;
  const awayTeamCode = currentEvent ? getCanonicalTeamCode(currentEvent.away_team) : "";
  const homeTeamCode = currentEvent ? getCanonicalTeamCode(currentEvent.home_team) : "";

  // ==================== 投影資料查詢 ====================
  // 當球員被選中且比賽日期存在時，從後端取得該球員的投影數據
  // useQuery key 包含 playerName + gameDate，任一變更時自動 refetch
  const {
    data: projectionData,
    isLoading: isProjectionLoading,
  } = useQuery({
    queryKey: ["playerProjection", playerName, gameDate],
    queryFn: () => getPlayerProjection(playerName, gameDate),
    enabled: !!playerName && !!gameDate,
    staleTime: 5 * 60 * 1000, // 5 分鐘內不重新取得
    retry: false, // 404（球員無投影）不需重試
  });

  const {
    data: awayLineup,
    isLoading: isAwayLineupLoading,
  } = useQuery({
    queryKey: ["teamLineup", awayTeamCode, gameDate],
    queryFn: () => getTeamLineup(awayTeamCode, gameDate),
    enabled: Boolean(awayTeamCode && gameDate),
    staleTime: 60 * 1000,
    retry: false,
  });

  const {
    data: homeLineup,
    isLoading: isHomeLineupLoading,
  } = useQuery({
    queryKey: ["teamLineup", homeTeamCode, gameDate],
    queryFn: () => getTeamLineup(homeTeamCode, gameDate),
    enabled: Boolean(homeTeamCode && gameDate),
    staleTime: 60 * 1000,
    retry: false,
  });

  // marketToProjectionMetric: 把 MarketKey 轉成投影面板用的 metric key
  // MarketKey 是完整的 market 名稱（如 "player_points"）
  // 投影面板需要簡短的 metric key（如 "points"）
  const projectionMetric = (() => {
    switch (selectedMarket) {
      case "player_points": return "points" as const;
      case "player_rebounds": return "rebounds" as const;
      case "player_assists": return "assists" as const;
      case "player_points_rebounds_assists": return "pra" as const;
      default: return "points" as const;
    }
  })();

  // 從計算結果中取出 threshold（盤口線）
  // result.results 是各家盤口的結果陣列，取第一個的 line 作為 threshold
  const currentThreshold = result?.results?.[0]?.line ?? null;

  const mutation = useMutation({
    mutationFn: calculateNoVig,
    onSuccess: (data) => {
      setResult(data);
    },
    onError: (error) => {
      console.error("Calculation failed:", error);
    },
  });

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
        <span>Back to Events</span>
      </button>

      <section className="grid gap-6 md:grid-cols-[1.1fr_0.9fr] mb-8">
        <div className="card">
          <div className="section-eyebrow">Event workspace</div>
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
            <p>3. Compare the result with projection data and historical performance before saving a stance.</p>
          </div>
        </div>
      </section>

      {currentEvent ? (
        <section className="mb-8">
          <div className="mb-4">
            <p className="section-eyebrow">Lineup Status</p>
            <h2 className="mt-2 text-2xl font-semibold text-dark">Projected starters and confidence</h2>
          </div>
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

      {playerName && (
        <div className="mt-8">
          <PlayerProjectionPanel
            projection={projectionData ?? null}
            metric={projectionMetric}
            threshold={currentThreshold}
            isLoading={isProjectionLoading}
          />
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
          />
        </div>
      </div>
    </div>
  );
}
