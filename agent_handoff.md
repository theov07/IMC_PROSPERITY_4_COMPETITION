# Agent Handoff — Leo2 branch

Shared coordination file for Léo, Claude, and Codex.

---

## Current Context (2026-04-24 — Round 3 started, naive baseline built)

### Team ranking
- **R1 final** : 1st France, 77th Global on algo trading
- **R1 champion** : `champion_generalized` (107k finale PnL)
- **R2 final** : `champion_final_v8_osm_deeps` — **82,352 PnL** on live 1-day session
- **R3 started** : GOAT phase, leaderboard reset, options trading introduced

### Round 3 — Products & framework
- `HYDROGEL_PACK` (delta-1, limit 200, mid ~10,000, vol ~2.17%/day)
- `VELVETFRUIT_EXTRACT` (delta-1 underlying, limit 200, mid ~5,250, vol ~2.15%/day)
- `VEV_4000`..`VEV_6500` (10 European call vouchers, limit 300 each, TTE=5d at live start)
- Manual: Ornamental Bio-Pods (2 bids uniform [670..920] step 5, sell next round at 920)

**New framework** in `prosperity/options/`:
- `black_scholes.py` — pure-Python BS call/put + greeks (delta/gamma/vega/theta)
- `implied_vol.py` — Newton-Raphson IV solver with bisection fallback
- `smile.py` — polynomial smile fit in log-moneyness, `smile_predict(K, coeffs, S, T)`

**Naive strategy**: `prosperity/strategies/round_3/option_mm_bs.py` — `OptionMMBSStrategy`.
- Penny-improve around market (best_bid+1, best_ask-1) with BS fair as inventory-skew reference
- Skip quoting when `BS_fair < min_quote_price` (default 2) — protects against deep OTM rounding chaos
- `enable_takers=False` by default (naive = passive only)
- Self-contained smile fit from state.order_depths each tick (10 strikes)

**Naive champion**: `r3_naive_champion` → **+123,526 PnL** 3-day backtest realistic.
- HYDROGEL v4_F5 anchor=10000 → ~18k/day
- VELVETFRUIT v4_F5 anchor=5250 → ~15k/day
- VEV options penny-improve MM → near 0 (neutral)

### Observed edges (Round 3)
- **Realized vol 2.15%/day vs implied 1.25%/day** = 70% gap → LONG VOL overlay potentially profitable
- **Magritte "Ceci n'est pas une pipe"** → IMC hint: market price ≠ fair value on options → fade mispricings

### Decisions (Round 3)
- European call model (no American exercise)
- Time in DAYS, sigma = daily vol, r=0 (prosperity convention)
- Smile: quadratic polynomial in log-moneyness (3+ strikes needed for fit)
- Deep OTM (K=6000, 6500, mid=0.5 floor) skipped via `min_quote_price=2.0`
- HYDROGEL + VELVETFRUIT reuse `_V4_F5_PARAMS` from Round 2 with anchor overrides

### Next steps (Round 3)
- Delta-hedge via VELVETFRUIT (long options → short S to be delta-neutral)
- Smile-aware quoting (bid/ask tighter than penny-improve using BS ± calibrated edge)
- Option coordinator to share smile fit across 10 VEV instances (avoid duplicate work)
- Research Ornamental Bio-Pods optimal bid (similar to R2 MAF analysis)
- Add vol_arb strategy: buy vega when implied < realized, delta-hedge

---

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

## Current Context (2026-04-19 — Round 2 ongoing, compaction point)

### Team ranking
- **R1 final** : 1st France, 77th Global on algo trading
- **R1 champion** : `champion_generalized` (107k finale PnL)
- **R2 ongoing** : same 2 products (OSM + IPR), with Market Access Fee (MAF) mechanic

### Current champion — `champion_19april_am`

