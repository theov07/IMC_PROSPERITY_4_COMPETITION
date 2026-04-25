# TODO

Priority list for turning this repository from a solid framework into a competition-winning platform.

## Round 3 LIVE alpha exploration (untestable in backtest — to do during live)

Backtest space is saturated (Pareto frontier reached on velvet+options).
These alpha sources only show in actual live IMC data:

- **Informed vs uninformed trader detection on skew deformation** — when
  one strike's IV residual jumps, watch participant flow:
  - If informed trader pattern → follow direction (e.g., gamma_scalp boost)
  - If uninformed dump → fade (e.g., temporary mean-rev taker)
  - Discrimination needs participant-level fill data live
- **Gap exploit on thin option strikes** — like R1/R2 HYDROGEL gap exploit,
  only visible in live order book where L1 thin + L2 gap → sweep aggressively
- **Time-of-session adaptive params** — first 100 live ticks build, last 100
  harvest. Different aggressiveness per phase
- **Participant flow patterns** — specific traders (Caesar, Penelope etc.)
  had distinctive flow in R1. Map who's trading which strike when
- **End-of-session unwind dynamics** — how to exit large positions before
  session close without crossing wide spreads

**Action plan for LIVE submission**:
1. Upload `v38_drop_bad` as primary (Pareto winner at 86k PnL level)
2. Observe live PnL vs backtest +86,451 projection
3. If live > backtest by >20% → live-only alpha confirmed, build dynamic
   detector for next iteration
4. If live < backtest → strategy was overfit, consider v46 (more conservative)

## Round 3 (current) — Options trading on Velvetfruit

Products: HYDROGEL_PACK (delta-1, limit 200), VELVETFRUIT_EXTRACT (delta-1 underlying, limit 200),
VEV_4000..VEV_6500 (10 European call vouchers, limit 300 each, TTE=5d at round start).

### Done
- ~~Create `prosperity/options/` module: black_scholes, implied_vol, smile fitting (quadratic polynomial)~~
- ~~Create naive `option_mm_bs` strategy (penny-improve around market with BS fair as reference)~~
- ~~Configure ROUND_3 + `r3_naive_champion` member with v4_F5 for HYDROGEL/VELVETFRUIT + BS-MM for vouchers~~
- ~~Register in strategies registry + export_submission registry + STRATEGY_FILE_DEPS for options module inlining~~
- ~~Backtest baseline: **+123,526 PnL over 3 days** (day 0: +35,842)~~

### Next
- Build smile-aware option MM that actually quotes tighter than `best ± 1` based on BS fair
- Delta-hedge via VELVETFRUIT_EXTRACT (buy options → sell S to stay delta-neutral, capture convexity)
- Vol-arbitrage: realized daily vol ≈ 2.15% but implied ≈ 1.25% — consider LONG vol overlay
- Deep OTM (K=6000, 6500) need special handling: currently skipped via `min_quote_price=2.0`
- Ornamental Bio-Pods manual challenge: 2 bids uniform [670..920] step 5, resell at 920 — reuse Round 2 MAF analysis
- Add `prosperity/options/coordinator.py` for shared smile fit (avoid 10x duplicate work per tick)

### Framework improvements
- `prosperity/options/hedging.py`: compute hedge ratios for a basket of options
- Add `VolSurface` caching that shares across options within a tick
- Parameterize `option_mm_bs` for per-strike overrides (deep OTM vs ATM vs deep ITM)

## Critical

- ~~Make the submission exporter derive from a stricter canonical source to reduce drift between modular code and exported code.~~ (done: exporter now inlines actual strategy source files)
- Extend the local-vs-official reconciliation tool with richer diagnostics for fills, pnl, positions, and quote behavior.
- Add an experiment registry: strategy, round, params, days tested, total pnl, per-product pnl, notes, submission id.
- Add backtest-json pairing confidence and better auto-discovery explanations in the dashboard UI itself.
-Notebook 
-Vérifier que c'est FIFO et pas LIFO qui a été implémenté 
## High Value

- Make round activation faster: one place to fill products, limits, conversions, and strategy mappings when a new round opens.
- Improve passive fill simulation with a one-iteration queue heuristic; exact LIFO is not recoverable from snapshot-only public data.
- Add a tournament runner that compares all strategies and saves ranked outputs to `artifacts/`.
- ~~Add richer metrics to comparison output: turnover, max drawdown, inventory pressure, sharpe-like stability proxies.~~ (done: compare/grid-search now expose drawdown, fill efficiency, inventory pressure, passive adverse markout proxies)
- Extend `research/analysis.py` with per-product microstructure reports and event detection.
- Build a standard workflow to calibrate bot signals from official logs and raw trade CSVs.
- ~~Add proper handling and research utilities for `state.observations` and conversion data.~~ (done: backtester now exports observation / conversion traces and forwards best-effort observation data to strategies when present)
- Add liquidation / unwind modules that can be reused across strategies.
- ~~Add per-side quote metrics: quote age, refresh rate, stale quote exposure, and quote-to-fill by side.~~ (done: backtester now exports quote age, refresh, stale exposure, and bid/ask fill efficiency)
- ~~Add inventory episode metrics: unwind half-life, time-at-limit, time one-sided, and inventory sign flips.~~ (done: backtester now exports one-sided time, sign flips, unwind duration, and open-episode length)

