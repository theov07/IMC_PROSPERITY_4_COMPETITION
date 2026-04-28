# R4 Live Probes Analysis — Hidden patterns from 4 probe submissions

Source logs:
- EXTREME: 510640.json/log
- SIZE: 510749.json/log
- SHADOW: 510782.json/log
- ON_OFF: 510847.json/log

## TL;DR — 5 nouvelles découvertes

1. **Mark 55 est NET SELLER en live** (27/46, 55/80, 50/88) — pas balanced comme historique
2. **Mark 14 est BUY-biased en live** (66% buys) — différent de l'historique 50/50
3. **SHADOW probe = 0 PnL mais capture ALL Mark↔Mark** (best for pure analysis)
4. **SIZE n'est pas un filtre** — Mark 55 trade aussi sur size 1 que 200
5. **MEGA_ASK déclenche cascade Mark↔Mark** (+80 trades vs +32 sur MEGA_BID)

## Per-probe summary

| Probe | PnL | Our | M↔M | Best insight |
|---|---:|---:|---:|---|
| EXTREME | +330 | 26 | 117 | Mark 67 pure buyer in P4_MEGA_ASK confirmed |
| SIZE | +111 | 40 | 108 | Size doesn't filter Marks |
| SHADOW | 0 | 0 | 144 | We see EVERYTHING without interfering |
| ON_OFF | +327 | 14 | 131 | OFF has 4x more flow than ON (phagocytose) |

## Mark classification (UPDATED with live data)

| Mark | Pure role | Live evidence | v5 weight | Should change? |
|---|---|---|---:|---|
| Mark 67 | PURE BUYER | 31/0, 7/0, 5/0 — never sells | 0 (not used) | maybe +0.3 follow |
| Mark 22 | PURE SELLER | 0/19, 0/26 | 0 | maybe -0.3 fade |
| Mark 49 | PURE SELLER (rare) | 0/26 SHADOW, 0/8 EXT | -0.8 | KEEP |
| Mark 14 | BUY-biased MM | 33/17, 42/37 (66% buy) | -0.5 | KEEP (fade buy bias) |
| Mark 55 | NET SELLER (live!) | 27/46, 55/80 | 0 | TRY -0.3 |
| Mark 01 | MM balanced | 13/10, 38/4 | -0.2 | KEEP |

## Key live patterns we missed in backtest

### Mark 14 is BUY-biased in live D3 first 10%
- SHADOW: 75 buys / 54 sells (58% buy)
- ON_OFF OFF: 54 buys / 31 sells (64% buy)

**v5 already fades Mark 14 with weight -0.5 → captures this correctly.**

### Mark 55 is NET SELLER in live D3 first 10%
- SHADOW: 82 buys / 126 sells (39% buy = 61% sell)
- ON_OFF OFF: 50 buys / 88 sells (36% buy = 64% sell)

**v5 does NOT use Mark 55 (weight 0). Adding fade -0.3 might capture extra alpha.**

### Mark 67 NEVER sells
- All probes confirm: 31, 7, 31, 5, 7 buys total in various phases / 0 sells
- v5 doesn't follow him. Adding +0.3 might add small bullish bias.

## Probe-by-probe details

### EXTREME (5 phases, 1000 ticks)

| Phase | Total | With Us | M↔M | Notable |
|---|---:|---:|---:|---|
| P1 DARK (no quotes) | 32 | 0 | 32 | Only Mark 01/14/55 trade (MMs) — Mark 67/22/49 absent |
| P2 TIGHT_MM | 51 | 37 | 14 | Mark 55 dominates: 13 buy / 24 sell from us |
| P3 MEGA_BID (bid+2) | 55 | 23 | 32 | Mark 55 sells 23 to us, Mark 67 buys 6 from others |
| **P4 MEGA_ASK (ask-2)** | **99** | 19 | **80** | **Cascade!** Mark 14 buys 32 externally, Mark 55 sells 32 externally |
| P5 NORMAL_MM | 76 | 64 | 12 | Mark 55 again dominant (25 buy / 39 sell with us) |

