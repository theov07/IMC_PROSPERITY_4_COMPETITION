# HYDROGEL Round 4 Research Log

## Objective

- Start from `prosperity/strategies/round_4/r3_combined_best_round3_submission.py`
- Trade `HYDROGEL_PACK` only
- Maximize 3-day round 4 backtest PnL
- Treat max drawdown as a first-class metric, not a side note
- Work in two phases:
  - strong non-counterparty baseline first
  - then trader-ID / clustering / following / maker-response overlays only if they add real edge

## Initial observations

- Round 4 HYDRO counterparties are almost entirely:
  - `Mark 14`
  - `Mark 38`
  - tiny residual `Mark 22`
- This suggests a simple and structured market ecology, which is good for signal extraction.

## Research plan

1. Isolate HYDRO from the monolithic round-3-combined script and benchmark it.
2. Compare that base against existing round-4 HYDRO-only baselines already present in the repo.
3. Diagnose per-day failures and drawdown sources before adding trader-aware logic.
4. Build trader-aware overlays only where the data supports them:
   - direct following / fading
   - good-vs-bad trader clustering
   - intra-trader persistence
   - inter-trader reaction / lead-lag
   - maker sizing / skew response to flow
5. Keep only robust changes that help both PnL and drawdown.

## Test log

- Baseline benchmark complete:
  - `r4_hydro_from_r3_combined_v0`: `107,670.0`, DD `19,030.0`
    - day 1: `39,567.0`
    - day 2: `27,604.0`
    - day 3: `40,499.0`
  - `r4_hydro_port_v9_only`: `31,744.0`, DD `2,821.0`
  - `r4_hydro_counterparty_v1_only`: `31,346.1`, DD `2,821.0`
  - `r4_hydro_mark14_v1`: `25,615.0`, DD `3,077.0`

- Conclusion:
  - The round-3-combined guarded-anchor HYDRO base is massively stronger in raw PnL.
  - The current round-4 repo baselines are safer but far weaker.
  - Main optimization target now is not “find any alpha” but “preserve the 107k engine while reducing its drawdown and then testing trader-aware overlays on top.”

- First non-counterparty targeted sweep:
  - baseline: `107,670.0`, DD `19,030.0`
  - `maker_size_base_pct=0.15`: `108,083.0`, DD `18,297.0`
    - first clear improvement on both PnL and drawdown
  - `inventory_aversion_gamma=0.0015`: `107,509.0`, DD `18,960.0`
    - slightly safer, slightly worse PnL
  - `guard_reversion_threshold=7.5`: `110,329.0`, DD `19,705.0`
    - strong PnL boost, but worse drawdown and weaker day 2
  - `passive_unwind_trigger=0.30`: `107,647.0`, DD `19,030.0`
    - basically flat
  - `pct_kept_for_takers=0.02`: no meaningful effect

- Counterparty diagnostics:
  - `Mark 14` and `Mark 38` dominate almost all HYDRO flow.
  - Their 1-20 trade markouts are almost perfect mirrors:
    - `Mark 14`: strongly positive future move in his trade direction
    - `Mark 38`: strongly negative future move in his trade direction
  - Their 1-second net-flow correlation is about `-0.99` every day.
  - Their own-sign persistence is only about `0.49-0.54`.
  - Reading:
    - they are useful as immediate fair-value information
    - they are not useful as a naive slow follower signal

- Broader non-ID hill-climb:
  - `maker_size_base_pct=0.12`: `107,726.0`, DD `17,784.0`
    - safest size cut, but not enough PnL
  - `take_edge_lo=0.5`, `take_edge_hi=1.0` on top of `maker_size_base_pct=0.15`: `108,713.0`, DD `18,297.0`
    - better than the first size-only winner
  - `guard_reversion_threshold=6.0` on top of the stronger size/taker base:
    - with `maker_size_base_pct=0.15`, `take_edge_lo=0.5`, `take_edge_hi=1.0`, `inventory_aversion_gamma=0.0015`
    - `110,515.0`, DD `18,878.0`
    - this is the first big step up in raw PnL while still keeping DD reasonable
  - pushing guard too high keeps improving day 3 but keeps hurting day 2:
    - `guard=6.5` non-ID: `110,797.0`, DD `18,882.0`
    - `guard=7.0` non-ID: `110,649.0`, DD `18,943.0`
  - Reading:
    - day 2 is the weak day of the family
    - more “let the anchor re-engage later” is good in trend/reversion regimes, but too much of it starves day 2

