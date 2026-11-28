# SPO-155 ablation results: real history data

**Run:** branch `feature/SPO-155-injury-feature-ablation` @ c405221, 2026-11-27. Data: Eason's `nba_history` dump (migrations 001-005) restored read-only into a throwaway Postgres; two exports with `build_dataset --seasons 2023:2025 --hours-before-tip 3`, the second with `--absence-source actual`. 85,089 rows each, same keys. Season 2026 rows used: 0.
**Split:** train 2024-25 regular season pregame (26,251 rows); validation 2025-26 regular season pregame (26,623 rows); every arm scored on the same 26,100 rows where the naive last-10/last-5 mean exists.

**Recommendation: do not ship official injury features yet.** Official coverage is 0 of 26,623 validation rows and 0 of 26,251 train rows: the database has no official injury report rows, no `injury_snapshots`, and no `source_refreshes`. The official arm is not measurable. Keep the official path gated off and re-run only after (a) migrations 006/007 are applied to the history database and (b) official injury reports are backfilled for both the 2024-25 training window and the 2025-26 validation window. The dump used (migrations 001-005) has no official report, injury, lineup, source_refreshes, or odds snapshot rows, so 0 coverage is structural, not a join bug; production was not checked.

**What the other arms show (MAE, lower is better, 26,100 rows):**

| Market | no_official | boxscore_standin | naive_last10 |
|---|---|---|---|
| points | 4.791 | 4.648 | 4.691 |
| rebounds | 1.956 | 1.916 | 1.944 |
| assists | 1.388 | 1.366 | 1.377 |
| threes | 0.950 | 0.934 | 0.906 |
| steals | 0.740 | 0.728 | 0.738 |
| blocks | 0.535 | 0.528 | 0.511 |
| PR | 5.768 | 5.576 | 5.680 |
| PA | 5.252 | 5.090 | 5.195 |
| RA | 2.696 | 2.623 | 2.687 |
| PRA | 6.334 | 6.063 | 6.212 |
| double-double (Brier) | 0.0559 | 0.0551 | 0.0679 |
| triple-double (Brier) | 0.00628 | 0.00549 | 0.00518 |

- `no_official` (the SPO-158 baseline) loses to the naive mean on all 10 sum markets; its numbers match `docs/decisions/SPO-158/baseline_metrics_real.json` exactly on these rows. Its double-double and triple-double Brier differ from SPO-158 only because this table uses 26,100 rows instead of 26,623.
- `boxscore_standin` beats the naive mean on 8 of 10 sum markets and on double-double, but not on threes, blocks, or triple-double.
- **Caution:** the stand-in uses the actual box score to see who did not play. That is known only after the game, so it is an upper bound on what absence information could add, not a feature we can use before tip. It suggests absence information is worth getting at T; it does not justify turning on the official path.
- Pinball loss is only at q=0.5 (half the MAE), because the trainer has no quantile model.

## Independent check (Backtest)

- Re-run reproduced the JSON and report byte-for-byte.
- All arms share one row mask; the 523 dropped validation rows have fewer than 5 prior games. `naive_last10` recomputed from `player_game_stats`: 0 mismatches (12 columns x 85,089 rows); 484 rows fall back to last-5. Naive for double-double and triple-double is the train base rate.
- Paired cluster bootstrap by game date (5,000 draws, 164 dates): stand-in vs naive is better on 8 of 10 sum markets with CIs excluding 0 (PRA -0.149, 95% CI -0.210 to -0.102) and significantly worse on threes (+0.028) and blocks (+0.017). In the first half of the dates, the points and assists CIs include 0. Stand-in vs `no_official` is better on all 10 sum markets in both halves (PRA -0.270, CI -0.314 to -0.232).
- Shuffling the stand-in columns still moves PRA from 6.334 to 6.277, so about a fifth of the gain is extra model capacity, not information.
- The 2024-25 fitted baseline loses to naive, so "stand-in beats naive" mostly shows after-the-fact absence information rescuing a weak fit.

# SPO-155 injury-feature ablation

not measurable: official coverage 0 rows. With 0 coverage, keep the official path gated/dark; re-run after the 2024-25 official reports are backfilled.

Official coverage: 0 of 26623 validation rows have a non-missing official injury value.

The point model gives q=0.5 only. The trainer has no quantile model, so pinball at 0.25 and 0.75 is not scored.

Shared scored rows: 26100. Season 2025 regular-season pregame rows where every catalog label is present and the last-10/last-5 naive exists for every sum market. Every measured arm is scored on this same set. Season 2026-27 is not in it.

## official

Status: not_measurable.
not measurable: official coverage 0 rows. With 0 coverage, keep the official path gated/dark; re-run after the 2024-25 official reports are backfilled.
Official coverage: 0 of 26623 validation rows.

## no_official

