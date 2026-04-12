"""Naive passive market maker V5 — best spread + all improvements.

Core: ALWAYS be at the best spread, full capacity. On top of that:

  1. Inventory skew (from V4):
     Shift bid/ask when position accumulates to favour unwinding.
     Param: inv_skew_ticks (0 = disabled)

  2. Adaptive tighten:
     When spread is wide (>= spread_extra_threshold), tighten by an extra tick.
     Wider spread = more room = safer to intercale deeper.
     Param: spread_extra_threshold (0 = disabled, e.g. 4 = extra tighten when spread >= 4)

  3. Size scaling near position limit:
     When |position| / limit exceeds size_reduce_ratio, cut quoting size
     on the overloaded side (the side that would increase |position|).
     This avoids getting stuck at the limit.
     Param: size_reduce_ratio (1.0 = disabled, e.g. 0.75 = cut at 75% inventory)

  4. Imbalance filter:
     When book imbalance is strong, only tighten on the favourable side.
     Positive imbalance (more bid volume) = price likely to rise = safe to tighten ask.
     Param: imb_threshold (0.0 = disabled, e.g. 0.3 = filter when |imbalance| > 0.3)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class NaiveTightMarketMakerV5Strategy(BaseStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        # ── params ──
        base_tighten = int(self.params.get("tighten_ticks", 1))
        inv_skew_ticks = int(self.params.get("inv_skew_ticks", 0))
        spread_extra_threshold = int(self.params.get("spread_extra_threshold", 0))
        size_reduce_ratio = float(self.params.get("size_reduce_ratio", 1.0))
        imb_threshold = float(self.params.get("imb_threshold", 0.0))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        spread = book.best_ask - book.best_bid

        # ── 2. Adaptive tighten ──
        tighten = base_tighten
        if spread_extra_threshold > 0 and spread >= spread_extra_threshold:
            tighten = base_tighten + 1

        # ── 4. Imbalance filter: asymmetric tighten ──
        tighten_bid = tighten
        tighten_ask = tighten
        if imb_threshold > 0.0 and book.imbalance is not None:
            if book.imbalance > imb_threshold:
                # More bid volume → price likely to rise → safe to tighten ask, cautious on bid
                tighten_bid = max(0, tighten - 1)
            elif book.imbalance < -imb_threshold:
                # More ask volume → price likely to fall → safe to tighten bid, cautious on ask
                tighten_ask = max(0, tighten - 1)

        # ── Price logic ──
        if spread >= 2:
            bid_price = min(book.best_bid + tighten_bid, book.best_ask - 1)
            ask_price = max(book.best_ask - tighten_ask, book.best_bid + 1)
        else:
            bid_price = book.best_bid
            ask_price = book.best_ask

        # ── 1. Inventory skew ──
        limit = self.position_limit()
        inv_ratio = position / limit if limit > 0 else 0.0
        skew = round(inv_ratio * inv_skew_ticks)

        bid_price = bid_price - skew
        ask_price = ask_price - skew

        # safety: never cross
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # ── 3. Size scaling near position limit ──
        buy_size = buy_cap
        sell_size = sell_cap

        if size_reduce_ratio < 1.0 and limit > 0:
            abs_ratio = abs(position) / limit
            if abs_ratio >= size_reduce_ratio:
                if position > 0:
                    # Long → cut buy size (don't add more), keep sell full
                    buy_size = max(1, buy_cap // 3)
                elif position < 0:
                    # Short → cut sell size, keep buy full
                    sell_size = max(1, sell_cap // 3)

        # ── Orders ──
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        # ── memory / logging ──
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_spread"] = book.spread
        memory["last_skew"] = skew

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={"skew": skew, "position": position},
        )

        return orders, 0
