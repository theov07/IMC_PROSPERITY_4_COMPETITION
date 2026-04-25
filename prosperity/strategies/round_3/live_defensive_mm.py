"""Round 3 live-defensive market maker for delta-1 products.

This is deliberately book-following rather than anchor-based.  The live Round 3
logs showed that a rigid fair value can build toxic inventory when the market
drifts away from the historical anchor.  This strategy keeps the stable
``best_bid+1 / best_ask-1`` behavior, but throttles the side that would add
inventory into a short-term adverse trend and boosts the unwind side.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class R3LiveDefensiveMMStrategy(BaseStrategy):
    """Book-following MM with inventory and short-trend protection."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None:
            return [], 0

        mid = book.mid_price
        if mid is None:
            return [], 0

        trend = self._update_trend(float(mid), memory)
        bid_price, ask_price = self._base_quotes(book)
        bid_size, ask_size = self._side_sizes(position, trend)

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        if bid_price is not None and buy_cap > 0 and bid_size > 0:
            orders.append(Order(self.product, bid_price, min(bid_size, buy_cap)))
        if ask_price is not None and sell_cap > 0 and ask_size > 0:
            orders.append(Order(self.product, ask_price, -min(ask_size, sell_cap)))

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price if bid_size > 0 else None,
            ask_price=ask_price if ask_size > 0 else None,
            extras={
                "trend": round(trend, 2),
                "bid_size": bid_size,
                "ask_size": ask_size,
            },
        )
        memory["last_bid_price"] = bid_price if bid_size > 0 else None
        memory["last_ask_price"] = ask_price if ask_size > 0 else None
        memory["trend"] = trend
        return orders, 0

    def _update_trend(self, mid: float, memory: Dict[str, Any]) -> float:
        alpha = float(self.params.get("trend_alpha", 0.05))
        ema = memory.get("trend_ema")
        if ema is None:
            memory["trend_ema"] = mid
            return 0.0
        ema_f = float(ema)
        new_ema = alpha * mid + (1.0 - alpha) * ema_f
        memory["trend_ema"] = new_ema
        return mid - new_ema

    def _base_quotes(self, book: BookSnapshot) -> tuple[int | None, int | None]:
        tighten_ticks = int(self.params.get("tighten_ticks", 1))
        bid_price = book.best_bid
        ask_price = book.best_ask

        if book.spread is not None and book.spread >= 2:
            bid_price = min(book.best_bid + tighten_ticks, book.best_ask - 1)
            ask_price = max(book.best_ask - tighten_ticks, book.best_bid + 1)

        return int(bid_price), int(ask_price)

    def _side_sizes(self, position: int, trend: float) -> tuple[int, int]:
        limit = max(1, self.position_limit())
        base = int(self.params.get("maker_size", 30))
        min_size = int(self.params.get("min_maker_size", 4))
        stop_ratio = float(self.params.get("inventory_stop_ratio", 0.62))
        reduce_ratio = float(self.params.get("inventory_reduce_ratio", 0.35))
        unwind_boost = float(self.params.get("unwind_boost", 1.45))
        trend_threshold = float(self.params.get("trend_threshold", 2.0))
        hard_trend = float(self.params.get("hard_trend_threshold", 7.0))

        bid_size = base
        ask_size = base
        abs_ratio = abs(position) / limit

        if position > 0:
            bid_size = max(0, int(round(base * max(0.0, 1.0 - abs_ratio / max(reduce_ratio, 1e-6)))))
            ask_size = int(round(base * (1.0 + unwind_boost * abs_ratio)))
            if abs_ratio >= stop_ratio:
                bid_size = 0
        elif position < 0:
            ask_size = max(0, int(round(base * max(0.0, 1.0 - abs_ratio / max(reduce_ratio, 1e-6)))))
            bid_size = int(round(base * (1.0 + unwind_boost * abs_ratio)))
            if abs_ratio >= stop_ratio:
                ask_size = 0

        # Do not add inventory into a strong adverse short-term drift.
        if trend <= -hard_trend:
            bid_size = 0
        elif trend < -trend_threshold:
            bid_size = min(bid_size, max(min_size, base // 3))

        if trend >= hard_trend:
            ask_size = 0
        elif trend > trend_threshold:
            ask_size = min(ask_size, max(min_size, base // 3))

        if 0 < bid_size < min_size:
            bid_size = min_size
        if 0 < ask_size < min_size:
            ask_size = min_size

        return max(0, bid_size), max(0, ask_size)

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        trend = memory.get("trend")
        return {"R3Trend": float(trend)} if trend is not None else {}
