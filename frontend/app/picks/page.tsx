/**
 * picks/page.tsx - Minimal Daily Picks Page
 * 
 * Design Philosophy:
 * - Clear information hierarchy
 * - High probability in green, medium probability in yellow
 * - Cards use white background with black border
 * - Clean hover effects
 */

"use client";

import { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { 
  RefreshCw, 
  AlertCircle, 
  TrendingUp, 
  Target, 
  Clock,
  Users,
  Zap,
  ChevronRight,
  Flame,
  BarChart3,
  Calendar
} from "lucide-react";
import Link from "next/link";
import { getDailyPicks, triggerDailyAnalysis } from "@/lib/api";
import { getTodayString, getDateDisplayTitle, formatProbability } from "@/lib/utils";
import { 
  type DailyPick, 
  METRIC_DISPLAY_NAMES, 
  DIRECTION_DISPLAY_NAMES 
} from "@/lib/schemas";
import { DatePicker } from "@/components/DatePicker";
import { TeamLogo } from "@/components/TeamLogo";

/**
 * Probability confidence level
 */
function getProbabilityLevel(probability: number): "high" | "medium" {
  return probability >= 0.70 ? "high" : "medium";
}

/**
 * metric → market conversion
 */
function metricToMarket(metric: string): string {
  switch (metric) {
    case "points": return "player_points";
    case "rebounds": return "player_rebounds";
    case "assists": return "player_assists";
    case "pra": return "player_points_rebounds_assists";
    default: return "player_points";
  }
}

/**
 * Single pick card
 */
function PickCard({ pick, index }: { pick: DailyPick; index: number }) {
  const level = getProbabilityLevel(pick.probability);
  const metricName = METRIC_DISPLAY_NAMES[pick.metric] || pick.metric;
  const directionName = DIRECTION_DISPLAY_NAMES[pick.direction] || pick.direction;
  const animationDelay = `${index * 50}ms`;
  
  const marketKey = metricToMarket(pick.metric);
  const linkHref = `/event/${pick.event_id}?player=${encodeURIComponent(pick.player_name)}&market=${marketKey}&threshold=${pick.threshold}`;
  
  return (
    <div 
      className="animate-fade-in"
      style={{ animationDelay }}
    >
      <Link href={linkHref}>
        <div className={`
          card group cursor-pointer
          transition-all duration-200
          hover:-translate-y-1
          ${level === "high" 
            ? "hover:border-green-500" 
            : "hover:border-yellow"
          }
        `}>
          {/* High probability badge */}
          {level === "high" && (
            <div className="absolute top-4 right-4">
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-500 text-white text-xs font-bold">
                <Flame className="w-3 h-3" />
                HOT
              </div>
            </div>
          )}
          
          {/* Player info */}
          <div className="flex items-center gap-4 mb-4">
            <TeamLogo 
              teamName={pick.player_team || pick.home_team} 
              size={40} 
              className="shrink-0"
            />
            <div className="flex-1 min-w-0 pr-16">
              <h3 className="text-lg font-bold text-dark truncate">
                {pick.player_name}
              </h3>
              <p className="text-sm text-gray truncate">
                {pick.away_team} @ {pick.home_team}
              </p>
            </div>
          </div>
          
          {/* Prediction content */}
          <div className="flex items-center justify-between mb-4">
            <div className={`
              px-4 py-2 rounded-lg text-sm font-bold
              ${pick.direction === "over"
                ? "bg-green-500/10 text-green-600 border-2 border-green-500/30"
                : "bg-blue-500/10 text-blue-600 border-2 border-blue-500/30"
              }
            `}>
              {metricName} {directionName} {pick.threshold}
            </div>
            
            {/* Probability display */}
            <div className={`
              text-3xl font-mono font-bold
              ${level === "high" ? "text-green-500" : "text-yellow"}
            `}>
              {formatProbability(pick.probability)}
            </div>
          </div>
          
          {/* Probability progress bar */}
          <div className="progress-bar mb-4">
            <div 
              className={`progress-bar-fill ${level === "high" ? "high" : "medium"}`}
              style={{ width: `${pick.probability * 100}%` }}
            />
          </div>
          
          {/* Bottom info */}
          <div className="flex items-center justify-between text-sm text-gray">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5">
                <BarChart3 className="w-4 h-4" />
                {pick.n_games} games
              </span>
              <span className="flex items-center gap-1.5">
                <Users className="w-4 h-4" />
                {pick.bookmakers_count} bookmakers
              </span>
            </div>
            
            <ChevronRight className="w-5 h-5 text-gray group-hover:text-red transition-colors" />
          </div>
        </div>
      </Link>
    </div>
  );
}

/**
 * Loading skeleton
 */
function PickSkeleton() {
  return (
    <div className="card">
      <div className="flex items-center gap-4 mb-4">
        <div className="w-10 h-10 skeleton rounded-lg" />
        <div className="flex-1">
          <div className="h-5 w-32 skeleton mb-2" />
          <div className="h-4 w-48 skeleton" />
        </div>
      </div>
      <div className="flex items-center justify-between mb-4">
        <div className="h-10 w-36 skeleton rounded-lg" />
        <div className="h-8 w-16 skeleton" />
      </div>
      <div className="h-2 skeleton rounded-full mb-4" />
      <div className="flex items-center justify-between">
        <div className="h-4 w-40 skeleton" />
        <div className="h-4 w-4 skeleton" />
      </div>
    </div>
  );
}

/**
 * Stat card
 */
function StatCard({ 
  icon: Icon, 
  label, 
  value, 
  subValue 
}: { 
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | number;
  subValue?: string;
}) {
  return (
    <div className="card">
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-lg bg-red flex items-center justify-center">
          <Icon className="w-6 h-6 text-white" />
        </div>
        <div>
          <p className="text-sm text-gray font-medium">{label}</p>
          <p className="text-2xl font-bold text-dark">{value}</p>
          {subValue && (
            <p className="text-xs text-gray">{subValue}</p>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Main page component
 */
export default function PicksPage() {
  const todayString = getTodayString();
  const [selectedDate, setSelectedDate] = useState(todayString);
  const [isTriggering, setIsTriggering] = useState(false);
  const queryClient = useQueryClient();
  
  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["daily-picks", selectedDate],
    queryFn: async () => {
      return await getDailyPicks({ date: selectedDate });
    },
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
  
  const handleRefresh = useCallback(async () => {
    await queryClient.invalidateQueries({ 
      queryKey: ["daily-picks", selectedDate] 
    });
    await refetch();
  }, [selectedDate, refetch, queryClient]);
  
  const handleTriggerAnalysis = useCallback(async () => {
    setIsTriggering(true);
    try {
      await triggerDailyAnalysis(selectedDate);
      await queryClient.invalidateQueries({ 
        queryKey: ["daily-picks", selectedDate] 
      });
      await refetch();
    } catch (e) {
      console.error("Failed to trigger analysis:", e);
    } finally {
      setIsTriggering(false);
    }
  }, [selectedDate, refetch, queryClient]);
  
  const dateTitle = getDateDisplayTitle(selectedDate);
  const picks = data?.picks || [];
  const stats = data?.stats;
  
  const highProbCount = picks.filter((p: DailyPick) => p.probability >= 0.70).length;
  const mediumProbCount = picks.filter((p: DailyPick) => p.probability >= 0.65 && p.probability < 0.70).length;
  
  return (
    <div className="min-h-screen page-enter">
      <div className="max-w-4xl mx-auto px-6 py-12">
        {/* Page title section */}
        <div className="text-center mb-16">
          <div className="inline-block mb-6">
            <span className="badge-danger">
              <Target className="w-3.5 h-3.5 mr-1.5" />
              AI Auto Analysis
            </span>
          </div>
          
          <h1 className="hero-title mb-4">
            Daily <span className="text-red">Picks</span>
          </h1>
          
          <div className="accent-line mx-auto mb-6" />
          
          <p className="text-lg text-gray max-w-lg mx-auto">
            Automatically filter high-value betting options with over 65% probability based on historical data
          </p>
        </div>

        {/* Date selection section */}
        <div className="card mb-10">
          <DatePicker
            value={selectedDate}
            onChange={setSelectedDate}
          />
        </div>

        {/* Stats cards section */}
        {!isLoading && stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10">
            <StatCard 
              icon={Target}
              label="High Prob Picks"
              value={picks.length}
              subValue={`${highProbCount} ≥70%`}
            />
            <StatCard 
              icon={Calendar}
              label="Events Analyzed"
              value={stats.total_events}
              subValue="games"
            />
            <StatCard 
              icon={Users}
              label="Players Analyzed"
              value={stats.total_players}
              subValue="players"
            />
            <StatCard 
              icon={Clock}
              label="Analysis Time"
              value={`${stats.analysis_duration_seconds.toFixed(1)}s`}
              subValue={data?.analyzed_at ? new Date(data.analyzed_at).toLocaleTimeString() : ""}
            />
          </div>
        )}

        {/* Actions section */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-4">
            <h2 className="text-2xl font-bold text-dark">
              {dateTitle} Picks
            </h2>
            {!isLoading && (
              <span className="badge-neutral">
                {picks.length} picks
              </span>
            )}
          </div>
          
          <div className="flex items-center gap-3">
            <button
              onClick={handleRefresh}
              disabled={isFetching}
              className="btn-refresh"
            >
              <RefreshCw className={`w-4 h-4 ${isFetching ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </button>
            
            <button
              onClick={handleTriggerAnalysis}
              disabled={isTriggering || isFetching}
              className="btn-primary flex items-center gap-2"
            >
              <Zap className={`w-4 h-4 ${isTriggering ? "animate-pulse" : ""}`} />
              <span>{isTriggering ? "Analyzing..." : "Re-analyze"}</span>
            </button>
          </div>
        </div>

        {/* Error message */}
        {isError && (
          <div className="card mb-8 border-red">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-lg bg-red flex items-center justify-center shrink-0">
                <AlertCircle className="w-5 h-5 text-white" />
              </div>
              <div>
                <h3 className="font-bold text-dark mb-1">
                  Load Failed
                </h3>
                <p className="text-gray text-sm mb-3">
                  {error instanceof Error ? error.message : "Unable to fetch analysis data, please try again later"}
                </p>
                <button
                  onClick={() => refetch()}
                  className="text-sm font-bold text-red hover:underline"
                >
                  Click to retry →
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Loading state */}
        {isLoading && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[...Array(6)].map((_, i) => (
              <PickSkeleton key={i} />
            ))}
          </div>
        )}

        {/* No data state */}
        {!isLoading && picks.length === 0 && (
          <div className="card text-center py-16">
            <div className="w-20 h-20 mx-auto mb-6 rounded-full border-2 border-dark/20 flex items-center justify-center">
              <TrendingUp className="w-10 h-10 text-gray" />
            </div>
            <h3 className="text-2xl font-bold text-dark mb-3">
              No High Probability Picks
            </h3>
            <p className="text-gray mb-8 max-w-md mx-auto">
              {data?.message || "No betting options with over 65% probability found today, or data analysis is not yet complete"}
            </p>
            <button
              onClick={handleTriggerAnalysis}
              disabled={isTriggering}
              className="btn-primary"
            >
              <Zap className="w-4 h-4 mr-2" />
              {isTriggering ? "Analyzing..." : "Analyze Now"}
            </button>
          </div>
        )}

        {/* Picks list */}
        {!isLoading && picks.length > 0 && (
          <>
            {/* High probability (>=70%) */}
            {highProbCount > 0 && (
              <div className="mb-10">
                <div className="flex items-center gap-3 mb-6">
                  <div className="w-10 h-10 rounded-lg bg-green-500 flex items-center justify-center">
                    <Flame className="w-5 h-5 text-white" />
                  </div>
                  <h3 className="text-xl font-bold text-dark">
                    High Confidence Picks
                    <span className="text-green-500 ml-2">≥70%</span>
                  </h3>
                  <span className="badge-success">
                    {highProbCount}
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {picks
                    .filter((p: DailyPick) => p.probability >= 0.70)
                    .map((pick: DailyPick, index: number) => (
                      <PickCard key={`${pick.player_name}-${pick.metric}`} pick={pick} index={index} />
                    ))
                  }
                </div>
              </div>
            )}

            {/* Medium probability (65-70%) */}
            {mediumProbCount > 0 && (
              <div>
                <div className="flex items-center gap-3 mb-6">
                  <div className="w-10 h-10 rounded-lg bg-yellow flex items-center justify-center">
                    <TrendingUp className="w-5 h-5 text-dark" />
                  </div>
                  <h3 className="text-xl font-bold text-dark">
                    Medium Confidence Picks
                    <span className="text-yellow ml-2">65-70%</span>
                  </h3>
                  <span className="badge-warning">
                    {mediumProbCount}
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {picks
                    .filter((p: DailyPick) => p.probability >= 0.65 && p.probability < 0.70)
                    .map((pick: DailyPick, index: number) => (
                      <PickCard key={`${pick.player_name}-${pick.metric}`} pick={pick} index={index} />
                    ))
                  }
                </div>
              </div>
            )}
          </>
        )}

        {/* Bottom note */}
        <div className="mt-16 text-center">
          <div className="divider-light mb-8" />
          <p className="text-sm text-gray max-w-lg mx-auto">
            Probabilities are calculated based on historical data, for reference only. Threshold values are taken from the mode of all bookmakers.
            <br />
            Click any pick to view detailed historical data and analysis.
          </p>
        </div>
      </div>
    </div>
  );
}
