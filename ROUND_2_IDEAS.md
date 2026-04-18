# Round 2 — Alpha Ideas & Roadmap

## Current state (v4_F2 — best confirmed backtest)

- **60,383 PnL OSM 3j** (vs baseline 57,992, +4.1%)
- inventory ratio **0.209** (vs baseline 0.282, −26%)
- Params tuned: `unwind_take_edge=3.0`, `pct_kept_for_takers=0.05`
- Live alpha (far-quote at 89 ticks on empty book) preserved in `_gap_exploit`

## v4_F3 (maker-aggressive unwind) — ⛔ ABANDONED

- Adds `_asym_passive_skew` helper (shifts passives toward mid on unwind side)
- Tested live on IMC: **+132 MM core vs baseline v4_F, only +13 vs v4_F2** (within noise)
- Backtest: −821 PnL (artifact — backtest has no queue-priority model)
- **Conclusion: abandon** — complexity not justified by marginal live edge
- v4_F2 is mechanically equivalent for the far-quote alpha (even more permissive
  via `pct_kept_for_takers=0.05`), so we don't lose anything by staying on v4_F2

## Live A/B test analysis (3 submissions, 1 simu each)

After isolating the far-quote alpha (fills at |price - 10000| > 30 ticks):

| Config | Total PnL | Far fills | Far-PnL | **MM Core PnL** |
|---|---|---|---|---|
| v4_F (unwind=1.0, kept=0.1) | 2,926 | 3 | 1,321 | 1,605 |
| **v4_F2 (unwind=3.0, kept=0.05)** | **1,724** | **0** | **0** | **1,724** |
| v4_F3 (skew=1, trigger=0.3) | 2,706 | 2 | 969 | 1,737 |

**Key learnings**:
1. Total PnL dominated by far-quote lottery (variance massive on 0-3 fills)
2. MM core stable at 1,605-1,737 across configs (spread only 8%)
3. v4_F2 tuned unwind confirmed in live: +119 MM core vs baseline
4. v4_F3 maker edge too small to justify; abandon

---

## Grid searches — ALL COMPLETE

| Grid | Winner | Δ PnL | Adopted in v4_F4 |
|---|---|---|---|
| 1: `take_edge_lo` × `take_edge_hi` | `lo=0.3, hi=0.8` | +117 | ✅ |
| 2: `taker_buy_threshold` × `taker_sell_threshold` | baseline 9990/10025 | 0 | — |
| 3: `mid_smooth_half_life` × `maker_size_base_pct` | marginal (+47 but inv+7%) | rejected | ❌ |
| 4: `anchor_drift_bound` × `ar_gain` | `drift=2, ar_gain=0.3` | **+2,907** | ✅ |

## v4_F5 champion (latest)

- **63,420 PnL** (+248 vs v4_F4, +9.4% vs baseline)
- inventory ratio **0.181** (−37% vs baseline, best yet)
- One new feature added: `inventory_aversion_gamma=0.0015` (Avellaneda-Stoikov lite)
  - Grid searched γ ∈ {0.0005..0.03}, sweet spot at 0.0015
- Other 3 features tested but abandoned:
  - wall_mid (volume-filtered fair value): ALL values > 0 degrade
  - taker_cooldown: ALL values > 1 degrade
  - microprice_size_tilt: ALL values > 0 degrade

## v4_F4 champion (previous best)

- **63,172 PnL OSM 3j** (+5,180 vs baseline, +8.9%)
- inventory ratio 0.214 (baseline 0.282, -24%)
- Cumulative gains from grid 1 + grid 4: +2,789 (92% additivity vs expected +3,024)
- Params vs v4_F2: `take_edge_lo=0.3, take_edge_hi=0.8, anchor_drift_bound=2.0`
- Live alpha preserved: `OB_cleared_shift=89` far-quote intact

---

## Ideas to implement after grids (ranked by priority)

### 🔥 High priority (backtestable, orthogonal to current features)

