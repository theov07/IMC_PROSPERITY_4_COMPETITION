# R4 Live Insights — Hidden patterns that backtest doesn't show

Source: `R4_CHAMPION_v5` live + `R4_LIVE_ALPHA_PROBE` live + backtest D3 first 10%.

## TL;DR (3 insights)

1. **We phagocytose flow** — when we quote, Mark↔Mark trades drop -77% to -88%. Our quotes win priority over Mark 14/01/55 (concurrent MMs).

2. **Mark 14 + Mark 01 are "queue followers"** — they only trade when they win the queue. When we improve, they go silent. **They are NOT informed → fading them is correct**.

3. **Mark 49 amplifies sells when we bias UP** — our cp_bias UP raises bid → Mark 49 lifts higher → we accumulate short cheap → profit on downtrend.

## Volume comparison (VELVET, D3 first 10%)

| Régime | Mark↔Mark | Us-involved | Total qty |
|---|---:|---:|---:|
| Backtest D3 (no us) | 43 trades | 0 | 246 |
| Probe live (passive MM only) | **5 trades** | 36 | 228 |
| V5 live (full strat) | **10 trades** | 90 | 622 |

V5 generates 2.5x volume vs backtest because we trigger Mark 49 to sell more.

## Per-Mark behavior (VELVET buy/sell qty across regimes)

| Trader | BT (no us) | Probe | V5 | Interpretation |
|---|---|---|---|---|
| Mark 14 | 75 / 54 | **0 / 0** | 133 / 25 | Queue follower — silent when we improve |
| Mark 01 | 51 / 14 | **0 / 0** | 126 / 54 | Queue follower — silent when we improve |
| Mark 55 | 82 / 126 | 82 / 126 | 79 / 126 | High-vol taker — invariant to our presence |
| Mark 49 | 0 / 26 | 0 / 8 | **0 / 67** | Pure seller — amplifies under v5 (lift our raised bid) |
| Mark 22 | 0 / 26 | 0 / 26 | 0 / 23 | Pure seller — invariant |
| Mark 67 | 38 / 0 | 20 / 0 | 34 / 22 | Pure buyer — slightly reduced |

## PnL outcomes

| Strategy | Live PnL | Final Velvet pos | Mid drift D3 first 10% |
|---|---:|---:|---:|
| Probe (passive only) | +382 | +58 long | -42 (down) |
| V5 (full + cp_bias + OBI) | **+6,214** | -55 short | -42 (down) |
| Backtest v5 expectation | (+5,694 at ts=99900) | n/a | -42 |

V5 / Probe = **16x better PnL** despite same window. The cp_bias signal + OBI tilt successfully capture the crash by going short.

## Reactivity test (do Marks copy us?)

For each of our SUBMISSION buy/sell, we counted Mark trades in next 5 ticks (T+100..500).
**Result: no detectable copy-trading**. Marks don't react to our individual trades within 500 ticks.

But there's an INDIRECT effect: our quotes shape the mid price, and Marks respond to mid moves.

## Strategic implications

1. **cp_bias signal validated**: Mark 49 fade weight -0.8 captures real flow asymmetry.
2. **Backtest underestimates our market impact**: in backtest we get fills only when historical trades pass our quotes. In live, we displace concurrent MMs.
3. **Probe research is INSUFFICIENT for finding informed flow**: Mark 14/01 disappear under our passive bid because they lose queue. Need to be aggressive (or shifting prices like cp_bias does) to draw them out.
4. **Position-driven, not signal-driven**: v5's PnL came from ending up SHORT during the down move (-55 final pos), not from cp_bias direct edge per trade.

## Future angles

1. **Test cp_bias with INVERSE Mark 14 weight** (+0.5 instead of -0.5): if Mark 14 only trades when they win queue, maybe they're informed AT THAT MOMENT specifically. Worth testing.
2. **Build "shadow" strategy** that quotes 1 tick BEHIND Mark 14/01: be the second-in-queue, see if their fills correlate with future moves.
3. **Adaptive size**: when Mark 49 is selling heavily (volume spike), increase OUR bid size to accumulate more short.
4. **Look at HYDROGEL live data** (Tibo/Theo strategy) for any cross-product signal we missed.
