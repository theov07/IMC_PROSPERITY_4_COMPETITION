# R4 Roadmap — État + Idées priorisées

Status: D0 of R4 submission window. v9 champion locked (+1,842 PnL vs v5).
Backtest 3-day on Leo3: 176,593 PnL / 67,628 DD / ratio 2.61 / submission size 95.2% of 100KB.

---

## Honest assessment of v9

**v9 est une amélioration MARGINALE et probablement partly overfit:**
- Δ vs v5 = +1,842 sur 3 jours = **+1.05% relatif** (dans le bruit)
- Win concentré sur Day 1 (+1,940), Days 2/3 ~neutres
- Mark 22 fires rarement → faible stat sample
- 19 variants v8/v9 testés → on a peut-être pêché celui qui matche le mieux les 3 jours

**Mais** : DD inchangé (67,628 vs 67,465), gratuit en taille (95.2% < 100KB), ratio +0.02.
Risque limité de l'inclure même si overfit.

---

## DONE & locked

| Item | Status | Commit |
|---|---|---|
| Counterparty Fade Signal (3D grid + M22 finer) | ✅ 35 variants tested | 987ce55 |
| Live alpha probes (5 deployed) | ✅ EXTREME, SHADOW, ON_OFF, SIZE, BASIC | 1fbc089 |
| Live probe analysis | ✅ 5 insights documented | 1fbc089 |
| R3 options diagnosis | ✅ VEV_5200 stuck +300 root cause | 160c745 |
| HTML dashboards | ✅ R3 live (v2), v5 backtest, v9 backtest | 8f30941, 160c745 |
| Backtest cache infrastructure | ✅ `scripts/cached_backtest.py` + `artifacts/backtest_cache/round_4/` | (this commit) |
| v9 champion (M22cond_z15_w04) | ✅ +1,842 vs v5 | 987ce55 |

---

## Currently testing (this commit)

| Idea | Variants | Expected outcome |
|---|---|---|
| **v10 — Reduce position limits on options** (structural fix, non-overfit) | lim150_5100_5200, lim100_all, lim200_5100_5200, lim200_all | Trade Day 1-2 PnL for less Day 3 drift loss |
| **v11 — Tiny live-tune weights** (M55=-0.05, M67=+0.05) | M55+M67, M55 only, M67 only | Should be ~neutral on backtest, ready to scale in live |

---

## High priority — REAL alpha potential

### A. Trader ID clustering / behavior analysis
**Why**: User's recap of last year's R5 video says 3 trader types: retail/noise, MM, informed.
Our goal as MM: **capture noise from retail + always be on side of informed**.

**What to do**:
- For each trader ID (in 3-day historical + live probe data), compute:
  - Signed flow per trader → bullish/bearish bias
  - Hit rate (% of trades that lead to favorable next-50-tick move)
  - Realized PnL contribution to us (when we trade with them, are we WINNING?)
  - Vol profile (do they MM constantly or trade in bursts?)
- Cluster traders into: noise (random), MM (constant 2-sided), informed (one-sided + win)
- **Output**: per-trader scorecard + cluster assignment

**Estimated alpha**: Could replace M22cond v9 with per-trader weights of various signs.
Backtest 3-day potential: +5,000 to +15,000 (if we find 2-3 new good traders).

### B. Cross-asset signals
**Why**: User noted "trade on hydro → predict other assets". Information leaks across products.
Our trades on VEV options are also visible to others — they may follow.

**What to do**:
- For each pair (X, Y) ∈ {VELVET, HYDROGEL, VEV_5000-6500}:
  - Compute lead-lag correlation: does X's flow at ts predict Y's mid at ts+50?
  - Test asymmetry: VEV options flow → VELVET return? VELVET flow → VEV options return?
- Build cross-asset signal: e.g., "if VEV_5200 buys spike, VELVET goes down → fade"

**Estimated alpha**: Unknown but could be significant (untapped axis).

### C. "Recopier les meilleurs"
**Why**: User: "les autres traders ont aussi accès à ce qu'on fait, recopier les meilleurs".
The lead-lag analysis from R4 D1+D2+D3 already showed: M55 and M67 lead by ~50 ticks, M01 and M14 fade (their flow predicts opposite).