- Trader-aware overlay results:
  - Best idea is not “follow all IDs”, but a conservative `Mark 14` fair-value nudge.
  - `Mark 14` only beats `Mark 14 + Mark 38`:
    - `Mark 14` only: `110,782.0`, DD `18,878.0`
    - both marks: lower PnL, slightly higher DD
  - Reading:
    - because `Mark 38` is almost the mirror of `Mark 14`, adding both mostly saturates the same signal
    - the cleaner overlay is a single positive `Mark 14` anchor shift

- Final local tuning around the best regime:
  - Best stable family found:
    - `maker_size_base_pct=0.16`
    - `guard_reversion_threshold=6.5`
    - `take_edge_lo=0.55`
    - `take_edge_hi=1.10`
    - `inventory_aversion_gamma=0.0020`
    - `Mark 14` anchor shift only
  - With `mark_anchor_shift_per_unit` in the `1.0-1.1` plateau and no inventory-target overlay:
    - final best: `111,487.0`, DD `19,085.0`
    - days: `[40,265.0, 25,543.0, 45,679.0]`
  - The `Mark 14` inventory target ended up irrelevant in the final regime:
    - target `50`, target `20`, and target `0` all came out effectively flat
    - the real counterparty edge is fair-value translation, not target-inventory following

- Final candidate:
  - member: `r4_hydro_only_v1_guarded_mark14`
  - wrapper: `submissions/round_4/r4_hydro_only_v1_guarded_mark14.py`
  - structure:
    - hydro-only
    - round-3 guarded-anchor engine
    - lower but still productive maker sizing
    - wider taker gates
    - slightly stronger inventory aversion
    - small `Mark 14` anchor shift
  - outcome vs original hydro-only monolith base:
    - start: `107,670.0`, DD `19,030.0`
    - final: `111,487.0`, DD `19,085.0`
    - gain: `+3,817.0` for only `+55.0` extra DD

- Deeper follow-up after the first final candidate:
  - Generic latent modules were mostly dead ends:
    - fill toxicity: worse
    - jump filter: much worse
    - microprice tilt: worse and higher DD
    - spread widening: catastrophic for PnL
    - spread z-score: basically flat
    - naive momentum following: worse
  - Important reading:
    - HYDRO alpha is not coming from generic “flow chasing” bricks
    - it is coming from the guarded-anchor core plus a very specific named-trader overlay

- New structural alpha found:
  - I added a small passive `mark_size_skew` on top of the `Mark 14` anchor shift.
  - Logic:
    - if `Mark 14` is directionally positive, slightly increase bid size and reduce ask size
    - if negative, do the symmetric opposite
    - this is not a follower overlay; it is a maker-side adverse-selection control
  - This was the first new deep idea that consistently improved the best prior regime.

- Best second-generation regime:
  - family:
    - `guarded_anchor`
    - `Mark 14` anchor shift
    - small `Mark 14` size skew
  - good local plateau:
    - `mark_size_skew` around `0.10-0.15`
    - `inventory_aversion_gamma` around `0.0018-0.0019`
    - `take_edge_lo / hi` slightly wider than before
  - best final point found:
    - member: `r4_hydro_only_v2_guarded_mark14_skew`
    - wrapper: `submissions/round_4/r4_hydro_only_v2_guarded_mark14_skew.py`
    - `PnL`: `111,761.0`
    - `DD`: `19,085.0`
    - days: `[40,202.0, 25,721.0, 45,838.0]`

- Reading of the v2 improvement:
  - relative to the v1 final (`111,487.0`), the extra edge comes from:
    - slightly wider taker thresholds: `0.60 / 1.15`
    - slightly softer inventory bias than the previous best local point: `gamma=0.0019`
    - small `Mark 14` maker size skew
  - day 2 improved the most from this second round of research
  - the drawdown stayed effectively in the same band, so this looks like a real quality improvement rather than just extra gross risk-taking

## Notes

- Avoid timestamp hardcoding.
- Prefer interpretable MM behavior over fragile oracle behavior.
- For trader IDs, the right question is not “can we use them?” but “do they improve fills, fair value, or inventory control enough to justify the complexity?”

## v5-Based Reboot

- New baseline from friend file:
  - `prosperity/strategies/round_4/hydro_mv_v5_best.py`
  - `PnL`: `153,117.0`
  - `DD`: `20,086.0`
  - days: `[45,258.0, 34,096.0, 73,763.0]`
