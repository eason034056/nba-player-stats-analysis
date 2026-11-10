import { describe, expect, it } from "vitest";

import { selectDDHistory, selectDDOdds } from "@/lib/player-dd";
import {
  noVigResponseSchema,
  playerDDHistoryResponseSchema,
} from "@/lib/schemas";
import jokicHistory from "@/test/fixtures/player-dd-history/jokic.json";
import jokicService from "@/test/fixtures/player-dd-history/jokic.service.json";
import jokicEmptySeason from "@/test/fixtures/player-dd-history/jokic-empty-season.json";
import missingPlayer from "@/test/fixtures/player-dd-history/missing-player.json";
import wilsonHistory from "@/test/fixtures/player-dd-history/wilson.json";
import recordedNoVig from "@/test/fixtures/props-no-vig/player-double-double.json";

describe("player DD response schemas", () => {
  it("parses the player-dd-history body, including a null rate", () => {
    const populated = playerDDHistoryResponseSchema.parse({
      player: "Nikola Jokic",
      season: null,
      n_games: 75,
      dd_games: 61,
      prob_dd: 0.8133,
      message: null,
    });
    expect(populated.prob_dd).toBe(0.8133);
    expect(populated.dd_games).toBe(61);

    const empty = playerDDHistoryResponseSchema.parse({
      player: "Nobody",
      season: null,
      n_games: 0,
      dd_games: 0,
      prob_dd: null,
      message: "Player 'Nobody' not found",
    });
    expect(empty.prob_dd).toBeNull();
    expect(selectDDHistory(empty).status).toBe("empty");
  });

  it("keeps yes/no mirrors and does not require them on Over/Under rows", () => {
    const binary = noVigResponseSchema.parse({
      event_id: "evt-1",
      player_name: "Nikola Jokic",
      market: "player_double_double",
      results: [
        {
          bookmaker: "draftkings",
          line: 0.5,
          over_odds: -250,
          under_odds: 200,
          p_over_imp: 0.7143,
          p_under_imp: 0.3333,
          vig: 0.0476,
          p_over_fair: 0.6818,
          p_under_fair: 0.3182,
          fetched_at: "2026-05-08T12:00:00Z",
          yes_price: -250,
          no_price: 200,
          p_yes_imp: 0.7143,
          p_no_imp: 0.3333,
          yes_fair_prob: 0.6818,
          no_fair_prob: 0.3182,
        },
        {
          bookmaker: "fanduel",
          line: 0.5,
          over_odds: -240,
          under_odds: -240,
          p_over_imp: 0.7059,
          p_under_imp: 0.2941,
          vig: 0.045,
          p_over_fair: 0.6755,
          p_under_fair: 0.3245,
          fetched_at: "2026-05-08T12:00:00Z",
          yes_price: -240,
          no_price: null,
          p_yes_imp: 0.7059,
          p_no_imp: null,
          yes_fair_prob: 0.6755,
          no_fair_prob: 0.3245,
        },
      ],
      consensus: {
        method: "mean",
        p_over_fair: 0.6787,
        p_under_fair: 0.3213,
        p_yes_fair: 0.6787,
        p_no_fair: 0.3213,
      },
      message: null,
    });

    expect(binary.results[0]?.yes_price).toBe(-250);
    expect(binary.results[0]?.no_price).toBe(200);
    expect(binary.results[1]?.no_price).toBeNull();
    expect(binary.results[1]?.p_no_imp).toBeNull();
    expect(binary.consensus?.p_yes_fair).toBe(0.6787);
    expect(binary.consensus?.p_no_fair).toBe(0.3213);

    const selected = selectDDOdds(binary);
    expect(selected.status).toBe("ready");
    if (selected.status === "ready") {
      expect(selected.books[1]?.noPrice).toBeNull();
      expect(selected.books[0]?.yesPrice).toBe(-250);
      expect(selected.consensusYesFair).toBe(0.6787);
    }

    const overUnder = noVigResponseSchema.parse({
      event_id: "evt-2",
      player_name: "Stephen Curry",
      market: "player_points",
      results: [
        {
          bookmaker: "draftkings",
          line: 24.5,
          over_odds: -110,
          under_odds: -110,
          p_over_imp: 0.5238,
          p_under_imp: 0.5238,
          vig: 0.0476,
          p_over_fair: 0.5,
          p_under_fair: 0.5,
          fetched_at: "2026-05-08T12:00:00Z",
        },
      ],
      consensus: {
        method: "mean",
        p_over_fair: 0.5,
        p_under_fair: 0.5,
      },
      message: null,
    });

    expect(overUnder.results[0]?.yes_price).toBeUndefined();
    expect(overUnder.consensus?.p_yes_fair).toBeUndefined();
    expect(selectDDOdds(overUnder).status).toBe("unavailable");
  });
});

