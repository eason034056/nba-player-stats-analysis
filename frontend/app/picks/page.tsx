/**
 * /picks — NBA Daily Picks.
 *
 * The board is the November 2026 layout. Date, team filter, session
 * storage, re-analyze, and lineup badges stay on this page. A reverse
 * add lives on the game page and the pick context menu. Ask-the-agent
 * lives on the game page. Numbers come from getDailyPicks.
 */

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { DailyPicksBoard } from "@/components/picks/DailyPicksBoard";
import { useAgentWidget } from "@/contexts/AgentWidgetContext";
import { useBetSlip } from "@/contexts/BetSlipContext";
import { getDailyPicks, getLineups, triggerDailyAnalysis } from "@/lib/api";
import { createAgentPickContextFromDailyPick } from "@/lib/agent-chat";
import { isOutPick } from "@/lib/picks-board";
import type { DailyPick } from "@/lib/schemas";
import { complementHitRateLabel, slipPickFromDaily } from "@/lib/bet-slip-board";
import { getCanonicalTeamCode } from "@/lib/team-logos";
import { getTodayString } from "@/lib/utils";

const STORAGE_KEY_DATE = "picks-filter-date";
const STORAGE_KEY_TEAMS = "picks-filter-teams:v2";
const STALE_BOARD_MINUTES = 15;