- This base is structurally different from the old guarded-anchor family:
  - passive spread capture is the engine
  - selective AR takers are the accelerator
  - inventory often runs near the limit, so taker-capacity allocation matters a lot

- What clearly does not transfer from the old family:
  - `use_anchor_guard=True` is catastrophic here:
    - example `guard_reversion_threshold=5.0`: `113,163.0`
  - `passive_unwind` also hurts:
    - `trigger=0.60`, `skew=1`: `151,066.0`
  - Reading:
    - v5 already has good selectivity through `ar_taker_edge=12`
    - extra macro guards mostly starve the best flow
    - making passive unwind more aggressive gives away too much spread

- What helps, but only a little:
  - counterparty fair shift based on `Mark 14`:
    - `shift=0.75`: `153,335.0`
    - `shift=1.00`: `153,380.0`
  - with this family, `Mark 38` adds useful opposite information:
    - `Mark 14 + Mark 38`, `shift=0.75`: `153,494.0`
  - Reading:
    - the trader IDs should not dominate the model
    - they work best as a small translation of fair value

- New deep alpha found:
  - inventory-aware taker edge on top of v5.
  - Logic:
    - when already long, make further buy takers harder and sell takers easier
    - when already short, do the symmetric opposite
    - this preserves passive spread capture while wasting less capacity on same-direction takers
  - Standalone result:
    - `inventory_taker_edge_shift=3.0`: `156,575.0`, `DD=19,992.0`

- Best combined family:
  - inventory-aware taker edge
  - small fair shift from `Mark 14 + Mark 38`
  - no passive unwind
  - no hard anchor guard
  - best point found:
    - `inventory_taker_edge_shift=4.0`
    - `trader_fair_shift_per_unit=0.5`
    - `trader_buy_weights={"Mark 14": 1.0, "Mark 38": -1.0}`
    - `trader_sell_weights={"Mark 14": -1.0, "Mark 38": 1.0}`
  - result:
    - `PnL`: `157,378.0`
    - `DD`: `19,982.0`
    - days: `[48,582.0, 39,682.0, 69,114.0]`

- Interpretation of the final improvement:
  - most of the gain is structural, not predictive:
    - better use of inventory and taker capacity
  - trader IDs are still useful, but as a small overlay only
  - the combo is robust because each part has a narrow, interpretable job:
    - passive book earns spread
    - AR takers fire only on large deviations
    - inventory-aware edge avoids digging deeper in the loaded direction
    - trader signal nudges fair in the right direction without replacing the core model

## v6 Follow-Up Deep Dive

- I revisited the round-4 trade tape before adding more code, and the most important microstructure fact is:
  - `Mark 14` is consistently the passive side
    - buys at the bid
    - sells at the ask
  - `Mark 38` is effectively the crossing side against him
    - buys at the ask
    - sells at the bid
- Reading:
  - `Mark 14` behaves like an informed maker
  - `Mark 38` behaves like the liquidity taker hitting that quote
  - this explains why trader-ID alpha helps mostly as a fair/value nudge and not as a naive “follow the tape” strategy

- I extended `hydro_mv_v6_invaware` with optional research hooks for:
  - fair-shift damping when trader signal conflicts with the AR core
  - trader-aware passive size skew
  - trader-aware taker-edge skew
- Result of that whole branch:
  - none of these fine-grained overlays beat the base `v6`
  - several were effectively flat
  - the best lesson was negative:
    - the current `v6` trader overlay is already close to the right complexity level
    - pushing more signal logic into execution does not automatically add alpha

- The real next alpha was much simpler:
  - retune the execution intensity of the base `v6` engine itself
  - the two useful axes were:
    - slightly larger maker base size
    - slightly stronger trader fair shift

- Local sweep highlights around `v6`:
  - `ar_taker_size_pct=0.35`: `157,782.0`, `DD=19,982.0`
  - `maker_size_base_pct=0.30`: `157,771.0`, `DD=19,982.0`
  - `maker_size_base_pct=0.30` + `trader_fair_shift_per_unit=1.00`: `157,885.0`, `DD=19,982.0`
  - `maker_size_base_pct=0.30` + `trader_fair_shift_per_unit=1.10`: `157,941.0`, `DD=19,982.0`
  - `maker_size_base_pct=0.30` + `trader_fair_shift_per_unit=1.15`: `157,941.0`, `DD=19,982.0`

