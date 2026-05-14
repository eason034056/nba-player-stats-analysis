/**
 * wnba/event/[eventId]/page.tsx — WNBA Event Detail / No-Vig Calculator
 *
 * SPO-33 Phase 2 deliverable. Sister page of `/event/[eventId]` (NBA),
 * intentionally slimmer for Phase 2 scope:
 *
 *   Phase 2 (this page)         | Future tickets
 *   ----------------------------+-----------------------------------------
 *   ✓ 12-tile MarketSelect      | × Player projection panel (SPO-35)
 *   ✓ Player autocomplete       | × Team lineup panels (SPO-34)
 *   ✓ Bookmaker filter          | × Daily picks integration (SPO-35)
 *   ✓ No-vig calculation        | × Agent chat widget (SPO-36)
 *   ✓ Results table             |
 *
 * The "missing" panels each depend on data layers (WNBA projections,
 * WNBA lineup ingestion) that Phase 2 does not own. When SPO-34 / SPO-35
 * land, they drop into this page using the same component contracts the
 * NBA page already proves.
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
  getWNBAEvents,
  calculateWNBANoVig,
  getWNBAPlayerSuggestions,
} from "@/lib/api";
import { TeamLogo } from "@/components/TeamLogo";
import {
  calculatorFormSchema,
  type CalculatorFormData,
  type NoVigResponse,
} from "@/lib/schemas";
import { formatFullDate } from "@/lib/utils";
import { PlayerInput } from "@/components/PlayerInput";
import { BookmakerSelect } from "@/components/BookmakerSelect";
import { MarketSelect, type MarketKey } from "@/components/MarketSelect";
import { ResultsTable } from "@/components/ResultsTable";

export default function WNBAEventPage() {
  const params = useParams();
  const eventId = params.eventId as string;

  const searchParams = useSearchParams();
  const routeDate = searchParams.get("date");
  const initialPlayer = searchParams.get("player") || "";
  const initialMarket = (searchParams.get("market") as MarketKey) || "player_points";

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

  // Event metadata — cached by date. Backend namespaces this as
  // `events:wnba:...` via CacheService.build_events_key(league="wnba"),
  // so NBA + WNBA caches don't collide.
  const { data: eventsData, isLoading: isEventsLoading } = useQuery({
    queryKey: ["wnba-events", routeDate || "all"],
    queryFn: () => getWNBAEvents(routeDate || undefined),
    staleTime: 5 * 60 * 1000,
  });

  const currentEvent = eventsData?.events.find((e) => e.event_id === eventId);

  const mutation = useMutation({
    mutationFn: calculateWNBANoVig,
    onSuccess: (data) => {
      setResult(data);
    },
    onError: (error) => {
      console.error("WNBA no-vig calculation failed:", error);
    },
  });

  // Auto-run when arriving with prefilled query params (deep-link pattern
  // from a future WNBA picks page). Same eslint-disable as NBA's page.
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
        <span>Back to WNBA</span>
      </button>

      <section className="grid gap-6 md:grid-cols-[1.1fr_0.9fr] mb-8">
        <div className="card">
          <div className="section-eyebrow">WNBA event workspace</div>
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
          <p className="text-xs uppercase tracking-[0.22em] text-light mb-3">
            How to read this page
          </p>
          <div className="space-y-4 text-sm leading-7 text-gray">
            <p>1. Pick a market, then choose a player and optional bookmakers.</p>
            <p>2. Run the no-vig calculation to inspect fairer over/under pricing.</p>
            <p>
              3. Projection + lineup panels ship with WNBA Phase 3 / Phase 4 — for
              now this page surfaces the live odds layer only.
            </p>
          </div>
        </div>
      </section>

      <form onSubmit={handleSubmit(onSubmit)}>
        <div className="card mb-6">
          <MarketSelect value={selectedMarket} onChange={handleMarketChange} />
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
                  // SPO-33: route player autocomplete to the WNBA endpoint
                  // and namespace the TanStack Query cache to "wnba" so it
                  // doesn't collide with NBA caches in the same session.
                  suggestFn={getWNBAPlayerSuggestions}
                  cacheNamespace="wnba"
                />
              )}
            />
            {errors.player_name && (
              <p className="text-red text-sm mt-2">{errors.player_name.message}</p>
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

        <div className="card mb-6">
          <button
            type="submit"
            disabled={mutation.isPending || !playerName}
            className="btn-primary w-full md:w-auto"
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>Calculating...</span>
              </>
            ) : (
              <>
                <Calculator className="w-5 h-5" />
                <span>Calculate No-Vig</span>
              </>
            )}
          </button>
        </div>
      </form>

      {mutation.isError && (
        <div className="card border-red/40 mb-6">
          <div className="flex items-center gap-3 text-red">
            <AlertCircle className="w-5 h-5" />
            <span className="font-semibold">Calculation failed</span>
          </div>
          <p className="text-sm text-gray mt-2">
            {mutation.error instanceof Error
              ? mutation.error.message
              : "Unknown error — check the browser console for details."}
          </p>
        </div>
      )}

      {result && (
        <section>
          <div className="mb-4">
            <p className="section-eyebrow">No-vig results</p>
            <h2 className="mt-2 text-2xl font-semibold text-dark">
              {result.player_name} — {result.market.replace(/_/g, " ")}
            </h2>
          </div>
          <ResultsTable data={result} />
        </section>
      )}
    </div>
  );
}
