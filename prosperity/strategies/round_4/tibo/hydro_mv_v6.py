"""HYDROGEL_PACK — mv_v6: Dynamic anchor variants.

Same passive MM + AR taker core as v5. The only difference is how the anchor
is computed. Four modes selectable via `anchor_mode` param:

  "fixed"              — v5 baseline: clamped EWMA barely moves (±drift_bound)
  "slow_ewma"          — remove drift_bound clamping; anchor drifts freely at
                         a slow rate. Adapts to persistent regime changes over
                         minutes. Grid: anchor_alpha.
  "rolling_median"     — rolling window median of mid prices. Naturally adapts
                         when price spends more time at a new level. Robust to
                         outliers. Grid: anchor_window.
  "regime_switch"      — slow anchor by default; switches to a fast alpha when
                         price has trended away from anchor for N consecutive
                         ticks. Explicitly models "new regime" vs MR noise.
                         Grid: anchor_regime_threshold, anchor_regime_ticks,
                               anchor_fast_alpha.
  "inv_protected"      — only update anchor when position is near flat. When
                         we're heavily positioned we freeze the reference (we
                         need it to signal our exit). When flat we adapt.
                         Grid: anchor_alpha, anchor_pos_threshold.

All other params (AR gain, taker edge, passive MM) are identical to v5_best.
"""

