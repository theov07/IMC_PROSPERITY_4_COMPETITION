"""Osmium flat-modular strategy (Round 2).

Each sub-feature is a private helper; a single `compute_orders` orchestrates
them in an explicit order. No `super().compute_orders` — the logic is local
and auditable top-to-bottom, matching the `mm_first_v2.py` template.

Modules (in order of invocation):

  _handle_broken_book       wide gap-quotes when OB side(s) are empty
  _compute_signal           EMA-anchor + AR(1) mean-rev shift on mid
  _apply_eod_flatten        liquidation branch near end-of-day
  _take_abs                 unconditional taker on absolute price thresholds
  _gap_exploit              thin-L1 sweep when gap L1→L2 is large
  _compute_take_edges       buy/sell edge from inventory pressure + trend
  _take_edge_orders         mean-rev taker using adjusted_mid ± edge
  _reanchor_passive_prices  post-take best bid/ask recomputation
  _apply_inventory_sizing   aggravate/unwind sizing around inv_target
  _apply_toxic_flow         shrink quote side when flow is adverse
  _apply_jump_filter        shrink quote side on bid/ask jump
  _passive_quotes           emit final passive bid/ask

All private helpers return lists of Order and/or mutate bookkeeping state.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class OsmiumModulaireStrategy(BaseStrategy):

    # ── signal ─────────────────────────────────────────────────────────

    def _compute_signal(
        self,
        mid: float,
        memory: Dict[str, Any],
    ) -> Tuple[float, float, int]:
        """Compute adjusted_mid = mid + trend_shift and derived inv_target.

        Two signal modes share a common shift computation:
          - mean_rev: raw = anchor - mid  (reverts toward the anchor)
          - trend:   raw = mid - EMA      (chases the trend)

        Mean-reversion around the anchor is further nudged by an AR(1) term
        so strong last-tick moves pull the fair value against them.
        """
        signal_mode = str(self.params.get("signal_mode", "trend"))
        sens = float(self.params.get("trend_sensitivity", 1.0))
        max_shift = float(self.params.get("trend_max_shift", 5.0))
        inv_per_tick = float(self.params.get("trend_inv_target_per_tick", 0.0))
        limit = self.position_limit()

        fixed_anchor = float(self.params.get("anchor_price", 10000.0))
        anchor_alpha = float(self.params.get("anchor_alpha", 0.0))
        if anchor_alpha > 0.0:
            ema = memory.get("anchor_ema")
            if ema is None:
                ema = fixed_anchor if fixed_anchor else mid
            ema = anchor_alpha * mid + (1.0 - anchor_alpha) * ema
            memory["anchor_ema"] = ema
            anchor_value = ema
        else:
            anchor_value = fixed_anchor

        ar_gain = float(self.params.get("ar_gain", 0.0))
        prev_mid = memory.get("osm_prev_mid")
        ar_shift = 0.0
        if prev_mid is not None and ar_gain > 0.0:
            ar_shift = -ar_gain * (mid - prev_mid)
        memory["osm_prev_mid"] = mid
        if ar_shift != 0.0 and sens != 0.0:
            anchor_value = anchor_value + ar_shift / sens

        trend_shift = 0.0
        if signal_mode == "mean_rev" and anchor_value != 0.0:
            raw = anchor_value - mid
            trend_shift = max(-max_shift, min(max_shift, raw * sens))
        elif signal_mode == "trend":
            alpha = float(self.params.get("trend_alpha", 0.0))
            if alpha > 0.0:
                ema = memory.get("trend_ema")
                if ema is None:
                    ema = mid
                ema = alpha * mid + (1.0 - alpha) * ema
                memory["trend_ema"] = ema
                raw = mid - ema
                trend_shift = max(-max_shift, min(max_shift, raw * sens))

        inv_target = int(round(max(-limit, min(limit, trend_shift * inv_per_tick))))
        adjusted_mid = mid + trend_shift
        return adjusted_mid, trend_shift, inv_target

    # ── end-of-day flatten ─────────────────────────────────────────────

    def _apply_eod_flatten(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        position: int,
    ) -> Optional[List[Order]]:
        """Liquidate the inventory past `eod_flatten_ts`. None if inactive."""
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

    # ── taker modules ──────────────────────────────────────────────────

    def _take_abs(
        self,
        order_depth: OrderDepth,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        """Unconditional takes when best price crosses absolute thresholds."""
        orders: List[Order] = []
        take_abs_buy = self.params.get("take_abs_buy")
        take_abs_sell = self.params.get("take_abs_sell")

        if take_abs_buy is not None and buy_cap > 0:
            for ask_p in sorted(order_depth.sell_orders):
                if ask_p > float(take_abs_buy) or buy_cap <= 0:
                    break
                available = -order_depth.sell_orders[ask_p]
                qty = min(available, buy_cap)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, ask_p, qty))
                order_depth.sell_orders[ask_p] += qty
                if order_depth.sell_orders[ask_p] == 0:
                    del order_depth.sell_orders[ask_p]
                buy_cap -= qty

        if take_abs_sell is not None and sell_cap > 0:
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if bid_p < float(take_abs_sell) or sell_cap <= 0:
                    break
                volume = order_depth.buy_orders[bid_p]
                qty = min(volume, sell_cap)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, bid_p, -qty))
                order_depth.buy_orders[bid_p] -= qty
                if order_depth.buy_orders[bid_p] == 0:
                    del order_depth.buy_orders[bid_p]
                sell_cap -= qty

        return orders, buy_cap, sell_cap

    def _gap_exploit(
        self,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        """Sweep thin L1 when L1→L2 gap exceeds threshold."""
        gap_min = float(self.params.get("gap_trigger_min", 0))
        if gap_min <= 0:
            return [], buy_cap, sell_cap

        orders: List[Order] = []
        limit = self.position_limit()
        gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.15))
        gap_max_vol = int(gap_vol_pct * limit) if limit else 0
        gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 1))

        bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        bid_gap_ok = False
        if len(bids) >= 2:
            b1, b2 = bids[0], bids[1]
            bid_gap_ok = (b1 - b2) >= gap_min and order_depth.buy_orders[b1] <= gap_max_vol
        bs = memory.get("_gap_bid_streak", 0)
        bs = bs + 1 if bid_gap_ok else 0
        memory["_gap_bid_streak"] = bs
        if bs >= gap_confirm and bid_gap_ok and sell_cap > 0:
            b1 = bids[0]
            qty = min(order_depth.buy_orders[b1], sell_cap)
            if qty > 0:
                orders.append(Order(self.product, b1, -qty))
                order_depth.buy_orders[b1] -= qty
                if order_depth.buy_orders[b1] == 0:
                    del order_depth.buy_orders[b1]
                sell_cap -= qty

        asks = sorted(order_depth.sell_orders.keys())
        ask_gap_ok = False
        if len(asks) >= 2:
            a1, a2 = asks[0], asks[1]
            ask_gap_ok = (a2 - a1) >= gap_min and -order_depth.sell_orders[a1] <= gap_max_vol
        asr = memory.get("_gap_ask_streak", 0)
        asr = asr + 1 if ask_gap_ok else 0
        memory["_gap_ask_streak"] = asr
        if asr >= gap_confirm and ask_gap_ok and buy_cap > 0:
            a1 = asks[0]
            qty = min(-order_depth.sell_orders[a1], buy_cap)
            if qty > 0:
                orders.append(Order(self.product, a1, qty))
                order_depth.sell_orders[a1] += qty
                if order_depth.sell_orders[a1] == 0:
                    del order_depth.sell_orders[a1]
                buy_cap -= qty

        return orders, buy_cap, sell_cap

    def _compute_take_edges(
        self,
        position: int,
        inv_target: int,
        trend_shift: float,
    ) -> Tuple[float, float]:
        """Return (buy_edge, sell_edge) adjusted by inventory pressure + trend."""
        take_edge = float(self.params.get("take_edge", 1.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 0.0))
        trend_take_boost = float(self.params.get("trend_take_boost", 0.0))
        limit = self.position_limit()

        buy_edge = take_edge
        sell_edge = take_edge
        pressure = abs(position - inv_target) / max(1.0, float(limit))
        if position < inv_target:
            buy_edge = max(0.0, buy_edge - unwind_take_edge * pressure)
        elif position > inv_target:
            sell_edge = max(0.0, sell_edge - unwind_take_edge * pressure)
        if trend_shift > 0.0:
            buy_edge = buy_edge - trend_shift * trend_take_boost
        elif trend_shift < 0.0:
            sell_edge = sell_edge - (-trend_shift) * trend_take_boost
        return buy_edge, sell_edge

    def _take_edge_orders(
        self,
        order_depth: OrderDepth,
        adjusted_mid: float,
        buy_edge: float,
        sell_edge: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, int]:
        """Mean-rev taker: buy below adjusted_mid - edge, sell above + edge."""
        orders: List[Order] = []
        take_count = 0
        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > adjusted_mid - buy_edge or buy_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_price]
            qty = min(available, buy_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_price, qty))
            buy_cap -= qty
            take_count += 1
        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < adjusted_mid + sell_edge or sell_cap <= 0:
                break
            volume = order_depth.buy_orders[bid_price]
            qty = min(volume, sell_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, bid_price, -qty))
            sell_cap -= qty
            take_count += 1
        return orders, buy_cap, sell_cap, take_count

    # ── price anchoring ────────────────────────────────────────────────

    def _reanchor_passive_prices(
        self,
        book: BookSnapshot,
        taker_orders: List[Order],
    ) -> Tuple[int, int]:
        """Compute passive bid/ask using the first book level not swept."""
        tighten_ticks = int(self.params.get("tighten_ticks", 1))
        swept_ask_prices = {o.price for o in taker_orders if o.quantity > 0}
        swept_bid_prices = {o.price for o in taker_orders if o.quantity < 0}

        real_best_ask = book.best_ask
        for ask_price, _ in book.ask_levels:
            if ask_price not in swept_ask_prices:
                real_best_ask = ask_price
                break

        real_best_bid = book.best_bid
        for bid_price, _ in book.bid_levels:
            if bid_price not in swept_bid_prices:
                real_best_bid = bid_price
                break

        spread = real_best_ask - real_best_bid
        if spread >= 2:
            bid_price = min(real_best_bid + tighten_ticks, real_best_ask - 1)
            ask_price = max(real_best_ask - tighten_ticks, real_best_bid + 1)
        else:
            bid_price = real_best_bid
            ask_price = real_best_ask
        if bid_price >= ask_price:
            ask_price = bid_price + 1
        return bid_price, ask_price

    # ── inventory-adaptive sizing ──────────────────────────────────────

    def _apply_inventory_sizing(
        self,
        position: int,
        inv_target: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        buy_size = min(buy_cap, maker_size)
        sell_size = min(sell_cap, maker_size)

        soft_ratio = float(self.params.get("inventory_soft_ratio", 0.35))
        aggravate_min_frac = float(self.params.get("aggravate_min_frac", 0.25))
        unwind_boost_frac = float(self.params.get("unwind_boost_frac", 0.25))
        limit = float(self.position_limit())
        pressure = abs(position - inv_target) / max(1.0, limit)

        if pressure <= soft_ratio or soft_ratio >= 1.0:
            return buy_size, sell_size

        scaled = min(1.0, (pressure - soft_ratio) / max(1e-9, 1.0 - soft_ratio))
        aggravate_frac = 1.0 - (1.0 - aggravate_min_frac) * scaled
        unwind_mult = 1.0 + unwind_boost_frac * scaled

        if position > inv_target:
            if buy_size > 0:
                buy_size = max(1, int(round(buy_size * aggravate_frac)))
            if sell_size > 0:
                sell_size = min(sell_cap, max(1, int(round(sell_size * unwind_mult))))
        elif position < inv_target:
            if sell_size > 0:
                sell_size = max(1, int(round(sell_size * aggravate_frac)))
            if buy_size > 0:
                buy_size = min(buy_cap, max(1, int(round(buy_size * unwind_mult))))
        return buy_size, sell_size

    # ── flow / jump filters ────────────────────────────────────────────

    def _apply_toxic_flow(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        trend_shift: float,
        buy_size: int,
        sell_size: int,
    ) -> Tuple[int, int, float]:
        toxic_window = int(self.params.get("toxic_window", 6))
        toxic_threshold = float(self.params.get("toxic_threshold", 0.6))
        toxic_size_frac = float(self.params.get("toxic_size_frac", 0.5))

        flow_history = memory.setdefault("flow_history", [])
        prev_best_bid = memory.get("prev_best_bid")
        prev_best_ask = memory.get("prev_best_ask")
        trades = state.market_trades.get(self.product, [])
        if toxic_window > 0 and prev_best_bid is not None and prev_best_ask is not None and trades:
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
            total = sum(abs(x) for x in flow_history)
            if total > 0:
                flow_score = signed / total

        suppress_toxic = (
            (flow_score > 0 and trend_shift > 1.0)
            or (flow_score < 0 and trend_shift < -1.0)
        )
        if not suppress_toxic:
            if flow_score > toxic_threshold and sell_size > 0:
                sell_size = max(1, int(round(sell_size * toxic_size_frac)))
            elif flow_score < -toxic_threshold and buy_size > 0:
                buy_size = max(1, int(round(buy_size * toxic_size_frac)))
        return buy_size, sell_size, flow_score

    def _apply_jump_filter(
        self,
        real_best_bid: int,
        real_best_ask: int,
        memory: Dict[str, Any],
        trend_shift: float,
        buy_size: int,
        sell_size: int,
    ) -> Tuple[int, int]:
        prev_best_bid = memory.get("prev_best_bid")
        prev_best_ask = memory.get("prev_best_ask")
        jump_size_frac = float(self.params.get("jump_size_frac", 0.5))
        trend_jump_threshold = float(self.params.get("trend_jump_threshold", 0.0))

        bid_jumped = bool(prev_best_bid is not None and real_best_bid == prev_best_bid + 1)
        ask_jumped = bool(prev_best_ask is not None and real_best_ask == prev_best_ask - 1)
        if bid_jumped and sell_size > 0 and trend_shift >= -trend_jump_threshold:
            sell_size = max(1, int(round(sell_size * jump_size_frac)))
        if ask_jumped and buy_size > 0 and trend_shift <= trend_jump_threshold:
            buy_size = max(1, int(round(buy_size * jump_size_frac)))
        return buy_size, sell_size

    def _passive_quotes(
        self,
        bid_price: int,
        ask_price: int,
        buy_size: int,
        sell_size: int,
    ) -> List[Order]:
        orders: List[Order] = []
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))
        return orders

    # ── broken-book gap quotes (Theo-style) ────────────────────────────

    def _handle_broken_book(
        self,
        book: BookSnapshot,
        position: int,
        memory: Dict[str, Any],
    ) -> Optional[List[Order]]:
        """If one/both sides of the OB are empty, post wide gap-quotes at
        last_bid - shift / last_ask + shift to catch counterparties that
        cross back through the hole. Returns None when book is two-sided."""
        if book.best_bid is None:
            pass
        elif book.best_ask is None:
            pass
        else:
            return None

        shift = int(self.params.get("empty_side_shift", 0))
        if shift <= 0:
            return []
        size = int(self.params.get("gap_size", 20))
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        last_bid = memory.get("_last_bid")
        last_ask = memory.get("_last_ask")

        orders: List[Order] = []
        if book.best_bid is None and book.best_ask is None:
            if last_bid is not None and buy_cap > 0:
                orders.append(Order(self.product, last_bid - shift, min(size, buy_cap)))
            if last_ask is not None and sell_cap > 0:
                orders.append(Order(self.product, last_ask + shift, -min(size, sell_cap)))
            return orders
        if book.best_bid is None:
            if last_bid is not None and buy_cap > 0:
                orders.append(Order(self.product, last_bid - shift, min(size, buy_cap)))
            return orders
        if book.best_ask is None:
            if last_ask is not None and sell_cap > 0:
                orders.append(Order(self.product, last_ask + shift, -min(size, sell_cap)))
            return orders
        return []

    # ── orchestrator ───────────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is not None:
            memory["_last_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_last_ask"] = book.best_ask

        if book.best_bid is None or book.best_ask is None:
            broken_orders = self._handle_broken_book(book, position, memory)
            return broken_orders or [], 0

        eod_orders = self._apply_eod_flatten(state, order_depth, position)
        if eod_orders is not None:
            return eod_orders, 0

        mid = (book.best_bid + book.best_ask) / 2.0
        adjusted_mid, trend_shift, inv_target = self._compute_signal(mid, memory)

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        abs_orders, buy_cap, sell_cap = self._take_abs(order_depth, buy_cap, sell_cap)
        gap_orders, buy_cap, sell_cap = self._gap_exploit(order_depth, memory, buy_cap, sell_cap)

        if not order_depth.buy_orders or not order_depth.sell_orders:
            memory["inv_target"] = inv_target
            memory["trend_shift"] = trend_shift
            return abs_orders + gap_orders, 0

        buy_edge, sell_edge = self._compute_take_edges(position, inv_target, trend_shift)
        take_orders, buy_cap, sell_cap, take_count = self._take_edge_orders(
            order_depth, adjusted_mid, buy_edge, sell_edge, buy_cap, sell_cap,
        )

        bid_price, ask_price = self._reanchor_passive_prices(book, take_orders)

        buy_size, sell_size = self._apply_inventory_sizing(
            position, inv_target, buy_cap, sell_cap,
        )
        buy_size, sell_size, flow_score = self._apply_toxic_flow(
            state, memory, trend_shift, buy_size, sell_size,
        )
        buy_size, sell_size = self._apply_jump_filter(
            book.best_bid, book.best_ask, memory, trend_shift, buy_size, sell_size,
        )

        passive_orders = self._passive_quotes(bid_price, ask_price, buy_size, sell_size)

        memory["prev_best_bid"] = book.best_bid
        memory["prev_best_ask"] = book.best_ask
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_flow_score"] = flow_score
        memory["last_take_count"] = take_count
        memory["inv_target"] = inv_target
        memory["trend_shift"] = trend_shift

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "buy_size": buy_size,
                "sell_size": sell_size,
                "flow_score": flow_score,
                "takes": take_count,
                "trend_shift": round(trend_shift, 2),
                "inv_target": inv_target,
            },
        )

        return abs_orders + gap_orders + take_orders + passive_orders, 0
