v1 → VELVETFRUIT MM only (+20,127)

Pure penny-improve market maker. You capture the spread (best_bid+1 / best_ask-1) ~333 trades/day. Inventory-adaptive sizing means you quote smaller on the side that would push you further into position. Grid search found `maker_size_base_pct=0.30` (conservative sizing) is optimal — you fill frequently at small size rather than rarely at large size.

No options, no signal. Pure passive spread capture.

v2 → adds 4 VEV option strikes (+36,366, +16k over v1)

Two distinct sources of edge:

VEV_4000 (+12,157): This is deep ITM (K=4000 vs spot≈5250). Its market spread is ~20 ticks. It behaves like a leveraged VELVETFRUIT position — the market makers on both sides are wide, so penny-improving earns a large spread per fill. The 333+ fills/day are small sizes but the spread is wide. This is pure spread capture, no directional bet. The `ask_offset=1` keeps it symmetric.

VEV_5200/5300/5400 (+4k combined): These are OTM calls (delta 0.3–0.65). The strategy posts a penny-improve bid but a wide ask (`ask_offset=10`) — so you almost never sell, you only buy. This passively accumulates a long call position. When VELVETFRUIT rises across the day, those calls gain MTM value. This is the long-vol overlay: you're not buying vol directly, you're letting the market sell calls to you at fair prices, and you benefit when the underlying moves.

VEV_5400 gets `prevent_crossing=True` because its spread is persistently 1-tick — without this, bid+1 = best_ask every tick, turning passive quotes into taker orders that fill at 300 units and creates large unhedged directional risk (-1,393 without it).

v3 (ask_adapt) → adds z-score sell signal (+48,922, +12k over v2)

Same accumulation as v2. The addition is a z-score on VELVETFRUIT spot (rolling 500-tick window) that adapts only the ask side of VEV_5200/5300/5400:

- `expensive` (z > threshold): tighten ask to best_ask - 1 — you're willing to sell calls at current price. This reduces your long call exposure when VELVETFRUIT is at a rolling high, locking in MTM gains before the expected mean-reversion.
- `cheap` (z < -threshold): widen ask by +5 extra — you hold your calls through the dip, not getting shaken out.
- `neutral`: same as v2 behavior.
One important clarification in your description: the "+12k gain comes from structural bid crossing" is not quite right. VEV_5200/5300 already cross on tight spreads in v2 (same prevent_crossing=False behavior). The +12k gain in v3 comes specifically from the ask_adapt sells — when VELVETFRUIT peaks on days 1 and 2, v3 sells some of the accumulated long calls at best_ask-1, capturing a few hundred PnL per event that v2 just holds through.

Quick summary table:

Version	Products	Key mechanism	3-day PnL
v1	VELVETFRUIT only	Spread capture MM	+20,127
v2	+ 4 VEV strikes	Wide spread ITM (VEV_4000) + long call accumulation	+36,366
v3 ask_adapt	same	+ sell calls at rolling highs, hold through dips	+48,922