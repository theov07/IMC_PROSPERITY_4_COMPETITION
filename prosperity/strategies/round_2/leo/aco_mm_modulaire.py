"""ASH_COATED_OSMIUM flat-modular strategy (Round 2, Leo).

Ported from Theo's `AshCoatedOsmiumMMStrategy` (submission 283574), adopted by Leo.
Pure penny-improve MM with gap fills when the book is empty/one-sided, hard
position cap (default +/-30 of 80), inventory-skew sizing and a minimum-spread
filter. No directional signal and no active takers.

Modules (in order of invocation inside compute_orders):

  _update_last_prices        cache last_bid / last_ask in memory
  _handle_empty_book         gap quotes when both sides empty
  _handle_one_sided_book     gap quote on the empty side only
  _compute_inventory_sizes   apply skew + hard cap
  _compute_quote_prices      penny-improve with safety collapse
  _emit_orders               assemble Order list
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class AcoMMModulaireStrategy(BaseStrategy):
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        if book.best_bid is not None:
            memory["_last_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_last_ask"] = book.best_ask

        gap_shift = int(self.params.get("empty_side_shift", 85))
        gap_size = int(self.params.get("gap_size", 30))
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if book.best_bid is None and book.best_ask is None:
            last_bid = memory.get("_last_bid")
            last_ask = memory.get("_last_ask")
            if last_bid is None or last_ask is None:
                return orders, 0
            gap_buy = last_bid - gap_shift
            gap_sell = last_ask + gap_shift
            if buy_cap > 0:
                orders.append(Order(self.product, gap_buy, min(gap_size, buy_cap)))
            if sell_cap > 0:
                orders.append(Order(self.product, gap_sell, -min(gap_size, sell_cap)))
            return orders, 0

        if book.best_bid is None:
            last_bid = memory.get("_last_bid")
            if last_bid is not None and buy_cap > 0:
                orders.append(Order(self.product, last_bid - gap_shift, min(gap_size, buy_cap)))
            return orders, 0

        if book.best_ask is None:
            last_ask = memory.get("_last_ask")
            if last_ask is not None and sell_cap > 0:
                orders.append(Order(self.product, last_ask + gap_shift, -min(gap_size, sell_cap)))
            return orders, 0

        spread = book.best_ask - book.best_bid
        min_spread = int(self.params.get("min_spread_to_quote", 4))
        if spread < min_spread:
            return orders, 0

        base_size = int(self.params.get("base_size", 10))
        inv_skew_threshold = int(self.params.get("inv_skew_threshold", 15))
        inv_reduce_factor = float(self.params.get("inv_reduce_factor", 0.4))
        max_pos = int(self.params.get("max_pos_to_buy", 30))
        min_pos = int(self.params.get("min_pos_to_sell", -30))

        bid_size = base_size
        ask_size = base_size
        if position > inv_skew_threshold:
            bid_size = max(1, int(base_size * inv_reduce_factor))
            ask_size = min(sell_cap, int(base_size * (1.0 + inv_reduce_factor)))
        elif position < -inv_skew_threshold:
            ask_size = max(1, int(base_size * inv_reduce_factor))
            bid_size = min(buy_cap, int(base_size * (1.0 + inv_reduce_factor)))

        if position >= max_pos:
            bid_size = 0
        if position <= min_pos:
            ask_size = 0

        bid_size = min(bid_size, buy_cap)
        ask_size = min(ask_size, sell_cap)

        improve_ticks = int(self.params.get("improve_ticks", 1))
        bid_price = book.best_bid + improve_ticks
        ask_price = book.best_ask - improve_ticks
        if bid_price >= ask_price:
            bid_price = book.best_bid
            ask_price = book.best_ask

        if bid_size > 0:
            orders.append(Order(self.product, bid_price, bid_size))
        if ask_size > 0:
            orders.append(Order(self.product, ask_price, -ask_size))
        return orders, 0
