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
import { getEvents, calculateNoVig } from "@/lib/api";
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
import { PlayerHistoryStats } from "@/components/PlayerHistoryStats";

/**
 * Event Page Component
 */
export default function EventPage() {
  const params = useParams();
  const eventId = params.eventId as string;

  const searchParams = useSearchParams();
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
    queryKey: ["events", "all"],
    queryFn: () => getEvents(),
    staleTime: 5 * 60 * 1000,
  });

  const currentEvent = eventsData?.events.find(
    (e) => e.event_id === eventId
  );

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
    <div className="max-w-5xl mx-auto px-6 py-10 page-enter">
      {/* Back button */}
      <button
        onClick={() => router.back()}
        className="flex items-center gap-2 text-gray hover:text-dark 
                   transition-colors duration-150 mb-8 font-semibold"
      >
        <ArrowLeft className="w-5 h-5" />
        <span>Back to Events</span>
      </button>

      {/* Game info card */}
      <div className="card mb-8">
        {isEventsLoading ? (
          <div className="animate-pulse">
            <div className="skeleton h-8 w-64 mb-4" />
            <div className="skeleton h-4 w-48" />
          </div>
        ) : currentEvent ? (
          <>
            <div className="flex items-center gap-4 mb-4 flex-wrap">
              <div className="flex items-center gap-3">
                <TeamLogo teamName={currentEvent.away_team} size={44} />
                <span className="text-2xl font-bold text-dark">
                  {currentEvent.away_team}
                </span>
              </div>
              <span className="text-gray text-xl font-bold">@</span>
              <div className="flex items-center gap-3">
                <TeamLogo teamName={currentEvent.home_team} size={44} />
                <span className="text-2xl font-bold text-dark">
                  {currentEvent.home_team}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2 text-gray">
              <Calendar className="w-4 h-4" />
              <span>{formatFullDate(currentEvent.commence_time)}</span>
            </div>
          </>
        ) : (
          <div className="flex items-center gap-3 text-red">
            <AlertCircle className="w-6 h-6" />
            <span className="font-semibold">Game information not found</span>
          </div>
        )}
      </div>

      {/* Calculator form */}
      <form onSubmit={handleSubmit(onSubmit)}>
        {/* Market type selection */}
        <div className="card mb-6">
          <MarketSelect
            value={selectedMarket}
            onChange={handleMarketChange}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* Player input */}
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

          {/* Bookmaker selection */}
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

        {/* Calculate button */}
        <div className="flex justify-center">
          <button
            type="submit"
            disabled={mutation.isPending || !playerName}
            className="btn-primary flex items-center gap-2 px-10 py-4 text-lg
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

      {/* Error message */}
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

      {/* Results */}
      <div className="mt-8">
        <ResultsTable
          data={result}
          isLoading={mutation.isPending}
        />
      </div>

      {/* Help text */}
      {!result && !mutation.isPending && (
        <div className="mt-8 card">
          <h3 className="text-sm font-bold text-dark mb-2">
            📊 What is No-Vig Probability?
          </h3>
          <p className="text-sm text-gray leading-relaxed">
            Bookmaker odds include "vig" (vig/juice), causing the sum of Over and Under 
            implied probabilities to exceed 100%. No-vig probability normalizes these 
            implied probabilities to derive a fair probability estimate closer to reality. 
            Bookmakers with lower vig have odds closer to true probability.
          </p>
        </div>
      )}

      {/* Historical Data Analysis Section */}
      <div className="mt-12 pt-8 border-t-2 border-dark/10">
        <div className="card">
          <PlayerHistoryStats
            eventId={eventId}
            initialPlayer={playerName}
            initialMarket={selectedMarket}
            initialThreshold={initialThreshold}
            onPlayerSelect={(name) => setValue("player_name", name)}
          />
        </div>
      </div>
    </div>
  );
}