**Idea 1 — Volume-filtered mid ("wall mid")**
- Compute mid from book levels with volume ≥ threshold (e.g. 10)
- Excludes toxic small orders from fair value
- New params: `mid_vol_filter=False` (default off), `mid_vol_threshold=10`
- Implementation: new helper `_compute_wall_mid(book, threshold)` that scans
  `book.bid_levels` / `ask_levels` and returns filtered mid
- Use as input to `_compute_anchor_signal` and `_fire_takers`

**Idea 2 — Size scaling by microprice deviation**
- Signal: `delta = microprice − mid`
- If `delta > 0` (bid-heavy), expect price up → increase sell_size, reduce buy_size
- If `delta < 0`, inverse
- New params: `microprice_size_gain=0.0` (off), `microprice_size_threshold=0.2`
- Predictive, not just reactive (unlike current z-score size tilt which is mean-rev)

**Idea 3 — Taker cooldown**
- After firing a taker on side X, block takers on same side for N ticks
- Prevents overtrading in volatile sequences (backtest fires 5 takers then all revert)
- New params: `taker_cooldown_ticks=0` (default off)
- Memory: `_last_taker_buy_ts`, `_last_taker_sell_ts`

**Idea 4 — Fair value biased by inventory (Avellaneda-Stoikov lite)**
- Shift fair value toward zero-inventory: `fair_biased = fair − gamma × position × sigma`
- Alternative to current asymmetric take edges (maker-style instead of taker-style)
- New params: `inventory_aversion_gamma=0.0` (off)
- More subtle than `unwind_take_edge`, captures more spread

### 🟡 Medium priority

**Idea 5 — Adaptive spread widening in high vol**
- When `sigma > spread_widen_threshold`, post at `best_ask − 2` instead of `−1`
- Reduces adverse selection in volatile regimes
- New params: `spread_widen_vol_threshold=0`, `spread_widen_extra_ticks=0`

**Idea 6 — Soft position target ≠ 0**
- If OSM has a slight drift (confirm via data), target a small biased position
- Grid search on `inventory_target` (default 0)

**Idea 7 — Order flow toxicity via fill-rate asymmetry**
- Track recent fill rate on bid vs ask sides
- If our asks fill 5× faster than our bids → market dropping → pause bid quoting
- New helper `_fill_rate_toxicity`

**Idea 8 — Mean-rev z-score on SPREAD (not mid)**
- Wide spread (z > 2) often reverts → post more aggressively in this state
- Opposite of current behavior which tightens in high vol

### 🔴 Live-only (cannot backtest)

**Idea 9 — Multi-shift far-quote probing**
- Upload 3 variants with `OB_cleared_shift` ∈ {50, 70, 110}
- Find the sweet spot where aggressors cross

**Idea 10 — Empty-book probe**
- Post a probe quote far from mid at t=0 to measure aggressor behavior
- Passive, no downside

**Idea 11 — Bot-follower**
- Analyze live logs for consistently profitable participants
- Follow their direction with delay

---

## Dead ends (don't revisit)

- **Pure fixed anchor** (v4_B: −2,690 PnL vs baseline)
- **Toxic flow filter** (noise in backtest)
- **Jump filter** (noise in backtest)
- **Maker-aggressive passive skew (v4_F3)**: live-tested, +13 MM core vs v4_F2
  (within noise), backtest -821, complexity not justified — helper stays in code
  as opt-in but not used in champion config

---

## Implementation workflow for each idea

1. Add helper in `mm_first_v4_combo.py` with opt-in params (no-op default)
2. Integrate in `compute_orders` at correct position (respect ordering — asym_passive_skew must stay AFTER _gap_exploit to preserve far-quote)
3. Create config variant in `config.py` with feature enabled
4. Backtest on R2 days -1/0/1, compare per-product vs v4_F2
5. Grid search params if positive signal
6. If confirmed winner: merge into v4_F4 champion + export for IMC

---

## Scaling reminders

- Backtest (realistic mode) ≈ 24× too optimistic vs live
- Simu test IMC → Simu finale IMC ≈ 10× scaling
- **Rule**: always compare strategies **in ratio**, never in absolute PnL across regimes
- Per-product PnL (not aggregated) is the source of truth for tuning
