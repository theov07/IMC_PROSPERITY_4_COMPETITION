# Round 2 — Alpha Ideas & Roadmap

## Current champion state (19 April AM)

**`champion_19april_am`** — combined OSM + IPR

| Product | Strategy | Key params |
|---|---|---|
| ASH_COATED_OSMIUM | `mm_first_v4_combo` (v4_F5) | anchor_drift=2, unwind=3.0, kept=0.05, invbias=0.0015, take_edge_lo=0.3/hi=0.8 |
| INTARIAN_PEPPER_ROOT | `theo_best_clean_generalized_v4` | empty_side_shift=85 (Theo default) |

- **Backtest 3 days** : 301,688 PnL (OSM 63,420 + IPR 238,268)
- **Live simu test** : 3,000-10,000 per sim (high variance on far-quote fills)
- **Slim export** : 92.4 KB (under 100KB IMC limit)

Variants uploaded:
- `champion_19april_am` (IPR shift=85)
- `champion_19april_am_s89` (IPR shift=89, test)

---

## OSM progression summary

| Config | PnL OSM 3j | Δ baseline | inv |
|---|---|---|---|
| Baseline Tibo v3 | 57,992 | — | 0.282 |
| v4_F | 59,725 | +3.0% | 0.232 |
| v4_F2 (tuned unwind) | 60,383 | +4.1% | 0.209 |
| v4_F4 (grid winners) | 63,172 | +8.9% | 0.214 |
| **v4_F5 champion** 🏆 | **63,420** | **+9.4%** | **0.181** |

**v4_F5 = v4_F4 + `inventory_aversion_gamma=0.0015` (AS-lite)**

---

## Grid searches — ALL COMPLETE

| Grid | Winner | Δ PnL | In champion |
|---|---|---|---|
| 1: take_edge_lo × take_edge_hi | lo=0.3, hi=0.8 | +117 | ✅ |
| 2: taker_buy × taker_sell | baseline 9990/10025 | 0 | — |
| 3: half_life × maker_size | marginal (+47 but inv+7%) | rejected | ❌ |
| 4: anchor_drift × ar_gain | drift=2, ar_gain=0.3 | **+2,907** | ✅ (biggest win) |
| 4-fine: anchor_drift | drift=2 > 3 > 5 | +118 | ✅ |
| 5: unwind_take_edge + pct_kept | unwind=3, kept=0.05 | +658 | ✅ |
| 6-10: (various) | see below | mostly dead | — |

---

## Ideas tested in order — full tally

### ✅ WINNERS (in v4_F5 champion)

1. **Anchor drift bound = 2** (grid 4) — **+2,907 PnL** 🏆
2. **Unwind take edge = 3.0** + **pct_kept = 0.05** — **+658 PnL**
3. **take_edge_lo = 0.3** + **hi = 0.8** — +117 PnL
4. **Inventory aversion γ = 0.0015** (AS-lite fair value bias) — +248 PnL

### ❌ DEAD ENDS (tested, all fail)

**Backtestable tests that failed**:
- Pure fixed anchor (v4_B) — −2,690 PnL
- Wall mid (volume-filtered fair value, any threshold) — all dead
- Taker cooldown (any value ≥ 2) — all dead
- Microprice size tilt (any gain) — all dead
- Spread widening (any threshold) — dead
- Soft position target ≠ 0 — dead
- Fill-rate toxicity filter — dead
- Spread z-score skew — dead
- Toxic flow filter — dead
- Jump filter — dead
- Maker-aggressive passive skew (v4_F3, kept as opt-in, not in champion)

**Live-only tests (no backtest signal, validated live)**:
- Multi-shift far-quote (5, 30, 60, 89, 120) — only 89 viable
- Empty-book probe (always-on at 80) — no additional alpha
- Probe_t0 (multi-distance at session start) — 0 fills
- Momentum follower — MM core −76 (within noise)
- shift=5 on OB_cleared — 0 far fills (too shallow)
- shift=89 on IPR — comparable to 85, inconclusive

