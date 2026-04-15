"""Fusion B v4 — regime split + slope-biased residual z crossing.

Strong trend regime (|trend_ticks| >= regime_trend_cut): reuse v2 trend-biased
accumulation (delegated to the V5 parent via super().compute_orders).

Neutral regime (|trend_ticks| < regime_trend_cut): mean-reversion on the
residual z-score of (mid - fv), with a slope-aware sell threshold so the
signal is not washed out by a drifting fair value.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_1.regression_mm_v5 import Round1RegressionMMV5Strategy


class LeoFusionBV4Strategy(Round1RegressionMMV5Strategy):

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

        mid = book.mid_price if book.mid_price is not None else (book.best_bid + book.best_ask) / 2.0
        stats = self._update_regression(state=state, mid=mid, memory=memory)
        trend_ticks = stats["trend_ticks"]

        regime_cut = float(self.params.get("v4_regime_trend_cut", 1.0))
        if abs(trend_ticks) >= regime_cut:
            # Strong trend: delegate to V5 parent (v2 behavior)
            return super().compute_orders(
                state=state, book=book, order_depth=order_depth,
                position=position, memory=memory,
            )

        # Neutral regime: residual z-score crossing, slope-biased
        fv = stats["fair_value"]
        residual_z = stats["residual_z"]
        slope = stats["slope"]

        buy_z = float(self.params.get("v4_buy_z", 1.0))
        sell_z = float(self.params.get("v4_sell_z", 1.0))
        slope_bias_k = float(self.params.get("v4_slope_bias_k", 25.0))
        passive_spread = float(self.params.get("v4_passive_spread", 3.0))

        # Slope bias: in an up-drift, require more edge to sell
        sell_z_eff = sell_z + slope_bias_k * max(0.0, slope)
        buy_z_eff = buy_z + slope_bias_k * max(0.0, -slope)

        orders: List[Order] = []

        bid_price = min(round(fv - passive_spread), book.best_ask - 1)
        ask_price = max(round(fv + passive_spread), book.best_bid + 1)
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # Buy side: only if z indicates cheap vs fv
        if residual_z <= -buy_z_eff:
            for ask_p in sorted(order_depth.sell_orders):
                if ask_p > fv or buy_cap <= 0:
                    break
                qty = min(-order_depth.sell_orders[ask_p], buy_cap)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, ask_p, qty))
                buy_cap -= qty

        # Sell side: only if z indicates rich vs fv
        if residual_z >= sell_z_eff:
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if bid_p < fv or sell_cap <= 0:
                    break
                qty = min(order_depth.buy_orders[bid_p], sell_cap)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, bid_p, -qty))
                sell_cap -= qty

        limit = self.position_limit()
        passive_max = int(self.params.get("v4_passive_size", limit))
        buy_size = max(0, min(buy_cap, passive_max, limit - position))
        sell_size = max(0, min(sell_cap, passive_max, limit + position))
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "reg_slope": round(slope, 4),
                "reg_r2": round(stats["r2"], 3),
                "trend_ticks": round(trend_ticks, 2),
                "residual_z": round(residual_z, 2),
                "sell_z_eff": round(sell_z_eff, 2),
                "buy_z_eff": round(buy_z_eff, 2),
                "fair_value": round(fv, 2),
                "regime": "neutral",
            },
        )
        return orders, 0
