# Theo Round 1 Analysis

Stable folders for official-log review:

- `v8_naive_106170/`
  - run id: `106170`
  - submission id: `5a1dd381-60d1-483b-b0db-43bf0f647af1`
  - official final PnL: `3194.09375`
- `v9_trend_107797/`
  - run id: `107797`
  - submission id: `12f1849f-e742-4581-bced-fa268f4527a3`
  - official final PnL: `7519.6875`
- `v10_mr_trend_109579/`
  - run id: `109579`
  - submission id: `f132314a-d158-4adc-a338-e885f40acacc`
  - official final PnL: `9386.5`
- `v11_hold_110477/`
  - run id: `110477`
  - submission id: `79b856ef-91b6-4034-9976-aae66f601760`
  - official final PnL: `9542.5`
- `v19_book_follow_118950/`
  - run id: `118950`
  - submission id: `8ef05877-f534-43af-878e-06adbe561b88`

Current read on `109579`:

- `INTARIAN_PEPPER_ROOT` contributes `6857.0` PnL, `ASH_COATED_OSMIUM` contributes `2529.5`.
- IPR buy flow is the weak point:
  - total buy qty: `135`
  - all official buys happen `at_or_above_ask`
  - 5-tick weighted markout on buys: `-5.326`
- IPR sell flow is better:
  - total sell qty: `55`
  - sells are passive `inside_spread`
  - 5-tick weighted markout on sells: `+1.966`
- IPR ends the run at `+80` position, so the strategy effectively wants to stay max long anyway.
- Several passive sells are followed by immediate ask re-buys, which creates churn.

Next iteration:

- `theo_round1_v11` keeps `ASH_COATED_OSMIUM` unchanged from V10.
- For `INTARIAN_PEPPER_ROOT`, V11 adds a strong-trend hold mode to suppress passive asks when already heavily long.

Current read on `110477`:

- V11 is not worse in the official run: `9542.5` vs `9386.5` for V10 on run `109579`.
- `ASH_COATED_OSMIUM` is unchanged between the two runs: official PnL stays `2529.5`.
- The entire delta comes from `INTARIAN_PEPPER_ROOT`:
  - V10 official IPR PnL: `6857.0`
  - V11 official IPR PnL: `7013.0`
- Official IPR flow in V11 becomes very sparse and directional:
  - only `9` trades
  - only `BUY` fills
  - final position stays `+80`

Day-0 local backtest takeaway:

- For IPR, live `110477` looks much closer to local `realistic` / `worse` than to `queue`.
- `queue` still massively overestimates passive activity:
  - V10 day 0 queue: `979` IPR trades
  - V11 day 0 queue: `14` IPR trades
- Conservative fills align better with the official shape:
  - V11 day 0 realistic: `11` IPR trades, end position `+80`
  - V11 official 110477: `9` IPR trades, end position `+80`

Working assumption going forward:

- For IPR iteration, optimize primarily against `--execution-rule realistic` or `worse`.
- Treat `queue` as an upper bound / stress test, not as the main decision metric.

Local `realistic` ranking by day:

- `day 0`
  - V9: `78377.0`
  - V10: `77181.0`
  - V11: `79024.0`
- `day -1`
  - V9: `78710.0`
  - V10: `77418.0`
  - V11: `79090.0`

Interpretation:

- On both `day 0` and `day -1`, V11 is the best local `realistic` version for `INTARIAN_PEPPER_ROOT`.
- V10 improves the official hidden run versus V9, but locally it still overtrades relative to V11.
- V11 is the cleanest alignment between local conservative backtest and official IMC behavior.

Rejected experiment:

- V12 = V11 + "skip the first ask uptick" during strong uptrend.
- Result on `day 0 realistic`: `79015.0`, slightly below V11 `79024.0`.
- Conclusion: this specific micro-timing filter does not help; keep V11 as the current IPR baseline.

Current promoted candidate:

- V13 = V11 hold logic + tuned IPR entry params
  - `take_edge=0.75`
  - `trend_take_boost=0.55`
