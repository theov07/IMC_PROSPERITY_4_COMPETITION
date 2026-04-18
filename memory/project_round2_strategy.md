---
name: Round 2 strategy analysis and theo_claude_test1
description: PnL drivers in Round 2, gap exploit mechanics, and theo_claude_test1 design decisions
type: project
---

IPR trends +1000pts/day (11K→14K over 3 days). Core strategy: buy 80 units ASAP, hold = ~80K/day.

Gap scout mechanic: when at max position (>=78) and ask side is fragile (exactly 1 level), post passive SELL at `min(recent_asks[-6]) + 85`. Fills when a market trade sweeps to that price at the same tick. Then gap_rebuy_mode triggers on a 20-tick pullback.

ACO is mean-reverting (~10000, ±15pts/day). v7 ignored ACO completely = 0 PnL. Adding a penny-improve MM (bid at best_bid+1, ask at best_ask-1, size 10, inv management at ±15) generates ~14.7K/day purely from passive fills (16-tick spread).

**Why:** Empty-book gap fills at ±85 don't work for ACO (trade prices stay within 9979-10020, never reaching ±85 offsets).

**How to apply:**
- theo_claude_test1 = v7 IPR + ACO market maker = 282K (vs v7's 238K)
- gap_scout early window extended to 8500 (was 5200), new late window at 143K-145K
- gap_scout_size_limit raised from 5 to 7
- MAF bid raised to 500 for extra market access

theo_tester_round_2 (2026-04-18): PEPPER_ROOT-only variant built on v12. Generalizes the one-sided-book pattern (v2/v4/v6/v7 PnL spikes all came from ask-side or bid-side becoming empty/fragile, not specific timestamps). Adds symmetric bid-side gap scout (`gap_buy_scout_*` params) mirroring the ask-side scout. Local backtest 238,014 = v12 parity (bid scout only fires on live IMC fragile-bid events). Buy-cap bookkeeping: gap_buy_scout_size uses `buy_cap - buy_size - anchor_buy_size` remaining to prevent cannibalising passive build orders.
