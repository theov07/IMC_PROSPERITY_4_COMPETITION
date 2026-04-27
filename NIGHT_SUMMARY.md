# Night autonomous run — 2026-04-27 02:00–05:00

User went to bed; agent worked autonomously on R4 risk-mgmt + alpha exploration.

---

## TL;DR

**Baseline still locked**: `R4_BASELINE__r4_velvet_options_only` — **157,712 / DD 72,582 / Ratio 2.17**.
No risk-mgmt variant beat it on 3-day total PnL. **Don't change the upload yet.**

What I learned:
1. **D3 underperformance ≠ EOD problem** — it's a regime-detection problem.
2. **EOD (time-based) is OVERFIT** (rejected, user was right).
3. **VWAP signal CAN detect D3 trend** — but is too noisy intraday on D1/D2 (causes churn).
4. **Trader clustering is real**: Mark 67 = pure buyer (+27k 3d PnL); Mark 49 = pure seller (-15k).
5. **Counterparty HTML report** at `artifacts/analysis/round_4/counterparties_velvet_3d.html` (1.4MB).
6. **Option strikes 4500/5000/5100 have ZERO external trade flow** (1-5 trades over 3 days). Far-OTM 5300+ has all volume.

---

## Files created tonight

### Analysis scripts (in `scripts/`)
- `investigate_d3_underperf.py` — per-day metrics breakdown
- `d3_velvet_endday.py` — VELVET mid trajectory in D3 last 5%
- `d3_crash_drill.py` — fills + position evolution in D3 crash window
- `analyze_r4_mid_per_day.py` — per-day vol/range/drift across all VEV strikes
- `option_volume_analysis.py` — per-strike volume + counterparty top 5
- `vpin_vwap_velvet.py` — VPIN + rolling VWAP on VELVET D1/D2/D3
- `trader_correlation_analysis.py` — per-trader 3-day PnL clustering
- `compare_eod_variants.py` — EOD comparison (rejected variants)
- `compare_conditional_variants.py` — conditional variants vs baseline
- `compare_r4_3d_baselines.py` — earlier baseline comparison

### New code in `prosperity/strategies/base/base.py`
- `_apply_eod_unwind()` — opt-in via `eod_unwind_start_pct`. **Default disabled (overfit)**.
- `_apply_intraday_stop_loss()` — opt-in via `stop_loss_drawdown_pnl`. PnL-drawdown trigger.
- `_apply_conditional_unwind()` — opt-in via `cond_unwind_enabled`. **VWAP-triggered active flatten** (the right approach but signal noisy).
- `_trend_direction()` — EMA fast/slow crossover. Didn't fire on R4 data.
- `_vwap_signal()` — rolling-window VWAP signal. **Now uses time-window cumulative**, not EMA.