**What to do**:
- Take top-PnL trader (whoever is making the most money in the historical data)
- Reconstruct their strategy: when do they buy? what spreads? what sizes?
- Either:
  - (a) Build our MM around following them
  - (b) Try to BE them — copy their patterns

**Estimated alpha**: High variance. Could be +20k or fail.

### D. Day 3 chute deep analysis
**Why**: Our Day 3 = 18,753 vs Day 1 = 73,528, Day 2 = 84,312. **75% drop on Day 3**.
Most loss is on options (-7,335).

**What to do**:
- Plot per-tick our position vs price for Day 3 → find when drift begins
- Identify which trader IDs are TRADING on Day 3 (vs Day 1/2): is there a regime change?
- Look for early-warning signals: VWAP breakdown, OBI flip, spread widening
- Build a "Day 3 detector" that downsizes positions when triggered

**Estimated alpha**: Could halve Day 3 loss → +3-4k.

### E. Delta hedge options→VELVET (non-overfit, theoretical)
**Why**: Day 3 loss = -7,335 on options because we're stuck LONG delta. If we hedge with VELVET short, we neutralize directional exposure.

**What to do**:
- Compute delta of each VEV option (Black-Scholes given strike + spot + IV)
- Net options delta = Σ position[i] × delta[i]
- Target VELVET position = -net_delta (offsets options)
- Adjust VELVET quoting to hit target

**Estimated alpha**: Day 3 loss → ~0 if hedge is good. But hedge has cost. Net could be +3-5k.

---

## Medium priority

### F. Deep OTM options as cheap hedge
**Why**: User: "acheter beaucoup options deep otm car ça coûte rien". VEV_6500 trades at 1-2 ticks.
If price drops sharply, deep OTM puts spike in value (gamma). Cheap insurance.

**What to do**:
- Buy 50 VEV_6500 calls (or whatever cheapest OTM) on D1
- Hold passively — they cost almost nothing
- If big move → they pay off; otherwise expire 0
- Combine with our short delta exposure to convert tail risk to bounded loss

**Estimated alpha**: -1k cost, +5k+ in tail scenarios. Improves robustness more than EV.

### G. Repartir from zero — clean slate
**Why**: User: "lock notre meilleur version backtest 3d puis repartir sur une nouvelle strat de 0".
We've layered many overlays on the original mm_first_v4_combo. Maybe a cleaner architecture finds new alpha.

**What to do**: New strategy file, no inherited cruft. Just:
1. Pure penny-improve MM
2. Position-aware sizing
3. Clean signal injection point
4. Test against v9.

**Estimated alpha**: 0 to ?? Risk: spending days for nothing. Low priority unless v9 is upper bound.

### H. Garde-fous (defensive)
**Why**: Robustness for unknown live scenarios.

**What to do**:
- Vol breakout limit: if realized vol > 3x normal, halve position limits
- Stop trading product if PnL drawdown > 50% intraday
- Sanity check on quote prices: refuse if bid/ask > 100 ticks from last mid

**Estimated alpha**: 0 in expectation, +3-10k in tail scenarios.

---

## Low priority / nice to have

| Item | Notes |
|---|---|
| Per-product fine-tuning | Gain marginal, time better spent on high-priority items |
| More live probes | We have enough data now; further probes have diminishing returns |
| Improve fill model | Realistic mode is already good enough |
| Refactor base.py | Already cleaned to 18KB |

---

## Recommended next 3 actions (in order)

1. **Wait for v10/v11 results** (running now). If v10 lim200 wins → may save 1-2k on Day 3.
2. **Trader ID clustering analysis** (idea A) — biggest unexplored alpha axis. 1-2 hours of analysis.
3. **Cross-asset signal exploration** (idea B) — second biggest. 1-2 hours.

If the above don't yield wins, fall back to:
- **Delta hedge** (idea E) — solid theoretical base, but more code.
- **Day 3 deep analysis** (idea D) — likely small gain but de-risks live.

---

## Constraints reminder

- Submission size: <100KB (we're at 95.2%)
- Latency: 200-tick avg < 5ms (we're at 0.83ms)
- Position limits: VELVET 200, options 300 (200 in v10 variants), HYDROGEL 80 (disabled)
- Round duration: 1M timestamps per day
- No internet, no file I/O, no threading