Combines best-of-both products:
- **OSM** : `mm_first_v4_combo` with v4_F5 tuned params
- **IPR** : `theo_best_clean_generalized_v4` (Theo's live-winning IPR strat, sub 307401)
- Backtest 3 days: **301,688 PnL** (OSM 63,420 + IPR 238,268)
- Live simu test: 3,000-10,000 per sim (variance due to far-quote randomness)
- Uploaded variants :
  - `champion_19april_am` : IPR empty_side_shift=85 (Theo default)
  - `champion_19april_am_s89` : IPR empty_side_shift=89 (to match OSM)
- Slim exports (under 100KB limit) via `scripts/_minify_submission.py` + `scripts/_strip_dead_helpers.py`

### Strategy stack (OSM) — v4_F5 params

```python
# Grid-searched winning params
anchor_price=10000.0
anchor_alpha=0.02
anchor_drift_bound=2.0         # Biggest win: grid 4 found this
ar_gain=0.3
ar_shift_source="mid_smooth"
unwind_take_edge=3.0           # Grid 4: boost vs Tibo's 1.0
pct_kept_for_takers=0.05       # Grid 4: loosen from 0.1
take_edge_lo=0.3               # Grid 1
take_edge_hi=0.8               # Grid 1
inventory_aversion_gamma=0.0015  # Added in v4_F5 (AS-lite)
# + OB_cleared_shift=89 (live far-quote alpha, invisible in backtest)
```

Delta vs baseline Tibo v3 (63,420 vs 57,992): **+9.4% PnL, −37% inventory pressure**

### Strategy stack (IPR) — Theo v4

Extracted from live submission 307401.
- Class: `TheoBestCleanGeneralizedV4Strategy` at `prosperity/strategies/round_2/theo/theo_best_clean_generalized.py`
- Inherits from V3 → V2 → Base
- ~100 params (regression + regime + gap_trap + startup phase)
- Key: `empty_side_shift=85` for far-quote on empty book side

### MAF (Market Access Fee) — **IN PROGRESS**

**Mechanic recap**:
- Blind auction at submission time, 1 bid per team
- Top 50% of bids accepted → pay OWN bid (first-price pay-as-bid)
- Bid in finale XIRECs units, deducted from R2 final PnL
- Negative bids → treated as 0
- Teams without `bid()` method → counted as 0 for median
- Teams without trader.py → ignored entirely from median calc

**Research pipeline** : `research/round_2_MAF/`
- `01_generate_synthetic_data.py` : Monte Carlo +25% volume in ORDER BOOK
- `02_measure_delta_pnl.py` : backtest normal vs enriched → V measurement
- `03_bid_optimization.py` + `03b_sensitivity_analysis.py` : optimal bid under adversary distribution model
- `04_final_report.py` : consolidated

**Current V measurement (limited)**:
- Synthetic adds +25% book depth (ratio 1.296 effective)
- Backtest ΔPnL: +967 ± 333 (simu test units) = **+0.27% of baseline**
- **Known issue**: synthetic enriches BOOK only, NOT TRADES
  - MAF in live gives +25% of TOTAL order flow (quotes AND trades)
  - Backtest fills are market_trades driven, not book-depth driven
  - → V measurement is significantly UNDERESTIMATED

**Open question (end of session)**:
- Should we enrich trades too in synthetic data?
- Leo's instinct: yes, because wiki says "extra flow to trade against" implies trades
- Claude's analysis: likely yes, MAF = +25% of total flow (quotes + aggressive orders that become trades)
- **Next step**: modify script 01 to also enrich `trades_round_2_day_X.csv`

### PnL scaling regimes (IMPORTANT)

Do NOT mix PnL across regimes. Always reason in RATIOS (%).

| Regime | Example (champion R2) | Scaling vs next |
|---|---|---|
| Backtest local (realistic) | ~300k total 3 days | ÷104 to simu test |
| Simu test IMC (per day) | 3,000-11,000 | ×8.9 to finale |
| Simu finale IMC (ranking) | ~100k estimated | — |

Backtest is ~24-100× more optimistic than simu test in absolute terms.

---

## Decisions (confirmed)

### Strategy decisions

- **OSM champion** : v4_F5 params (mm_first_v4_combo). Validated via grid search + live sims.
- **IPR champion** : Theo v4 (theo_best_clean_generalized_v4) with shift=85. Shift=89 test inconclusive (need more sims).
- **Combined champion** : champion_19april_am (uploaded as SLIM version, 92.4KB)
- **Abandoned features (backtest-tested, all dead)** : wall_mid, taker_cooldown, maker_unwind_skew, microprice_size_tilt, spread_widen, soft_position_target, fill_toxicity, spread_zscore
- **Kept feature** : inventory_aversion_gamma (AS-lite) — small but real gain on inventory pressure

### Submission tooling

- **100KB limit enforced by IMC** — minify/strip pipeline in place
- **Export workflow** : `scripts/export_submission.py --member X --round 2`
- **Minify** : `scripts/_minify_submission.py` strips docstrings + blanks (≈22% reduction)
- **Strip dead** : `scripts/_strip_dead_helpers.py` removes no-op opt-in helpers (≈15% more)
- Typical result: 142KB → 92.4KB

### MAF decision inputs

- Adversary bid distribution : 35% no-bid, 25% wiki-copy (@15), rest value-anchored
- Median adversary bid estimated : ~15-100 XIRECs
- V measurement pending proper methodology (trades enrichment)
- **Preliminary bid range** : 100-1500 XIRECs depending on V refinement

---

## Open Points / Next Actions

### 🚨 Priority 1 — Finish V measurement
- Fix `research/round_2_MAF/01_generate_synthetic_data.py` to also enrich `trades_*.csv`
- Re-run script 02 to get proper V
- Expected V range (post-fix) : likely 5-15% of PnL (in %) vs current 0.27%

### ~~🥈 Priority 2 — Finalize bid~~ ✅ DONE
- V mesurée via 80% subsampling = **11,194 finale (break-even)**
- Bid décidé = **2,173 XIRECs finale**
- Raisonnement : hedge tournament-regret + markup anti-focal prime
- Add `def bid(self): return 2173` to Trader template in submission
- Analyse complète : `research/round_2_MAF/FINDINGS.md` + scripts 05-17

### 🥉 Priority 3 — More sims of champion_19april_am
- Currently 2 sims of each variant (shift=85 and shift=89)
- Variance very high due to far-quote randomness
- More sims would help validate which shift is better

### Lower priority
- Manual R2 "Invest & Expand" — 50k XIRECs across 3 growth pillars (doc Notion needed)
- Grid search interactions between params (currently tuned independently)

---

## Key Files Reference

| What | Where |
|---|---|
| Champion combined config | `MEMBER_OVERRIDES["champion_19april_am"]` in `prosperity/config.py` |
| OSM strategy (mm_first_v4_combo) | `prosperity/strategies/round_2/leo/mm_first_v4_combo.py` |
| IPR strategy (Theo v4) | `prosperity/strategies/round_2/theo/theo_best_clean_generalized.py` |
| Slim submission (ready to upload) | `artifacts/submissions/round_2/champion_19april_am_SLIM.py` |
| MAF research | `research/round_2_MAF/` |
| Synthetic data (current, book-only) | `data/round_2_synthetic_s{42,43,44}/` |
| Export script | `scripts/export_submission.py` |
| Minify pipeline | `scripts/_minify_submission.py` + `_strip_dead_helpers.py` |
| R1 final log (107k) | `logs/round_1/final_submission_champion_generalized/273329.*` |

---

## Log

### 2026-04-19 (compaction session) — Claude

Covered this session:
1. **Champion combined** : built `champion_19april_am` combining v4_F5 OSM + Theo v4 IPR. Variant s89 for IPR shift test.
2. **Slim export pipeline** : created `_minify_submission.py` + `_strip_dead_helpers.py` to fit IMC's 100KB limit.
3. **Live sim analysis** : verified v4_F5 inventory improvement (−37% vs baseline). Tested multi-shift variants (shift=5, 30, 60, 89, 120) and probe variants — all live-only alpha tests dead (only OB_cleared_shift=89 works).
4. **MAF pricing research** : built 4-script pipeline in `research/round_2_MAF/`. Measured V = +0.27% of backtest PnL, but noted **critical flaw** — synthetic data only enriches book, not trades. Needs fix before bid decision.
5. **Bid analysis** : modeled adversary bid distribution, sensitivity across 7 scenarios. Robust bid range currently 200-1500 pending proper V measurement.

Left hanging:
- Fix script 01 to enrich trades too → re-measure V
- Final bid decision

Tools / scripts committed this session:
- `prosperity/strategies/round_2/theo/theo_best_clean_generalized.py` (extracted from Theo's 307401)
- `scripts/_minify_submission.py`
- `scripts/_strip_dead_helpers.py`
- `research/round_2_MAF/0{1,2,3,3b,4}*.py`
- `data/round_2_synthetic_s{42,43,44}/` (book-enriched data)

---

### 2026-04-18 — Claude (earlier sessions summary)

Covered earlier sessions this weekend:
1. **R1 → R2 transition analysis** : OSM dynamics stable, IPR spread 13→14, gap L1→L2 frequency 84%→96%. OSM × IPR correlation = 0 in both rounds.
2. **v4_F → v4_F2 → v4_F4 → v4_F5 progression** : grid searches on unwind, anchor_drift, take_edges. Final +9.4% PnL vs baseline.
3. **Idea exploration** : 8 ideas tested (wall mid, taker cooldown, invbias, microprice size, spread widen, pos target, fill toxicity, spread zscore) — only invbias won.
4. **Live-only probes** : 3 ideas tested (multi-shift far-quote, empty-book probe t0, momentum follower) — all dead.
5. **Cleanup** : removed 42 orphan MEMBER_OVERRIDES + 31 submission files. Config 2286→771 lines.
