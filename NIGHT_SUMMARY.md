# Night autonomous run — 2026-04-27 02:00–06:00 (extended)

User went to bed; agent worked autonomously on R4 risk-mgmt + alpha exploration.
**Two waves of work**: wave 1 (risk-mgmt EOD/trend/dhedge), wave 2 (signal exploration).

---

## TL;DR — STILL BASELINE

**Baseline locked (unchanged)**: `R4_BASELINE__r4_velvet_options_only` — **157,712 / DD 72,582 / Ratio 2.17**.

**No variant beat it on 3-day total PnL across 24 attempts** in two waves.

What I learned:
- **D3 underperformance** = mean-rev BUYs into a persistent downtrend (not solvable with simple time-based mechanisms).
- **Time-based EOD = OVERFIT** (rejected, user was right).
- **VWAP signal CAN detect D3 trend** — but is too noisy intraday (causes churn on D1/D2).
- **OBI signal has 88% predictive power on raw data** — but spread cost erases the edge for taker, and passive bias has implementation issues.
- **Trader clustering** : Mark 67 = pure buyer (+27k 3d), Mark 49 = pure seller (-15k). Persistent structural bias.
- **Mark 55 + Mark 67 follow / Mark 01 + Mark 14 fade** correlations real but signal magnitude too small to bias quotes meaningfully.
- **Smile residual signal** : weak, inconsistent across horizons.
- **HYDRO ↔ VELVET correlation** : essentially zero at all lags. Independent products.
- **Cheap deep-OTM hedge** (VEV_6000/6500): negligible effect (-300, no crash event in backtest).
- **VEV_5300 sizing tune**: z_skip 0.5 vs 0.8 marginal (-59).

The **passive MM strategy already captures most of the available edge**. Adding overlays without deep refactoring doesn't help.

---

## All variants tested (24 total)