### New code in `prosperity/strategies/round_3/r3_guarded_anchor_mm.py`
- `_compute_velvet_hedge_target()` — sums option deltas for delta-neutral hedge target.
- Hooks: `delta_hedge_enabled`, `vwap_gate_enabled`, `trend_gate_enabled`.
- Refactored to inject `inventory_target` for delta hedge (uses MMFirstV4Combo's built-in mechanism).

### Member configs added
| Variant | Mechanism | Result |
|---|---|---|
| `r4_velvet_eod_v1` (0.85) | EOD time-based | +2k vs baseline (overfit, rejected) |
| `r4_velvet_eod_aggressive` (0.75) | EOD too early | -119k DISASTER |
| `r4_velvet_eod_conservative` (0.92) | EOD late | -3k |
| `r4_velvet_eod_v4` (0.95) | EOD very late | -19k |
| `r4_velvet_eod_v5` (0.97) | EOD super late | -36k |
| `r4_velvet_eod_v1_trend` | EOD + EMA trend | identical to eod_v1 |
| `r4_velvet_trend_only` | EMA trend gate alone | 0 effect (EMA never fired) |
| `r4_velvet_trend_aggressive` | tight EMA gate | 0 effect |
| `r4_velvet_stoploss_v1` (30k) | Intraday DD trigger | 0 effect (never hit) |
| `r4_velvet_stoploss_tight` (15k) | tight stop | -43k DISASTER |
| `r4_velvet_dhedge_v1` | full delta hedge via inventory_target | 0 effect (lever too weak) |
| `r4_velvet_dhedge_partial` | half delta hedge | 0 effect |
| `r4_velvet_vwap_gate` (8) | passive VWAP gate | 0 effect |
| `r4_velvet_vwap_gate_tight` (4) | tight passive | 0 effect |
| `r4_velvet_cond_unwind` (5%, EMA-VWAP) | active VWAP unwind, EMA bug | 0 effect |
| `r4_velvet_cond_unwind_v3` (rolling VWAP) | proper VWAP signal | -130k DISASTER (signal noisy) |
| `r4_velvet_cond_unwind_strict` | strict signal | TBD |

---

## D3 ROOT CAUSE (definitive)

D3 baseline PnL = +20,452 vs D1=+68,920 / D2=+68,340 (3.4× worse).

### What happens
- Tick 0 → 950,000: VELVET range 5,191 → 5,300, normal MM accumulates +74,128 PnL.
- Tick 950,000 → 999,900 (last 5%): VELVET drops -45.5 (-0.86%) **persistently**.
- Our long position (199 VELVET + 300 on VEV_4000/5100/5200 + smaller on others) gets hammered:
  - VELVET delta drop: -9k
  - VEV_4000 (delta ≈ 1.0) drop -3.6%: -13k
  - VEV_5100 (ATM) drop -22%: -12k
  - VEV_5200 drop -30%: -9k
  - Other strikes: -10k+
- **WORSE**: in the crash window, our z-velvet flips to -2.08 (oversold) → strategy fires "BUY mean-rev" → we accumulate 35 buys / 28 sells. **We BUY THE CRASH.**

### Why standard hedges/unwinds don't work
- **EOD (time-based)** : punishes D2 rebound (-24k) for the +30k D3 saving. Net -2k.
- **EMA trend gate** : EMA fast/slow diff stays small on VELVET → never fires.
- **Stop-loss intraday** : either too loose (never fires) or too tight (fires on D2 dip = wrong).
- **Delta hedge via inventory_target** : MMFirstV4Combo only uses inv_target in fair-value bias, not in size/skew → too weak.
- **VWAP gate (passive only)** : doesn't unwind existing 199 long; we still bleed on what we hold.
- **VWAP-triggered active unwind** : the signal CAN trigger correctly on D3, but also fires intra-day on D1/D2 (mid temporarily dips below VWAP) → causes churn → kills PnL.

### What MIGHT work (next iteration)
1. **VWAP signal with persistence** : require N consecutive ticks of mid << VWAP before unwind fires (not 1 tick).
2. **Delta hedging done RIGHT** : not via inventory_target (weak), but via direct `target_pos` injection in size/skew calc. Need a deeper refactor of MMFirstV4Combo.
3. **Trader-bias signal** : monitor Mark 67 BUY volume → bias VELVET long when Mark 67 active. Live-only alpha.
4. **Cheap deep-OTM hedge** : buy 100 VEV_6000/6500 at price 0.5 (cost ~100). If VELVET crashes 5%, options spike → free crash insurance. **Untested**.
5. **Per-period regime classifier** : Use VPIN + drift to classify each day as range/uptrend/downtrend. Switch strategy parameters accordingly.

---

## DATA INSIGHTS

### Per-day VPIN + drift
| Day | VPIN | drift | Range | regime |
|---|---:|---:|---:|---|
| D1 | 0.46 | +20.5 | 85 | toxic + uptrend |
| D2 | **0.23** | +28.0 | 93 | calm + uptrend |
| D3 | 0.46 | **-63.5** | 108 | toxic + DOWNTREND |

D2 is **dramatically calmer** (VPIN half of D1/D3). D3 has same VPIN as D1 — so it's NOT toxic flow that's different, it's **drift direction**.

### Trader 3-day PnL clustering (VELVET only)
| Trader | Total Vol | 3-day PnL | Profile |
|---|---:|---:|---|
| **Mark 67** | 1,510 | **+27,261** 🟢 | Pure BUYER (1510 buys, 0 sells) — biggest winner |
| Mark 14 | 3,524 | +6,906 🟢 | Balanced MM (50/50) |
| Mark 01 | 2,792 | +4,366 🟢 | Slight short bias |
| Mark 22 | 843 | -9,984 🔴 | Pure SELLER — loses on uptrend days |
| Mark 55 | 6,551 | -13,204 🔴 | High-vol MM eaten by adverse |
| Mark 49 | 1,186 | -15,346 🔴 | Pure SELLER — biggest loser |

**Insight**: traders have **persistent structural bias** (always buys or always sells). Not informed flow. **A "follow Mark 67's volume" or "fade Mark 49's" signal could work as side bias.**

Per-day trader PnL :
- D1 (drift +20): Mark 67 wins +9k (right side), Mark 49 loses -4.7k
- D2 (drift +28): Mark 67 wins +21.7k (HUGE), Mark 49 loses -14k
- D3 (drift -63): Mark 49 finally wins +3.4k, Mark 67 finally loses -3.5k

So Mark 67 is uptrend-correlated, Mark 49 is downtrend-correlated. **Volumes are inversely correlated**: when Mark 67 buys >500/day, drift is positive 100% of the time.

### Option strike volume (3-day external trades)
| Strike | Total trades | Volume | Note |
|---|---:|---:|---|
| 4000 | 442 | 876 | Deep ITM — MM hub (Mark 14, Mark 38 balanced) |
| **4500** | **3** | **6** | **NO EXTERNAL FLOW** |
| **5000** | **3** | **6** | **NO EXTERNAL FLOW** |
| **5100** | **3** | **6** | **NO EXTERNAL FLOW** |
| 5200 | 47 | 162 | Sparse |
| 5300 | 164 | 548 | Active (Mark 01 BUY 439 vs Mark 22 SELL 545) |
| 5400 | 276 | 959 | Active (Mark 01 BUY **911** !!! vs Mark 22 SELL ?) |
| 5500 | 306 | 1069 | Active |
| 6000 | 317 | 1105 | Active |
| 6500 | 317 | 1105 | Active |

**ATM (4500/5000/5100) has NO external taker flow.** Our 200 trades there per day come from us posting passive + other MMs hitting us.

**Far OTM**: Mark 01 BUYS heavily (+1500 contracts across 5300/5400/5500), Mark 22 SELLS heavily.

---

## RECOMMENDED NEXT STEPS (ranked)

### 🥇 1. Build trader-volume signal (Mark 67 bias)
This is the biggest **untested** alpha. The trader analysis shows clear persistent bias.
Implementation:
- Track rolling Mark 67 buy volume per N ticks
- If Mark 67 is BUYING above-average → bias VELVET long (raise reservation price)
- If Mark 49 is SELLING above-average → bias VELVET short
- ⚠ **Note**: Live IMC may have DIFFERENT participants. This is R4-historical specific. But the *pattern* (some traders are persistent buyers/sellers) likely generalizes.

### 🥈 2. Cheap deep-OTM hedge (VEV_6000/6500 long position)
Buy 100 long at price 0.5 (cost ~100 each strike = 200 total cash).
- Normal day: options expire worthless → -200 loss.
- Crash day (5%+ underlying drop): options spike to 5+ → +500–1000 gain on each.
- Asymmetric payoff (max loss bounded, gain unbounded).

### 🥉 3. VWAP signal with persistence requirement
Build the cond_unwind v4 with:
- Require 50+ consecutive ticks of mid < VWAP - threshold before firing
- Use larger window (300k = 30%) for more stable VWAP
- Threshold 30+ to avoid false alarms

### 4. Direct delta-hedge via override
Currently `inventory_target` is a weak lever. A stronger delta hedge would override the size computation directly. Requires modifying `_compute_sizes` in MMFirstV4Combo or using a custom strategy class.

### 5. VEV_5300 sizing (z_skip 0.8 → 0.5)
Currently +1,535. If we match the gate to other strikes, +500–1000 expected.

### 6. Counterparty HTML report deep-dive
Open `artifacts/analysis/round_4/counterparties_velvet_3d.html` in browser. Should have visual evidence of who's trading what when. Requires manual inspection.

---

## STATE FOR USER WHEN WAKING

1. **Read this file (`NIGHT_SUMMARY.md`)** for the full picture.
2. **Run** `python scripts/compare_conditional_variants.py` for variant table.
3. **Open** `artifacts/analysis/round_4/counterparties_velvet_3d.html` for visual counterparty dive.
4. **All work committed locally on branch Leo3**. NOT pushed.
5. **Baseline upload still recommended**: `R4_BASELINE__r4_velvet_options_only__pnl158k_dd73k_ratio217.py`.
6. **Decision pending**: trader-bias signal, cheap OTM hedge, or stick with baseline.

If you want me to continue exploring tomorrow, the highest-ROI next move is **building the Mark 67 trader-bias signal** (it's a concrete, testable alpha that's not in any current variant).
