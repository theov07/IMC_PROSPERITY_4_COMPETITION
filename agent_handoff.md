# Agent Handoff — Leo2 branch

Shared coordination file for Léo, Claude, and Codex.

Use this file to:
- share current context
- ask targeted questions
- record decisions
- hand off work between agents
- keep one clear source of truth while several people/tools work on the repo

## How To Use

- Add a dated section when you write.
- Sign your note with `Léo`, `Claude`, or `Codex`.
- Keep decisions separate from open questions.
- Prefer short, concrete bullets over long paragraphs.
- When a point is resolved, move it to `Decisions`.

---

## Current Context (2026-04-18 — Round 2 live)

### Round 1 results (official)

- Final ranking: **1st France, 77th Global** on algo trading.
- Champion submitted: `champion_generalized` (combines Tibo's `mm_first_v2` on OSM + Théo's `theo_best_generalized` on IPR).
- Final simu PnL: **107,673.56 XIRECs** (submission 273329).
- Logs archived at `logs/round_1/final_submission_champion_generalized/`.
- Manual trading: weaker than algo, team's point to improve.

### Round 2 status

- **Same products**: `ASH_COATED_OSMIUM` (OSM) and `INTARIAN_PEPPER_ROOT` (IPR), same position limits (80).
- **New mechanic — Market Access Fee (MAF)**: blind auction to get +25% extra volume in the book. Top 50% of bidders accepted, fee deducted from final PnL. Ignored during testing (backtest can't evaluate it). **Decision pending — see open points.**
- **Manual challenge**: "Invest & Expand" — 50k XIRECs across 3 growth pillars. Doc still needs to be pulled from Notion (the `docs/wiki/round_2_info.txt` file truncates at the manual section).
- **Data**: 3 days in `data/round_2/` (days -1, 0, 1), 10k ticks each.

### Team workstreams

- **Léo (this branch)**: focus on alpha R&D + decision-making (MAF bid, baseline choice, this handoff).
- **Théo**: IPR specialist. Built `theo_best_generalized.py` with block-OLS regression, regime detection, trim system. Has a gap study (`artifacts/analysis/round_2/theo/gap_study_official/`) analyzing one-sided book events — v2/v4/v6/v7 each captured ~7-8k PnL in simu final. Multiple R2 submission candidates in `artifacts/submissions/round_2/theo/`.
- **Tibo**: OSM specialist. Maintains `mm_first_v2.py` (modular template — the canonical starting point for new strategies). Added dynamic take_edge, z-score skew, gap exploit with `OB_cleared_shift` for far-quote posting.
- **Another Claude agent**: actively grid-searching strategies in parallel. **Coordinate to avoid conflict on `mm_first_v2` / `theo_best_generalized` / configs.**

---

## Code structure (post-refactor)

```
prosperity/strategies/
├── base/                     # BaseStrategy, AS, BS, MM, stat_arb, conversion_arb
├── round_1/                  # All R1 iterations (naive_tight_mm_v34..v41, fusion_a..d, regression_mm_v3..v5)
│   ├── metal_winner/         # The winners: mm_first_v2 + (mm_first legacy)
│   ├── theo_best_generalized.py
│   └── ... 
├── round_2/{leo,theo,tibo}/  # Per-member R2 folders (mostly empty, to be filled)
├── alpha_osm.py              # Léo's earlier alpha experiments (pistes 1-3, all underperformed)
└── alpha_ipr.py              # Léo's earlier IPR dip alpha (underperformed)
```

**Canonical MM template going forward**: `prosperity/strategies/round_1/metal_winner/mm_first_v2.py`. Highly modular with helpers (`_compute_quote_prices`, `_compute_zscore`, `_zscore_size_factors`, `_compute_sizes`, `_dynamic_take_edge`, `_fire_takers`, `_gap_exploit`, `_zscore_price_skew`, `_passive_quotes`, `_log_taker_fills`). New variants should subclass or duplicate this pattern.

---

## Decisions (confirmed)

### Market dynamics (from R2 analysis)

- **OSM dynamics R1 → R2 essentially unchanged**: mean 10000, std ~5, AR(1) returns = **−0.50** (strong mean-reversion), spread mode 16 (59% of ticks), trades/day ~465 (vs 422 in R1). The OSM config transfers 1:1 from R1.
- **IPR trend still +0.108/tick = +1000/day deterministic**. Perfectly linear across all 3 R2 days. Day 1 opens at 12990 (continuity from R1 day 0 close at 13000).
- **IPR regime shifted in 2 ways**:
  - Spread modal: **13 → 14** (+1 tick wider)
  - Gap L1→L2 ≥3 frequency: **84% → 96%** (book much thinner on top)
- **OSM × IPR correlation = 0** in both R1 and R2 (Pearson, Spearman, tail dependence, rolling, cross-gap-event co-occurrence). Products are fully independent — trade them as such, no cross-hedging, no basket alpha.

### Alpha discoveries & traps

- **The 85-tick far-quote alpha is invisible in backtests**. It comes from live-only quote-reactive bots (Valentina/Caesar-like) that react to our posted quotes. Max distance from mid in public trade tape = ~11 ticks in both R1 and R2. **Never grid-search `OB_cleared_shift` on backtest — only test in live simu.**
- **Same alpha didn't work on IPR in R1 but works in R2.** Cause is NOT cross-product linkage (confirmed zero correlation). The internal IPR regime change (thinner top-of-book, more gaps) is what makes IPR now attract quote-reactive bots.
- **Post-gap waiting time on IPR ~memoryless**: p50 = 22 ticks, p90 = 54 ticks before a trade prints at ≤ fair_value. Features (spread, imbalance, trend velocity) explain <1% of variance. Use a fixed-timeout unwind rule, don't build a fancy predictor.
- **Net economics of a gap sell on IPR**: capture ~85 ticks, pay ~2.4 ticks in adverse carry during wait → ~82 ticks net/fill. Highly profitable.

### Scaling between regimes

| Regime | Units |
|---|---|
| Backtest local (`realistic` mode) | ~24× optimistic vs live |
| Simu test IMC (during round) | 1× baseline |
| Simu final IMC (ranking) | **~10× simu test** |

**Rule**: never compare absolute PnL across regimes. Use only relative ranking between strategies on the same regime. Teams confirmed: R1 simu test = 12k, simu final = 107k → factor 8.9× ≈ 10×.

### Historical lessons (R0, still valid)

- **Queue priority matters**: backtest fills "join" orders as if they have queue priority. In live IMC, joining = behind existing orders → 0 fills. **Always tighten (1 tick inside) or take aggressively — never just join.**
- `qty_join_threshold` is a backtest-only artifact. Discarded.
- Trade CSV has `buyer/seller = None`: no named counterparty signal available. No Olivia-style copy-trade alpha exists in R1/R2 data.
- `flow_window`, `asym_strength`, `spread_min_frac`, `cooldown_ticks`: all neutral or harmful.

### Failed alpha experiments

Léo's earlier alpha round (`prosperity/strategies/alpha_osm.py`, `alpha_ipr.py`) tested 4 pistes: volume-filtered fair value, AR(1) calibrated fair value, regime detection dual-window, IPR micro-dip entry. **All 4 underperformed the baseline by 1-4% on OSM** and IPR dip entry lost on trend carry. Root cause: fair value was integrated only into taker decisions, not into passive quote prices where most PnL comes from. Archived, do not reuse as-is — the lesson is "integrate signals into passive quotes, not just takers".

---

## Open Points / Next Actions

### 🚨 Priority 1 — MAF bid decision (critical, blind auction)

- Top 50% = +25% extra order book volume
- Bid is deducted from final PnL only if accepted
- Backtest can't evaluate it (MAF ignored during testing)
- Need: game-theory model — expected value of +25% volume (in simu-final units), distribution of adversary bids
- **Rough reasonable range**: 10-20k XIRECs in final-PnL units (= 1-2k in simu-test units). Bidding more than the marginal value of +25% is money-losing.
- **Decision pending** — Léo needs to decide before R2 closes.

### 🥈 Priority 2 — Implement waiting time unwind timer in `mm_first_v2`

- Add helper `_unwind_timer` that blocks passive quotes on the unwind side for N ticks after a gap fill
- Default `unwind_hold_ticks=50` (or 60 after short on IPR / 20 after long) 
- Should be wrapped in a new variant (e.g. `mm_first_v3` or IPR-specific config) to avoid conflict with the parallel grid-search work on `mm_first_v2`

### 🥉 Priority 3 — Retune `theo_best_generalized` for IPR R2 regime

- **`gap_trigger_min` too high** for IPR: current 10, but with 96% of gaps ≥3 in R2 it almost never fires. Lower to 3-4.
- Passive quote baseline should target 14-wide spread (vs 13 in R1 config).
- `OB_cleared_shift` = 85 seems good but only confirmable in live simu — not backtest.

### Analysis still needed

- **Per-product PnL breakdown** of R1 submissions (to pick true best OSM and best IPR independently instead of just using `champion_generalized`). Léo: do you have these? Currently we only have the champion_generalized aggregate 107k.
- **Manual "Invest & Expand"**: need the Notion doc for the 3 growth pillars + returns profile to optimize 50k allocation.

### Tooling — confirmed OK

- Per-product comparison: Léo confirms "already done" — existing tooling in `prosperity/tooling/compare.py` and `grid_search.py` shows per-product PnL (no aggregation).

---

## Key Files Reference

| What | Where |
|---|---|
| Canonical MM template | `prosperity/strategies/round_1/metal_winner/mm_first_v2.py` |
| IPR sophisticated strategy | `prosperity/strategies/round_1/theo_best_generalized.py` |
| Strategy registry | `prosperity/strategies/__init__.py` |
| All member configs | `prosperity/config.py` |
| Current champion config | `MEMBER_OVERRIDES["champion_generalized"]` in config.py |
| R1 final log | `logs/round_1/final_submission_champion_generalized/273329.{json,log,py}` |
| R2 data | `data/round_2/prices_round_2_day_{-1,0,1}.csv` + trades |
| Théo's gap study | `artifacts/analysis/round_2/theo/gap_study_official/` |
| R2 wiki (partial) | `docs/wiki/round_2_info.txt` (manual section truncated) |
| Backtest CLI | `backtest.py --strategy <member> --round 2 --days -1 0 1 --match-trades realistic` |

---

## Log

### 2026-04-18 — Claude (session: Leo2 onboarding + R2 analysis)

Thorough R2 market analysis vs R1. Delivered three major analytical pieces:

1. **R1 vs R2 general market comparison**: OSM stable, IPR spread+gap shifted (see Decisions).
2. **OSM × IPR cross-product dependency**: exhaustive test (Pearson/Spearman/lead-lag/copula/tail/volatility-clustering/gap-co-occurrence) → **zero linkage, both rounds**. Products fully independent.
3. **IPR intra-product regime + waiting time model**: the 85-tick alpha's "prey" is invisible in public tape (max distance 11 ticks). It must be a live quote-reactive phenomenon. Post-gap waiting time on IPR is ~memoryless, p50=22 ticks, suggesting a fixed ~50-tick unwind timeout.

Decision: no cross-product alpha exists. Focus remains on per-product optimization. Next action is Priority 1 (MAF bid) or Priority 2 (waiting time timer implementation).

Todo state at session close:
- [x] Cross-product correlation analysis (done — zero)
- [x] Intra-IPR regime analysis (done — book thinning)
- [x] Waiting time model (done — use fixed timeout)
- [ ] Per-product baseline selection (awaiting Léo's per-product PnL data for R1 submissions)
- [ ] MAF bid game-theory model
- [ ] Waiting time timer implementation in `mm_first_v2` variant
- [ ] Retune IPR config (`gap_trigger_min=3-4`, spread 14)
- [ ] Manual "Invest & Expand" (awaiting Notion doc)