export default function PicksPage() {
  const { setPageContext, submitAction } = useAgentWidget();
  const { picks: slipPicks, isInSlip, addPick, removePick } = useBetSlip();
  const todayString = getTodayString();
  const [selectedDate, setSelectedDate] = useState(todayString);
  const [isTriggering, setIsTriggering] = useState(false);
  const [selectedTeams, setSelectedTeams] = useState<Set<string>>(new Set());
  const queryClient = useQueryClient();
  const dailyPicksQueryKey = useMemo(
    () => ["daily-picks", selectedDate] as const,
    [selectedDate],
  );

  useEffect(() => {
    const storedDate = sessionStorage.getItem(STORAGE_KEY_DATE);
    if (storedDate) {
      setSelectedDate(storedDate);
    }
    const storedTeams = sessionStorage.getItem(STORAGE_KEY_TEAMS);
    if (storedTeams) {
      try {
        const teams = JSON.parse(storedTeams);
        if (Array.isArray(teams) && teams.length > 0) {
          setSelectedTeams(new Set(teams));
        }
      } catch {
        // A bad stored value falls back to no team filter.
      }
    }
  }, []);

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: dailyPicksQueryKey,
    queryFn: () => getDailyPicks({ date: selectedDate }),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const {
    data: lineupsData,
    isLoading: isLineupsLoading,
    isError: isLineupsError,
  } = useQuery({
    queryKey: ["lineups", selectedDate],
    queryFn: () => getLineups(selectedDate),
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const handleDateChange = useCallback((date: string) => {
    setSelectedDate(date);
    sessionStorage.setItem(STORAGE_KEY_DATE, date);
    setSelectedTeams(new Set());
    sessionStorage.setItem(STORAGE_KEY_TEAMS, JSON.stringify([]));
  }, []);

  const handleTriggerAnalysis = useCallback(async () => {
    setIsTriggering(true);
    try {
      await triggerDailyAnalysis(selectedDate);
      await queryClient.invalidateQueries({ queryKey: dailyPicksQueryKey });
      await refetch();
    } catch (triggerError) {
      console.error("Failed to trigger analysis:", triggerError);
    } finally {
      setIsTriggering(false);
    }
  }, [dailyPicksQueryKey, queryClient, refetch, selectedDate]);

  const allPicks = useMemo(() => data?.picks ?? [], [data?.picks]);

  const allTeams = useMemo(() => {
    const teamsSet = new Set<string>();
    allPicks.forEach((pick: DailyPick) => {
      const teamCode = pick.player_team_code || getCanonicalTeamCode(pick.player_team);
      if (teamCode) teamsSet.add(teamCode);
    });
    return Array.from(teamsSet).sort();
  }, [allPicks]);

  useEffect(() => {
    if (allTeams.length === 0) return;
    setSelectedTeams((prev) => {
      const filtered = new Set(Array.from(prev).filter((team) => allTeams.includes(team)));
      if (filtered.size === prev.size) return prev;
      sessionStorage.setItem(STORAGE_KEY_TEAMS, JSON.stringify(Array.from(filtered)));
      return filtered;
    });
  }, [allTeams]);

  const handleToggleTeam = useCallback((team: string) => {
    setSelectedTeams((prev) => {
      const next = new Set(prev);
      if (next.has(team)) next.delete(team);
      else next.add(team);
      sessionStorage.setItem(STORAGE_KEY_TEAMS, JSON.stringify(Array.from(next)));
      return next;
    });
  }, []);

  const handleClearTeams = useCallback(() => {
    setSelectedTeams(new Set());
    sessionStorage.setItem(STORAGE_KEY_TEAMS, JSON.stringify([]));
  }, []);

  const picks = useMemo(() => {
    if (selectedTeams.size === 0) return allPicks;
    return allPicks.filter((pick: DailyPick) =>
      selectedTeams.has(pick.player_team_code || getCanonicalTeamCode(pick.player_team)),
    );
  }, [allPicks, selectedTeams]);

  const lineupsByTeam = useMemo(() => {
    return new Map(
      (lineupsData?.lineups ?? []).map((lineup) => [
        getCanonicalTeamCode(lineup.team),
        lineup,
      ]),
    );
  }, [lineupsData?.lineups]);

  const analyzedAt = data?.analyzed_at ? new Date(data.analyzed_at) : null;
  const boardAgeMinutes =
    analyzedAt != null ? Math.floor((Date.now() - analyzedAt.getTime()) / 60000) : null;
  const isStaleBoard = boardAgeMinutes != null && boardAgeMinutes > STALE_BOARD_MINUTES;
  const isFilterEmptyState = !isLoading && allPicks.length > 0 && picks.length === 0;

  useEffect(() => {
    if (!isFilterEmptyState) return;
    console.debug("filter_empty_state", {
      date: selectedDate,
      selectedTeams: Array.from(selectedTeams),
      totalPicks: allPicks.length,
    });
  }, [allPicks.length, isFilterEmptyState, selectedDate, selectedTeams]);

  useEffect(() => {
    setPageContext({
      route: "/picks",
      date: selectedDate,
      selected_teams: Array.from(selectedTeams),
    });
  }, [selectedDate, selectedTeams, setPageContext]);

  const handleToggleSlip = useCallback(
    (pick: DailyPick) => {
      const id = `${pick.player_name}-${pick.metric}`;
      const existing = slipPicks.find(
        (item) => item.player_name === pick.player_name && item.metric === pick.metric,
      );
      if (isOutPick(pick)) {
        if (existing) removePick(id);
        return;
      }
      const reverse = pick.direction === "over" ? "under" : "over";
      if (existing && existing.direction !== reverse) {
        removePick(id);
        return;
      }
      removePick(id);
      addPick(slipPickFromDaily(pick, pick.direction, pick.probability));
    },
    [addPick, removePick, slipPicks],
  );

  const handleReviewBoard = useCallback(async () => {
    await submitAction({
      action: "review_board",
      message: "Review this board and identify the cleanest bet.",
      contextPatch: {
        visible_picks: picks
          .filter((pick) => !isOutPick(pick))
          .slice(0, 6)
          .map((pick) => createAgentPickContextFromDailyPick(pick)),
      },
    });
  }, [picks, submitAction]);

  return (
    <DailyPicksBoard
      league="nba"
      selectedDate={selectedDate}
      onDateChange={handleDateChange}
      analyzedAt={data?.analyzed_at}
      isStale={isStaleBoard}
      picks={picks}
      isLoading={isLoading}
      isError={isError}
      errorMessage={error instanceof Error ? error.message : null}
      onRetry={() => void refetch()}
      onReanalyze={() => void handleTriggerAnalysis()}
      isReanalyzing={isTriggering || isFetching}
      emptyMessage={data?.message ?? null}
      minProbability={0.65}
      teams={allTeams}
      selectedTeams={selectedTeams}
      onToggleTeam={handleToggleTeam}
      onClearTeams={handleClearTeams}
      teamFilterEmpty={isFilterEmptyState}
      lineupFor={(pick) =>
        lineupsByTeam.get(pick.player_team_code || getCanonicalTeamCode(pick.player_team)) ?? null
      }
      showLineup
      isLineupLoading={isLineupsLoading}
      isLineupError={isLineupsError}
      slipDirection={(pick) =>
        isInSlip(pick.player_name, pick.metric)
          ? (slipPicks.find(
              (item) => item.player_name === pick.player_name && item.metric === pick.metric,
            )?.direction ?? null)
          : null
      }
      onToggleSlip={handleToggleSlip}
      slipCaption={(pick) => {
        const leg = slipPicks.find(
          (item) => item.player_name === pick.player_name && item.metric === pick.metric,
        );
        return leg ? complementHitRateLabel(leg) : null;
      }}
      onReviewBoard={() => void handleReviewBoard()}
    />
  );
}