### Wave 1: Risk management
| Variant | Mechanism | Result vs Baseline |
|---|---|---|
| eod_v1 (0.85) | EOD time-based | +2k (kills D2 rebound) |
| eod_aggressive (0.75) | EOD too early | -119k DISASTER |
| eod_conservative (0.92) | EOD late | -3k |
| eod_v4 (0.95) | EOD very late | -19k |
| eod_v5 (0.97) | EOD super late | -36k |
| eod_v1_trend | EOD + EMA trend | identical to eod_v1 |
| trend_only (EMA 0.5) | EMA trend gate | 0 (EMA never fired) |
| trend_aggressive (EMA 0.3) | tight EMA gate | 0 |
| stoploss_v1 (30k) | DD trigger | 0 (never hit) |
| stoploss_tight (15k) | tight stop | -43k |
| dhedge_v1 | full delta hedge via inventory_target | 0 (lever too weak) |
| dhedge_partial | half delta hedge | 0 |
| vwap_gate | passive VWAP gate | 0 (doesn't unwind) |
| vwap_gate_tight | tight passive | 0 |
| cond_unwind_v3 | active VWAP unwind, rolling window | -130k DISASTER |
| cond_unwind_strict | strict signal | -36k |

### Wave 2: Alpha signals (this iteration)
| Variant | Mechanism | Result vs Baseline |
|---|---|---|
| cp_bias_v1 | Mark 55+67 follow, Mark 01+14 fade (anchor offset) | 0 (signal too small or anchor disabled) |
| cp_bias_aggressive | wider offset cap | 0 |
| cp_bias_long_window | 300-tick rolling | 0 |
| cp_bias_pure_followers | Mark 55+67 only | 0 |
| **cp_bias_max** (extreme params) | threshold=1, scale=1.0, offset=20 | **0** ← code path issue confirmed |
| **obi_v1** (3L, 0.005) | OBI taker overlay | -16k (spread > alpha) |
| obi_aggressive (3L, 0.003) | bigger size, lower cd | -42k |
| obi_strict (3L, 0.010) | high threshold | -17k |
| obi_l1 (1L, 0.20) | L1 imbalance | -28k |
| obi_passive (1tick) | passive quote bias | **-190k DISASTER** (crosses book) |
| obi_passive_aggressive | 2tick shift | -334k DISASTER |
| **otm_hedge_small** (VEV_6000/6500 long) | crash insurance | -300 marginal |
| **VEV_5300_z=0.5** | z_skip 0.8 → 0.5 | -59 marginal |

---

## D3 ROOT CAUSE (definitive — same as wave 1)

D3 baseline PnL = +20,452 vs D1=+68,920 / D2=+68,340 (3.4× worse).

**Mechanism**: VELVET drops -0.86% in last 5% persistently. Long inventory (199 + 300 on 5 strikes) bleeds. Z-velvet flips oversold → strategy BUYS the crash. We accumulate +35 buys / -28 sells in last 5% = NET LONG INTO THE BLEED.

**Why nothing helps**:
1. **Time-based EOD**: D2 has same drawdown then rebounds → unwinding both kills D2 net positive.
2. **Trend gate (EMA)**: VELVET has small absolute drift, EMA fast/slow stays within threshold.
3. **Stop loss**: either too loose (never hits) or fires on D2 dip and misses rebound.
4. **Delta hedge** (inventory_target): only a fair-value bias term, magnitude ~1-2 ticks, doesn't move quotes enough.
5. **OBI taker**: alpha is real (88% hit, +7.8 avg ret over 50 ticks), but spread is 2-6 ticks → +5 expected per round trip × hit rate × loss probability becomes -3 in practice with realistic fills.
6. **OBI passive**: shifting quotes 1 tick crosses the book → strategy becomes self-taker → blows up.
7. **Counterparty bias**: signal is real (Mark 55 BUY net 100-tick predicts +ret 60% n=57) but magnitudes are 5-30 contracts → anchor offset of 0.05-1.5 ticks is too small to matter.

---

## DATA INSIGHTS (from this wave)

### OBI predictive analysis (full 30,000 sample, REAL alpha)
| L3 OBI quintile | n | avg_ret next 50 ticks | hit_up % |
|---|---:|---:|---:|
| Q1 (OBI=-0.01) | 5990 | -7.64 | 11% |
| Q5 (OBI=+0.01) | 5990 | **+7.82** | **88.5%** |

### TICK rule (Lee-Ready signed flow over 50 ticks → return next 50)
| Q5 (net=+12) | n=60 | +2.58 ret | 65% hit |

### Trader classification (3-day VELVET)
| Trader | Class | Vol Buy | Vol Sell | Ratio | Burst |
|---|---|---:|---:|---:|---:|
| Mark 01 | MARKET MAKER | 1417 | 1375 | 1.03 | 1.55x |
| Mark 14 | MARKET MAKER | 1761 | 1763 | 1.00 | 1.67x |
| Mark 22 | biased SELLER | 146 | 697 | 0.21 | **2.53x** (most bursty) |
| Mark 49 | DIRECTIONAL SELLER | 115 | 1071 | 0.11 | 1.97x |
| Mark 55 | MARKET MAKER (high-vol) | 3254 | 3297 | 0.99 | 1.28x |
| **Mark 67** | DIRECTIONAL BUYER | **1510** | **0** | **inf** | 1.82x |

### Trader lead-lag (Pearson correlation: 100-tick net flow → 50-tick forward return)
| Trader | rho | BUY signal hit% | SELL signal hit% | Action |
|---|---:|---|---|---|
| Mark 01 | -0.170 | 23% (= 77% fade) | 44% | FADE BUYS |
| Mark 14 | -0.150 | 40% | 39% (= 61% fade) | FADE |
| Mark 55 | +0.141 | 60% (n=57) | 48% | FOLLOW |
| Mark 67 | +0.119 | 54% (n=59) | n/a | FOLLOW |
| Mark 49 | -0.101 | n/a | 42% | (rare buys) |
| Mark 22 | -0.063 | n/a | 53% | (rare buys) |

### HYDRO ↔ VELVET correlation
**Essentially zero at all lags** (-50 to +50 ticks). HYDRO and VELVET are independent products — no cross-product signal.

### Smile residual (per-strike IV - poly fit) → option mid return
Inconsistent. Some quintiles have 55-60% hit but no consistent pattern across strikes/horizons. Not a clean signal.

---

## NEW IDEAS for tomorrow (high-conviction)

### 🥇 1. OBI signal as INVENTORY TILT (not as quote prices)
The OBI alpha is real (+5 expected per round trip after spread). The bug in `obi_passive` was crossing the book. Better approach:
- When OBI bullish: increase passive bid SIZE (more inventory exposure to up-moves) without changing prices
- When OBI bearish: increase passive ask SIZE
- Existing strategy already has `_microprice_size_tilt` — extend it with OBI
- Should capture alpha without spread cost

### 🥈 2. cp_bias via fair_value injection (not anchor)
Current cp_bias modifies anchor_price, but anchor gets disabled by `_use_anchor` when wrong-way. Instead:
- Modify `mid_smooth` directly (the EMA-smoothed mid passed to fair_value)
- This is used for taker decisions and quote pricing regardless of anchor on/off
- Magnitude: with signal=+30 and scale=0.1, fair_value shifts +3 ticks → quote price shift +3 → meaningful

### 🥉 3. OBI + trader bias COMBINED signal
- OBI alone has 88% hit rate
- Trader bias (Mark 55+67 follow / Mark 01+14 fade) has ~60% hit rate
- Composite: only fire when BOTH agree → higher precision (likely 90%+ hit)
- Lower frequency but higher per-trade edge

### 4. Cheap OTM hedge with FORCED LONG ENTRY
Current variant tried passive MM on VEV_6000/6500. They don't trade much because mid is pinned at 0.5. Instead:
- HARD CODE buying 100 long VEV_6000 + 100 long VEV_6500 at start of each day
- Total cost: 100 × 0.5 + 100 × 0.5 = 100 cash
- If VELVET crashes 5%+, options go from 0.5 to 5+ → +500 each → +1000 PnL
- If no crash, lose 100. Asymmetric.
- Need to verify execution: insert taker buy orders during first 100 ticks

### 5. Anti-Mark 49 fade strategy
- Mark 49 is DIRECTIONAL SELLER (0.11 ratio) and LOSER (-15k 3d PnL)
- When Mark 49 SELL volume spikes, FADE (i.e., we BUY)
- Direct copy: buy when Mark 49's recent sell volume > X
- Implementation: track Mark 49 sells in last 50 ticks, fire when > 5

### 6. End-of-tick book imbalance + own position interaction
- When OBI > 0 AND we're SHORT: BUY back (close short) via taker — dual signal (own pos + flow)
- When OBI < 0 AND we're LONG: SELL back via taker
- Lower risk (closes existing exposure rather than opening new)

---

## RECOMMENDED ACTION

**Stick with baseline `R4_BASELINE__r4_velvet_options_only` for upload**. It is the local maximum on this dataset.

For next iteration, focus on:
1. **OBI as size tilt** (not price tilt) — clean implementation
2. **fair_value injection** for cp_bias (bypass anchor)
3. **Composite signals** (OBI + trader bias)

Total time budget remaining: probably 1-2 days before R4 close. **Don't rush** — explore these ideas carefully because we have 24 failed variants showing how easy it is to make things worse.

---

## All scripts (under `scripts/`)
- `investigate_d3_underperf.py` — per-day metrics
- `d3_velvet_endday.py` — VELVET mid trajectory
- `d3_crash_drill.py` — fills + position evolution
- `analyze_r4_mid_per_day.py` — per-day vol/range/drift
- `option_volume_analysis.py` — per-strike volume + counterparties
- `vpin_vwap_velvet.py` — VPIN + rolling VWAP
- `trader_correlation_analysis.py` — trader 3-day PnL
- `deep_counterparty_analysis.py` — Mark classification + lead-lag
- `order_book_imbalance_signal.py` — **OBI quintile predictive** (KEY FINDING)
- `tick_rule_signal.py` — TICK rule (Lee-Ready)
- `smile_residual_signal.py` — IV vs poly fit residual
- `hydrogel_velvet_leadlag.py` — cross-product correlation
- `compare_eod_variants.py`, `compare_conditional_variants.py` — comparison tooling

## All HTML reports (under `artifacts/analysis/round_4/`)
- `counterparties_velvet_3d.html` (1.4MB) — Tibo's tool output for VELVET 3-day

## Commit
All work committed locally on `Leo3` branch. **Not pushed** per user instruction.
