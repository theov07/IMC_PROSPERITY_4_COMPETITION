─── INPUTS ────────────────────────────────────────────────────────────
  state.order_depth, position, memory (persists across ticks)

─── 1. MID PRICE ──────────────────────────────────────────────────────
  mid = book.mid_price (or best_bid/ask fallback)
  mid_smooth = EWMA(mid, window=50, half_life=10)   ← stored in memory
    └─ used as reference price for taker triggers (steps 3 & 4)

─── 2. QUOTE LEVEL SELECTION ──────────────────────────────────────────
  inv_ratio = position / limit

  if |inv_ratio| < inv_step_threshold (0.9):
    L1: bid_price = best_bid + 1  ← penny-improve both sides
        ask_price = best_ask - 1

  if inv_ratio >= +0.9 (very long):
    L2: bid_price = best_bid      ← join (don't improve) on the bid side
        ask_price = best_ask - 1  ← stay aggressive on ask (want to sell)

  if inv_ratio <= -0.9 (very short):
    L2: bid_price = best_bid + 1  ← stay aggressive on bid (want to buy)
        ask_price = best_ask      ← join on ask side

  → bid_price / ask_price are now set but NOT yet used (passive quoting is last)
  → Crossing prevention caps bid_price < best_ask and ask_price > best_bid

─── 3. CAPACITY & SIZES ───────────────────────────────────────────────
  buy_cap  = limit - position   (how many units we can still buy)
  sell_cap = limit + position   (how many units we can still sell)

  bid_size = base_size × (1 - position/limit)   ← shrinks when long
  ask_size = base_size × (1 + position/limit)   ← shrinks when short
    base_size = maker_size_base_pct × limit

  → These are shared by ALL order types below

─── 4. PRICE-SIGNAL TAKERS (mid_smooth OR absolute threshold) ─────────
  For each ask level (ascending):
    trigger if:  ask_p ≤ mid_smooth − take_edge   ← price is cheap vs fair
              OR ask_p ≤ taker_buy_threshold       ← absolute floor
    qty = min(available_at_level, buy_cap, int(bid_size × 0.3))
    → send aggressive BUY, deduct from buy_cap

  For each bid level (descending):
    trigger if:  bid_p ≥ mid_smooth + take_edge   ← price is rich vs fair
              OR bid_p ≥ taker_sell_threshold      ← absolute ceiling
    qty = min(volume_at_level, sell_cap, int(ask_size × 0.3))
    → send aggressive SELL, deduct from sell_cap

  KEY: buy_cap / sell_cap reduced → passive quote will be smaller

─── 5. GAP EXPLOIT TAKERS (structural signal) ─────────────────────────
  Runs on REMAINING buy_cap / sell_cap after step 4.

  Bid side (sell into thin L1):
    condition: (best_bid − 2nd_bid) ≥ gap_trigger_min (10)
           AND best_bid volume ≤ gap_trigger_max_vol_pct × limit (10%)
    persistence: condition must hold for gap_trigger_confirm_ticks (2)
                 consecutive ticks  ← stored in memory["_gap_bid_streak"]
    → if confirmed: send aggressive SELL for min(bid1_vol, sell_cap, int(ask_size))
    → deduct from sell_cap

  Ask side (buy into thin L1):
    symmetric logic → send aggressive BUY, deduct from buy_cap

  KEY: if L1 is cleared, next tick best_bid drops to L2.
       Normal passive quoting (step 6) will then bid at L2+1,
       capturing the gap spread from anyone who sells into us.

─── 6. PASSIVE QUOTING ────────────────────────────────────────────────
  quote_buy  = min(buy_cap,  int(bid_size))   ← capped by remaining capacity
  quote_sell = min(sell_cap, int(ask_size))

  Hard stop (inventory guard):
    if |position| / limit ≥ (1 − pct_kept_for_takers):
      position > 0 → quote_buy  = 0   ← don't add more longs at extreme
      position < 0 → quote_sell = 0   ← don't add more shorts at extreme

  → post Order(bid_price, +quote_buy)    ← price from step 2
  → post Order(ask_price, −quote_sell)   ← price from step 2

─── INTERACTIONS SUMMARY ──────────────────────────────────────────────
  Step 4 takers eat into buy_cap/sell_cap → step 6 passive is smaller
  Step 5 gap exploit eats further into remaining cap → step 6 even smaller
  Step 2 L2 stepping changes passive price, not size
  Hard stop (step 6) can zero out passive entirely at extreme inventory,
    preserving capacity for next-tick takers to unwind the position