Status: measured.
Official coverage: 0 of 26623 validation rows.
- no_official player_points MAE 4.790916966996275 on 26100 rows; pinball q=0.5 2.3954584834981376 on 26100 rows.
- no_official player_rebounds MAE 1.956110119847767 on 26100 rows; pinball q=0.5 0.9780550599238835 on 26100 rows.
- no_official player_assists MAE 1.3875004702683094 on 26100 rows; pinball q=0.5 0.6937502351341547 on 26100 rows.
- no_official player_threes MAE 0.9500966549079553 on 26100 rows; pinball q=0.5 0.4750483274539776 on 26100 rows.
- no_official player_steals MAE 0.7402258034418018 on 26100 rows; pinball q=0.5 0.3701129017209009 on 26100 rows.
- no_official player_blocks MAE 0.5346105944292155 on 26100 rows; pinball q=0.5 0.2673052972146078 on 26100 rows.
- no_official player_points_rebounds MAE 5.767835617605486 on 26100 rows; pinball q=0.5 2.883917808802743 on 26100 rows.
- no_official player_points_assists MAE 5.251598545134284 on 26100 rows; pinball q=0.5 2.625799272567142 on 26100 rows.
- no_official player_rebounds_assists MAE 2.696275429597415 on 26100 rows; pinball q=0.5 1.3481377147987075 on 26100 rows.
- no_official player_points_rebounds_assists MAE 6.333649070471299 on 26100 rows; pinball q=0.5 3.1668245352356497 on 26100 rows.
- no_official player_double_double Brier 0.05588493404389708 on 26100 rows; log loss 0.1993584273573927 on 26100 rows.
- no_official player_triple_double Brier 0.006275285860860177 on 26100 rows; log loss 0.03975405804861985 on 26100 rows.

## boxscore_standin

Status: measured.
Official coverage: 0 of 26623 validation rows.
- boxscore_standin player_points MAE 4.647745098801972 on 26100 rows; pinball q=0.5 2.323872549400986 on 26100 rows.
- boxscore_standin player_rebounds MAE 1.9157413618544494 on 26100 rows; pinball q=0.5 0.9578706809272247 on 26100 rows.
- boxscore_standin player_assists MAE 1.366126820190762 on 26100 rows; pinball q=0.5 0.683063410095381 on 26100 rows.
- boxscore_standin player_threes MAE 0.9340362077245147 on 26100 rows; pinball q=0.5 0.46701810386225734 on 26100 rows.
- boxscore_standin player_steals MAE 0.7279614910586473 on 26100 rows; pinball q=0.5 0.36398074552932363 on 26100 rows.
- boxscore_standin player_blocks MAE 0.5282536297803074 on 26100 rows; pinball q=0.5 0.2641268148901537 on 26100 rows.
- boxscore_standin player_points_rebounds MAE 5.576106683229267 on 26100 rows; pinball q=0.5 2.7880533416146336 on 26100 rows.
- boxscore_standin player_points_assists MAE 5.089672175631379 on 26100 rows; pinball q=0.5 2.5448360878156895 on 26100 rows.
- boxscore_standin player_rebounds_assists MAE 2.6232105343151613 on 26100 rows; pinball q=0.5 1.3116052671575806 on 26100 rows.
- boxscore_standin player_points_rebounds_assists MAE 6.063424966425576 on 26100 rows; pinball q=0.5 3.031712483212788 on 26100 rows.
- boxscore_standin player_double_double Brier 0.05512039035459139 on 26100 rows; log loss 0.19339885169503745 on 26100 rows.
- boxscore_standin player_triple_double Brier 0.005486878721066422 on 26100 rows; log loss 0.035304078248019656 on 26100 rows.

## naive_last10

Status: measured.
Official coverage: 0 of 26623 validation rows.
- naive_last10 player_points MAE 4.690563218390804 on 26100 rows; pinball q=0.5 2.345281609195402 on 26100 rows.
- naive_last10 player_rebounds MAE 1.943521072796935 on 26100 rows; pinball q=0.5 0.9717605363984675 on 26100 rows.
- naive_last10 player_assists MAE 1.3767969348659004 on 26100 rows; pinball q=0.5 0.6883984674329502 on 26100 rows.
- naive_last10 player_threes MAE 0.9058582375478926 on 26100 rows; pinball q=0.5 0.4529291187739463 on 26100 rows.
- naive_last10 player_steals MAE 0.7384559386973178 on 26100 rows; pinball q=0.5 0.3692279693486589 on 26100 rows.
- naive_last10 player_blocks MAE 0.5109386973180077 on 26100 rows; pinball q=0.5 0.25546934865900384 on 26100 rows.
- naive_last10 player_points_rebounds MAE 5.679586206896552 on 26100 rows; pinball q=0.5 2.839793103448276 on 26100 rows.
- naive_last10 player_points_assists MAE 5.19467816091954 on 26100 rows; pinball q=0.5 2.59733908045977 on 26100 rows.
- naive_last10 player_rebounds_assists MAE 2.6873141762452106 on 26100 rows; pinball q=0.5 1.3436570881226053 on 26100 rows.
- naive_last10 player_points_rebounds_assists MAE 6.211946360153258 on 26100 rows; pinball q=0.5 3.105973180076629 on 26100 rows.
- naive_last10 player_double_double Brier 0.06794527945822611 on 26100 rows; log loss 0.26271687879670774 on 26100 rows.
- naive_last10 player_triple_double Brier 0.005183792737478466 on 26100 rows; log loss 0.03260983131966631 on 26100 rows.

