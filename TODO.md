# TODO

Priority list for turning this repository from a solid framework into a competition-winning platform.

## Critical

- Remove `.env` from git tracking and replace it with `.env.example` if needed.
- Make the submission exporter derive from a stricter canonical source to reduce drift between modular code and exported code.
- Build a local-vs-official reconciliation tool for fills, pnl, and positions.
- Add an experiment registry: strategy, round, params, days tested, total pnl, per-product pnl, notes, submission id.
- Make round activation faster: one place to fill products, limits, conversions, and strategy mappings when a new round opens.

## High Value

- Improve passive fill simulation with better maker heuristics and queue assumptions.
- Add a tournament runner that compares all strategies and saves ranked outputs to `artifacts/`.
- Add richer metrics to comparison output: turnover, max drawdown, inventory pressure, sharpe-like stability proxies.
- Extend `research/analysis.py` with per-product microstructure reports and event detection.
- Build a standard workflow to calibrate bot signals from official logs and raw trade CSVs.
- Add proper handling and research utilities for `state.observations` and conversion data.
- Add liquidation / unwind modules that can be reused across strategies.

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

- Build a more realistic queue and passive fill probability model.
- Add toxicity detection to reduce quoting during adverse flow.
- Add advanced quote policy logic: when to join, improve, widen, or remove one side.
- Add explicit soft liquidation and hard liquidation rules.
- Add regime detection for stable, trending, choppy, stressed, and low-liquidity markets.
- Add pnl attribution separating spread capture, inventory drift, adverse selection, and take-vs-make effects.
- Add multi-level fair value estimators such as wall-mid and liquidity-weighted fair value.
- Add trade-flow and order-book pressure features on multiple horizons and levels.
- Add a short-horizon predictor ensemble using microprice, imbalance, trade flow, spread state, and momentum features.
- Add bot-conditioned alpha so identical trades are interpreted differently depending on the participant.
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
- Add richer HTML or dashboard summaries so post-submission review is faster.

## Nice To Have

- One-click scripts for export plus compile-check.
- Static HTML report generation after compare / grid-search runs.
- Better dashboard filters for timestamp windows, products, and trade side.
- A shared summary page that links the best baseline, latest exports, latest logs, and latest analysis outputs.
