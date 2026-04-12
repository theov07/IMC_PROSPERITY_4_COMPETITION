"""Naive passive market maker V7 — top of book + 5 toggleable improvements.

Core: always at best spread, full capacity, sweep absurd orders.

All 5 features are independently toggleable via params (0 = off):

  1. Asymmetric sizing (asym_strength):
     Reduce size on the side that would INCREASE |position|.
     asym_strength=0.0: disabled (symmetric)
     asym_strength=1.0: full asymmetry (overloaded side = 0, unwind side = full cap)

  2. Spread-dependent sizing (spread_min_frac):
     When spread is tight, reduce size (less edge per trade).
     spread_min_frac=1.0: disabled (always full cap)
     spread_min_frac=0.25: only 25% capacity when spread=1, scales up with spread

  3. Trade flow detection (flow_window):
     Classify recent market trades as aggressive buy/sell by comparing
     trade price to the previous tick's best bid/ask (the trade CSV has
     no buyer/seller info, so we infer side from the book).
       trade_price >= prev_best_ask → aggressive buy
       trade_price <= prev_best_bid → aggressive sell
       between → indeterminate, ignored
     If strong directional flow, reduce size on the side that would get
     picked off.
     flow_window=0: disabled
     flow_window=5: keep last 5 classified trades in rolling history

  4. Cooldown post-fill (cooldown_ticks):
     After a fill, skip quoting for N ticks to avoid whipsawing.
     cooldown_ticks=0: disabled
     cooldown_ticks=2: skip 2 ticks after fill

  5. Penny jump detection (pj_detect):
     If the best price changed by exactly 1 tick since last tick (someone
     jumped in front), don't tighten — just join best instead.
     pj_detect=0: disabled
     pj_detect=1: enabled

  5b. Penny jump size reaction (pj_size_frac):
     When a penny jump is detected, reduce size on the adverse side
     (the side that would get picked off if the jumper has a signal).
       bid jumped → reduce ask size (we'd sell into a rising market)
       ask jumped → reduce buy size (we'd buy into a falling market)
     pj_size_frac=1.0: disabled (full size always)
     pj_size_frac=0.5: half size on adverse side after jump

  5c. Penny jump quantity threshold (pj_qty_threshold):
     Modifies join-vs-tighten decision based on how much qty is at
     the new best (the jumper's order size).
       qty at best <= threshold → join (small order, fills fast, we're next)
       qty at best >  threshold → tighten (large wall, we'd never fill behind it)
     pj_qty_threshold=0: disabled (always join on jump, i.e. original pj_detect)
     pj_qty_threshold=5: re-tighten if jumper posted >= 5 units

  6. Queue-aware quoting (qty_join_threshold):
     Every tick, look at the actual qty sitting at best bid/ask.
     Supersedes pj_detect — no need to detect a "jump", we just react
     to the current queue depth at all times.
       qty at best bid <= threshold → join bid (small wall, we'll be next soon)
       qty at best bid >  threshold → tighten bid (large wall, go in front)
       same logic on ask side independently
     qty_join_threshold=0: disabled (always tighten when spread allows)
     qty_join_threshold=5: join if <= 5 units at best, tighten if > 5
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class NaiveTightMarketMakerV7Strategy(BaseStrategy):

    def _take_absurd_orders(
        self, order_depth: OrderDepth, mid: float, buy_cap: int, sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        take_edge = float(self.params.get("take_edge", 1.0))

        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > mid - take_edge or buy_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_price]
            qty = min(available, buy_cap)
            if qty > 0:
                orders.append(Order(self.product, ask_price, qty))
                buy_cap -= qty

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < mid + take_edge or sell_cap <= 0:
                break
            volume = order_depth.buy_orders[bid_price]
            qty = min(volume, sell_cap)
            if qty > 0:
                orders.append(Order(self.product, bid_price, -qty))
                sell_cap -= qty

        return orders, buy_cap, sell_cap

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        tighten_ticks = int(self.params.get("tighten_ticks", 1))
        asym_strength = float(self.params.get("asym_strength", 0.0))
        spread_min_frac = float(self.params.get("spread_min_frac", 1.0))
        flow_window = int(self.params.get("flow_window", 0))
        cooldown_ticks = int(self.params.get("cooldown_ticks", 0))
        pj_detect = int(self.params.get("pj_detect", 0))
        pj_size_frac = float(self.params.get("pj_size_frac", 1.0))
        pj_qty_threshold = int(self.params.get("pj_qty_threshold", 0))
        qty_join_threshold = int(self.params.get("qty_join_threshold", 0))
        join_size_frac = float(self.params.get("join_size_frac", 1.0))
        level2_ticks = int(self.params.get("level2_ticks", 0))
        level2_frac = float(self.params.get("level2_frac", 0.0))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        mid = (book.best_bid + book.best_ask) / 2.0

        # ── Sweep absurd orders ──
        take_orders, buy_cap, sell_cap = self._take_absurd_orders(
            order_depth, mid, buy_cap, sell_cap,
        )
        orders.extend(take_orders)

        # ── Clean book after sweep ──
        swept_ask_prices = {o.price for o in take_orders if o.quantity > 0}
        swept_bid_prices = {o.price for o in take_orders if o.quantity < 0}

        real_best_ask = book.best_ask
        for ask_p, _ in book.ask_levels:
            if ask_p not in swept_ask_prices:
                real_best_ask = ask_p
                break

        real_best_bid = book.best_bid
        for bid_p, _ in book.bid_levels:
            if bid_p not in swept_bid_prices:
                real_best_bid = bid_p
                break

        spread = real_best_ask - real_best_bid

        # ── Feature 4: Cooldown post-fill ──
        prev_position = memory.get("prev_position", 0)
        filled = position != prev_position
        memory["prev_position"] = position

        if cooldown_ticks > 0:
            if filled:
                memory["cooldown_remaining"] = cooldown_ticks
            remaining = memory.get("cooldown_remaining", 0)
            if remaining > 0:
                memory["cooldown_remaining"] = remaining - 1
                return orders, 0  # skip passive quoting, only keep take orders

        # ── Read previous tick's book (used by flow + pj_detect) ──
        prev_best_bid = memory.get("prev_best_bid")
        prev_best_ask = memory.get("prev_best_ask")

        # ── Feature 5: Penny jump detection ──
        do_tighten = True
        bid_jumped = False
        ask_jumped = False
        if pj_detect and prev_best_bid is not None and prev_best_ask is not None:
            bid_jumped = (real_best_bid == prev_best_bid + 1)
            ask_jumped = (real_best_ask == prev_best_ask - 1)
            if bid_jumped or ask_jumped:
                # 5c: qty threshold — re-tighten if jumper posted a large order
                if pj_qty_threshold > 0:
                    qty_at_bid = order_depth.buy_orders.get(real_best_bid, 0)
                    qty_at_ask = abs(order_depth.sell_orders.get(real_best_ask, 0))
                    large_bid = bid_jumped and qty_at_bid > pj_qty_threshold
                    large_ask = ask_jumped and qty_at_ask > pj_qty_threshold
                    if large_bid or large_ask:
                        do_tighten = True   # large wall → go in front
                    else:
                        do_tighten = False  # small order → join
                else:
                    do_tighten = False  # original behaviour: always join

        memory["prev_best_bid"] = real_best_bid
        memory["prev_best_ask"] = real_best_ask

        # ── Price: top of book ──
        # Feature 6: queue-aware quoting — per-side join vs tighten based on qty at best
        if qty_join_threshold > 0:
            qty_at_bid = order_depth.buy_orders.get(real_best_bid, 0)
            qty_at_ask = abs(order_depth.sell_orders.get(real_best_ask, 0))
            tighten_bid = spread >= 2 and do_tighten and qty_at_bid > qty_join_threshold
            tighten_ask = spread >= 2 and do_tighten and qty_at_ask > qty_join_threshold
        else:
            tighten_bid = spread >= 2 and do_tighten
            tighten_ask = spread >= 2 and do_tighten

        bid_price = min(real_best_bid + tighten_ticks, real_best_ask - 1) if tighten_bid else real_best_bid
        ask_price = max(real_best_ask - tighten_ticks, real_best_bid + 1) if tighten_ask else real_best_ask

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # ── Sizing: start from full capacity ──
        buy_size = buy_cap
        sell_size = sell_cap

        # ── Feature 1: Asymmetric sizing ──
        if asym_strength > 0.0:
            limit = self.position_limit()
            if limit > 0:
                inv_ratio = position / limit  # -1 to +1
                # When long (inv_ratio > 0): reduce buy, keep sell
                # When short (inv_ratio < 0): reduce sell, keep buy
                reduce_buy = max(0.0, inv_ratio * asym_strength)   # 0 to 1
                reduce_sell = max(0.0, -inv_ratio * asym_strength)  # 0 to 1
                buy_size = max(1, int(buy_cap * (1.0 - reduce_buy)))
                sell_size = max(1, int(sell_cap * (1.0 - reduce_sell)))

        # ── Feature 2: Spread-dependent sizing ──
        if spread_min_frac < 1.0:
            # Scale from spread_min_frac (at spread=1) to 1.0 (at spread>=3)
            spread_factor = min(1.0, spread_min_frac + (1.0 - spread_min_frac) * (spread - 1) / 2.0)
            buy_size = max(1, int(buy_size * spread_factor))
            sell_size = max(1, int(sell_size * spread_factor))

        # ── Feature 5b: Penny jump adverse-side size reduction ──
        if pj_size_frac < 1.0 and (bid_jumped or ask_jumped):
            if bid_jumped:
                sell_size = max(1, int(sell_size * pj_size_frac))  # bid jumped → price rising → reduce ask
            if ask_jumped:
                buy_size = max(1, int(buy_size * pj_size_frac))    # ask jumped → price falling → reduce bid

        # ── Feature 3: Trade flow detection (price-vs-book inference) ──
        if flow_window > 0:
            flow_history = memory.setdefault("flow_history", [])
            trades = state.market_trades.get(self.product, [])
            if trades and prev_best_bid is not None and prev_best_ask is not None:
                for t in trades:
                    if t.price >= prev_best_ask:
                        flow_history.append(t.quantity)   # aggressive buy
                    elif t.price <= prev_best_bid:
                        flow_history.append(-t.quantity)  # aggressive sell
            if len(flow_history) > flow_window:
                del flow_history[:-flow_window]

            if flow_history:
                net = sum(flow_history)
                total = sum(abs(x) for x in flow_history)
                if total > 0:
                    flow_strength = net / total
                    if flow_strength > 0.3:
                        sell_size = max(1, sell_size // 2)
                    elif flow_strength < -0.3:
                        buy_size = max(1, buy_size // 2)

        # ── Orders ──
        if join_size_frac < 1.0:
            if not tighten_bid and buy_size > 0:
                buy_size = max(1, int(buy_size * join_size_frac))
            if not tighten_ask and sell_size > 0:
                sell_size = max(1, int(sell_size * join_size_frac))

        bid_orders: List[Tuple[int, int]] = []
        ask_orders: List[Tuple[int, int]] = []

        def _split_level_size(total: int) -> Tuple[int, int]:
            if total <= 1 or level2_frac <= 0.0:
                return total, 0
            secondary = int(round(total * level2_frac))
            secondary = max(0, min(secondary, total - 1))
            return total - secondary, secondary

        can_two_level = (
            level2_frac > 0.0
            and level2_ticks > tighten_ticks
            and spread >= (2 * level2_ticks + 1)
        )
        level2_bid_price = min(real_best_bid + level2_ticks, real_best_ask - 1)
        level2_ask_price = max(real_best_ask - level2_ticks, real_best_bid + 1)

        primary_buy_size, secondary_buy_size = _split_level_size(buy_size) if (can_two_level and tighten_bid) else (buy_size, 0)
        primary_sell_size, secondary_sell_size = _split_level_size(sell_size) if (can_two_level and tighten_ask) else (sell_size, 0)

        if primary_buy_size > 0:
            bid_orders.append((bid_price, primary_buy_size))
        if secondary_buy_size > 0 and level2_bid_price > bid_price and level2_bid_price < ask_price:
            bid_orders.append((level2_bid_price, secondary_buy_size))

        if primary_sell_size > 0:
            ask_orders.append((ask_price, primary_sell_size))
        if secondary_sell_size > 0 and level2_ask_price < ask_price and level2_ask_price > bid_price:
            ask_orders.append((level2_ask_price, secondary_sell_size))

        for price, size in bid_orders:
            orders.append(Order(self.product, price, size))
        for price, size in ask_orders:
            orders.append(Order(self.product, price, -size))

        # ── logging ──
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "buy_size": buy_size,
                "sell_size": sell_size,
            },
        )

        return orders, 0