- Final best point retained:
  - member: `r4_hydro_mv_v7_maker30_fair110`
  - wrapper: `submissions/round_4/r4_hydro_mv_v7_maker30_fair110.py`
  - exported final submission:
    - `artifacts/submissions/round_4/r4_hydro_mv_v7_maker30_fair110_round4_submission.py`
  - parameters vs `v6`:
    - `maker_size_base_pct=0.30` instead of `0.25`
    - `trader_fair_shift_per_unit=1.10` instead of `0.5`
    - everything else stays on the same robust `v6` structure

- Final validated backtest on the real wrapper:
  - `PnL`: `157,941.0`
  - `DD`: `19,982.0`
  - days: `[49,429.0, 39,111.0, 69,401.0]`

- Interpretation of the new gain:
  - the engine still wins by spread capture plus selective takers
  - the stronger maker size increases monetization of the same good regime without changing the drawdown band
  - the larger fair shift makes the trader signal matter a little more, but still in a controlled way
  - importantly, this is not timestamp hardcoding and not a brittle branch-on-day design
  - it is still the same interpretable market-making family, just tuned to exploit the observed round-4 ecology a bit better

## MM Pivot

- New request:
  - push the HYDRO strategy toward a more HFT-style market-making profile
  - reduce the “always stuck near `+200/-200`” behavior
  - still maximize total PnL as much as possible

- First hard lesson:
  - simple hard inventory controls do work mechanically, but they destroy too much alpha
  - examples:
    - hard same-side taker block + passive cutoff around `0.60-0.70` inventory ratio
    - average inventory drops a lot, roughly into the `0.58-0.66` area
    - but PnL collapses into the `99k-118k` band
  - Reading:
    - this HYDRO ecology is still rewarding directional inventory usage
    - forcing a “flat book only” philosophy is too expensive on this dataset

- Second hard lesson:
  - naive inventory quote-shift / passive unwind is also bad here
  - small quote repricing toward unwind reduced PnL materially while barely changing average inventory
  - Reading:
    - the strategy is not failing because it lacks quote movement alone
    - it needs a softer reshaping of accumulation, not a crude repricing hammer

- Better idea:
  - keep the `v7` engine, but reshape passive accumulation more smoothly
  - I added optional soft MM controls in `hydro_mv_v6_invaware`:
    - `working_position_limit`
    - `inventory_same_side_power`
    - `inventory_opposite_side_boost`
    - optional passive repricing / taker blocking hooks
  - Most useful one by far:
    - convex same-side size decay through `inventory_same_side_power`
  - Reading:
    - this is closer to real MM behavior:
      - do not abruptly stop trading
      - just contract the accumulating side faster as inventory builds

- Important frontier found:
  - Best raw PnL after the full loop:
    - same `v7` family, just more persistent trader signal
    - `trader_signal_decay=0.93`
    - result: `158,898.0`, `DD=19,982.0`
    - but still very inventory-heavy:
      - avg inventory ratio about `0.8968`
      - aggressive share about `0.8395`
  - Best MM-leaning compromise:
    - `inventory_same_side_power=1.4`
    - `trader_signal_decay=0.93`
    - keep `maker_size_base_pct=0.30`
    - keep `trader_fair_shift_per_unit=1.10`
    - result: `158,893.0`, `DD=19,982.0`
    - avg inventory ratio improves to about `0.8883`
    - aggressive share improves to about `0.8332`

- Why I retained the MM-leaning version as the new submitted candidate:
  - it is only `5.0` below the absolute best raw PnL point
  - but it is directionally more aligned with the request:
    - slightly less inventory glue
    - slightly more passive participation
    - slightly less taker dependence
  - so this is the best “same PnL, more MM-like” point I found

- Final MM-soft candidate:
  - member: `r4_hydro_mv_v8_mmsoft`
  - wrapper: `submissions/round_4/r4_hydro_mv_v8_mmsoft.py`
  - exported file:
    - `artifacts/submissions/round_4/r4_hydro_mv_v8_mmsoft_round4_submission.py`
  - validated backtest:
    - `PnL`: `158,893.0`
    - `DD`: `19,982.0`
    - days: `[50,288.0, 40,380.0, 68,225.0]`

- Quant interpretation:
  - the round-4 HYDRO market still pays a lot for intelligent inventory usage
  - full HFT flat-inventory MM is too defensive on this path
  - the best practical answer is therefore:
    - keep the strong `v7` directional/MM hybrid core
    - make inventory accumulation softer and more two-sided
    - not eliminate inventory, just stop it from being quite as sticky
