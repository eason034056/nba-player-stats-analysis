/** Shared NBA `top_read` objects for the Today board tests. */

export const giannisTopRead = {
  player: "Giannis Antetokounmpo",
  market: "player_points",
  side: "under" as const,
  line: 31.5,
  probability: 0.81,
};

/** Fails `topReadSchema` (empty player, unknown side, non-finite line, probability above 1). */
export const brokenTopRead = {
  player: "",
  market: "player_points",
  side: "sideways",
  line: Number.NaN,
  probability: 2,
};
