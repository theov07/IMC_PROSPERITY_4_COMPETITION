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

### High priority
- [ ] **Add Mark 55 fade** with weight -0.3 → A/B vs v5
- [ ] **Re-tune Mark 14** with finer grid (-0.3, -0.4, -0.5, -0.6, -0.7)
- [ ] **Test Mark 67 follow** with +0.2 to +0.4 → may help on uptrend days

### Medium priority
- [ ] **Volume-conditional firing**: only fade Mark 49 when his sell volume > 2σ above mean
- [ ] **Mark 14 conditional**: maybe Mark 14 buys = INFORMED when winning queue (test inverse weight)

### Research
- [ ] Why Mark 55 net sells in live but not in historical 3-day data?
- [ ] Why Mark 14 BUY bias in live but balanced historical?
- [ ] Are Mark patterns persistent across multiple live runs (sample size limited)?