from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional, Set, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydroMVV6(BaseStrategy):

    # ── Dynamic anchor ────────────────────────────────────────────────────

    def _update_anchor(self, raw_mid: float, position: int, memory: Dict[str, Any]) -> float:
        mode         = str(self.params.get("anchor_mode", "fixed"))
        anchor_fixed = float(self.params.get("anchor_price", 10000))
        anchor_alpha = float(self.params.get("anchor_alpha", 0.02))
        anchor_ema   = float(memory.get("_anchor_ema", anchor_fixed))

        if mode == "fixed":
            # Original v5: barely moves (drift_bound keeps it ≈ anchor_fixed)
            drift_bound = float(self.params.get("anchor_drift_bound", 1.5))
            if anchor_alpha > 0:
                anchor_ema = anchor_alpha * raw_mid + (1.0 - anchor_alpha) * anchor_ema
            if drift_bound > 0:
                anchor_ema = max(anchor_fixed - drift_bound,
                                 min(anchor_fixed + drift_bound, anchor_ema))

        elif mode == "slow_ewma":
            # Unclamped slow EWMA — drifts to new regime over time.
            # anchor_alpha controls adaptation speed; no drift_bound cap.
            if anchor_alpha > 0:
                anchor_ema = anchor_alpha * raw_mid + (1.0 - anchor_alpha) * anchor_ema

        elif mode == "rolling_median":
            # Rolling window median. Adapts when price spends time at new level.
            window = int(self.params.get("anchor_window", 500))
            buf = list(memory.get("_anchor_buf", []))
            buf.append(raw_mid)
            if len(buf) > window:
                buf = buf[-window:]
            memory["_anchor_buf"] = buf
            anchor_ema = statistics.median(buf)

        elif mode == "regime_switch":
            # Two-speed anchor: slow normally, fast when price has trended
            # away from anchor for >= regime_ticks consecutive ticks.
            regime_threshold = float(self.params.get("anchor_regime_threshold", 10.0))
            regime_ticks     = int(self.params.get("anchor_regime_ticks", 20))
            fast_alpha       = float(self.params.get("anchor_fast_alpha", 0.1))

            dist     = raw_mid - anchor_ema
            prev_mid = float(memory.get("_anchor_prev_mid", raw_mid))
            delta    = raw_mid - prev_mid
            memory["_anchor_prev_mid"] = raw_mid

            # "Trending away": price outside threshold band AND delta pushes further out
            trending_away = abs(dist) > regime_threshold and (dist * delta) >= 0
            streak = int(memory.get("_anchor_trend_streak", 0))
            streak = streak + 1 if trending_away else max(0, streak - 1)
            memory["_anchor_trend_streak"] = streak

            effective_alpha = fast_alpha if streak >= regime_ticks else anchor_alpha
            anchor_ema = effective_alpha * raw_mid + (1.0 - effective_alpha) * anchor_ema
            memory["_anchor_regime_active"] = int(streak >= regime_ticks)

        elif mode == "inv_protected":
            # Only update anchor when |position| is small (we're near flat).
            # When positioned heavily, freeze: we need the old reference to exit.
            limit         = self.position_limit()
            pos_threshold = float(self.params.get("anchor_pos_threshold", 0.3))
            if limit > 0 and abs(position) < limit * pos_threshold:
                anchor_ema = anchor_alpha * raw_mid + (1.0 - anchor_alpha) * anchor_ema
            # else: freeze anchor_ema unchanged

        memory["_anchor_ema"] = anchor_ema
        return anchor_ema

    # ── AR model ──────────────────────────────────────────────────────────

    def _update_ar(
        self, raw_mid: float, position: int, memory: Dict[str, Any],
    ) -> Tuple[float, float, float]:
        ms_hl    = float(self.params.get("mid_smooth_half_life", 20))
        ms_alpha = 1.0 - 0.5 ** (1.0 / ms_hl)
        prev_ms  = memory.get("_mid_smooth")
        mid_s    = raw_mid if prev_ms is None else ms_alpha * raw_mid + (1.0 - ms_alpha) * float(prev_ms)
        memory["_mid_smooth"] = mid_s

        anchor_ema = self._update_anchor(raw_mid, position, memory)

        ar_hl    = float(self.params.get("ar_smooth_half_life", 5))
        ar_alpha = 1.0 - 0.5 ** (1.0 / ar_hl)
        delta    = 0.0 if prev_ms is None else mid_s - float(prev_ms)
        ar_mom   = float(memory.get("_ar_momentum", 0.0))
        ar_mom   = ar_alpha * delta + (1.0 - ar_alpha) * ar_mom
        memory["_ar_momentum"] = ar_mom

        ar_gain    = float(self.params.get("ar_gain", 8.0))
        fair_value = anchor_ema - ar_gain * ar_mom
        memory["_fair_value"] = fair_value

        raw_dev  = mid_s - fair_value
        dev_hl   = float(self.params.get("dev_smooth_half_life", 5))
        dev_alpha = 1.0 - 0.5 ** (1.0 / dev_hl)
        dev_s    = float(memory.get("_dev_smooth", raw_dev))
        dev_s    = dev_alpha * raw_dev + (1.0 - dev_alpha) * dev_s
        memory["_dev_smooth"] = dev_s
        memory["_dev_raw"]    = raw_dev
        return mid_s, fair_value, dev_s

    # ── Mark 14 tracking ─────────────────────────────────────────────────

    def _update_m14(self, state: TradingState, memory: Dict[str, Any]) -> int:
        trader = str(self.params.get("informed_trader_name", "Mark 14"))
        net = 0
        for trade in state.market_trades.get(self.product, []):
            if trade.buyer == trader:    net += trade.quantity
            elif trade.seller == trader: net -= trade.quantity
        signal = 1 if net > 0 else (-1 if net < 0 else 0)
        memory["_m14_signal"] = signal
        return signal

    # ── Sizing ────────────────────────────────────────────────────────────

    def _passive_sizes(self, position: int) -> Tuple[float, float]:
        limit    = self.position_limit()
        base     = float(self.params.get("maker_size_base_pct", 0.15)) * limit
        inv_bias = self.params.get("use_inventory_bias", True)
        if inv_bias and limit > 0:
            bid_size = base * (1.0 - position / limit)
            ask_size = base * (1.0 + position / limit)
        else:
            bid_size = ask_size = base
        return max(0.0, bid_size), max(0.0, ask_size)

    # ── Passive quoting ───────────────────────────────────────────────────

    def _passive_quotes(
        self,
        book: BookSnapshot,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        position: int,
        dev: float,
    ) -> List[Order]:
        if not self.params.get("passive_quoting", True):
            return []
        bid_price = (book.best_bid + 1) if book.best_bid is not None else None
        ask_price = (book.best_ask - 1) if book.best_ask is not None else None

        if self.params.get("use_ar_quote_bias", False) and bid_price and ask_price:
            bias_ticks = int(self.params.get("ar_quote_bias_ticks", 2))
            if dev > 0:
                ask_price = max(book.best_bid + 1 if book.best_bid else ask_price,
                                ask_price - bias_ticks)
            elif dev < 0:
                bid_price = min(book.best_ask - 1 if book.best_ask else bid_price,
                                bid_price + bias_ticks)

        if bid_price is not None and ask_price is not None and bid_price >= ask_price:
            bid_price = ask_price - 1

        limit    = self.position_limit()
        hard_pct = float(self.params.get("pct_kept_for_takers", 0.2))
        if abs(position) >= limit * (1.0 - hard_pct):
            if position > 0: bid_size  = 0.0
            else:            ask_size  = 0.0

        orders: List[Order] = []
        qty_bid = min(buy_cap,  int(bid_size))
        qty_ask = min(sell_cap, int(ask_size))
        if qty_bid > 0 and bid_price is not None:
            orders.append(Order(self.product, bid_price,  qty_bid))
        if qty_ask > 0 and ask_price is not None:
            orders.append(Order(self.product, ask_price, -qty_ask))
        return orders

    # ── AR takers ─────────────────────────────────────────────────────────

    def _ar_takers(
        self,
        book: BookSnapshot,
        order_depth: OrderDepth,
        fair_value: float,
        dev: float,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, Set[int], Set[int]]:
        if not self.params.get("use_ar_taker", False):
            return [], buy_cap, sell_cap, set(), set()

        take_edge      = float(self.params.get("ar_taker_edge", 1.0))
        taker_size_pct = float(self.params.get("ar_taker_size_pct", 0.3))
        orders: List[Order] = []
        buy_px:  Set[int] = set()
        sell_px: Set[int] = set()

        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fair_value - take_edge or buy_cap <= 0:
                break
            avail = -order_depth.sell_orders[ask_p]
            qty   = min(avail, buy_cap, max(1, int(bid_size * taker_size_pct)))
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            if bid_p < fair_value + take_edge or sell_cap <= 0:
                break
            avail = order_depth.buy_orders[bid_p]
            qty   = min(avail, sell_cap, max(1, int(ask_size * taker_size_pct)))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                sell_px.add(bid_p)
                sell_cap -= qty

        return orders, buy_cap, sell_cap, buy_px, sell_px

    # ── Anchor guard (v5 guard feature, optional) ─────────────────────────

    def _guard_allows_taker(
        self, raw_mid: float, position: int, memory: Dict[str, Any],
    ) -> bool:
        if not self.params.get("use_anchor_guard", False):
            return True
        anchor    = float(memory.get("_anchor_ema", self.params.get("anchor_price", 10000)))
        prev_mid  = memory.get("_guard_prev_mid", raw_mid)
        memory["_guard_prev_mid"] = raw_mid
        raw_delta = raw_mid - float(prev_mid)
        alpha     = float(self.params.get("guard_trend_alpha", 0.3))
        trend_ema = float(memory.get("_guard_trend_ema", raw_delta))
        trend_ema = alpha * raw_delta + (1.0 - alpha) * trend_ema
        memory["_guard_trend_ema"] = trend_ema
        dist      = raw_mid - anchor
        threshold = float(self.params.get("guard_reversion_threshold", 3.0))
        max_dist  = float(self.params.get("guard_max_dist", 80.0))
        reverting = abs(dist) <= max_dist and (dist * trend_ema <= -threshold)
        near      = abs(dist) <= float(self.params.get("guard_near_band", 0.5))
        inv_dist  = float(self.params.get("guard_inventory_dist", 40.0))
        wrong_way = (position > 0 and dist < -inv_dist) or (position < 0 and dist > inv_dist)
        guard_on  = (near or reverting) and not wrong_way
        memory["_guard_on"] = int(guard_on)
        return guard_on

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

        # Store position so _update_anchor (inv_protected) can read it
        memory["_last_position"] = position

        mid_s, fair_value, dev = self._update_ar(float(mid), position, memory)
        sigma  = self._update_volatility(float(mid), memory)
        signal = self._update_m14(state, memory)

        if book.best_bid is not None: memory["_prev_best_bid"] = book.best_bid
        if book.best_ask is not None: memory["_prev_best_ask"] = book.best_ask

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        sell_cap_init = sell_cap
        buy_cap_init  = buy_cap

        bid_size, ask_size = self._passive_sizes(position)

        guard_ok = self._guard_allows_taker(float(mid), position, memory)

        taker_orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px = (
            self._ar_takers(book, order_depth, fair_value, dev,
                            bid_size, ask_size, buy_cap, sell_cap)
            if guard_ok else ([], buy_cap, sell_cap, set(), set())
        )

        passive_orders = self._passive_quotes(
            book, bid_size, ask_size, buy_cap, sell_cap, position, dev,
        )
        all_orders = taker_orders + passive_orders

        taker_sold   = sum(-o.quantity for o in taker_orders if o.quantity < 0)
        taker_bought = sum( o.quantity for o in taker_orders if o.quantity > 0)
        anchor_val   = float(memory.get("_anchor_ema", self.params.get("anchor_price", 10000)))

        # Per-tick quote trace — accumulated in memory and flushed every log_flush_ts.
        # Captures all signals needed to diagnose position build-up in live.
        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":     position,
                "mid":          round(float(mid), 2),
                "FairValue":    round(fair_value, 2),
                "Anchor":       round(anchor_val, 2),
                "DevSmooth":    round(dev, 3),
                "ar_mom":       round(float(memory.get("_ar_momentum", 0.0)), 4),
                "guard":        int(guard_ok),
                "M14Signal":    signal,
                "taker_sell":   taker_sold,
                "taker_buy":    taker_bought,
                "bid_size":     int(bid_size),
                "ask_size":     int(ask_size),
                "sigma":        round(sigma, 4),
            },
        )

        return all_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value"))   is not None: out["FairValue"] = float(v)
        if (v := memory.get("_dev_smooth"))   is not None: out["DevSmooth"] = float(v)
        if (v := memory.get("_m14_signal"))   is not None: out["M14Signal"] = float(v)
        if (v := memory.get("_anchor_ema"))   is not None: out["Anchor"]    = float(v)
        if (v := memory.get("_ar_momentum"))  is not None: out["ar_mom"]    = float(v)
        if (v := memory.get("_guard_on"))     is not None: out["guard"]     = float(v)
        return out
