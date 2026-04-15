"""Osmium mean-reversion MM exploiting AR(1) ~ -0.5 on tick returns.

Extends NaiveTightMarketMakerV10Strategy with two additions:
  1. AR1 bias: a term `-ar_gain * last_return` is added to `trend_shift`.
     Since returns reverse ~50% tick-to-tick, a positive move implies the next
     move is negative — so we want to sell more aggressively. The term pushes
     adjusted_mid DOWN after an up-tick (encouraging takes on bids) and UP
     after a down-tick.
  2. Rolling EMA anchor: instead of a fixed `anchor_price`, the anchor is an
     EMA of mid with `anchor_alpha`. Set alpha=0 to use the fixed anchor.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.naive_tight_mm_v10 import NaiveTightMarketMakerV10Strategy


class OsmiumMeanRevStrategy(NaiveTightMarketMakerV10Strategy):

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

        mid = (book.best_bid + book.best_ask) / 2.0

        # EOD flatten: aggressive liquidation near end of day
        eod_ts = int(self.params.get("eod_flatten_ts", 0))
        if eod_ts > 0 and state.timestamp >= eod_ts and position != 0:
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
            return orders, 0

        ar_gain = float(self.params.get("ar_gain", 0.0))
        anchor_alpha = float(self.params.get("anchor_alpha", 0.0))
        fixed_anchor = float(self.params.get("anchor_price", 10000.0))

        # Rolling EMA anchor
        if anchor_alpha > 0.0:
            ema = memory.get("anchor_ema")
            if ema is None:
                ema = fixed_anchor if fixed_anchor else mid
            ema = anchor_alpha * mid + (1.0 - anchor_alpha) * ema
            memory["anchor_ema"] = ema
            self.params["anchor_price"] = ema

        # AR1 bias encoded as a mid shift BEFORE calling parent
        prev_mid = memory.get("osm_prev_mid")
        ar_shift = 0.0
        if prev_mid is not None and ar_gain > 0.0:
            last_return = mid - prev_mid
            # last_return > 0 (price went UP) → next move down → want to sell:
            # push adjusted_mid DOWN so buy_edge widens / sell_edge narrows.
            ar_shift = -ar_gain * last_return
        memory["osm_prev_mid"] = mid

        # Temporarily patch params so parent picks up extra trend_shift via
        # a fake increment on trend_sensitivity? No — simpler: override the
        # mean_rev trend_max_shift path by pre-biasing the anchor.
        # The parent computes: trend_shift = clamp((anchor - mid) * sens).
        # To add ar_shift, we move the anchor by ar_shift / sens.
        if ar_shift != 0.0:
            sens = float(self.params.get("trend_sensitivity", 1.0)) or 1.0
            self.params["anchor_price"] = float(self.params.get("anchor_price", fixed_anchor)) + ar_shift / sens

        try:
            result = super().compute_orders(state, book, order_depth, position, memory)
        finally:
            if anchor_alpha == 0.0:
                self.params["anchor_price"] = fixed_anchor

        return result
