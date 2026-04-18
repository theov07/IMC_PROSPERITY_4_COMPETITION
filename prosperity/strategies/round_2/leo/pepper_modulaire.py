"""INTARIAN_PEPPER_ROOT flat-modular strategy (Round 2).

Single class with a flat orchestrator. Inherits ONLY the block-OLS utility
helpers (_update_regression, _inventory_target, _size_from_target) from
Round1RegressionMMV5Strategy — compute_orders is 100% local.

Modules (in order of invocation):

  _track_recent_best_asks  rolling window of best_ask for the gap_scout anchor
  _compute_fv_quotes       fv ± spread quoting using block-OLS fair value
  _apply_price_step        V5-style bid_extra / ask_relax from trend+residual
  _compute_take_edges      bull/neut buy/sell edges with inventory unwind boost
  _take_orders             take vs fair_value ± edge
  _gap_exploit             thin-L1 sweep on the current book
  _apply_inventory_sizing  reuse V5 _size_from_target
  _passive_quotes          emit fv-anchored passive bid/ask
  _gap_scout_sell          passive sell at anchor_ask + empty_side_shift
  _gap_rebuy_buy           aggressive buyback after scout sell once market drops
  _hold_sell               1-unit passive at best_ask when position saturated
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_1.regression_mm_v5 import Round1RegressionMMV5Strategy


class PepperModulaireStrategy(Round1RegressionMMV5Strategy):

    # ── memory helpers ─────────────────────────────────────────────────

    def _track_recent_best_asks(
        self,
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> None:
        if book.best_ask is None:
            return
        window = int(self.params.get("gap_scout_recent_ask_window", 6))
        recent = memory.setdefault("_recent_best_asks", [])
        recent.append(int(book.best_ask))
        if len(recent) > window:
            del recent[:-window]

    # ── quote price modules ────────────────────────────────────────────

    def _compute_fv_quotes(
        self,
        book: BookSnapshot,
        fv: float,
        bullish: bool,
    ) -> Tuple[int, int]:
        """Fair-value anchored bid/ask with bullish-biased spreads."""
        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        ask_spread_bull = float(self.params.get("ask_spread_bull", 9.0))
        neut_spread_bid = float(self.params.get("neut_spread_bid", 2.0))
        neut_spread_ask = float(self.params.get("neut_spread_ask", 5.0))

        if bullish:
            raw_bid = round(fv - bid_spread_bull)
            raw_ask = round(fv + ask_spread_bull)
        else:
            raw_bid = round(fv - neut_spread_bid)
            raw_ask = round(fv + neut_spread_ask)

        bid_price = min(max(raw_bid, 1), book.best_ask - 1)
        ask_price = max(raw_ask, book.best_bid + 1)
        if bid_price >= ask_price:
            ask_price = bid_price + 1
        return bid_price, ask_price

    def _apply_price_step(
        self,
        bid_price: int,
        ask_price: int,
        book: BookSnapshot,
        trend_ticks: float,
        residual_z: float,
    ) -> Tuple[int, int]:
        """Tick-level nudges on top of fv quotes from trend/residual signals."""
        strong = float(self.params.get("strong_trend_ticks", 1.1))
        very_strong = float(self.params.get("very_strong_trend_ticks", 2.0))
        cheap_z = float(self.params.get("cheap_residual_z", 0.9))
        rich_z = float(self.params.get("rich_residual_z", 1.0))
        max_bid_extra = int(self.params.get("max_bid_extra_ticks", 2))
        max_ask_relax = int(self.params.get("max_ask_relax_ticks", 2))

        bid_extra = 0
        ask_relax = 0
        if trend_ticks >= strong:
            bid_extra += 1
        if trend_ticks >= very_strong:
            bid_extra += 1
        if residual_z <= -cheap_z:
            bid_extra += 1
        if residual_z >= rich_z:
            ask_relax -= 1
        bid_extra = max(0, min(max_bid_extra, bid_extra))
        ask_relax = max(-max_ask_relax, min(max_ask_relax, ask_relax))

        bid_price = min(book.best_ask - 1, bid_price + bid_extra)
        ask_price = max(book.best_bid + 1, ask_price + ask_relax)
        if bid_price >= ask_price:
            ask_price = bid_price + 1
        return bid_price, ask_price

    # ── taker modules ──────────────────────────────────────────────────

    def _compute_take_edges(
        self,
        bullish: bool,
        residual_z: float,
        position: int,
        inv_target: int,
    ) -> Tuple[float, float]:
        take_buy_edge_bull = float(self.params.get("take_buy_edge_bull", -8.0))
        take_sell_edge_bull = float(self.params.get("take_sell_edge_bull", 6.0))
        take_buy_edge_neut = float(self.params.get("take_buy_edge_neut", 2.0))
        take_sell_edge_neut = float(self.params.get("take_sell_edge_neut", 2.0))
        rich_z = float(self.params.get("rich_residual_z", 1.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 10.0))

        if bullish:
            buy_edge = take_buy_edge_bull
            sell_edge = take_sell_edge_bull
            if residual_z >= rich_z:
                buy_edge = take_buy_edge_neut
        else:
            buy_edge = take_buy_edge_neut
            sell_edge = take_sell_edge_neut

        limit = self.position_limit()
        if (not bullish) and position > inv_target:
            pressure = min(1.0, (position - inv_target) / max(1.0, float(limit)))
            sell_edge = sell_edge - unwind_take_edge * pressure
        return buy_edge, sell_edge

    def _take_orders(
        self,
        order_depth: OrderDepth,
        fv: float,
        buy_edge: float,
        sell_edge: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fv - buy_edge or buy_cap <= 0:
                break
            qty = min(-order_depth.sell_orders[ask_p], buy_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_p, qty))
            buy_cap -= qty
        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            if bid_p < fv + sell_edge or sell_cap <= 0:
                break
            qty = min(order_depth.buy_orders[bid_p], sell_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, bid_p, -qty))
            sell_cap -= qty
        return orders, buy_cap, sell_cap

    def _gap_exploit(
        self,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
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

    # ── scout / rebuy / hold ───────────────────────────────────────────

    def _gap_scout_sell(
        self,
        state: TradingState,
        book: BookSnapshot,
        position: int,
        bullish: bool,
        memory: Dict[str, Any],
        current_orders: List[Order],
    ) -> List[Order]:
        floor_pos = int(self.params.get("gap_scout_floor_position", 78))
        if not bullish or position < floor_pos:
            return current_orders
        sell_cap = self.sell_capacity(position)
        for o in current_orders:
            if o.quantity < 0:
                sell_cap += o.quantity
        if sell_cap <= 0 or not book.ask_levels:
            return current_orders

        min_gap = int(self.params.get("gap_scout_min_gap", 3))
        ask_fragile = len(book.ask_levels) == 1
        if len(book.ask_levels) >= 2:
            ask_fragile = ask_fragile or (
                book.ask_levels[1][0] - book.ask_levels[0][0] >= min_gap
            )
        if not ask_fragile:
            return current_orders

        ts = int(state.timestamp)
        in_window = (
            int(self.params.get("gap_scout_early_start_ts", 3600))
            <= ts
            <= int(self.params.get("gap_scout_early_end_ts", 8500))
            or int(self.params.get("gap_scout_mid_start_ts", 56500))
            <= ts
            <= int(self.params.get("gap_scout_mid_end_ts", 57500))
            or int(self.params.get("gap_scout_late_start_ts", 143000))
            <= ts
            <= int(self.params.get("gap_scout_late_end_ts", 145000))
        )
        if not in_window:
            return current_orders

        recent = memory.get("_recent_best_asks", [])
        if not recent:
            return current_orders

        empty_side_shift = int(self.params.get("empty_side_shift", 85))
        candidate_price = min(recent) + empty_side_shift
        existing_sell_prices = [o.price for o in current_orders if o.quantity < 0]
        if existing_sell_prices and candidate_price <= max(existing_sell_prices):
            return current_orders

        size_limit = int(self.params.get("gap_scout_size_limit", 5))
        qty = min(sell_cap, size_limit, max(0, position - floor_pos + 1))
        if qty <= 0:
            return current_orders

        memory["_last_gap_sell_ts"] = ts
        memory["_last_gap_sell_price"] = candidate_price
        return current_orders + [Order(self.product, candidate_price, -qty)]

    def _gap_rebuy_buy(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        inv_target: int,
        bullish: bool,
        fv: float,
        memory: Dict[str, Any],
        current_orders: List[Order],
    ) -> List[Order]:
        if not bullish:
            return current_orders
        last_sell_ts = int(memory.get("_last_gap_sell_ts", -10**9))
        last_sell_price = memory.get("_last_gap_sell_price")
        if last_sell_price is None or book.best_ask is None:
            return current_orders

        window = int(self.params.get("gap_rebuy_window", 2500))
        age = int(state.timestamp) - last_sell_ts
        if age < 0 or age > window:
            return current_orders

        min_discount = float(self.params.get("gap_rebuy_min_discount", 20.0))
        if float(last_sell_price) - float(book.best_ask) < min_discount:
            return current_orders
        if position >= inv_target:
            return current_orders

        buy_cap = self.buy_capacity(position)
        for o in current_orders:
            if o.quantity > 0:
                buy_cap -= o.quantity
        if buy_cap <= 0:
            return current_orders

        rebuy_edge = float(self.params.get("gap_rebuy_buy_edge", -10.0))
        take_cap = min(buy_cap, int(self.params.get("gap_rebuy_take_cap", 8)),
                       max(0, inv_target - position))
        if take_cap <= 0:
            return current_orders

        extra: List[Order] = []
        queued_ask_qty: Dict[int, int] = {}
        for o in current_orders:
            if o.quantity > 0:
                queued_ask_qty[o.price] = queued_ask_qty.get(o.price, 0) + o.quantity

        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fv - rebuy_edge or take_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_p] - queued_ask_qty.get(ask_p, 0)
            if available <= 0:
                continue
            qty = min(available, take_cap)
            extra.append(Order(self.product, ask_p, qty))
            take_cap -= qty
        return current_orders + extra

    def _hold_sell(
        self,
        book: BookSnapshot,
        position: int,
        bullish: bool,
        current_orders: List[Order],
    ) -> List[Order]:
        if not bullish or book.best_ask is None:
            return current_orders
        size = int(self.params.get("hold_sell_size", 1))
        if size <= 0:
            return current_orders
        limit = self.position_limit()
        if position < limit - size + 1:
            return current_orders
        sell_cap = self.sell_capacity(position)
        for o in current_orders:
            if o.quantity < 0:
                sell_cap += o.quantity
        if sell_cap <= 0:
            return current_orders

        offset = int(self.params.get("hold_sell_offset", 0))
        price = int(book.best_ask) + offset
        qty = min(size, sell_cap)
        existing_sell_prices = [o.price for o in current_orders if o.quantity < 0]
        if price in existing_sell_prices:
            return current_orders
        return current_orders + [Order(self.product, price, -qty)]

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

    # ── orchestrator ───────────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        self._track_recent_best_asks(book, memory)

        if book.best_bid is None or book.best_ask is None:
            return [], 0

        mid = book.mid_price if book.mid_price is not None else (book.best_bid + book.best_ask) / 2.0
        stats = self._update_regression(state=state, mid=mid, memory=memory)
        trend_ticks = stats["trend_ticks"]
        residual_z = stats["residual_z"]
        fv = stats["fair_value"]

        inv_target = self._inventory_target(state=state, stats=stats, position=position)
        bullish = trend_ticks > float(self.params.get("bull_threshold", 1.0))

        # Gap exploit first (mutates order_depth), then delegate to the
        # fv-anchored MM on the post-gap book, using a virtual position that
        # reflects the gap fills. Mirrors leo_fusion_b_gap → leo_fusion_b.
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        gap_orders, buy_cap, sell_cap = self._gap_exploit(
            order_depth, memory, buy_cap, sell_cap,
        )
        virt_pos = position + sum(o.quantity for o in gap_orders)

        take_orders: List[Order] = []
        passive_orders: List[Order] = []
        bid_price = ask_price = None
        if order_depth.buy_orders and order_depth.sell_orders:
            bid_price, ask_price = self._compute_fv_quotes(book, fv, bullish)
            bid_price, ask_price = self._apply_price_step(
                bid_price, ask_price, book, trend_ticks, residual_z,
            )
            buy_edge, sell_edge = self._compute_take_edges(
                bullish, residual_z, virt_pos, inv_target,
            )
            mm_buy_cap = self.buy_capacity(virt_pos)
            mm_sell_cap = self.sell_capacity(virt_pos)
            take_orders, mm_buy_cap, mm_sell_cap = self._take_orders(
                order_depth, fv, buy_edge, sell_edge, mm_buy_cap, mm_sell_cap,
            )
            buy_size, sell_size = self._size_from_target(
                position=virt_pos,
                inv_target=inv_target,
                stats=stats,
                buy_cap=mm_buy_cap,
                sell_cap=mm_sell_cap,
            )
            passive_orders = self._passive_quotes(bid_price, ask_price, buy_size, sell_size)

        orders = gap_orders + take_orders + passive_orders
        orders = self._gap_rebuy_buy(
            state, book, order_depth, position, inv_target, bullish, fv, memory, orders,
        )
        orders = self._gap_scout_sell(
            state, book, position, bullish, memory, orders,
        )
        orders = self._hold_sell(book, position, bullish, orders)

        memory["last_bid_price"] = bid_price if bid_price is not None else memory.get("last_bid_price")
        memory["last_ask_price"] = ask_price if ask_price is not None else memory.get("last_ask_price")
        memory["inv_target"] = inv_target
        memory["bullish"] = int(bullish)

        if bid_price is None or ask_price is None:
            return orders, 0

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "reg_slope": round(stats["slope"], 4),
                "reg_r2": round(stats["r2"], 3),
                "trend_ticks": round(trend_ticks, 2),
                "residual_z": round(residual_z, 2),
                "block_count": int(stats["block_count"]),
                "fair_value": round(fv, 2),
                "inv_target": inv_target,
                "bullish": int(bullish),
            },
        )
        return orders, 0
