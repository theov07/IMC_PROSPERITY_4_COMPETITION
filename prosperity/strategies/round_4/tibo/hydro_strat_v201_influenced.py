"""HYDROGEL_PACK market maker — v201 influenced (self-contained).

Full v200 guard + AR logic with a Mark 14 informed-trader gate wired in.
Inherits only from BaseStrategy; all MM logic is self-contained here.

Strategy flow (each tick):
  1. Read Mark 14's net direction from state.market_trades (T-1 data):
       signal = +1 net-bought, -1 net-sold, 0 silent
  2. Run the full v200 guard + AR + taker + gap MM pipeline
  3. Apply the gate on the resulting order list:
       signal > 0 → strip ask orders, scale bid sizes × mark14_agree_factor
       signal < 0 → strip bid orders, scale ask sizes × mark14_agree_factor
       signal == 0 → return orders unchanged

Guard logic (from v200):
  Guard ON  (price reverting toward anchor_price=10000):
    - AR mean-reversion signal shifts fair value toward anchor (ar_gain=0.2)
    - Taker orders fire when ask <= fair - take_edge
    - Gap exploit active
  Guard OFF (price trending away):
    - ar_gain → 0, take_edges → ∞ (pure passive penny-improve)

Key params:
  informed_trader_name   — counterparty to track (default "Mark 14")
  mark14_agree_factor    — size multiplier when agreeing (default 2.0)
  anchor_price           — fixed mean-reversion anchor (default 10000)
  ar_gain                — AR signal strength (default 0.2)
  guard_trend_alpha      — fast trend EMA alpha (default 0.45)
  guard_reversion_threshold — min reverting-force to enable guard (default 3.0)
  maker_size_base_pct    — base quote size as % of position limit (default 0.15)
  take_edge_lo / _hi     — vol-scaled taker edge bounds (default 0.3 / 0.8)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydroMMV201Influenced(BaseStrategy):

    # ── Mark 14 signal ────────────────────────────────────────────────────

    def _informed_signal(
        self, state: TradingState, memory: Dict[str, Any],
    ) -> int:
        """Return net direction Mark 14 traded last tick (+1, -1, or 0)."""
        trader = str(self.params.get("informed_trader_name", "Mark 14"))
        net = 0
        for trade in state.market_trades.get(self.product, []):
            if trade.buyer == trader:
                net += trade.quantity
            elif trade.seller == trader:
                net -= trade.quantity
        signal = 1 if net > 0 else (-1 if net < 0 else 0)
        memory["_m14_signal"]  = signal
        memory["_m14_net_vol"] = net
        return signal

    def _apply_gate(
        self,
        orders: List[Order],
        signal: int,
        position: int,
    ) -> List[Order]:
        """Strip opposing orders and scale agreeing orders by mark14_agree_factor."""
        if signal == 0:
            return orders
        factor = float(self.params.get("mark14_agree_factor", 2.0))
        if signal > 0:
            cap = self.buy_capacity(position)
            return [
                Order(self.product, o.price,
                      min(cap, max(1, int(o.quantity * factor))))
                for o in orders if o.quantity > 0
            ]
        else:
            cap = self.sell_capacity(position)
            return [
                Order(self.product, o.price,
                      -min(cap, max(1, int(abs(o.quantity) * factor))))
                for o in orders if o.quantity < 0
            ]

    # ── Guard (v200 logic) ────────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        signal = self._informed_signal(state, memory)

        mid    = book.mid_price
        anchor = self.params.get("anchor_price")
        if mid is None or anchor is None:
            orders, conv = self._core_compute_orders(
                state, book, order_depth, position, memory)
            return self._apply_gate(orders, signal, position), conv

        use_anchor = self._use_anchor(float(mid), float(anchor), position, memory)
        memory["_guard_use_anchor"] = int(use_anchor)

        if use_anchor:
            orders, conv = self._core_compute_orders(
                state, book, order_depth, position, memory)
        else:
            old_anchor  = self.params.get("anchor_price")
            old_ar      = self.params.get("ar_gain")
            old_take_lo = self.params.get("take_edge_lo")
            old_take_hi = self.params.get("take_edge_hi")
            try:
                self.params["anchor_price"] = None
                self.params["ar_gain"]      = 0.0
                self.params["take_edge_lo"] = 1_000_000.0
                self.params["take_edge_hi"] = 1_000_000.0
                orders, conv = self._core_compute_orders(
                    state, book, order_depth, position, memory)
            finally:
                self.params["anchor_price"] = old_anchor
                self.params["ar_gain"]      = old_ar
                self.params["take_edge_lo"] = old_take_lo
                self.params["take_edge_hi"] = old_take_hi

        return self._apply_gate(orders, signal, position), conv

    def _use_anchor(
        self, mid: float, anchor: float, position: int, memory: Dict[str, Any],
    ) -> bool:
        prev_mid  = memory.get("_guard_prev_mid")
        memory["_guard_prev_mid"] = mid
        raw_trend = 0.0 if prev_mid is None else mid - float(prev_mid)

        alpha = float(self.params.get("guard_trend_alpha", 0.3))
        trend = float(memory.get("_guard_trend_ema", raw_trend))
        trend = alpha * raw_trend + (1.0 - alpha) * trend
        memory["_guard_trend_ema"] = trend

        dist = mid - anchor
        memory["_guard_dist"]  = dist
        memory["_guard_trend"] = trend

        near_band      = float(self.params.get("guard_near_band", 0.0))
        min_dist       = float(self.params.get("guard_min_dist", 0.0))
        max_dist       = float(self.params.get("guard_max_dist", 80.0))
        threshold      = float(self.params.get("guard_reversion_threshold", 0.0))
        inventory_dist = float(self.params.get("guard_inventory_dist", 40.0))

        near_anchor = abs(dist) <= near_band
        reverting   = min_dist <= abs(dist) <= max_dist and (dist * trend) <= -threshold
        wrong_way   = (position > 0 and dist < -inventory_dist) or (
                       position < 0 and dist > inventory_dist)

        return (near_anchor or reverting) and not wrong_way

    # ── Core MM pipeline (v200 logic) ─────────────────────────────────────

    def _core_compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None and book.best_ask is None:
            if memory.get("_last_mid") is None:
                return [], 0
        raw_mid = book.mid_price
        if raw_mid is None and book.best_bid is not None:
            raw_mid = float(book.best_bid)
        if raw_mid is None and book.best_ask is not None:
            raw_mid = float(book.best_ask)
        mid = raw_mid if raw_mid is not None else memory["_last_mid"]
        if raw_mid is not None:
            memory["_last_mid"] = raw_mid

        mid_smooth = self._smooth_mid(mid, memory)
        self._compute_zscore(mid, memory)
        sigma = self._update_volatility(mid, memory)

        fair_value = self._compute_anchor_signal(mid, mid_smooth, memory)
        fair_value = self._apply_inventory_bias(fair_value, position, memory)

        limit    = self.position_limit()
        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        bid_price = (book.best_bid + 1) if book.best_bid is not None else None
        ask_price = (book.best_ask - 1) if book.best_ask is not None else None

        bid_size, ask_size = self._compute_sizes(position, limit)
        bid_factor, ask_factor = self._zscore_size_factors(memory)
        bid_size = max(0.0, bid_size * bid_factor)
        ask_size = max(0.0, ask_size * ask_factor)

        base_edge           = self._dynamic_take_edge(memory)
        buy_edge, sell_edge = self._compute_asym_take_edges(base_edge, position)

        taker_orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px = self._fire_takers(
            order_depth, fair_value, bid_size, ask_size, buy_cap, sell_cap, buy_edge, sell_edge,
        )

        gap_orders, buy_cap, sell_cap, bid_price, ask_price = self._gap_exploit(
            order_depth, memory, limit, bid_size, ask_size,
            bid_price, ask_price, buy_cap, sell_cap, taker_buy_px, taker_sell_px,
        )

        bid_price, ask_price = self._asym_passive_skew(bid_price, ask_price, position, book)
        bid_size, ask_size   = self._apply_toxic_flow(state, memory, bid_size, ask_size)

        passive_orders, _, _ = self._passive_quotes(
            bid_price, ask_price, bid_size, ask_size, buy_cap, sell_cap, position, limit,
        )

        if book.best_bid is not None:
            memory["_prev_best_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_prev_best_ask"] = book.best_ask

        self._log_taker_fills(state, memory, taker_buy_px, taker_sell_px)
        z = memory.get("zscore")
        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=bid_price, ask_price=ask_price,
            extras={
                "position":   position,
                "fair":       round(fair_value, 2),
                "buy_edge":   round(buy_edge, 2),
                "sell_edge":  round(sell_edge, 2),
                "bid_size":   int(bid_size),
                "ask_size":   int(ask_size),
                "zscore":     round(z, 4) if z is not None else None,
                "sigma":      round(sigma, 4),
                "guard_on":   memory.get("_guard_use_anchor", 1),
                "m14_signal": memory.get("_m14_signal", 0),
            },
        )

        return taker_orders + gap_orders + passive_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("mid_smoothed"))     is not None: out["MidSmooth"]  = float(m)
        if (a := memory.get("_anchor_ema"))       is not None: out["AnchorEMA"]  = float(a)
        if (z := memory.get("zscore"))            is not None: out["Z"]          = float(z)
        if (d := memory.get("_guard_dist"))       is not None: out["GuardDist"]  = float(d)
        if (t := memory.get("_guard_trend"))      is not None: out["GuardTrend"] = float(t)
        if (u := memory.get("_guard_use_anchor")) is not None: out["GuardOn"]    = float(u)
        if (s := memory.get("_m14_signal"))       is not None: out["M14Signal"]  = float(s)
        if (v := memory.get("_m14_net_vol"))      is not None: out["M14NetVol"]  = float(v)
        return out

    # ── Anchor signal ─────────────────────────────────────────────────────

    def _compute_anchor_signal(
        self, mid: float, mid_smooth: float, memory: Dict[str, Any],
    ) -> float:
        anchor_price = self.params.get("anchor_price")
        if anchor_price is None:
            return mid_smooth
        anchor_fixed = float(anchor_price)
        anchor_alpha = float(self.params.get("anchor_alpha", 0.0))
        if anchor_alpha > 0.0:
            ema = memory.get("_anchor_ema", anchor_fixed)
            ema = anchor_alpha * mid + (1.0 - anchor_alpha) * ema
            drift_bound = float(self.params.get("anchor_drift_bound", 0.0))
            if drift_bound > 0:
                ema = max(anchor_fixed - drift_bound, min(anchor_fixed + drift_bound, ema))
            memory["_anchor_ema"] = ema
            anchor_value = ema
        else:
            anchor_value = anchor_fixed
        ar_gain  = float(self.params.get("ar_gain", 0.0))
        ar_shift = 0.0
        if ar_gain > 0.0:
            source  = str(self.params.get("ar_shift_source", "mid"))
            current = mid_smooth if source == "mid_smooth" else mid
            prev    = memory.get("_ar_prev_signal")
            if prev is not None:
                ar_shift = -ar_gain * (current - float(prev))
            memory["_ar_prev_signal"] = current
        return anchor_value + ar_shift

    def _apply_inventory_bias(
        self, fair_value: float, position: int, memory: Dict[str, Any],
    ) -> float:
        gamma = float(self.params.get("inventory_aversion_gamma", 0.0))
        if gamma <= 0 or position == 0:
            return fair_value
        sigma = memory.get("sigma_smoothed", 1.0)
        return fair_value - gamma * position * (sigma ** 2)

    # ── Sizing ────────────────────────────────────────────────────────────

    def _compute_sizes(self, position: int, limit: int) -> Tuple[float, float]:
        base = float(self.params.get("maker_size_base_pct", 0.2)) * limit
        return base * (1.0 - position / limit), base * (1.0 + position / limit)

    def _zscore_size_factors(self, memory: Dict[str, Any]) -> Tuple[float, float]:
        z = memory.get("zscore")
        if z is None:
            return 1.0, 1.0
        threshold  = float(self.params.get("zscore_threshold", 1.0))
        size_scale = float(self.params.get("zscore_size_scale", 0.5))
        max_scale  = float(self.params.get("zscore_max_scale", 3.0))
        excess = max(0.0, abs(z) - threshold)
        scale  = min(max_scale, 1.0 + size_scale * excess)
        if z > threshold:
            return 1.0 / scale, scale
        if z < -threshold:
            return scale, 1.0 / scale
        return 1.0, 1.0

    # ── Take edge ─────────────────────────────────────────────────────────

    def _dynamic_take_edge(self, memory: Dict[str, Any]) -> float:
        lo = self.params.get("take_edge_lo")
        hi = self.params.get("take_edge_hi")
        if lo is None or hi is None:
            return float(self.params.get("take_edge", 1.0))
        sigma = memory.get("sigma_smoothed")
        if sigma is None:
            return float(lo)
        vol_lo = float(self.params.get("take_edge_vol_lo", 2.0))
        vol_hi = float(self.params.get("take_edge_vol_hi", 5.0))
        if sigma <= vol_lo:
            return float(lo)
        if sigma >= vol_hi:
            return float(hi)
        t = (sigma - vol_lo) / (vol_hi - vol_lo)
        return float(lo) + t * (float(hi) - float(lo))

    def _compute_asym_take_edges(
        self, base_edge: float, position: int,
    ) -> Tuple[float, float]:
        unwind = float(self.params.get("unwind_take_edge", 0.0))
        if unwind <= 0:
            return base_edge, base_edge
        limit    = self.position_limit()
        pressure = abs(position) / max(1.0, float(limit))
        if position > 0:
            return base_edge + unwind * pressure, max(0.0, base_edge - unwind * pressure)
        if position < 0:
            return max(0.0, base_edge - unwind * pressure), base_edge + unwind * pressure
        return base_edge, base_edge

    # ── Z-score ───────────────────────────────────────────────────────────

    def _compute_zscore(self, mid: float, memory: Dict[str, Any]) -> Optional[float]:
        window = int(self.params.get("zscore_window", 50))
        buf: List[float] = memory.setdefault("_zscore_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            memory["zscore"] = None
            return None
        n    = len(buf)
        mean = sum(buf) / n
        var  = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std  = var ** 0.5
        if std < 1e-9:
            memory["zscore"] = None
            return None
        z = (mid - mean) / std
        memory["zscore"]   = z
        memory["_zs_mean"] = mean
        memory["_zs_std"]  = std
        return z

    # ── Taker orders ──────────────────────────────────────────────────────

    def _fire_takers(
        self,
        order_depth: OrderDepth,
        fair_value: float,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        buy_edge: float,
        sell_edge: float,
    ) -> Tuple[List[Order], int, int, Set[int], Set[int]]:
        taker_buy_threshold  = self.params.get("taker_buy_threshold")
        taker_sell_threshold = self.params.get("taker_sell_threshold")
        orders: List[Order] = []
        taker_buy_px:  Set[int] = set()
        taker_sell_px: Set[int] = set()

        for ask_p in sorted(order_depth.sell_orders):
            available  = -order_depth.sell_orders[ask_p]
            mid_signal = ask_p <= fair_value - buy_edge
            abs_signal = taker_buy_threshold is not None and ask_p <= taker_buy_threshold
            if not (mid_signal or abs_signal) or buy_cap <= 0:
                break
            qty = min(available, buy_cap, int(bid_size * 0.3))
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                taker_buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            volume     = order_depth.buy_orders[bid_p]
            mid_signal = bid_p >= fair_value + sell_edge
            abs_signal = taker_sell_threshold is not None and bid_p >= taker_sell_threshold
            if not (mid_signal or abs_signal) or sell_cap <= 0:
                break
            qty = min(volume, sell_cap, int(ask_size * 0.3))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                taker_sell_px.add(bid_p)
                sell_cap -= qty

        return orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px

    # ── Gap exploit ───────────────────────────────────────────────────────

    def _gap_exploit(
        self,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        limit: int,
        bid_size: float,
        ask_size: float,
        bid_price: Optional[int],
        ask_price: Optional[int],
        buy_cap: int,
        sell_cap: int,
        taker_buy_px: Set[int],
        taker_sell_px: Set[int],
    ) -> Tuple[List[Order], int, int, Optional[int], Optional[int]]:
        gap_min     = float(self.params.get("gap_trigger_min", 10))
        shift       = float(self.params.get("OB_cleared_shift", 10))
        gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.10))
        gap_max_vol = int(gap_vol_pct * limit) if limit else 0
        gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 1))

        z        = memory.get("zscore")
        gap_gate = float(self.params.get("zscore_gap_gate",
                         self.params.get("zscore_threshold", 1.0)))
        bid_z_ok = z is None or z >= -gap_gate
        ask_z_ok = z is None or z <=  gap_gate

        orders: List[Order] = []
        memory["_gap_buy_px"]  = []
        memory["_gap_sell_px"] = []

        all_bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        all_asks = sorted(order_depth.sell_orders.keys())
        if all_bids:
            memory["_last_best_bid"] = all_bids[0]
        if all_asks:
            memory["_last_best_ask"] = all_asks[0]
        last_best_bid = memory.get("_last_best_bid")
        last_best_ask = memory.get("_last_best_ask")

        remaining_bids = [p for p in all_bids if p not in taker_sell_px]
        remaining_asks = [p for p in all_asks if p not in taker_buy_px]
        gap_swept_bids: Set[int] = set()
        gap_swept_asks: Set[int] = set()

        if gap_min > 0 and gap_max_vol > 0:
            bid_gap_ok = False
            bid1 = bid2 = bid1_vol = None
            if len(remaining_bids) >= 2:
                bid1, bid2 = remaining_bids[0], remaining_bids[1]
                bid1_vol   = order_depth.buy_orders[bid1]
                bid_gap_ok = (bid1 - bid2) >= gap_min and bid1_vol <= gap_max_vol
            bid_streak = memory.get("_gap_bid_streak", 0)
            bid_streak = bid_streak + 1 if bid_gap_ok else 0
            memory["_gap_bid_streak"] = bid_streak
            if bid_streak >= gap_confirm and bid_gap_ok and sell_cap > 0 and bid_z_ok:
                qty = min(bid1_vol, sell_cap, int(ask_size))
                if qty > 0:
                    orders.append(Order(self.product, bid1, -qty))
                    sell_cap -= qty
                    memory["_gap_sell_px"].append(bid1)
                    if qty >= bid1_vol:
                        gap_swept_bids.add(bid1)

            ask_gap_ok = False
            ask1 = ask2 = ask1_vol = None
            if len(remaining_asks) >= 2:
                ask1, ask2 = remaining_asks[0], remaining_asks[1]
                ask1_vol   = -order_depth.sell_orders[ask1]
                ask_gap_ok = (ask2 - ask1) >= gap_min and ask1_vol <= gap_max_vol
            ask_streak = memory.get("_gap_ask_streak", 0)
            ask_streak = ask_streak + 1 if ask_gap_ok else 0
            memory["_gap_ask_streak"] = ask_streak
            if ask_streak >= gap_confirm and ask_gap_ok and buy_cap > 0 and ask_z_ok:
                qty = min(ask1_vol, buy_cap, int(bid_size))
                if qty > 0:
                    orders.append(Order(self.product, ask1, qty))
                    buy_cap -= qty
                    memory["_gap_buy_px"].append(ask1)
                    if qty >= ask1_vol:
                        gap_swept_asks.add(ask1)

        final_bids = [p for p in remaining_bids if p not in gap_swept_bids]
        final_asks = [p for p in remaining_asks if p not in gap_swept_asks]
        if final_asks:
            ask_price = final_asks[0] - 1
        elif last_best_ask is not None:
            ask_price = last_best_ask + int(shift)
        if final_bids:
            bid_price = final_bids[0] + 1
        elif last_best_bid is not None:
            bid_price = last_best_bid - int(shift)

        return orders, buy_cap, sell_cap, bid_price, ask_price

    # ── Passive quoting ───────────────────────────────────────────────────

    def _asym_passive_skew(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        position: int,
        book: BookSnapshot,
    ) -> Tuple[Optional[int], Optional[int]]:
        skew_max = int(self.params.get("passive_unwind_skew_ticks", 0))
        if skew_max <= 0 or bid_price is None or ask_price is None:
            return bid_price, ask_price
        if book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price
        trigger  = float(self.params.get("passive_unwind_trigger", 0.3))
        limit    = self.position_limit()
        pressure = abs(position) / max(1.0, float(limit))
        if pressure < trigger:
            return bid_price, ask_price
        scaled = (pressure - trigger) / max(1e-9, 1.0 - trigger)
        skew   = int(round(skew_max * scaled))
        if skew <= 0:
            return bid_price, ask_price
        if position > 0:
            ask_price = max(book.best_bid + 1, ask_price - skew)
        elif position < 0:
            bid_price = min(book.best_ask - 1, bid_price + skew)
        return bid_price, ask_price

    def _passive_quotes(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        position: int,
        limit: int,
    ) -> Tuple[List[Order], int, int]:
        quote_buy  = min(buy_cap,  int(bid_size))
        quote_sell = min(sell_cap, int(ask_size))
        inv_abs    = abs(position) / float(limit) if limit else 0.0
        hard_stop  = 1.0 - float(self.params.get("pct_kept_for_takers", 0.2))
        if inv_abs >= hard_stop:
            if position > 0:
                quote_buy  = 0
            elif position < 0:
                quote_sell = 0
        orders: List[Order] = []
        if quote_buy > 0 and bid_price is not None:
            orders.append(Order(self.product, bid_price,  quote_buy))
        if quote_sell > 0 and ask_price is not None:
            orders.append(Order(self.product, ask_price, -quote_sell))
        return orders, buy_cap - quote_buy, sell_cap - quote_sell

    # ── Toxic flow ────────────────────────────────────────────────────────

    def _apply_toxic_flow(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        buy_size: float,
        sell_size: float,
    ) -> Tuple[float, float]:
        toxic_threshold = float(self.params.get("toxic_threshold", 0.0))
        if toxic_threshold <= 0:
            return buy_size, sell_size
        toxic_window    = int(self.params.get("toxic_window", 6))
        toxic_size_frac = float(self.params.get("toxic_size_frac", 0.75))
        flow_history    = memory.setdefault("_flow_history", [])
        prev_best_bid   = memory.get("_prev_best_bid")
        prev_best_ask   = memory.get("_prev_best_ask")
        if toxic_window > 0 and prev_best_bid is not None and prev_best_ask is not None:
            for trade in state.market_trades.get(self.product, []):
                if trade.price >= prev_best_ask:
                    flow_history.append(trade.quantity)
                elif trade.price <= prev_best_bid:
                    flow_history.append(-trade.quantity)
            if len(flow_history) > toxic_window:
                del flow_history[:-toxic_window]
        flow_score = 0.0
        if flow_history:
            signed = sum(flow_history)
            total  = sum(abs(x) for x in flow_history)
            if total > 0:
                flow_score = signed / total
        memory["_flow_score"] = flow_score
        if flow_score > toxic_threshold and sell_size > 0:
            sell_size = max(1.0, sell_size * toxic_size_frac)
        elif flow_score < -toxic_threshold and buy_size > 0:
            buy_size = max(1.0, buy_size * toxic_size_frac)
        return buy_size, sell_size

    # ── Taker fill logging ────────────────────────────────────────────────

    def _log_taker_fills(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        this_taker_buy_px: Set[int],
        this_taker_sell_px: Set[int],
    ) -> None:
        prev_taker_buy_px  = set(memory.get("_taker_buy_px", []))
        prev_taker_sell_px = set(memory.get("_taker_sell_px", []))
        prev_gap_buy_px    = set(memory.get("_gap_buy_px_prev", []))
        prev_gap_sell_px   = set(memory.get("_gap_sell_px_prev", []))
        memory["_taker_buy_px"]     = list(this_taker_buy_px)
        memory["_taker_sell_px"]    = list(this_taker_sell_px)
        memory["_gap_buy_px_prev"]  = list(memory.get("_gap_buy_px", []))
        memory["_gap_sell_px_prev"] = list(memory.get("_gap_sell_px", []))
        for trade in state.own_trades.get(self.product, []):
            if trade.buyer == "SUBMISSION":
                side, is_taker = "BUY",  trade.price in prev_taker_buy_px
            else:
                side, is_taker = "SELL", trade.price in prev_taker_sell_px
            if not is_taker:
                continue
            is_gap = (
                (side == "BUY"  and trade.price in prev_gap_buy_px)
                or (side == "SELL" and trade.price in prev_gap_sell_px)
            )
            self.log_taker_fill(
                state=state, memory=memory,
                side=side, price=trade.price, quantity=trade.quantity,
                gap_exploit=is_gap,
            )
