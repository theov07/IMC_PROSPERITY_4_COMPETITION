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

### 🥈 Priority 2 — Finalize bid
- Once V is measured properly, run script 04 with correct V
- Expected optimal bid : probably 500-2000 XIRECs
- Add `def bid(self): return X` to Trader template in submission

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