### SHADOW (queue 2nd then below)

| Phase | Total | With Us | M↔M | Notable |
|---|---:|---:|---:|---|
| P1 AT BEST (queue 2nd) | 146 | 0 | 146 | We see Mark 14 (33/17), Mark 55 (27/46) clearly |
| P2 BELOW BEST | 332 | 0 | 332 | Even more Mark↔Mark visible. All marks active. |

PnL = 0. Pure observation. Best probe for analysis.

### ON_OFF (50t cycles)

| Phase | Total | Behavior |
|---|---:|---|
| OFF (no quotes) | 338 contracts in 500 ticks | All Marks trade naturally |
| ON (penny improve) | 84 contracts | We capture ~70%, Marks reduce |

Volume ratio OFF/ON ≈ 4.0x. Confirms huge phagocytose effect.

### SIZE (cycle 1, 5, 30, 100, 200)

| Phase | Size | Our fills | M↔M | Insight |
|---|---:|---:|---:|---|
| P1 size 1 | 1 | 6 | 4 | Tiny, Mark 67 sells 2 to us (rare!) |
| P2 size 5 | 5 | 40 | 18 | Mark 55 dominates (13/22) |
| P3 size 30 | 30 | 33 | 12 | Same Mark 55 |
| P4 size 100 | 100 | 44 | 30 | Mark 49 starts to appear (8 sells) |
| P5 size 200 | 200 | 72 | 0 | We absorb 100% flow with mega-size |

Size doesn't change WHO trades, just HOW MUCH.

## Action items for v6

### High priority — DONE (all 11 variants LOSE vs v5 — see d0e479a)
- [x] **Add Mark 55 fade** -0.3 → -7,621 PnL vs v5 (LOSES)
- [x] **Re-tune Mark 14** finer grid → all worse than -0.5 (LOSES)
- [x] **Test Mark 67 follow** +0.2 → -2,490 vs v5 (closest, but LOSES)

### Medium priority — DONE (all 6 variants LOSE vs v5)
- [x] **Volume-conditional firing M49** (z=1.5/2.0/2.5/wider): all -8k to -10k vs v5 (LOSES)
- [x] **Mark 14 conditional** combined with M49 → LOSES too
- [x] **Soft baseline** (z below threshold → -0.2 instead of 0) → -10,887 (LOSES)

  **Result table (VELVET 3-day, realistic fill):**
  | Variant                 |    PnL | Δ vs v5 |
  |-------------------------|-------:|--------:|
  | **v5 baseline always-on** | **100,087** |       — |
  | v7 z=1.5                |  91,200 |  -8,887 |
  | v7 z=2.0                |  91,132 |  -8,955 |
  | v7 z=2.5                |  90,323 |  -9,764 |
  | v7 z=2.0 w=1000ticks    |  87,858 | -12,229 |
  | v7 M49+M14 cond z=2.0   |  89,484 | -10,603 |
  | v7 z=2.0 soft (-0.2)    |  89,200 | -10,887 |

  **Why conditional fails**: Mark 49 trades RARELY but each trade is informative.
  Always-on -0.8 captures every signal; gating misses 60-80% of them depending on z.
  The "rare-but-big" pattern is ALREADY anomalous → no benefit from extra anomaly filter.

### Research — pending (no actionable next step from backtest perspective)
- [ ] Why Mark 55 net sells in live but not in historical 3-day data?
- [ ] Why Mark 14 BUY bias in live but balanced historical?
- [ ] Are Mark patterns persistent across multiple live runs (sample size limited)?

## v8/v9 — NEW CHAMPION FOUND: M22 conditional fade (+1,842 PnL)

