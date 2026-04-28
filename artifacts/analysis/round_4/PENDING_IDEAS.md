# R4 — Pending ideas + things still to do

Tracker for what's done vs what's not. As of 2026-04-27 end-of-day.

---

## ✅ DONE

### Strategy / config wins
- [x] **R4_CHAMPION_v5** locked: 174,751 / 67,465 / 2.59 (+17,039 vs old baseline)
  - Mark 49 fade -0.8 + Mark 14 fade -0.5 + Mark 01 fade -0.2 + OBI size tilt
  - 27-point 3D grid validates this is OPTIMUM
- [x] All submissions <100KB (LF only)

### Live alpha probes (research)
- [x] **R4_LIVE_ALPHA_PROBE** (basic passive MM, 26 KB)
- [x] **R4_LIVE_ALPHA_PROBE_EXTREME** (5 phases: DARK / TIGHT / MEGA_BID / MEGA_ASK / NORMAL, 27.6 KB)
- [x] **R4_LIVE_ALPHA_PROBE_SHADOW** (queue 2nd vs below-best, 26.6 KB)
- [x] **R4_LIVE_ALPHA_PROBE_ONOFF** (50t ON/OFF cycles, 26.9 KB)
- [x] **R4_LIVE_ALPHA_PROBE_SIZE** (size cycle 1/5/30/100/200, 26.3 KB)

### Analysis scripts
- [x] D3 underperformance forensics (Mark 01 BUY spike pre-crash)
- [x] Per-option trader lead-lag
- [x] Per-strike Mark classification
- [x] Cross-trader correlation matrix (Mark 49 ↔ Mark 67 = -0.78)
- [x] OBI L3 predictive analysis (88% hit rate raw)
- [x] VPIN + VWAP analysis on VELVET
- [x] Deep OTM mystery (VEV_6000/6500 trade at price 0)
- [x] Live vs backtest comparison (we phagocytose 80% of flow)
- [x] R3 live dashboard HTML

### Live results captured
- [x] V5 live: +6,214 PnL (1.09x backtest expectation)
- [x] Probe live: +382 PnL (passive only, lower)
- [x] R3 live: +64,195 (analyzed in dashboard)

---

## ⏳ PENDING — Direct impact on R4 final

### High priority (could improve v5)
- [ ] Test inverse Mark 14 weight (+0.5 instead of -0.5) — may be informed when winning queue
- [ ] Adaptive size on Mark 49 sell spikes (volatility-conditional sizing)
- [ ] Test cheap deep-OTM forced hedge (VEV_6000/6500 long at price 0 = free)
- [ ] Reverse-engineer Mark 14/01 quote patterns to predict their next move

### Medium priority
- [ ] Per-day Mark behavior conditional logic (D2 vs D3 different patterns)
- [ ] State-conditional EOD unwind (only flatten if PnL >> 50% of peak)
- [ ] Volume-weighted fade (only fade Mark 49 when his volume > 2σ above mean)

### Low priority
- [ ] HYDROGEL re-tune for R4 (Tibo/Theo territory but might be relevant)
- [ ] Smile residual arb on VEV options (signal weak per analysis)
- [ ] Cross-product signal HYDROGEL ↔ VELVET (correlation = 0 but worth re-testing)

---

## 🔬 RESEARCH — for next round / iterations

### From live observations
- [ ] **Live IMC volume surge** — we get 2.5x more fills than backtest predicts. Investigate whether IMC live has different liquidity providers.
- [ ] **Mark 14/01 disappear in our queue** — quote at "queue 2nd" position to capture their flow indirectly (= shadow probe data)
- [ ] **Mark 49 amplification** — our cp_bias triggers his sells, validates he's a wrong-side trader. Could we BAIT him to dump more by raising bid even higher?

### Architecture
- [ ] Per-product cp_bias weights (currently only on VELVET; options not analyzed individually)
- [ ] Conditional cp_bias firing based on regime (uptrend vs downtrend)
- [ ] Fast-feedback loop: detect when Mark X stops appearing → switch off his weight

### Data exploration
- [ ] Time-of-day patterns in Mark behavior (start-of-day vs end-of-day)
- [ ] Mark size distribution (do they have characteristic order sizes?)
- [ ] Same-tick Mark↔Mark trades (are they trading at same prices simultaneously?)

### Manual challenge (R4 separate game)
- [ ] AETHER_CRYSTAL exotics: chooser, binary put, knock-out put
- [ ] Design positions with positive expected PnL under GBM 251% vol
- [ ] Submit via UI — separate from algo

---

## 🚀 LIVE SUBMISSION RECOMMENDATIONS

### Primary upload (the strategy that makes money)
```
artifacts/submissions/round_4/_BASELINE/R4_CHAMPION_v5__obi_fade_M49w08_M14_M01__pnl175k_dd67k_ratio259.py
```
89 KB, validated by 3D grid + live result +6.2k.

### Research uploads (collect data for next iteration)
Pick 1-2 depending on IMC limits:

1. **R4_LIVE_ALPHA_PROBE_EXTREME** (5-phase provocation)
   - Best for: identifying pure-buyers/sellers via mega quotes
   - Value: each phase forces clear behavior

2. **R4_LIVE_ALPHA_PROBE_SHADOW** (queue 2nd)
   - Best for: observing Mark 14/01 in action without interference
   - Value: discover whether they're informed when winning queue

3. **R4_LIVE_ALPHA_PROBE_ONOFF** (50t ON/OFF)
   - Best for: contrasting Mark↔Mark natural flow vs with-us flow
   - Value: see hidden trades that don't happen when we quote

4. **R4_LIVE_ALPHA_PROBE_SIZE** (size cycle 1/5/30/100/200)
   - Best for: detecting size-conditional Marks
   - Value: Mark X may only fill at specific size brackets

### Decision matrix

| Constraint | Pick |
|---|---|
| Only 1 upload allowed | CHAMPION_v5 |
| 1 primary + 1 research | CHAMPION_v5 + EXTREME |
| 1 primary + 2 research | + SHADOW (most analytically rich) |
| Unlimited research | All 4 probes (each captures different angle) |
