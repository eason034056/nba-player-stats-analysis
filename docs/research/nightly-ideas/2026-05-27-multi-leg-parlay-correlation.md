# Multi-leg parlay correlation modeling for player props

**Ticket:** SPO-65 (research only, no implementation)
**Author:** Scout
**Date:** 2026-05-27
**Status:** for owner review

## Problem statement

Sports Lab's synthesizer (`scripts/agents/agents.py:559`) emits **single-leg** recommendations only: one player, one stat, one line, one decision. The prop-betting consumer market is overwhelmingly **multi-leg**. PrizePicks, Underdog, Sleeper, and DraftKings build their entire UX around 2–6-leg combinations and price them with explicit (PrizePicks/Underdog/Sleeper, "pick'em" daily fantasy) or implicit (DraftKings SGP) correlation logic. A Sports Lab user who wants to mirror their PrizePicks slip today gets zero help from us on whether two correlated overs are EV+ together — the per-leg scorecards are computed as if every prop were independent. This is both a product-positioning gap (we look thin next to competitors) and a math gap (naïvely multiplying our single-leg `model_probability` values under-prices positively-correlated parlays and over-prices anti-correlated ones — Wizard of Odds reports a ~30% bias in a worked NFL example).

## Competitor landscape

- **PrizePicks (Pick'em, DFS-classified)** — User builds 2–6-leg lineups, picks More/Less. Power Play table (verbatim from their help center): **2-pick 3×, 3-pick 6×, 4-pick 10×, 5-pick 20×, 6-pick 37.5×**. Flex Play pays partial — e.g. 6/6 = 25×, 5/6 = 2×, 4/6 = 0.4×. Correlation is acknowledged but not numerically disclosed: *"Lineups with multiple athletes playing in the same game may have reduced payout rates"* and Demon/Goblin projection modifiers *"carry altered standard payout rates"* ([PrizePicks payouts](https://www.prizepicks.com/help-center/payouts)). Same-game stacks are allowed; the platform absorbs the correlation cost in the multiplier.

- **Underdog Fantasy (Pick'em + Pick'em Flex)** — Higher/Lower on stat projections, 2–8 picks. Standard requires all-correct; Flex (≥3 picks) allows 1–2 misses at reduced multiplier. Per-pick stat-difficulty multipliers (e.g. 0.7× easier, 1.5× harder) tag individual selections and compound multiplicatively across the slip ([Underdog Streaks multipliers](https://help.underdogfantasy.com/en/articles/11007684-streaks-base-multipliers), [Underdog Pick'em Flex payouts](https://help.underdogfantasy.com/en/articles/13161362-pick-em-flex-flexed-payouts)). [unverified] We could not retrieve the canonical Standard/Flex multiplier-by-leg table directly — Underdog's `app.underdogsports.com/rules/pick-em` and their help-center articles both returned HTTP 403 to non-browser clients. The shape is confirmed by their own help-center URLs and consistent third-party reporting; the exact per-leg numbers should be re-verified from a logged-in browser session before any implementation.

- **Sleeper Picks** — More/Less on stat projections. Sleeper assigns an **explicit numeric multiplier to each side of each pick** (e.g. Trout o1.5 TB at 1.79×, u1.5 TB at 1.72×) and the slip's payout is the **product of the leg multipliers** ([Sleeper Player Picks Rules](https://support.sleeper.com/en/articles/9047931-sleeper-player-picks-rules)). Hard rules: *"All contests must include at least one player from multiple teams. You may not include multiple picks for the same player."* Flex contests pay on 1–2 misses for ≥5-pick slips. The two-team-minimum rule is itself a correlation control — they're refusing the most heavily correlated stacks rather than re-pricing them.

- **DraftKings Same Game Parlay (sportsbook, not DFS)** — Combines multiple legs from one game into a single ticket with a single combined price. Critical UX limitation: *"DraftKings' approach to same game parlays … doesn't list the odds of individual legs. Bettors can only see what the entire parlay will pay."* ([DraftKings SGP overview](https://help.draftkings.com/hc/en-us/articles/22447258283795-DraftKings-Progressive-Parlays-Overview-US), background analysis at [Wizard of Odds](https://wizardofodds.com/article/same-game-parlays-the-mathematics-of-correlation/)). DraftKings uses a proprietary correlation model — undisclosed, but well-known in industry to be a Gaussian-copula hybrid layered on empirical joint frequencies. Cross-book pricing on identical 3-leg SGPs varies by 60–80 points, which is direct evidence that correlation modeling, not market efficiency, is what differentiates books here.

## Correlation theory primer

Two simple-minded approaches and one industry-standard approach:

**1. Naïve independence (wrong, but the implicit current Sports Lab assumption).** `P(all legs win) = Π P(leg_i)`. For positively correlated legs (e.g. LeBron pts over + Lakers team total over) this is a systematic under-estimate; for negatively correlated legs (e.g. LeBron pts over + Davis pts over when usage is zero-sum on the same possessions) it over-estimates. Wizard of Odds gives a worked NFL example: independence predicts 16.0%, Gaussian-copula joint predicts 21.2%, observed empirical frequency 20.4% — independence is off by ~30% relative ([Wizard of Odds, *Same-Game Parlays: The Mathematics of Correlation*](https://wizardofodds.com/article/same-game-parlays-the-mathematics-of-correlation/)).

**2. Empirical joint frequency.** Count how often historical games with matching conditions actually produced both legs winning. Cleanest when you have lots of data (e.g. game-script-style legs in NFL). Falls apart for player-prop combinations where the specific (player_A, player_B, line_A, line_B) cell is essentially empty in any reasonable sample — exactly the regime Sports Lab is in with a 30k-row `nba_player_game_logs.csv`.

**3. Copula decomposition (industry standard for player-prop SGPs).** Separate the per-leg marginal distribution from the cross-leg dependence structure. The Gaussian copula maps each leg's CDF to a latent standard normal `Z_i = Φ⁻¹(p_i)`, imposes a correlation matrix Σ on the latents, then back-transforms — preserving each leg's marginal probability while letting Σ carry the joint dependence. Σ is estimated separately from historical co-movement (same-team rebounds, same-game pace effects, usage-sharing pairs). Yu, Gabrio, Baio & Lawson (2023, *Annals of Operations Research*) is the closest published precedent to our use case — they fit a **multivariate Gaussian copula over basketball player performance indicators (points, rebounds, assists, etc.) inside a Bayesian network**, explicitly to derive joint probabilities for combined player outcomes ([DOI 10.1007/s10479-022-04871-5](https://doi.org/10.1007/s10479-022-04871-5), open-access summary at [IDEAS/RePEc](https://ideas.repec.org/a/spr/annopr/v325y2023i1d10.1007_s10479-022-04871-5.html)). Davis, Dawson & Krieger (2018, *Journal of Prediction Markets*) is the classic empirical-frequency precedent — they show favorites-ATS and game-total-over are correlated enough in CFB that the naïve-independence parlay price was profitably wrong for years ([DOI 10.5750/jpm.v12i2.1562](https://doi.org/10.5750/jpm.v12i2.1562)).

The recurring pragmatic recommendation in both academic and industry writing is a **hybrid**: empirical frequencies where the (sport, prop-pair, season) cell has ≥ ~50 observations; copula-smoothed estimates everywhere else.

## Proposed approach for Sports Lab

**Shape: a post-processor over an array of single-leg scorecards, not a new node inside the per-leg graph.** Concretely, a new `parlay_scorer` module (sibling to `scripts/agents/scoring.py`) that takes a list of already-computed scorecards plus the raw historical-signal blobs and emits a parlay-level scorecard: joint model probability, parlay-EV vs offered combined price, per-leg correlation contributions, and a recommend/avoid decision. The existing single-leg graph stays untouched — the parlay scorer runs *after* the synthesizer fans out across N legs. The synthesizer can keep its byte-identical NBA / WNBA prompt contracts; a new `parlay_synthesizer` produces the user-facing parlay narrative.

This shape (rather than a new graph) is justified by three properties: (a) parlay scoring is a **pure function** of already-computed per-leg signals plus a correlation matrix — there is no new LLM reasoning needed per leg, only one final synthesis; (b) it keeps the single-leg backtest harness unaffected, which matters because every single-leg regression test in `scripts/agents/tests` keeps its meaning; (c) it lets us ship a *correlation-naïve* v0 (independence + a flat "same-game penalty" multiplier) and graduate to a copula-fitted v1 without re-architecting. The realistic v1 is a **Gaussian copula over leg-pair correlations estimated from `data/nba_player_game_logs.csv`**, restricted to same-game pairs (cross-game pairs assumed independent — a reasonable approximation that matches what most public SGP literature uses).

## Open questions / risks

- **No per-leg distribution exposed today.** `scoring.compute_scorecard` returns a scalar `model_probability` (`scripts/agents/scoring.py:554`). The `get_variance_profile` tool *does* compute `cv` (`scripts/agents/scoring.py:341–344`) but it's used only as a flag, not surfaced into the scorecard. A copula needs either (a) full marginal CDFs or (b) at minimum (mean, std) per leg. Adding `model_probability_distribution: {mean, std, family}` to the scorecard is a pre-requisite — a small change but it touches the synthesizer prompt contract that SPO-32 / SPO-48 explicitly held byte-identical for the WNBA rollout.
- **Correlation matrix sparsity.** `data/nba_player_game_logs.csv` is ~30k rows of single-player-game observations. Any *player-pair* same-game cell (LeBron + Davis, both active, both > 25 min) has at most ~150 observations after filtering for rotation health and pace context. That's enough for a stable empirical correlation on the points–points axis, but immediately too sparse for cross-stat (LeBron pts ↔ Davis reb) at a specific (line_pts, line_reb) pair. We'd be relying on the copula structural assumption, not data, in those cells.
- **Lineup invalidation cascades.** A single OUT/questionable late scratch already invalidates a single-leg recommendation per the lineup-validity domain lens; for a 6-leg parlay it invalidates the entire ticket. Cache-freshness budget needs to be tightened, not just held.
- **Vig handling at the parlay level.** Books quote SGP as a single American-odds number with vig baked in; pick'em apps quote a flat multiplier. The vig-free-probability lens still applies but the conversion differs by venue. We'd need at minimum a `competitor: "prizepicks" | "underdog" | "sleeper" | "draftkings_sgp" | "implied"` switch on the parlay scorer.
- **Backtest CLV is harder.** Single-leg CLV uses closing-line movement on one market. Parlay CLV requires reconstructing the closing *joint* price across all legs, which most data providers do not snapshot. Backtest claims for a parlay product will be on shakier ground than our current single-leg backtest — owner should be told this before scoping.
- **Regulatory framing.** PrizePicks, Underdog, Sleeper are classified (in most US states) as **DFS/peer-to-peer**, not sportsbooks. DraftKings SGP is a **sportsbook product**. If Sports Lab presents parlay recommendations alongside sportsbook book-prices, we should make sure the UI does not imply a DFS-style multiplier when the user is actually targeting a DraftKings SGP. Not a blocker, but a content/legal cleanup item.
- **Competitor-payout opacity.** PrizePicks and Underdog do not publish their correlation-adjustment formulas. We cannot reproduce their exact price; we can only tell the user *our* estimated joint probability vs. their *offered* multiplier — which is exactly what they need to know, but framing matters.

## Effort estimate

**M (Medium)** — roughly **5–7 Forge heartbeats** of implementation work plus 2–3 Scout/Sentinel heartbeats around it. Breakdown:

- 1 Forge heartbeat — expose `(mean, std)` per leg in the scorecard; touch synthesizer payload contract carefully (regression-test parity vs. SPO-32 baseline).
- 1 Scout heartbeat — empirical correlation extraction script from `data/nba_player_game_logs.csv` (player-pair, same-game, by stat-pair); commit the explore script per the anti-hallucination policy.
- 2 Forge heartbeats — `parlay_scorer` module (independence baseline + Gaussian-copula path + competitor-multiplier conversion).
- 1 Forge heartbeat — `parlay_synthesizer` node + graph wiring for the multi-leg user query.
- 1 Forge heartbeat — frontend: parlay-builder UI surface + API route.
- 1 Sentinel heartbeat — integration tests against captured competitor responses; backtest-script for parlay CLV (with explicit caveat in the report that joint-closing-line is approximate).
- 1 Lens + 1 Sentinel heartbeat — review and QA.

Sizing **not S**, because the scorecard contract change ripples into the synthesizer prompt and into every regression baseline. Sizing **not L**, because the per-leg graph is untouched and the new module is a pure function — it can be built and tested in isolation. If the owner wants to descope, the cheapest credible v0.5 is **independence + flat same-game penalty multiplier (no copula)** — that is 2 Forge heartbeats and a 1-day shippable feature, at the cost of being mathematically the same as PrizePicks' undisclosed "reduced payout rate" handwave.

**Honest negative case:** if the owner's priority is single-leg accuracy (better CLV, better lineup-validity, better WNBA coverage), parlay work is a *distraction*. Multi-leg correlation modeling is a UX surface that costs us model-quality time without making any single recommendation better. Recommend deferring unless the product positioning vs. PrizePicks/Underdog is explicitly on the next-quarter roadmap.

## Sources

**Competitor primary sources**

- PrizePicks — *Player Pick Lineup standard payout rates.* https://www.prizepicks.com/help-center/payouts (retrieved 2026-05-27)
- Sleeper — *Sleeper Player Picks Rules.* https://support.sleeper.com/en/articles/9047931-sleeper-player-picks-rules (retrieved 2026-05-27)
- Underdog — *Streaks Base Multipliers.* https://help.underdogfantasy.com/en/articles/11007684-streaks-base-multipliers (retrieved 2026-05-27; canonical Pick'em multiplier table page 403'd, see Open Questions)
- Underdog — *Pick'em Flex – Flexed Payouts.* https://help.underdogfantasy.com/en/articles/13161362-pick-em-flex-flexed-payouts (retrieved 2026-05-27, 403'd to non-browser fetch)
- DraftKings — *Progressive Parlays Overview.* https://help.draftkings.com/hc/en-us/articles/22447258283795-DraftKings-Progressive-Parlays-Overview-US (retrieved 2026-05-27)

**Academic / quant sources**

- Yu, Y.; Gabrio, A.; Baio, G.; Lawson, A. (2023). *A Bayesian network to analyse basketball players' performances: a multivariate copula-based approach.* Annals of Operations Research, 325(1). DOI: [10.1007/s10479-022-04871-5](https://doi.org/10.1007/s10479-022-04871-5). Open-access metadata: https://ideas.repec.org/a/spr/annopr/v325y2023i1d10.1007_s10479-022-04871-5.html
- Davis, J.; Dawson, J.; Krieger, K. (2018). *Correlated Parlay Betting: An Analysis of Betting Market Profitability Scenarios in College Football.* The Journal of Prediction Markets, 12(2). DOI: [10.5750/jpm.v12i2.1562](https://doi.org/10.5750/jpm.v12i2.1562). https://www.ubplj.org/index.php/jpm/article/view/1562
- Shackleford, M. (Wizard of Odds). *Same-Game Parlays: The Mathematics of Correlation.* https://wizardofodds.com/article/same-game-parlays-the-mathematics-of-correlation/ (industry-math reference; worked Gaussian-copula example with formulas)
- OpticOdds. *Correlation in Same Game Parlays: How Sportsbooks are Tackling the Challenge.* https://opticodds.com/blog/correlation-in-same-game-parlays (industry context on hybrid empirical + copula approach)

**Internal sources referenced**

- `scripts/agents/agents.py:559` — `synthesizer_node` (single-leg output point)
- `scripts/agents/scoring.py:136`, `:554` — `compute_scorecard` returns scalar `model_probability`
- `scripts/agents/scoring.py:341–344` — `cv` (coefficient of variation) computed but not surfaced into the scorecard
- `scripts/agents/state.py:39` — `BettingState.scorecard` is a single dict, not an array of legs
- `data/nba_player_game_logs.csv` — header inspected; per-player-per-game rows with PTS/REB/AST/etc., suitable for empirical pair-correlation extraction