- Local `realistic` results:
  - `day 0`: `79038.0` on IPR vs `79024.0` for V11
  - `day -1`: `79100.0` on IPR vs `79090.0` for V11
- Interpretation:
  - gain is small but consistent
  - behavior shape stays close to V11 and close to official `110477`
  - this is a safe tuning candidate to submit before adding more logic

Official follow-up on `111852`:

- `111852` is the official run for V13.
- It is slightly worse than V11 in live IMC:
  - V11 official total: `9542.5`
  - V13 official total: `9511.5`
  - V11 official IPR: `7013.0`
  - V13 official IPR: `6982.0`
- Main read:
  - V13 bought the 80-lot IPR inventory earlier and in fewer, larger chunks
  - that worsened the entry price instead of improving the carry
  - conclusion: "buy earlier / harder" is not the next edge

Round of long-bias experiments after `111852`:

- User concern was correct: from V11 onward, IPR mostly behaves like `buy then hold`, with almost no sells.
- We implemented four separate V14 variants on top of a new configurable long-bias framework:
  - `V14A`: long inventory simple
  - `V14B`: long inventory + dip buying
  - `V14C`: long-biased MM
  - `V14D`: combo
- Local `day 0 realistic` results for IPR:
  - V11: `79024.0`
  - V14A: `75230.0`
  - V14B: `76265.0`
  - V14C: `76126.0`
  - V14D: `76902.0`
- Interpretation:
  - all four variants reintroduced a lot of IPR turnover
  - none beat the simpler V11 hold profile
  - in this environment, carrying the long seems more valuable than cycling it

Conservative trim experiment:

- V15 = V11 + tiny passive asks only when already very long in a strong uptrend,
  with asks quoted further away.
- Local `day 0 realistic` result:
  - V15: `79024.0`, exactly equal to V11
- Interpretation:
  - small, patient sells do not hurt the setup
  - but they did not create extra edge yet on the tested day

Current ranking after the latest iteration:

- Best live run so far: `V11` on `110477`
- Best local conservative baseline: `V11`
- Best recent experimental takeaway:
  - broad long-biased inventory-cycling underperforms
  - if we reintroduce sells, they must stay rare, patient, and probably only
    happen on clear local overextension while preserving a near-max long core

V16 candidate:

- Strategy direction:
  - keep the V11 long-hold profile
  - add only one focused feature family: `buy dips / don't chase`
  - no time scheduler, no broad inventory recycling
- Mechanically:
  - maintain strong-trend ask suppression from V11
  - track a fast EMA and recent high
  - cap aggressive IPR buys to `6` units when not clearly on a dip
  - still allow reloading on local pullbacks in uptrend

V16 local results:

- `day 0 realistic`
  - V11: `79024.0`
  - V16: `79049.0`
  - improvement: `+25.0`
- `day -1 realistic`
  - V11: `79090.0`
  - V16: `79049.0`
  - degradation: `-41.0`

Behavior change:

- On `day 0`, V16 turns the V11 taker buys from a few `8-11` lot clips into many
  smaller `6` lot clips.
- That slightly improves the aggregate 5-tick IPR markout on `day 0`:
  - V11: `-5.68`
  - V16: `-4.88`
- On `day -1`, the same fragmentation delays accumulation a bit too much, so the
  carry is slightly worse than V11.

Interpretation:

- V16 is not a safer baseline than V11.
- It is a deliberate live-oriented bet that targets the exact official failure
  mode seen on V13: buying too much too early when the market is stretched.
- If we want the most conservative submission, stay on V11.
- If we want to test a new idea with a clear hypothesis against the official
  environment, V16 is the current candidate.

Official follow-up on `114230`:

- `114230` is the official run for V16.
- total official PnL: `9540.5`
- comparison:
  - V11 `110477`: `9542.5`
  - V13 `111852`: `9511.5`
  - V16 `114230`: `9540.5`

What this means:

- V16 did not beat V11 on total official PnL.
- But it did recover almost all of the gap introduced by V13.
- Since `ASH` is unchanged at `2529.5`, this is entirely an IPR execution story.