## Synthetic Data And Stress Testing

- Build a synthetic scenario generator to test robustness outside the historical sample.
- Add stable-market profiles with tight spreads and anchored fair values.
- Add trending-market profiles with persistent directional drift.
- Add mean-reverting profiles with pullback toward a latent fair value.
- Add toxic-flow profiles with directional informed flow and adverse selection.
- Add basket profiles with correlated components, spread shocks, and temporary dislocations.
- Add option profiles with underlying paths, volatility regime shifts, and repricing noise.
- Add a semi-synthetic generator that starts from historical data and perturbs it with resampling, noise, shocks, and liquidity changes.
- Add multi-seed stress runs and summary reports so strategies are ranked on robustness, not only raw pnl.

## Expert Market Making Gaps

- Build a more realistic queue and passive fill probability model, while treating exact LIFO reconstruction as impossible with current data.
- Add toxicity detection to reduce quoting during adverse flow.
- Add advanced quote policy logic: when to join, improve, widen, or remove one side.
- Add explicit soft liquidation and hard liquidation rules.
- Add regime detection for stable, trending, choppy, stressed, and low-liquidity markets.
- ~~Add pnl attribution separating spread capture, inventory drift, adverse selection, and take-vs-make effects.~~ (done: backtester now exports spread / make / take / inventory drift / adverse-selection proxies)
- Add multi-level fair value estimators such as wall-mid and liquidity-weighted fair value.
- Add trade-flow and order-book pressure features on multiple horizons and levels.
- Add a short-horizon predictor ensemble using microprice, imbalance, trade flow, spread state, and momentum features.
- ~~Add bot-conditioned alpha so identical trades are interpreted differently depending on the participant.~~ (partial tooling done: official log analyzer now exposes participant-aware volume and post-trade markouts; strategy usage still to do)
- Add an opportunity classifier for deciding when to take aggressively versus quote passively.
- Add quote aging and quote refresh logic.
- Add dynamic sizing based on spread, confidence, inventory, and product risk.
- Add asymmetric quoting policies and one-sided quoting modes.
- Add position-aware take logic for controlled emergency inventory reduction.
- Add cross-product hedging where products are linked.
- Add an option risk layer with delta / gamma / vega-style approximations for derivative rounds.
- Add a stronger conversion decision engine that accounts for fees, limits, and timing.
- Add walk-forward validation to reduce parameter overfitting.
- Add ablation tooling to measure the real value of each feature and module.
- Add a stability score so strategies are ranked on robustness, not only pnl.
- Add experiment tracking with config, commit, days, metrics, notes, and submission ids.
- Add a one-command round bootstrap workflow.
- Add export verification to compare the modular strategy and exported single-file behavior.

## Strategy Work

- Evaluate `naive_tight_mm_v8` in tiny manual batches before any broader sweep.
- Focus V8 research on smart sizing, toxicity filtering, and selective taking while keeping top-of-book pricing unchanged.
- Calibrate `avellaneda_stoikov` on real product data instead of leaving it as a generic implementation.
- Prepare stat-arb templates for likely basket rounds.
- Prepare options templates for likely voucher / derivative rounds.
- Prepare conversion-arb templates for likely cross-market rounds.
- Add short-horizon predictors using imbalance, trade flow, wall-mid, and lagged microprice features.
- Add regime filters so strategies can change behavior in stable, trending, or stressed markets.
- Add bot-follower playbooks for known directional participants when official logs reveal them.

## Engineering

- Add `pyproject.toml` and standardize lint / format / test commands.
- Add CI to run tests and basic validation on pushes.
- Clean remaining encoding issues in some text files and comments.
- Add more unit tests for backtester fills, config dispatch, exporter correctness, and strategy invariants.
- Add regression fixtures based on official logs.

## Documentation

- Keep `README.md` current when commands, paths, or flags change.
- Add a short round bootstrap guide for the first 30 minutes after a round opens.
- Add per-member templates for recording experiments in `team/`.
- Document the expected CSV naming conventions and data ingestion assumptions.

## Log Analysis

- Improve the log analyzer so it makes fuller use of merged `.json` + `.log` data.
- Add position-over-time views to log analysis outputs.
- Surface submission metadata such as final profit, status, submission id, and loaded files directly in reports.
- Add runtime log inspection when useful debug information is present.
- ~~Add richer HTML or dashboard summaries so post-submission review is faster.~~ (done: dashboard now shows IMC / backtest diagnostics cards per symbol)
- ~~Add official-vs-local reconcile widgets to the dashboard instead of terminal-only summaries.~~ (done: dashboard now surfaces per-symbol reconcile summary cards when a backtest match exists)
- ~~Add markout curves after fills for horizons like `+1`, `+2`, `+5`, `+10` ticks / snapshots.~~ (done: backtester and official log analyzer now compute multi-horizon markout summaries)

## Nice To Have

- One-click scripts for export plus compile-check.
- Static HTML report generation after compare / grid-search runs.
- Better dashboard filters for timestamp windows, products, and trade side.
- A shared summary page that links the best baseline, latest exports, latest logs, and latest analysis outputs.