### Notable helper code kept but disabled
All opt-in helpers in `mm_first_v4_combo.py` (disabled by default params):
- `_compute_base_mid` (wall mid)
- `_probe_quotes` / `_probe_tick0`
- `_apply_momentum_follower`
- `_apply_toxic_flow` / `_apply_jump_filter` / `_apply_fill_rate_toxicity`
- `_taker_cooldown_active`
- `_microprice_size_tilt`
- `_apply_spread_widening` / `_apply_spread_zscore_skew`
- `_asym_passive_skew`
- `_apply_eod_flatten`

These are dead weight for champion but live in the combo source for potential
future reuse. They're stripped by `scripts/_strip_dead_helpers.py` during export.

---

## MAF (Market Access Fee) — IN PROGRESS

See `research/round_2_MAF/` for the pricing pipeline.

### Current state

- **V measurement** (V = MAF value in XIRECs) :
  - Synthetic book enrichment (+25% book depth)
  - ΔPnL backtest: +967 ± 333 = **+0.27% of baseline**
  - **Issue** : synthetic doesn't enrich TRADES, only book quotes
  - → V is UNDERESTIMATED

- **Known fix needed** : enrich `trades_round_2_day_X.csv` too, because
  MAF gives +25% of TOTAL order flow (book quotes + aggressive trades).

### Bid — DÉCIDÉ : **2,173 XIRECs finale**

- V mesurée (break-even) = **11,194 finale**
- Bid = 2,173 = hedge tournament-regret + anti-focal (prime)
- Capture 80% de la value MAF si accepté (+9,021 net)
- Voir `research/round_2_MAF/FINDINGS.md` pour raisonnement complet

**Adversary distribution estimate** (first principles):
- 35% no bid() method → 0
- 25% wiki copy-paste → 15
- 15% round small → 50-500
- 10% value-anchored low → 1k-5k
- 10% value-anchored high → 5k-20k
- 5% aggressive → 20k+

Simulated median adverse bid: **~15-100 XIRECs**

### Next steps for MAF

1. Fix script 01 to also enrich trades CSVs
2. Re-run script 02 → get proper V
3. Run script 04 with final V → final bid recommendation
4. Add `def bid(self): return X` to Trader template

---

## Implementation workflow (for future ideas)

1. Add helper in `mm_first_v4_combo.py` with opt-in params (no-op default)
2. Integrate in `compute_orders` at correct position (respect ordering)
3. Create config variant in `config.py` with feature enabled
4. Backtest on R2 days -1/0/1, compare per-product vs current champion
5. Grid search params if positive signal
6. If confirmed winner: merge into champion + export for IMC
7. Run minify + strip pipeline to stay under 100KB

---

## Scaling reminders (CRITICAL)

- **Backtest (realistic mode)** ≈ 24-100× too optimistic vs live absolute
- **Simu test IMC → Simu finale IMC** ≈ ×8.9 scaling
- **Rule** : always compare strategies **in ratio (%)**, never in absolute PnL across regimes
- **Per-product PnL** (not aggregated) is the source of truth for tuning
- **Far-quote variance** dominates total PnL in live (0-3 fills/sim, ±1500 PnL)
- MM core is the stable signal to optimize

---

## Files to know

| What | Where |
|---|---|
| Champion config | `MEMBER_OVERRIDES["champion_19april_am"]` in `prosperity/config.py` |
| OSM strategy code | `prosperity/strategies/round_2/leo/mm_first_v4_combo.py` |
| IPR strategy code | `prosperity/strategies/round_2/theo/theo_best_clean_generalized.py` |
| Slim submission | `artifacts/submissions/round_2/champion_19april_am_SLIM.py` |
| MAF research | `research/round_2_MAF/` |
| Synthetic data (incomplete) | `data/round_2_synthetic_s{42,43,44}/` |
