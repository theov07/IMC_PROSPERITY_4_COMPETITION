"""MMFirstV4ComboStrategy and R3GuardedAnchorMMStrategy.

Ported verbatim from Theo's velvettuned_v7.py.

MMFirstV4ComboStrategy: full-featured market maker with:
  - Penny-improve L1 quoting
  - Anchor price + EMA drift + AR mean-reversion signal
  - Inventory-adaptive sizing + aversion bias
  - Dynamic take edge (vol-scaled)
  - Gap exploit (thin L1 + large gap to L2)
  - Toxic flow detection
  - Passive unwind skew
  - Spread widening / zscore skew
  - Momentum follower, fill-rate toxicity, EOD flatten

R3GuardedAnchorMMStrategy(MMFirstV4ComboStrategy):
  - Adds a "guard" that disables the AR signal and takers when price
    is trending away from anchor (prevents shorting a rally).
  - When guard is OFF: AR gain → 0, take edges → ∞ (passive only).
  - When guard is ON:  full strategy (AR signal + takers active).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class MMFirstV4ComboStrategy(BaseStrategy):

    def _compute_quote_prices(
        self,
        book: BookSnapshot,
        inventory_ratio: float,
        mid_smooth: float,
    ) -> Tuple[Optional[int], Optional[int], str]:
        bid_price = (book.best_bid + 1) if book.best_bid is not None else None
        ask_price = (book.best_ask - 1) if book.best_ask is not None else None
        return bid_price, ask_price, "L1"

    def _compute_zscore(self, mid: float, memory: Dict[str, Any]) -> Optional[float]:
        window = int(self.params.get("zscore_window", 50))
        buf: List[float] = memory.setdefault("_zscore_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            memory["zscore"] = None
            return None
        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std = var ** 0.5
        if std < 1e-9:
            memory["zscore"] = None
            return None
        z = (mid - mean) / std
        memory["zscore"] = z
        memory["_zs_mean"] = mean
        memory["_zs_std"] = std
        return z

    def _zscore_size_factors(self, memory: Dict[str, Any]) -> Tuple[float, float]:
        z = memory.get("zscore")
        if z is None:
            return 1.0, 1.0
        threshold = float(self.params.get("zscore_threshold", 1.0))
        size_scale = float(self.params.get("zscore_size_scale", 0.5))
        max_scale  = float(self.params.get("zscore_max_scale", 3.0))
        excess = max(0.0, abs(z) - threshold)
        scale  = min(max_scale, 1.0 + size_scale * excess)
        if z > threshold:
            return 1.0 / scale, scale
        if z < -threshold:
            return scale, 1.0 / scale
        return 1.0, 1.0

    def _compute_sizes(self, position: int, limit: int) -> Tuple[float, float]:
        base = float(self.params.get("maker_size_base_pct", 0.2)) * limit
        bid_size = base * (1.0 - position / limit)
        ask_size = base * (1.0 + position / limit)
        return bid_size, ask_size

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

    def _compute_anchor_signal(
        self,
        mid: float,
        book: BookSnapshot,
        mid_smooth: float,
        memory: Dict[str, Any],
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
                ema = max(anchor_fixed - drift_bound,
                          min(anchor_fixed + drift_bound, ema))
            memory["_anchor_ema"] = ema
            anchor_value = ema
        else:
            anchor_value = anchor_fixed
        ar_gain = float(self.params.get("ar_gain", 0.0))
        ar_shift = 0.0
        if ar_gain > 0.0:
            source = str(self.params.get("ar_shift_source", "mid"))
            if source == "microprice":
                current = self._microprice(book)
            elif source == "mid_smooth":
                current = mid_smooth
            else:
                current = mid
            prev = memory.get("_ar_prev_signal")
            if prev is not None:
                ar_shift = -ar_gain * (current - prev)
            memory["_ar_prev_signal"] = current
        return anchor_value + ar_shift

    def _compute_asym_take_edges(
        self,
        base_edge: float,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[float, float]:
        unwind = float(self.params.get("unwind_take_edge", 0.0))
        if unwind <= 0:
            return base_edge, base_edge
        limit = self.position_limit()
        pressure = abs(position) / max(1.0, float(limit))
        if position > 0:
            sell_edge = max(0.0, base_edge - unwind * pressure)
            buy_edge  = base_edge + unwind * pressure
        elif position < 0:
            buy_edge  = max(0.0, base_edge - unwind * pressure)
            sell_edge = base_edge + unwind * pressure
        else:
            return base_edge, base_edge
        return buy_edge, sell_edge

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
        z           = memory.get("zscore")
        gap_gate    = float(self.params.get("zscore_gap_gate",
                            self.params.get("zscore_threshold", 1.0)))
        bid_z_ok = z is None or z >= -gap_gate
        ask_z_ok = z is None or z <= gap_gate
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
        final_remaining_bids = [p for p in remaining_bids if p not in gap_swept_bids]
        final_remaining_asks = [p for p in remaining_asks if p not in gap_swept_asks]
        if final_remaining_asks:
            ask_price = final_remaining_asks[0] - 1
        elif last_best_ask is not None:
            ask_price = last_best_ask + int(shift)
        if final_remaining_bids:
            bid_price = final_remaining_bids[0] + 1
        elif last_best_bid is not None:
            bid_price = last_best_bid - int(shift)
        return orders, buy_cap, sell_cap, bid_price, ask_price

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
        flow_history = memory.setdefault("_flow_history", [])
        prev_best_bid = memory.get("_prev_best_bid")
        prev_best_ask = memory.get("_prev_best_ask")
        trades = state.market_trades.get(self.product, [])
        if toxic_window > 0 and prev_best_bid is not None and prev_best_ask is not None:
            for trade in trades:
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

    def _apply_jump_filter(
        self,
        book: BookSnapshot,
        memory: Dict[str, Any],
        buy_size: float,
        sell_size: float,
    ) -> Tuple[float, float]:
        threshold = float(self.params.get("trend_jump_threshold", 0.0))
        if threshold <= 0:
            return buy_size, sell_size
        jump_size_frac = float(self.params.get("jump_size_frac", 0.5))
        prev_best_bid  = memory.get("_prev_best_bid")
        prev_best_ask  = memory.get("_prev_best_ask")
        bid_jumped = prev_best_bid is not None and book.best_bid == prev_best_bid + 1
        ask_jumped = prev_best_ask is not None and book.best_ask == prev_best_ask - 1
        if bid_jumped and sell_size > 0:
            sell_size = max(1.0, sell_size * jump_size_frac)
        if ask_jumped and buy_size > 0:
            buy_size = max(1.0, buy_size * jump_size_frac)
        return buy_size, sell_size

    def _compute_base_mid(self, raw_mid: float, book: BookSnapshot) -> float:
        vol_filter = int(self.params.get("mid_vol_filter", 0))
        if vol_filter <= 0:
            return raw_mid
        wall_bid = wall_ask = None
        for (p, v) in book.bid_levels:
            if v >= vol_filter:
                wall_bid = p
                break
        for (p, v) in book.ask_levels:
            if v >= vol_filter:
                wall_ask = p
                break
        if wall_bid is None or wall_ask is None:
            return raw_mid
        return (wall_bid + wall_ask) / 2.0

    def _taker_cooldown_active(
        self,
        state: TradingState,
        memory: Dict[str, Any],
    ) -> Tuple[bool, bool]:
        cooldown = int(self.params.get("taker_cooldown_ticks", 0))
        if cooldown <= 0:
            return False, False
        now          = int(state.timestamp)
        ts_increment = int(self.params.get("ts_increment", 100))
        last_buy     = memory.get("_last_taker_buy_ts")
        last_sell    = memory.get("_last_taker_sell_ts")
        buy_blocked  = last_buy  is not None and (now - last_buy)  < cooldown * ts_increment
        sell_blocked = last_sell is not None and (now - last_sell) < cooldown * ts_increment
        return buy_blocked, sell_blocked

    def _update_taker_cooldown(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        taker_buy_px: Set[int],
        taker_sell_px: Set[int],
    ) -> None:
        now = int(state.timestamp)
        if taker_buy_px:
            memory["_last_taker_buy_ts"]  = now
        if taker_sell_px:
            memory["_last_taker_sell_ts"] = now

    def _apply_inventory_bias(
        self,
        fair_value: float,
        position: int,
        memory: Dict[str, Any],
    ) -> float:
        gamma = float(self.params.get("inventory_aversion_gamma", 0.0))
        if gamma <= 0 or position == 0:
            return fair_value
        sigma = memory.get("sigma_smoothed", 1.0)
        return fair_value - gamma * position * (sigma ** 2)

    def _microprice_size_tilt(
        self,
        book: BookSnapshot,
        raw_mid: float,
        bid_size: float,
        ask_size: float,
    ) -> Tuple[float, float]:
        gain = float(self.params.get("microprice_size_gain", 0.0))
        if gain <= 0:
            return bid_size, ask_size
        threshold = float(self.params.get("microprice_size_threshold", 0.2))
        micro = self._microprice(book)
        delta = micro - raw_mid
        if abs(delta) < threshold:
            return bid_size, ask_size
        scale = 1.0 + gain * (abs(delta) - threshold)
        if delta > 0:
            return bid_size / scale, ask_size * scale
        else:
            return bid_size * scale, ask_size / scale

    def _apply_spread_widening(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> Tuple[Optional[int], Optional[int]]:
        threshold = float(self.params.get("spread_widen_vol_threshold", 0.0))
        if threshold <= 0 or bid_price is None or ask_price is None:
            return bid_price, ask_price
        if book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price
        sigma = memory.get("sigma_smoothed", 0.0)
        if sigma < threshold:
            return bid_price, ask_price
        extra   = int(self.params.get("spread_widen_extra_ticks", 1))
        new_bid = max(1, bid_price - extra)
        new_ask = ask_price + extra
        if book.best_ask is not None:
            new_bid = min(new_bid, book.best_ask - 1)
        if book.best_bid is not None:
            new_ask = max(new_ask, book.best_bid + 1)
        return new_bid, new_ask

    def _effective_position(self, position: int) -> int:
        target = int(self.params.get("inventory_target", 0))
        return position - target

    def _apply_fill_rate_toxicity(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        bid_size: float,
        ask_size: float,
    ) -> Tuple[float, float]:
        window = int(self.params.get("fill_toxicity_window", 0))
        if window <= 0:
            return bid_size, ask_size
        history = memory.setdefault("_fill_history", [])
        for trade in state.own_trades.get(self.product, []):
            qty = float(trade.quantity)
            if trade.buyer == "SUBMISSION":
                history.append(qty)
            elif trade.seller == "SUBMISSION":
                history.append(-qty)
        if len(history) > window:
            del history[:-window]
        if not history:
            return bid_size, ask_size
        signed  = sum(history)
        total   = sum(abs(x) for x in history)
        if total <= 0:
            return bid_size, ask_size
        imbalance = signed / total
        threshold = float(self.params.get("fill_toxicity_threshold", 0.7))
        frac      = float(self.params.get("fill_toxicity_frac", 0.5))
        if imbalance > threshold and bid_size > 0:
            bid_size = max(1.0, bid_size * frac)
        elif imbalance < -threshold and ask_size > 0:
            ask_size = max(1.0, ask_size * frac)
        return bid_size, ask_size

    def _apply_spread_zscore_skew(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> Tuple[Optional[int], Optional[int]]:
        window = int(self.params.get("spread_zscore_window", 0))
        if window <= 0 or bid_price is None or ask_price is None:
            return bid_price, ask_price
        if book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price
        spread = book.best_ask - book.best_bid
        buf: List[float] = memory.setdefault("_spread_buf", [])
        buf.append(spread)
        if len(buf) > window:
            del buf[:-window]
        if len(buf) < max(10, window // 4):
            return bid_price, ask_price
        mean = sum(buf) / len(buf)
        var  = sum((x - mean) ** 2 for x in buf) / max(len(buf) - 1, 1)
        std  = var ** 0.5
        if std < 1e-9:
            return bid_price, ask_price
        z         = (spread - mean) / std
        threshold = float(self.params.get("spread_zscore_threshold", 1.5))
        if z < threshold:
            return bid_price, ask_price
        shift   = int(self.params.get("spread_zscore_shift", 1))
        new_bid = min(book.best_ask - 1, bid_price + shift)
        new_ask = max(book.best_bid + 1, ask_price - shift)
        if new_bid >= new_ask:
            new_ask = new_bid + 1
        return new_bid, new_ask

    def _probe_tick0(
        self,
        book: BookSnapshot,
        state: TradingState,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        distances = self.params.get("probe_t0_distances")
        if not distances or book.best_bid is None or book.best_ask is None:
            return [], buy_cap, sell_cap
        max_ts = int(self.params.get("probe_t0_max_ts", 500))
        now    = int(state.timestamp)
        if now > max_ts:
            return [], buy_cap, sell_cap
        if memory.get("_probe_t0_fired", False):
            return [], buy_cap, sell_cap
        qty    = int(self.params.get("probe_t0_qty", 1))
        orders: List[Order] = []
        for dist in distances:
            d = int(dist)
            if d <= 0:
                continue
            b_qty = min(qty, buy_cap)
            a_qty = min(qty, sell_cap)
            if b_qty > 0:
                orders.append(Order(self.product, book.best_bid - d, b_qty))
                buy_cap -= b_qty
            if a_qty > 0:
                orders.append(Order(self.product, book.best_ask + d, -a_qty))
                sell_cap -= a_qty
        if orders:
            memory["_probe_t0_fired"] = True
        return orders, buy_cap, sell_cap

    def _apply_momentum_follower(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        window = int(self.params.get("momentum_window", 0))
        if window <= 0:
            return [], buy_cap, sell_cap
        history   = memory.setdefault("_momentum_history", [])
        prev_bid  = memory.get("_prev_best_bid")
        prev_ask  = memory.get("_prev_best_ask")
        for trade in state.market_trades.get(self.product, []):
            qty = float(trade.quantity)
            if prev_ask is not None and trade.price >= prev_ask:
                history.append(qty)
            elif prev_bid is not None and trade.price <= prev_bid:
                history.append(-qty)
        if len(history) > window:
            del history[:-window]
        if not history:
            return [], buy_cap, sell_cap
        signed = sum(history)
        total  = sum(abs(x) for x in history)
        if total <= 0:
            return [], buy_cap, sell_cap
        flow      = signed / total
        threshold = float(self.params.get("momentum_threshold", 0.8))
        qty       = int(self.params.get("momentum_qty", 3))
        orders: List[Order] = []
        if flow > threshold and buy_cap > 0:
            asks = sorted(order_depth.sell_orders.keys())
            if asks:
                ask_p     = asks[0]
                available = -order_depth.sell_orders[ask_p]
                q = min(qty, buy_cap, available)
                if q > 0:
                    orders.append(Order(self.product, ask_p, q))
                    buy_cap -= q
        elif flow < -threshold and sell_cap > 0:
            bids = sorted(order_depth.buy_orders.keys(), reverse=True)
            if bids:
                bid_p  = bids[0]
                volume = order_depth.buy_orders[bid_p]
                q = min(qty, sell_cap, volume)
                if q > 0:
                    orders.append(Order(self.product, bid_p, -q))
                    sell_cap -= q
        return orders, buy_cap, sell_cap

    def _probe_quotes(
        self,
        book: BookSnapshot,
        state: TradingState,
        memory: Dict[str, Any],
        position: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        probe_dist = int(self.params.get("probe_distance", 0))
        if probe_dist <= 0 or book.best_bid is None or book.best_ask is None:
            return [], buy_cap, sell_cap
        probe_qty      = int(self.params.get("probe_qty", 1))
        probe_interval = int(self.params.get("probe_interval_ticks", 100))
        ts_increment   = int(self.params.get("ts_increment", 100))
        now            = int(state.timestamp)
        last_probe     = memory.get("_last_probe_ts", -(10 ** 9))
        if (now - last_probe) < probe_interval * ts_increment:
            return [], buy_cap, sell_cap
        orders: List[Order] = []
        actual_bid_qty = min(probe_qty, buy_cap)
        actual_ask_qty = min(probe_qty, sell_cap)
        if actual_bid_qty > 0:
            probe_bid = book.best_bid - probe_dist
            orders.append(Order(self.product, probe_bid, actual_bid_qty))
            buy_cap -= actual_bid_qty
        if actual_ask_qty > 0:
            probe_ask = book.best_ask + probe_dist
            orders.append(Order(self.product, probe_ask, -actual_ask_qty))
            sell_cap -= actual_ask_qty
        if orders:
            memory["_last_probe_ts"] = now
        return orders, buy_cap, sell_cap

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

    def _apply_eod_flatten(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        position: int,
    ) -> Optional[List[Order]]:
        eod_ts = int(self.params.get("eod_flatten_ts", 0))
        if eod_ts <= 0 or state.timestamp < eod_ts or position == 0:
            return None
        orders: List[Order] = []
        if position > 0:
            for bid_price in sorted(order_depth.buy_orders, reverse=True):
                vol = order_depth.buy_orders[bid_price]
                qty = min(vol, position)
                if qty <= 0:
                    break
                orders.append(Order(self.product, bid_price, -qty))
                position -= qty
                if position == 0:
                    break
        else:
            need = -position
            for ask_price in sorted(order_depth.sell_orders):
                vol = -order_depth.sell_orders[ask_price]
                qty = min(vol, need)
                if qty <= 0:
                    break
                orders.append(Order(self.product, ask_price, qty))
                need -= qty
                if need == 0:
                    break
        return orders

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
                quote_buy = 0
            elif position < 0:
                quote_sell = 0
        orders: List[Order] = []
        if quote_buy > 0 and bid_price is not None:
            orders.append(Order(self.product, bid_price, quote_buy))
        if quote_sell > 0 and ask_price is not None:
            orders.append(Order(self.product, ask_price, -quote_sell))
        return orders, buy_cap - quote_buy, sell_cap - quote_sell

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
        memory["_taker_buy_px"]      = list(this_taker_buy_px)
        memory["_taker_sell_px"]     = list(this_taker_sell_px)
        memory["_gap_buy_px_prev"]   = list(memory.get("_gap_buy_px", []))
        memory["_gap_sell_px_prev"]  = list(memory.get("_gap_sell_px", []))
        for trade in state.own_trades.get(self.product, []):
            if trade.buyer == "SUBMISSION":
                side, is_taker = "BUY", trade.price in prev_taker_buy_px
            else:
                side, is_taker = "SELL", trade.price in prev_taker_sell_px
            if is_taker:
                is_gap = (
                    (side == "BUY"  and trade.price in prev_gap_buy_px)
                    or (side == "SELL" and trade.price in prev_gap_sell_px)
                )
                self.log_taker_fill(
                    state=state, memory=memory,
                    side=side, price=trade.price, quantity=trade.quantity,
                    gap_exploit=is_gap,
                )

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if order_depth.buy_orders and order_depth.sell_orders:
            eod_orders = self._apply_eod_flatten(state, order_depth, position)
            if eod_orders is not None:
                return eod_orders, 0
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
        if self.params.get("use_microprice_as_fair", False):
            micro    = self._microprice(book)
            base_mid = micro if micro else mid
        else:
            base_mid = self._compute_base_mid(mid, book)
        mid_smooth = self._smooth_mid(base_mid, memory)
        self._compute_zscore(base_mid, memory)
        sigma      = self._update_volatility(base_mid, memory)
        fair_value = self._compute_anchor_signal(base_mid, book, mid_smooth, memory)
        eff_position = self._effective_position(position)
        fair_value   = self._apply_inventory_bias(fair_value, eff_position, memory)
        limit         = self.position_limit()
        inventory_ratio = position / float(limit) if limit else 0.0
        bid_price, ask_price, _ = self._compute_quote_prices(book, inventory_ratio, fair_value)
        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        bid_size, ask_size = self._compute_sizes(position, limit)
        bid_factor, ask_factor = self._zscore_size_factors(memory)
        bid_size = max(0.0, bid_size * bid_factor)
        ask_size = max(0.0, ask_size * ask_factor)
        bid_size, ask_size = self._microprice_size_tilt(book, mid, bid_size, ask_size)
        base_edge       = self._dynamic_take_edge(memory)
        buy_edge, sell_edge = self._compute_asym_take_edges(base_edge, eff_position, memory)
        buy_blocked, sell_blocked = self._taker_cooldown_active(state, memory)
        if buy_blocked:
            buy_edge = 1_000_000.0
        if sell_blocked:
            sell_edge = 1_000_000.0
        taker_orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px = self._fire_takers(
            order_depth, fair_value, bid_size, ask_size, buy_cap, sell_cap,
            buy_edge=buy_edge, sell_edge=sell_edge,
        )
        self._update_taker_cooldown(state, memory, taker_buy_px, taker_sell_px)
        gap_orders, buy_cap, sell_cap, bid_price, ask_price = self._gap_exploit(
            order_depth, memory, limit, bid_size, ask_size,
            bid_price, ask_price, buy_cap, sell_cap,
            taker_buy_px, taker_sell_px,
        )
        bid_price, ask_price = self._asym_passive_skew(bid_price, ask_price, eff_position, book)
        bid_price, ask_price = self._apply_spread_widening(bid_price, ask_price, book, memory)
        bid_price, ask_price = self._apply_spread_zscore_skew(bid_price, ask_price, book, memory)
        bid_size, ask_size   = self._apply_toxic_flow(state, memory, bid_size, ask_size)
        bid_size, ask_size   = self._apply_jump_filter(book, memory, bid_size, ask_size)
        bid_size, ask_size   = self._apply_fill_rate_toxicity(state, memory, bid_size, ask_size)
        passive_orders, buy_cap, sell_cap = self._passive_quotes(
            bid_price, ask_price, bid_size, ask_size, buy_cap, sell_cap, position, limit
        )
        probe_orders, buy_cap, sell_cap = self._probe_quotes(
            book, state, memory, position, buy_cap, sell_cap,
        )
        passive_orders.extend(probe_orders)
        probe_t0_orders, buy_cap, sell_cap = self._probe_tick0(
            book, state, memory, buy_cap, sell_cap,
        )
        passive_orders.extend(probe_t0_orders)
        momentum_orders, buy_cap, sell_cap = self._apply_momentum_follower(
            state, order_depth, memory, buy_cap, sell_cap,
        )
        taker_orders.extend(momentum_orders)
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
                "position": position,
                "fair":     round(fair_value, 2),
                "buy_edge": round(buy_edge, 2),
                "sell_edge":round(sell_edge, 2),
                "bid_size": int(bid_size),
                "ask_size": int(ask_size),
                "zscore":   round(z, 4) if z is not None else None,
                "sigma":    round(sigma, 4),
                "flow_score": round(memory.get("_flow_score", 0.0), 3),
            },
        )
        return taker_orders + gap_orders + passive_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("mid_smoothed"))  is not None: out["MidSmooth"]  = float(m)
        if (a := memory.get("_anchor_ema"))   is not None: out["AnchorEMA"]  = float(a)
        z = memory.get("zscore")
        if z is not None:
            out["Z"] = float(z)
        return out


class R3GuardedAnchorMMStrategy(MMFirstV4ComboStrategy):
    """Guarded Anchor MM: disables AR + takers when price trends away from anchor.

    Guard logic (_use_anchor):
      - near_anchor: |mid - anchor| <= near_band (default 0)
      - reverting:   price is between [min_dist, max_dist] from anchor AND
                     trending back toward it (dist × trend_ema <= -threshold)
      - wrong_way_inventory: inventory pushes in the wrong direction
      - Guard ON (use anchor) = (near_anchor OR reverting) AND NOT wrong_way
      - Guard OFF: set ar_gain=0, take_edges=∞  → pure passive MM only
    """

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        # Counterparty bias layer (opt-in via params): compute trader-flow signal
        # Mark 55+67 follow / Mark 01+14 fade → returns weighted net flow signal
        # Mark this strategy as handling cp_bias internally — avoid double-application from on_tick
        self.params["_cp_bias_handled_internally"] = True

        cp_offset = 0
        if bool(self.params.get("counterparty_bias_enabled", False)):
            cp_signal = self._counterparty_signal(state, memory)
            cp_threshold = float(self.params.get("cp_signal_threshold", 5.0))
            cp_max_offset = float(self.params.get("cp_max_anchor_offset", 3.0))
            cp_scale = float(self.params.get("cp_anchor_scale_per_unit", 0.10))
            if abs(cp_signal) > cp_threshold:
                cp_offset = int(round(max(-cp_max_offset, min(cp_max_offset, cp_signal * cp_scale))))

        # Original guard logic
        orders, conv = self._compute_guarded(state, book, order_depth, position, memory)

        # Apply cp_bias as uniform price shift on all orders (post-strategy)
        if cp_offset != 0 and orders:
            shifted = []
            best_bid = book.best_bid
            best_ask = book.best_ask
            for o in orders:
                new_price = int(o.price) + cp_offset
                # Cap to avoid crossing the book
                if o.quantity > 0 and best_ask is not None and new_price >= best_ask:
                    new_price = int(best_ask) - 1
                elif o.quantity < 0 and best_bid is not None and new_price <= best_bid:
                    new_price = int(best_bid) + 1
                shifted.append(Order(o.symbol, new_price, o.quantity))
            return shifted, conv
        return orders, conv

    def _compute_guarded(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        mid    = book.mid_price
        anchor = self.params.get("anchor_price")
        if mid is None or anchor is None:
            return super().compute_orders(state, book, order_depth, position, memory)
        use_anchor = self._use_anchor(float(mid), float(anchor), position, memory)
        memory["_guard_use_anchor"] = int(use_anchor)
        if use_anchor:
            return super().compute_orders(state, book, order_depth, position, memory)
        old_anchor   = self.params.get("anchor_price")
        old_ar       = self.params.get("ar_gain")
        old_take_lo  = self.params.get("take_edge_lo")
        old_take_hi  = self.params.get("take_edge_hi")
        try:
            self.params["anchor_price"] = None
            self.params["ar_gain"]      = 0.0
            self.params["take_edge_lo"] = 1_000_000.0
            self.params["take_edge_hi"] = 1_000_000.0
            return super().compute_orders(state, book, order_depth, position, memory)
        finally:
            self.params["anchor_price"] = old_anchor
            self.params["ar_gain"]      = old_ar
            self.params["take_edge_lo"] = old_take_lo
            self.params["take_edge_hi"] = old_take_hi

    def _use_anchor(
        self,
        mid: float,
        anchor: float,
        position: int,
        memory: Dict[str, Any],
    ) -> bool:
        prev_mid = memory.get("_guard_prev_mid")
        memory["_guard_prev_mid"] = mid
        raw_trend = 0.0 if prev_mid is None else mid - float(prev_mid)
        alpha = float(self.params.get("guard_trend_alpha", 0.3))
        trend = float(memory.get("_guard_trend_ema", raw_trend))
        trend = alpha * raw_trend + (1.0 - alpha) * trend
        memory["_guard_trend_ema"] = trend
        dist = mid - anchor
        memory["_guard_dist"]  = dist
        memory["_guard_trend"] = trend
        near_band       = float(self.params.get("guard_near_band", 0.0))
        min_dist        = float(self.params.get("guard_min_dist", 0.0))
        max_dist        = float(self.params.get("guard_max_dist", 80.0))
        threshold       = float(self.params.get("guard_reversion_threshold", 0.0))
        inventory_dist  = float(self.params.get("guard_inventory_dist", 40.0))
        near_anchor = abs(dist) <= near_band
        reverting   = min_dist <= abs(dist) <= max_dist and (dist * trend) <= -threshold
        wrong_way   = (position > 0 and dist < -inventory_dist) or (
                       position < 0 and dist > inventory_dist)
        return (near_anchor or reverting) and not wrong_way

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        if (d := memory.get("_guard_dist"))       is not None: out["GuardDist"]  = float(d)
        if (t := memory.get("_guard_trend"))      is not None: out["GuardTrend"] = float(t)
        if (u := memory.get("_guard_use_anchor")) is not None: out["GuardOn"]    = float(u)
        return out


class DynamicAnchorMMStrategy(R3GuardedAnchorMMStrategy):
    """R3GuardedAnchorMMStrategy with anchor replaced by a slow EWMA of mid price.

    Instead of a fixed anchor_price=5250, the anchor tracks a very slow
    exponential moving average of the mid price. This lets the strategy
    adapt when VELVETFRUIT drifts over multi-day periods.

    Key param:
      anchor_slow_alpha  EWMA alpha for the slow anchor (default 0.0002,
                         half-life ≈ 3500 ticks ≈ 0.35 days).
                         Smaller = slower / more stable anchor.

    Set anchor_alpha=0.0 and anchor_drift_bound=0.0 in config so the parent's
    fast-drift logic is bypassed (the slow EMA is already smooth enough).
    """

    def _get_dynamic_anchor(self, mid: float, memory: Dict[str, Any]) -> float:
        alpha = float(self.params.get("anchor_slow_alpha", 0.0002))
        prev = memory.get("_dynamic_anchor")
        if prev is None:
            memory["_dynamic_anchor"] = float(mid)
            return float(mid)
        ema = (1.0 - alpha) * float(prev) + alpha * mid
        memory["_dynamic_anchor"] = ema
        return ema

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
            return super().compute_orders(state, book, order_depth, position, memory)
        anchor = self._get_dynamic_anchor(float(mid), memory)
        old_anchor = self.params.get("anchor_price")
        try:
            self.params["anchor_price"] = anchor
            return super().compute_orders(state, book, order_depth, position, memory)
        finally:
            self.params["anchor_price"] = old_anchor

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = super().feature_prices(memory)
        if (a := memory.get("_dynamic_anchor")) is not None:
            out["DynAnchor"] = float(a)
        return out