After v6/v7 failures, switched approach: instead of GATING existing strong signals (Mark 49),
ADD new signals conditionally for Marks NOT currently in v5 weights.

**Hypothesis confirmed**: Mark 22 = PURE SELLER (rare). When he dumps anomalously hard
(volume z-score > 1.5σ above his rolling mean), fading him with weight -0.4 captures alpha.
When he's silent or making small trades, no signal applied (weight 0).

### v8 — Initial test: ADD Mark 22 conditional fade

| Variant | PnL | Δ vs v5 |
|---|---:|---:|
| **v5 baseline (no M22)** | 100,087 | — |
| v8 M67cond z=2.5 (PURE BUYER follow) | 98,923 | -1,164 |
| v8 M67cond z=2.0 | 97,803 | -2,284 |
| v8 M67cond z=1.5 | 89,460 | -10,627 |
| v8 M67M22cond combined | 97,736 | -2,351 |
| **v8 M22cond z=2.0 w=-0.5** | **100,668** | **+581** ⭐ |

### v9 — Fine-grid search around M22cond winner

| Variant | PnL | Δ vs v5 |
|---|---:|---:|
| v9 z=1.0 w=-0.3 | 99,356 | -731 (too permissive — degenerates) |
| v9 z=1.2 w=-0.3 | 99,522 | -565 (still too permissive) |
| v9 z=1.5 w=-0.25 | 101,313 | +1,226 |
| **v9 z=1.5 w=-0.3** | **101,906** | **+1,819** |
| v9 z=1.5 w=-0.35 | 101,784 | +1,697 |
| **v9 z=1.5 w=-0.4** ⭐ | **101,929** | **+1,842 (BEST)** |
| v9 z=1.8 w=-0.3 | 101,742 | +1,655 |
| v9 z=2.0 w=-0.25 | 100,928 | +841 |
| v9 z=2.0 w=-0.3 (v8 winner) | 101,368 | +1,281 |
| v9 z=2.0 w=-0.35 | 101,258 | +1,171 |
| v9 z=2.0 w=-0.4 | 101,446 | +1,359 |
| v9 z=2.5 w=-0.3 | 100,764 | +677 |
| v9 z=2.5 w=-0.5 | 100,428 | +341 |
| v8 M22 ALWAYS-ON (-0.5) | 95,952 | -4,135 (proves CONDITIONAL is essential) |

### Final v9 champion full backtest

| Metric | v5 baseline | **v9 M22cond_z15_w04** | Δ |
|---|---:|---:|---:|
| TOTAL PnL (3-day, all products) | 174,751 | **176,593** | **+1,842** |
| Drawdown | 67,465 | 67,628 | +163 (negligible) |
| PnL/DD ratio | 2.59 | **2.61** | +0.02 |
| VELVET PnL | 100,087 | 101,929 | +1,842 |
| VELVET day 1 | 43,936 | 45,876 | +1,940 |
| VELVET day 2 | 32,032 | (~32k) | ~neutral |
| VELVET day 3 | 24,120 | (~24k) | ~neutral |

Win comes mostly from Day 1, but no day shows significant LOSS — robust pattern.

### Key insights

1. **Always-on M22 LOSES** (-4,135) — small noisy trades aren't informative
2. **Conditional firing IS essential** for M22 — only fades when sell volume spikes
3. **z=1.5 sweet spot** — z<1.2 fires too often (becomes always-on), z>2.5 fires too rarely
4. **w=-0.4 sweet spot** — symmetric to M14's -0.5 weight
5. **M67 follow doesn't work** — even conditionally, his "informed" trades aren't predictive
6. **v9 final submission**: 95.2% of 100KB ✅ within IMC limit

### Final decision

**UPLOAD v9 (M22cond_z15_w04) as primary.**
Saved at `artifacts/submissions/round_4/_BASELINE/R4_CHAMPION_v9__M22cond_z15_w04__pnl176k_dd68k_ratio261.py`