Official IPR execution quality:

- V11 official IPR:
  - pnl `7013.0`
  - weighted `markout_5 = -5.6625`
  - weighted `markout_10 = -5.04375`
- V13 official IPR:
  - pnl `6982.0`
  - weighted `markout_5 = -8.3625`
  - weighted `markout_10 = -7.69375`
- V16 official IPR:
  - pnl `7011.0`
  - weighted `markout_5 = -4.6875`
  - weighted `markout_10 = -4.525`

Interpretation:

- V16 genuinely improved average IPR buy quality in live IMC.
- The hypothesis behind V16 was therefore directionally correct.
- The reason it still finished almost tied with V11 is that it continued
  re-accumulating late at `12014`, which likely gave back most of the saved edge.

Current best read before V17:

- keep the smaller early buy clips from V16
- keep dip reloads
- once inventory is already substantially long, clamp or block late aggressive
  rebuys unless the market gives a fresh local pullback

Official follow-up on `118950`:

- `118950` is the official run for V19.
- the shape is directionally good: IPR buys happen low in the trend and sells happen on local highs.
- but the sell side is still too sparse:
  - official IPR trades: `34`
  - official IPR buy qty: `120`
  - official IPR sell qty: `40`
- reconstructing the run from the official log shows only `13` sell-opportunity ticks in total,
  and only `8` of them while position was already at least `+60`.
- several of those rich-bid windows were missed entirely, despite already holding enough inventory.

Interpretation:

- V19 does not need a wholesale redesign.
- the next edge is not "sell much more often".
- the next edge is "sell a tiny amount on the rare rich-bid windows where we are already very long".

V19 follow-up experiments:

- `V20` tested a broad combination:
  - explicit trim sells
  - more competitive asks
  - rebuy blocking
- result: rejected immediately
  - day 0 realistic IPR dropped to `69816.0`
  - too much carry was sacrificed for extra churn

- `V21` kept the V19 structure and added only tiny sell-opportunity takes plus a minimum neutral unwind size.
  - base params were slightly too eager and landed below V19 on day 0

- `V22` is the tuned version of that same idea:
  - only trim on sell-opportunity windows when already at full inventory (`position >= 80`)
  - trim size stays tiny (`2`)
  - no broader rebuy block, no passive ask rewrite

Local `realistic` read on the V19 branch:

- `day 0`
  - V19: `78553.0`
  - V22: `78817.0`
- `day -1`
  - V19: `79290.0`
  - V22: `79369.0`

Current read:

- `V22` is the first clean improvement over the official V19 branch.
- it is still slightly below `V17` on the two-day local aggregate.
- so `V22` is best viewed as the live-oriented continuation of the V19 idea, not as a proven new overall baseline.

V23 / V24 inventory-carry follow-up:

- `V23` tested an explicit carry floor plus fill-assist logic.
  - shape was directionally consistent with the research goal
  - but local realistic results stayed below `V17`
  - the main issue was not average inventory once full, but how long it still took to finish the last lots on weaker paths

- `V24` reframed the idea as inventory bands:
  - `0-60`: normal accumulation
  - `60-75`: assisted accumulation
  - `75-80`: top-up plus tiny trims above a floor

Best local `realistic` read for the tuned `V24`:

- `day 0`
  - total: `96027.0`
  - IPR: `79179.0`
  - trajectory: `t50=6300`, `t70=9300`, `t80=11500`
- `day -1`
  - total: `96130.0`
  - IPR: `79037.0`
  - trajectory: `t50=5000`, `t70=5900`, `t80=6100`

Comparison vs `V17`:

- `V24` improved on `V23` and moved back above the `V22` branch locally.
- but it still stayed below `V17` on both tested days.
- the remaining gap is mainly on day 0: `V24` still reaches `70-80` later than `V17`, so it gives back carry even though the later trims are cleaner and rarer.

Current read:

- `V24` is a valid isolated candidate and its submission export is ready.
- `V17` remains the safest baseline to submit.
