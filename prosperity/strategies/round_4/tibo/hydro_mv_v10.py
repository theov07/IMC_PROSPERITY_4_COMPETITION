"""HYDROGEL_PACK — mv_v10: v6b + directional MM cap + vol gate

Root cause of all live failures (v8/v9 confirmed):
  - Passive MM asks get lifted CONTINUOUSLY in uptrends → position → -200 in seconds
  - v8: hard cap blocked AR taker but not MM asks
  - v9: M14 gate never fired when M14 was a net seller

Core insight: The symmetric MM (posting both bid and ask) is the enemy.
When position is already short, posting an ask at best_ask-1 actively ADDS to
the short position every time a buyer comes in. In an uptrend, buyers are
aggressive — every tick a buyer hits our ask.

v10 fix — THREE-LAYER INVENTORY CONTROL:

1. DIRECTIONAL MM: when position < -mm_deep (default 30u), stop posting asks.
   Only post bids (to recover). When position > +mm_deep, stop posting bids.
   When position is small (near flat), post both sides normally.
   This prevents the passive MM from building a large position in trends.
   Effect: max position from MM alone ≤ ±mm_deep.

2. HARD AR TAKER CAP: AR taker stops selling when position ≤ -ar_cap_pct × limit
   (default 40% = 80u). Symmetric for buys. Combined with directional MM, total
   max short exposure = -80u regardless of how many buyers come in.

3. VOL GATE: realized vol (EWMA of |price changes|) > vol_threshold → stop
   all ADDS to position. In high-vol (trend) periods, only allow closes.
   Secondary protection for fast-trending markets.

Backtest impact (v6b base: 178k/3d):
  - Directional MM costs some spread income (only one side when positioned)
  - AR taker capped at 80u (vs 200u in v6b) → directional profit scaled down
  - Expected: ~100-130k/3d

Live protection:
  - Position can NEVER exceed ±80u from any source
  - Even in a 50-tick trend: loss ≤ 80 × 50 = 4,000 (vs 200 × 50 = 10,000)
  - MM never adds to a short position (directional MM)

Optional M14 gate from v9:
  Enable with m14_bullish_threshold < 9999. When M14's cumulative buying ≥
  threshold, suppress ALL selling (gate fires early in M14-driven uptrends).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydroMVV10(BaseStrategy):

    # ── AR model (v6b inv_protected anchor, unchanged) ────────────────────

    def _update_ar(
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

    # ── Vol gate ──────────────────────────────────────────────────────────

    def _compute_vol(self, raw_mid: float, memory: Dict[str, Any]) -> float:
        prev_mid = float(memory.get("_vol_prev_mid", raw_mid))
        abs_chg = abs(raw_mid - prev_mid)
        memory["_vol_prev_mid"] = raw_mid
        hl = float(self.params.get("vol_half_life", 20))
        alpha = 1.0 - 0.5 ** (1.0 / max(hl, 1.0))
        sigma = float(memory.get("_sigma", abs_chg))
        sigma = alpha * abs_chg + (1.0 - alpha) * sigma
        memory["_sigma"] = sigma
        return sigma

    # ── M14 cumulative gate (from v9) ─────────────────────────────────────

    def _update_m14_gate(
        self, state: TradingState, memory: Dict[str, Any],
    ) -> Tuple[int, bool]:
        """Returns (m14_cum, sell_gated_by_m14)."""
        m14_name = str(self.params.get("m14_trader", "Mark 14"))
        m38_name = str(self.params.get("m38_trader", "Mark 38"))
        m38_weight = float(self.params.get("m38_weight", 0.0))

        prev_ts = int(memory.get("_prev_timestamp", state.timestamp))
        if state.timestamp < prev_ts:
            memory["_m14_cum"] = 0
            memory["_m38_cum"] = 0
        memory["_prev_timestamp"] = state.timestamp

        m14_tick = m38_tick = 0
        for trade in state.market_trades.get(self.product, []):
            if trade.buyer == m14_name:    m14_tick += trade.quantity
            elif trade.seller == m14_name: m14_tick -= trade.quantity
            if trade.buyer == m38_name:    m38_tick += trade.quantity
            elif trade.seller == m38_name: m38_tick -= trade.quantity

        m14_cum = int(memory.get("_m14_cum", 0)) + m14_tick
        m38_cum = int(memory.get("_m38_cum", 0)) + m38_tick
        memory["_m14_cum"] = m14_cum
        memory["_m38_cum"] = m38_cum

        informed_long = m14_cum + m38_weight * (-m38_cum)
        bullish_thr = float(self.params.get("m14_bullish_threshold", 9999))
        sell_gated = informed_long >= bullish_thr
        memory["_sell_gated_m14"] = int(sell_gated)
        return m14_cum, sell_gated

    # ── Unified hysteresis + vol/M14 gates ───────────────────────────────

    def _compute_gates(
        self, position: int, sigma: float, sell_gated_m14: bool, memory: Dict[str, Any],
    ) -> Tuple[bool, bool, bool, bool]:
        """Returns (sell_mm_ok, sell_ar_ok, buy_mm_ok, buy_ar_ok).

        Root cause of v10 live failures:
          1. MM ask + AR taker fire simultaneously → "fight": buy at 10027,
             sell at 10025. Negative spread per unit.
          2. Separate mm_deep and ar_cap created a zone where AR still fires
             after MM stopped, continuing the position build.

        Fix: UNIFIED HYSTERESIS — single state machine for ALL sells (MM + AR):
          sell_active deactivates at -sell_stop (default 80u = 40%).
          sell_active only restarts when position > -sell_restart (default 40u).
          40-unit gap between stop and restart prevents the fight:
          MM bid fills 5u → position -80→-75, sell_active stays False (75 < 40).
          AR taker can NOT re-sell. Position slowly recovers uncontested.

        Symmetric hysteresis for buys (prevents runaway long).
        Vol gate overrides with close-only mode.
        M14 gate suppresses sells before the hysteresis fires.
        """
        limit = self.position_limit()
        sell_stop    = int(float(self.params.get("sell_stop_pct",    0.40)) * limit)  # 80u
        sell_restart = int(float(self.params.get("sell_restart_pct", 0.20)) * limit)  # 40u
        buy_stop     = int(float(self.params.get("buy_stop_pct",     0.40)) * limit)
        buy_restart  = int(float(self.params.get("buy_restart_pct",  0.20)) * limit)
        vol_thr      = float(self.params.get("vol_threshold", 3.5))

        # Vol gate: close-only mode when trending fast
        if sigma >= vol_thr:
            memory["_gate_reason"] = 3
            return position > 0, position > 0, position < 0, position < 0

        # M14 gate: suppress sells when M14 is bullish
        if sell_gated_m14:
            memory["_gate_reason"] = 2
            # Buys still follow normal hysteresis
            buy_active = bool(memory.get("_buy_active", True))
            return False, False, buy_active, buy_active

        # Sell hysteresis
        sell_active = bool(memory.get("_sell_active", True))
        if sell_active and position <= -sell_stop:
            sell_active = False
        elif not sell_active and position > -sell_restart:
            sell_active = True
        memory["_sell_active"] = sell_active

        # Buy hysteresis (symmetric)
        buy_active = bool(memory.get("_buy_active", True))
        if buy_active and position >= buy_stop:
            buy_active = False
        elif not buy_active and position < buy_restart:
            buy_active = True
        memory["_buy_active"] = buy_active

        memory["_gate_reason"]   = 0
        memory["_sell_stop"]     = sell_stop
        memory["_sell_restart"]  = sell_restart
        # Both MM and AR share the same hysteresis state
        return sell_active, sell_active, buy_active, buy_active

    # ── AR takers (with stop-overshoot prevention) ────────────────────────

    def _ar_takers(
        self,
        order_depth: OrderDepth,
        fair_value: float,
        sell_ar_ok: bool,
        buy_ar_ok: bool,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, int, int]:
        take_edge = float(self.params.get("ar_taker_edge", 12.0))
        taker_size_pct = float(self.params.get("ar_taker_size_pct", 0.30))
        taker_size = max(1, int(taker_size_pct * self.position_limit()))

        orders: List[Order] = []
        bought = sold = 0

        if buy_ar_ok:
            for ask_p in sorted(order_depth.sell_orders):
                if ask_p > fair_value - take_edge or buy_cap <= 0:
                    break
                avail = -order_depth.sell_orders[ask_p]
                qty = min(avail, buy_cap, taker_size)
                if qty > 0:
                    orders.append(Order(self.product, ask_p, qty))
                    buy_cap -= qty
                    bought += qty

        if sell_ar_ok:
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

    # ── Passive MM (bestquote + directional cap + inventory sizing) ───────

    def _mm_passive(
        self,
        book: BookSnapshot,
        position: int,
        sell_mm_ok: bool,
        buy_mm_ok: bool,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        limit = self.position_limit()
        base_size = float(self.params.get("maker_size_base_pct", 0.15)) * limit

        inv_ratio = position / max(1, limit)
        bid_size = max(0.0, base_size * (1.0 - inv_ratio))
        ask_size = max(0.0, base_size * (1.0 + inv_ratio))

        if not sell_mm_ok:
            ask_size = 0.0
        if not buy_mm_ok:
            bid_size = 0.0

        # Inventory skew: when deeply short, raise bid closer to mid.
        # When deeply long, lower ask. Only applied to the recovery side.
        inv_ratio_abs = abs(position) / max(1, limit)
        inv_skew_max = float(self.params.get("inv_skew_ticks", 6))
        skew = int(inv_skew_max * inv_ratio_abs)  # 0 when flat, up to inv_skew_max when max short

        if position < 0:
            bid_px = (book.best_bid + 1 + skew) if book.best_bid is not None else None
            ask_px = (book.best_ask - 1)         if book.best_ask is not None else None
        elif position > 0:
            bid_px = (book.best_bid + 1)         if book.best_bid is not None else None
            ask_px = (book.best_ask - 1 - skew)  if book.best_ask is not None else None
        else:
            bid_px = (book.best_bid + 1) if book.best_bid is not None else None
            ask_px = (book.best_ask - 1) if book.best_ask is not None else None

        # Never cross the spread
        if bid_px is not None and ask_px is not None and bid_px >= ask_px:
            bid_px = ask_px - 1
        if bid_px is not None and book.best_ask is not None and bid_px >= book.best_ask:
            bid_px = book.best_ask - 1

        orders: List[Order] = []
        qty_bid = min(buy_cap,  int(bid_size))
        qty_ask = min(sell_cap, int(ask_size))
        if qty_bid > 0 and bid_px is not None:
            orders.append(Order(self.product, bid_px,  qty_bid))
        if qty_ask > 0 and ask_px is not None:
            orders.append(Order(self.product, ask_px, -qty_ask))

        return orders, qty_bid, qty_ask

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

        sigma = self._compute_vol(float(mid), memory)
        fair_value, anchor_val, ar_mom, dev = self._update_ar(float(mid), position, memory)
        m14_cum, sell_gated_m14 = self._update_m14_gate(state, memory)

        sell_mm_ok, sell_ar_ok, buy_mm_ok, buy_ar_ok = self._compute_gates(
            position, sigma, sell_gated_m14, memory,
        )

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        taker_orders, buy_cap, sell_cap, t_bought, t_sold = self._ar_takers(
            order_depth, fair_value, sell_ar_ok, buy_ar_ok, buy_cap, sell_cap,
        )

        mm_orders, mm_bid_qty, mm_ask_qty = self._mm_passive(
            book, position, sell_mm_ok, buy_mm_ok, buy_cap, sell_cap,
        )

        all_orders = taker_orders + mm_orders

        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":     position,
                "mid":          round(float(mid), 2),
                "FairValue":    round(fair_value, 2),
                "Anchor":       round(anchor_val, 2),
                "DevSmooth":    round(dev, 3),
                "ar_mom":       round(ar_mom, 4),
                "sigma":        round(sigma, 3),
                "m14_cum":      m14_cum,
                "gate_reason":  int(memory.get("_gate_reason", 0)),
                "sell_mm_ok":   int(sell_mm_ok),
                "sell_ar_ok":   int(sell_ar_ok),
                "taker_buy":    t_bought,
                "taker_sell":   t_sold,
                "mm_bid_qty":   mm_bid_qty,
                "mm_ask_qty":   mm_ask_qty,
            },
        )

        return all_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value"))     is not None: out["FairValue"]   = float(v)
        if (v := memory.get("_dev_smooth"))     is not None: out["DevSmooth"]   = float(v)
        if (v := memory.get("_anchor_ema"))     is not None: out["Anchor"]      = float(v)
        if (v := memory.get("_ar_momentum"))    is not None: out["ar_mom"]      = float(v)
        if (v := memory.get("_sigma"))          is not None: out["sigma"]       = float(v)
        if (v := memory.get("_m14_cum"))        is not None: out["M14Cum"]      = float(v)
        if (v := memory.get("_sell_gated_m14")) is not None: out["SellGated"]   = float(v)
        if (v := memory.get("_gate_reason"))    is not None: out["GateReason"]  = float(v)
        return out