describe("recorded double-double payloads", () => {
  it("parses the CSV service history body for Jokic and Wilson", () => {
    const jokic = playerDDHistoryResponseSchema.parse(jokicHistory);
    expect(jokic).toEqual({
      player: "Nikola Jokic",
      season: null,
      n_games: 75,
      dd_games: 61,
      prob_dd: 0.8133,
      message: null,
    });
    expect(selectDDHistory(jokic)).toEqual({
      status: "ready",
      player: "Nikola Jokic",
      probDD: 0.8133,
      nGames: 75,
      ddGames: 61,
    });

    const wilson = playerDDHistoryResponseSchema.parse(wilsonHistory);
    expect(wilson.player).toBe("A'ja Wilson");
    expect(wilson.n_games).toBe(55);
    expect(wilson.dd_games).toBe(26);
    expect(wilson.prob_dd).toBe(0.4727);

    // The service also returns `games` as an alias. The HTTP model keeps
    // `n_games`. Zod strips the alias instead of treating it as the sample size.
    const service = playerDDHistoryResponseSchema.parse(jokicService);
    expect(service.n_games).toBe(75);
    expect(service.prob_dd).toBe(0.8133);
    expect("games" in service).toBe(false);
  });

  it("treats a zero-game sample as empty even if a rate is attached", () => {
    const emptySeason = playerDDHistoryResponseSchema.parse(jokicEmptySeason);
    expect(emptySeason.n_games).toBe(0);
    expect(emptySeason.prob_dd).toBeNull();
    expect(selectDDHistory(emptySeason)).toEqual({
      status: "empty",
      player: "Nikola Jokic",
      message: "No qualifying games for Nikola Jokic in season 1999-00",
    });

    const missing = playerDDHistoryResponseSchema.parse(missingPlayer);
    expect(selectDDHistory(missing).status).toBe("empty");
    expect(selectDDHistory({ ...missing, prob_dd: 0 }).status).toBe("empty");
  });

  it("does not turn dd_games / n_games into a rate when prob_dd is null", () => {
    const selection = selectDDHistory({
      player: "Nikola Jokic",
      season: null,
      n_games: 75,
      dd_games: 61,
      prob_dd: null,
      message: null,
    });
    expect(selection.status).toBe("empty");
  });

  it("keeps a returned prob_dd that does not equal dd_games / n_games", () => {
    const selection = selectDDHistory({
      player: "Nikola Jokic",
      season: null,
      n_games: 100,
      dd_games: 1,
      prob_dd: 0.5,
      message: null,
    });
    expect(selection).toEqual({
      status: "ready",
      player: "Nikola Jokic",
      probDD: 0.5,
      nGames: 100,
      ddGames: 1,
    });
  });

  it("parses the recorded binary no-vig body without changing yes/no values", () => {
    const parsed = noVigResponseSchema.parse(recordedNoVig);
    expect(parsed.market).toBe("player_double_double");
    expect(parsed.results[0]?.yes_price).toBe(-250);
    expect(parsed.results[0]?.no_price).toBe(200);
    expect(parsed.results[0]?.p_yes_imp).toBe(0.7143);
    expect(parsed.results[0]?.no_fair_prob).toBe(0.3182);
    expect(parsed.results[1]?.yes_price).toBe(-240);
    expect(parsed.results[1]?.no_price).toBeNull();
    expect(parsed.results[1]?.p_no_imp).toBeNull();
    expect(parsed.results[1]?.yes_fair_prob).toBe(0.6755);
    expect(parsed.results[1]?.no_fair_prob).toBe(0.3245);
    expect(parsed.consensus?.p_yes_fair).toBe(0.6787);
    expect(parsed.consensus?.p_no_fair).toBe(0.3213);

    const selected = selectDDOdds(parsed);
    expect(selected.status).toBe("ready");
    if (selected.status !== "ready") return;
    expect(selected.books[1]?.noPrice).toBeNull();
    expect(selected.books[1]?.noFair).toBe(0.3245);
    expect(selected.consensusYesFair).toBe(0.6787);
    expect(selected.consensusNoFair).toBe(0.3213);

    const tampered = noVigResponseSchema.parse({
      ...recordedNoVig,
      results: recordedNoVig.results.map((row, index) =>
        index === 1 ? { ...row, no_fair_prob: 0.1111 } : row,
      ),
    });
    const tamperedSelection = selectDDOdds(tampered);
    expect(tamperedSelection.status).toBe("ready");
    if (tamperedSelection.status !== "ready") return;
    expect(tamperedSelection.books[1]?.noFair).toBe(0.1111);
  });

  it("rejects a history body that omits n_games or gives prob_dd the wrong type", () => {
    const withoutSample: Record<string, unknown> = { ...jokicHistory };
    delete withoutSample.n_games;
    expect(() => playerDDHistoryResponseSchema.parse(withoutSample)).toThrow();
    expect(() =>
      playerDDHistoryResponseSchema.parse({
        player: jokicHistory.player,
        games: jokicHistory.n_games,
        dd_games: jokicHistory.dd_games,
        prob_dd: jokicHistory.prob_dd,
      }),
    ).toThrow();
    expect(() =>
      playerDDHistoryResponseSchema.parse({ ...jokicHistory, prob_dd: "0.8133" }),
    ).toThrow();
    expect(() =>
      playerDDHistoryResponseSchema.parse({ ...jokicHistory, n_games: "75" }),
    ).toThrow();
  });

  it("rejects a no-vig row whose yes_price is not a number", () => {
    expect(() =>
      noVigResponseSchema.parse({
        ...recordedNoVig,
        results: recordedNoVig.results.map((row, index) =>
          index === 0 ? { ...row, yes_price: "-250" } : row,
        ),
      }),
    ).toThrow();
    expect(() =>
      noVigResponseSchema.parse({
        ...recordedNoVig,
        results: recordedNoVig.results.map((row, index) =>
          index === 0 ? { ...row, bookmaker: null } : row,
        ),
      }),
    ).toThrow();
  });

  it(
    "keeps cache_state and data_age_seconds so a stale /props/no-vig snapshot can be detected",
    () => {
      const parsed = noVigResponseSchema.parse({
        ...recordedNoVig,
        cache_state: "stale",
        data_age_seconds: 90,
      }) as { cache_state?: string; data_age_seconds?: number };
      expect(parsed.cache_state).toBe("stale");
      expect(parsed.data_age_seconds).toBe(90);
    },
  );
});
