"""Osmium mean-rev V18 — vol-adaptive AR gain + layered passive.

Combines two orthogonal improvements:
  V17: vol-adaptive AR gain (reduce ar_gain in low-vol regime)
  V14: layered passive on favourable mean-rev side (best±2)

Both independently gave +300-400 PnL over v1 champion.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.osmium_mr import OsmiumMeanRevStrategy


class OsmiumMeanRevV18Strategy(OsmiumMeanRevStrategy):

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

        # ── Vol-adaptive AR gain (from v17) ──
        vol_window = int(self.params.get("vol_ema_window", 10))
        vol_threshold = float(self.params.get("vol_threshold", 5.0))
        ar_gain_hi = float(self.params.get("ar_gain_hi", 1.0))
        ar_gain_lo = float(self.params.get("ar_gain_lo", 0.7))

        prev_mid = memory.get("osm_prev_mid")
        if prev_mid is not None:
            ret_sq = (mid - prev_mid) ** 2
            alpha = 2.0 / (vol_window + 1)
            ema_sq = memory.get("vol_ema_sq", ret_sq)
            ema_sq = alpha * ret_sq + (1.0 - alpha) * ema_sq
            memory["vol_ema_sq"] = ema_sq
            vol = ema_sq ** 0.5
            if vol > vol_threshold:
                self.params["ar_gain"] = ar_gain_hi
            else:
                self.params["ar_gain"] = ar_gain_lo
        else:
            self.params["ar_gain"] = ar_gain_lo

        # ── Base orders from parent ──
        orders, convs = super().compute_orders(state, book, order_depth, position, memory)

        # ── Layered passive (from v14) ──
        dev_thr = float(self.params.get("layer_dev_threshold", 0.0))
        layer_size = int(self.params.get("layer_size", 0))
        if dev_thr <= 0.0 or layer_size <= 0:
            return orders, convs

        anchor = float(self.params.get("anchor_price", 10000.0))
        dev = mid - anchor

        best_bid = book.best_bid
        best_ask = book.best_ask
        spread = best_ask - best_bid
        if spread < 4:
            return orders, convs

        limit = int(self.params.get("position_limit", 80))
        filled_buy = sum(o.quantity for o in orders if o.quantity > 0)
        filled_sell = sum(-o.quantity for o in orders if o.quantity < 0)
        buy_room = limit - position - filled_buy
        sell_room = limit + position - filled_sell

        extras: List[Order] = []
        if dev < -dev_thr and buy_room > 0:
            price = best_bid + 2
            if price < best_ask:
                qty = min(layer_size, buy_room)
                extras.append(Order(self.product, price, qty))
        elif dev > dev_thr and sell_room > 0:
            price = best_ask - 2
            if price > best_bid:
                qty = min(layer_size, sell_room)
                extras.append(Order(self.product, price, -qty))

        return orders + extras, convs
