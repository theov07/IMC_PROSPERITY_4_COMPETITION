"""HYDROGEL_PACK — mv_v8: Hysteresis + inventory-skewed MM

Root cause of v7 live failure (confirmed from logs):
  - v7's anchor_limit=80 has zero hysteresis.
  - Pattern: MM buys 6 units (pos -80→-74), AR taker immediately re-sells 6
    (|pos|=74 < anchor_limit=80 AND dev=32 >> edge=15 → fires again).
  - Position oscillates between -74 and -86 for 53% of the session, paying
    spread both ways with zero net recovery. Final position: -91.

v8 fixes:

1. HYSTERESIS on AR taker (primary fix):
   Two separate thresholds for start/stop:
     ar_taker_stop_pct  (default 0.40 = 80u): taker DEACTIVATES when
       |position| >= stop. Won't fire again until recovery.
     ar_taker_start_pct (default 0.15 = 30u): taker REACTIVATES only when
       |position| < start.
   This gives 50-unit buffer between stop and restart, preventing the tight
   fight loop that destroyed v7.

2. INVENTORY SKEW on passive MM:
   When short, raise bid by floor(inv_skew_ticks × |pos/limit|) extra ticks
   above best_bid+1. When long, lower ask symmetrically. This makes the
   inventory-reducing side more competitive, speeding up recovery during trends.
   Default: inv_skew_ticks=8 → at pos=-80, bid is raised by 3 ticks.

3. Preserve v7's two-component architecture otherwise: AR taker for
   directional signal, passive bestquote MM for spread capture.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydroMVV8(BaseStrategy):

    # ── Fast EWMA mid ─────────────────────────────────────────────────────

    def _compute_fast_mid(self, mid: float, memory: Dict[str, Any]) -> float:
        hl = float(self.params.get("fast_mid_half_life", 5))
        alpha = 1.0 - 0.5 ** (1.0 / max(hl, 0.1))
        prev = float(memory.get("_fast_mid", mid))
        v = alpha * mid + (1.0 - alpha) * prev
        memory["_fast_mid"] = v
        return v

    # ── AR model (identical to v7) ────────────────────────────────────────

    def _update_slow_ar(
        self, raw_mid: float, position: int, memory: Dict[str, Any],
    ) -> Tuple[float, float, float, float]:
        ms_hl = float(self.params.get("mid_smooth_half_life", 20))
        ms_alpha = 1.0 - 0.5 ** (1.0 / ms_hl)
        prev_ms = memory.get("_mid_smooth")
        mid_s = raw_mid if prev_ms is None else ms_alpha * raw_mid + (1.0 - ms_alpha) * float(prev_ms)
        memory["_mid_smooth"] = mid_s

        anchor_price = float(self.params.get("anchor_price", 10000))
        anchor_alpha = float(self.params.get("anchor_alpha", 0.005))
        anchor_ema = float(memory.get("_anchor_ema", anchor_price))
        limit = self.position_limit()
        pos_thr = float(self.params.get("anchor_pos_threshold", 0.20))
        if limit > 0 and abs(position) < limit * pos_thr:
            anchor_ema = anchor_alpha * raw_mid + (1.0 - anchor_alpha) * anchor_ema
        memory["_anchor_ema"] = anchor_ema

        ar_hl = float(self.params.get("ar_smooth_half_life", 5))
        ar_alpha = 1.0 - 0.5 ** (1.0 / ar_hl)
        delta = 0.0 if prev_ms is None else mid_s - float(prev_ms)
        ar_mom = float(memory.get("_ar_momentum", 0.0))
        ar_mom = ar_alpha * delta + (1.0 - ar_alpha) * ar_mom
        memory["_ar_momentum"] = ar_mom

        ar_gain = float(self.params.get("ar_gain", 8.0))
        fair_value = anchor_ema - ar_gain * ar_mom
        memory["_fair_value"] = fair_value

        raw_dev = mid_s - fair_value
        dev_hl = float(self.params.get("dev_smooth_half_life", 5))
        dev_alpha = 1.0 - 0.5 ** (1.0 / dev_hl)
        dev_s = float(memory.get("_dev_smooth", raw_dev))
        dev_s = dev_alpha * raw_dev + (1.0 - dev_alpha) * dev_s
        memory["_dev_smooth"] = dev_s

        return fair_value, anchor_ema, ar_mom, dev_s

    # ── Taker gate (hysteresis + cooldown) ───────────────────────────────

    def _update_taker_gate(
        self, position: int, timestamp: int, memory: Dict[str, Any],
    ) -> Tuple[bool, bool]:
        """Returns (sell_taker_ok, buy_taker_ok).

        Two independent mechanisms:

        1. Hysteresis band (position-based):
           Sell taker deactivates when position <= -stop (default -80u).
           Re-activates only when position > -start (default -60u).
           Gap of 20u prevents the MM-vs-taker fight where 6u MM buys
           immediately enable 6u taker sells.

        2. Cooldown (time-based):
           After the taker fires, it cannot fire again for `cooldown_ticks`
           timestamps. Prevents tick-by-tick re-triggering even if the
           position briefly re-enters the hysteresis active band.
        """
        limit = self.position_limit()
        stop_pct  = float(self.params.get("ar_taker_stop_pct",  0.40))   # 80u
        start_pct = float(self.params.get("ar_taker_start_pct", 0.30))   # 60u
        cooldown  = int(self.params.get("taker_cooldown_ticks", 10))      # ticks
        stop  = int(stop_pct  * limit)
        start = int(start_pct * limit)

        sell_ok = bool(memory.get("_sell_taker_active", True))
        buy_ok  = bool(memory.get("_buy_taker_active",  True))

        # Short side hysteresis
        if sell_ok and position <= -stop:
            sell_ok = False
        elif not sell_ok and position > -start:
            sell_ok = True

        # Long side hysteresis (symmetric)
        if buy_ok and position >= stop:
            buy_ok = False
        elif not buy_ok and position < start:
            buy_ok = True

        # Cooldown gate (applied on top of hysteresis)
        if cooldown > 0:
            last_sell = int(memory.get("_sell_last_ts", -999999))
            last_buy  = int(memory.get("_buy_last_ts",  -999999))
            ts_increment = int(self.params.get("ts_increment", 100))
            ticks_since_sell = (timestamp - last_sell) // ts_increment
            ticks_since_buy  = (timestamp - last_buy)  // ts_increment
            if ticks_since_sell < cooldown:
                sell_ok = False
            if ticks_since_buy < cooldown:
                buy_ok = False

        memory["_sell_taker_active"] = sell_ok
        memory["_buy_taker_active"]  = buy_ok
        memory["_hysteresis_stop"]   = stop
        memory["_hysteresis_start"]  = start
        return sell_ok, buy_ok

    # ── AR takers with hysteresis gate ────────────────────────────────────

    def _ar_takers(
        self,
        order_depth: OrderDepth,
        fair_value: float,
        position: int,
        sell_ok: bool,
        buy_ok: bool,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, int, int]:
        take_edge = float(self.params.get("ar_taker_edge", 15.0))
        taker_size_pct = float(self.params.get("ar_taker_size_pct", 0.30))
        taker_size = max(1, int(taker_size_pct * self.position_limit()))

        orders: List[Order] = []
        bought = sold = 0

        if buy_ok:
            for ask_p in sorted(order_depth.sell_orders):
                if ask_p > fair_value - take_edge or buy_cap <= 0:
                    break
                avail = -order_depth.sell_orders[ask_p]
                qty = min(avail, buy_cap, taker_size)
                if qty > 0:
                    orders.append(Order(self.product, ask_p, qty))
                    buy_cap -= qty
                    bought += qty

        if sell_ok:
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if bid_p < fair_value + take_edge or sell_cap <= 0:
                    break
                avail = order_depth.buy_orders[bid_p]
                qty = min(avail, sell_cap, taker_size)
                if qty > 0:
                    orders.append(Order(self.product, bid_p, -qty))
                    sell_cap -= qty
                    sold += qty

        return orders, buy_cap, sell_cap, bought, sold

    # ── Inventory-skewed passive MM ───────────────────────────────────────

    def _mm_passive(
        self,
        book: BookSnapshot,
        position: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        """Bestquote MM with asymmetric inventory skew.

        When short (position < 0): raise bid by floor(inv_skew_ticks × |pos/limit|)
        ticks above best_bid+1. This makes bids more competitive during uptrends,
        capturing pullbacks faster. The ask side stays unaffected so we don't
        accidentally add to a short position.
        Symmetric logic when long.
        """
        limit = self.position_limit()
        base_size    = int(self.params.get("mm_base_size", 20))
        inv_skew_max = float(self.params.get("inv_skew_ticks", 8))

        inv_ratio = position / max(1, limit)  # in [-1, 1]
        bid_size = max(0, int(base_size * (1.0 - inv_ratio)))
        ask_size = max(0, int(base_size * (1.0 + inv_ratio)))

        # Asymmetric skew: only improve the inventory-reducing side
        if position < 0:
            skew = int(inv_skew_max * abs(inv_ratio))
            bid_px = (book.best_bid + 1 + skew) if book.best_bid is not None else None
            ask_px = (book.best_ask - 1)         if book.best_ask is not None else None
        elif position > 0:
            skew = int(inv_skew_max * abs(inv_ratio))
            bid_px = (book.best_bid + 1)         if book.best_bid is not None else None
            ask_px = (book.best_ask - 1 - skew)  if book.best_ask is not None else None
        else:
            bid_px = (book.best_bid + 1) if book.best_bid is not None else None
            ask_px = (book.best_ask - 1) if book.best_ask is not None else None

        # Prevent self-crossing (can happen when skew pushes bid up to ask)
        if bid_px is not None and ask_px is not None and bid_px >= ask_px:
            bid_px = book.best_bid if book.best_bid is not None else (ask_px - 1 if ask_px else None)
            if bid_px is not None and ask_px is not None and bid_px >= ask_px:
                bid_px = ask_px - 1

        bid_qty = min(bid_size, buy_cap)
        ask_qty = min(ask_size, sell_cap)

        orders: List[Order] = []
        if bid_qty > 0 and bid_px is not None:
            orders.append(Order(self.product, bid_px,  bid_qty))
        if ask_qty > 0 and ask_px is not None:
            orders.append(Order(self.product, ask_px, -ask_qty))

        return orders, bid_qty, ask_qty

    # ── Main entry ────────────────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        mid = book.mid_price
        if mid is None:
            return [], 0

        limit = self.position_limit()
        fast_mid = self._compute_fast_mid(float(mid), memory)
        fair_value, anchor_val, ar_mom, dev = self._update_slow_ar(float(mid), position, memory)

        sell_ok, buy_ok = self._update_taker_gate(position, state.timestamp, memory)

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        taker_orders, buy_cap, sell_cap, t_bought, t_sold = self._ar_takers(
            order_depth, fair_value, position, sell_ok, buy_ok, buy_cap, sell_cap,
        )

        # Record last fire timestamp for cooldown
        if t_sold > 0:
            memory["_sell_last_ts"] = state.timestamp
        if t_bought > 0:
            memory["_buy_last_ts"] = state.timestamp

        mm_orders, mm_bid_qty, mm_ask_qty = self._mm_passive(
            book, position, buy_cap, sell_cap,
        )

        all_orders = taker_orders + mm_orders

        stop  = int(float(self.params.get("ar_taker_stop_pct",  0.40)) * limit)
        start = int(float(self.params.get("ar_taker_start_pct", 0.15)) * limit)

        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":       position,
                "mid":            round(float(mid), 2),
                "fast_mid":       round(fast_mid, 2),
                "FairValue":      round(fair_value, 2),
                "Anchor":         round(anchor_val, 2),
                "DevSmooth":      round(dev, 3),
                "ar_mom":         round(ar_mom, 4),
                "sell_taker_ok":  int(sell_ok),
                "buy_taker_ok":   int(buy_ok),
                "taker_buy":      t_bought,
                "taker_sell":     t_sold,
                "mm_bid_qty":     mm_bid_qty,
                "mm_ask_qty":     mm_ask_qty,
                "hyst_stop":      stop,
                "hyst_start":     start,
            },
        )

        return all_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value"))          is not None: out["FairValue"]      = float(v)
        if (v := memory.get("_dev_smooth"))          is not None: out["DevSmooth"]      = float(v)
        if (v := memory.get("_anchor_ema"))          is not None: out["Anchor"]         = float(v)
        if (v := memory.get("_ar_momentum"))         is not None: out["ar_mom"]         = float(v)
        if (v := memory.get("_fast_mid"))            is not None: out["fast_mid"]       = float(v)
        if (v := memory.get("_sell_taker_active"))   is not None: out["sell_taker_ok"]  = float(v)
        if (v := memory.get("_buy_taker_active"))    is not None: out["buy_taker_ok"]   = float(v)
        if (v := memory.get("_hysteresis_stop"))     is not None: out["hyst_stop"]      = float(v)
        return out
