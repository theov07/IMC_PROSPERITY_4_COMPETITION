"""Classic market-making strategy with microprice fair value + inventory skew.

Refactored from the original round0.py into the BaseStrategy interface.
Supports multiple fair-value modes: fixed, anchored_microprice, microprice_ema, mid_ema.
"""

from __future__ import annotations

from math import ceil, floor
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


def _ewma(previous: float | None, current: float, alpha: float) -> float:
    if previous is None:
        return current
    return alpha * current + (1.0 - alpha) * previous


class MarketMakerStrategy(BaseStrategy):

    # ── fair value ───────────────────────────────────────────────────
    def _estimate_fair(self, book: BookSnapshot, memory: Dict[str, Any]) -> float:
        p = self.params
        previous_fair = memory.get("fair")
        reference = book.microprice or book.mid_price or p.get("anchor_price") or previous_fair or 0.0

        mode = p.get("fair_mode", "microprice_ema")
        alpha = p.get("ema_alpha", 0.15)

        if mode == "fixed":
            fair = p.get("anchor_price") or reference
        elif mode == "anchored_microprice":
            anchor = p.get("anchor_price") or reference
            w = p.get("anchor_weight", 0.9)
            blended = w * anchor + (1.0 - w) * reference
            fair = _ewma(previous_fair, blended, alpha)
        elif mode == "mid_ema":
            spot = book.mid_price if book.mid_price is not None else reference
            fair = _ewma(previous_fair, spot, alpha)
        else:  # microprice_ema (default)
            fair = _ewma(previous_fair, reference, alpha)

        memory["fair"] = fair
        return fair

    # ── aggressive taking ────────────────────────────────────────────
    def _take_opportunities(
        self, order_depth: OrderDepth, fair: float, buy_cap: int, sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        edge = self.params.get("take_edge", 1.0)

        for ask_price in sorted(order_depth.sell_orders):
            available = -order_depth.sell_orders[ask_price]
            if ask_price > fair - edge or buy_cap <= 0:
                break
            qty = min(available, buy_cap)
            if qty > 0:
                orders.append(Order(self.product, ask_price, qty))
                buy_cap -= qty

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            volume = order_depth.buy_orders[bid_price]
            if bid_price < fair + edge or sell_cap <= 0:
                break
            qty = min(volume, sell_cap)
            if qty > 0:
                orders.append(Order(self.product, bid_price, -qty))
                sell_cap -= qty

        return orders, buy_cap, sell_cap

    # ── inventory bias ───────────────────────────────────────────────
    def _inventory_bias(self, position: int) -> int:
        limit = self.position_limit()
        if limit <= 0:
            return 0
        aversion = self.params.get("inventory_aversion", 1.0)
        max_ticks = self.params.get("max_inventory_bias_ticks", 3)
        raw = (position / float(limit)) * aversion * max_ticks
        return int(round(max(-max_ticks, min(max_ticks, raw))))

    # ── passive quoting ──────────────────────────────────────────────
    def _quote(
        self, book: BookSnapshot, fair: float, position: int, buy_cap: int, sell_cap: int,
    ) -> List[Order]:
        orders: List[Order] = []
        p = self.params
        half_spread = p.get("quote_half_spread", 2)
        maker_size = p.get("maker_size", 12)

        bias = self._inventory_bias(position)
        adj_fair = fair - bias

        target_bid = floor(adj_fair - half_spread)
        target_ask = ceil(adj_fair + half_spread)

        if p.get("join_best", True) and book.best_bid is not None and book.best_ask is not None:
            improve = p.get("improve_ticks", 1)
            inside_bid = min(book.best_bid + improve, book.best_ask - 1)
            inside_ask = max(book.best_ask - improve, book.best_bid + 1)
            target_bid = max(target_bid, inside_bid)
            target_ask = min(target_ask, inside_ask)

        if book.best_ask is not None:
            target_bid = min(target_bid, book.best_ask - 1)
        if book.best_bid is not None:
            target_ask = max(target_ask, book.best_bid + 1)
        if target_ask <= target_bid:
            target_ask = target_bid + 1

        # Size logic
        quote_buy = min(buy_cap, maker_size)
        quote_sell = min(sell_cap, maker_size)

        limit = self.position_limit()
        inv_ratio = abs(position) / float(limit) if limit else 0.0

        if inv_ratio >= 0.85:
            quote_buy = max(1, quote_buy // 2)
            quote_sell = max(1, quote_sell // 2)

        # Lean harder on unwind side
        if position > 0:
            quote_sell = min(sell_cap, max(quote_sell, min(maker_size * 2, abs(position) // 4 + 1)))
        elif position < 0:
            quote_buy = min(buy_cap, max(quote_buy, min(maker_size * 2, abs(position) // 4 + 1)))

        # Cut quoting on overloaded side
        if inv_ratio >= 0.75:
            if position > 0:
                quote_buy = 0
            elif position < 0:
                quote_sell = 0

        if quote_buy > 0:
            orders.append(Order(self.product, target_bid, quote_buy))
        if quote_sell > 0:
            orders.append(Order(self.product, target_ask, -quote_sell))

        return orders

    # ── main entry ───────────────────────────────────────────────────
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        fair = self._estimate_fair(book, memory)
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        take_orders, buy_cap, sell_cap = self._take_opportunities(order_depth, fair, buy_cap, sell_cap)
        quote_orders = self._quote(book, fair, position, buy_cap, sell_cap)

        return take_orders + quote_orders, 0
