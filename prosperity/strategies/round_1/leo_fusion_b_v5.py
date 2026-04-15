"""Fusion B v5 — buy-and-hold core + scalp MM on top.

Philosophy: IPR trends up, so we want to ride +80 like v2. But around that
core we scalp the oscillations: whenever we're at max, sell a slice at
fv+edge (top of book), then buy it back at fv-edge. Core never drops below
scalp_floor (e.g. 60), so trend PnL is preserved.

Accumulation phase: if position < target, take any ask <= fv aggressively
and quote a fat bid at fv-1 to reach target asap (same as v2's bullish take).

Scalp phase: once position is in [scalp_floor, target]:
  - Sell side: take any bid >= fv + scalp_edge down to scalp_floor; place
    passive ask at fv + scalp_spread.
  - Buy side: take any ask <= fv - scalp_edge up to target; place passive
    bid at fv - scalp_spread.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_1.regression_mm_v5 import Round1RegressionMMV5Strategy


class LeoFusionBV5Strategy(Round1RegressionMMV5Strategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []
        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        mid = book.mid_price if book.mid_price is not None else (book.best_bid + book.best_ask) / 2.0
        stats = self._update_regression(state=state, mid=mid, memory=memory)
        fv = stats["fair_value"]
        trend_ticks = stats["trend_ticks"]
        residual_z = stats["residual_z"]

        limit = self.position_limit()
        target = int(self.params.get("v5_core_target", limit))           # +80
        scalp_range = int(self.params.get("v5_scalp_range", 20))          # core floats in [60, 80]
        scalp_floor = target - scalp_range
        scalp_edge = float(self.params.get("v5_scalp_edge", 1.0))         # crossing threshold
        scalp_spread = float(self.params.get("v5_scalp_spread", 2.0))     # passive quote spread
        accum_take_edge = float(self.params.get("v5_accum_take_edge", 0.0))  # accept asks <= fv - edge

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # ── Accumulation: push position up to target via takes ───────────────
        if position < target:
            # Take any ask at or below fv (cheap vs regression)
            for ask_p in sorted(order_depth.sell_orders):
                if ask_p > fv - accum_take_edge or buy_cap <= 0:
                    break
                # Don't overshoot target
                room = target - position - sum(o.quantity for o in orders if o.quantity > 0)
                if room <= 0:
                    break
                qty = min(-order_depth.sell_orders[ask_p], buy_cap, room)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, ask_p, qty))
                buy_cap -= qty

        # ── Scalp sells: sell down to scalp_floor at bids >= fv + edge ──────
        if position > scalp_floor:
            scalp_sell_room = position - scalp_floor - sum(
                -o.quantity for o in orders if o.quantity < 0
            )
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if bid_p < fv + scalp_edge or sell_cap <= 0 or scalp_sell_room <= 0:
                    break
                qty = min(order_depth.buy_orders[bid_p], sell_cap, scalp_sell_room)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, bid_p, -qty))
                sell_cap -= qty
                scalp_sell_room -= qty

        # ── Scalp buys: buy back up to target at asks <= fv - edge ──────────
        if position < target:
            scalp_buy_room = target - position - sum(
                o.quantity for o in orders if o.quantity > 0
            )
            for ask_p in sorted(order_depth.sell_orders):
                if ask_p > fv - scalp_edge or buy_cap <= 0 or scalp_buy_room <= 0:
                    break
                qty = min(-order_depth.sell_orders[ask_p], buy_cap, scalp_buy_room)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, ask_p, qty))
                buy_cap -= qty
                scalp_buy_room -= qty

        # ── Passive quotes (scalp makes) ─────────────────────────────────────
        bid_price = min(round(fv - scalp_spread), book.best_ask - 1)
        ask_price = max(round(fv + scalp_spread), book.best_bid + 1)
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # Passive buy: size = room to target
        pending_buy = sum(o.quantity for o in orders if o.quantity > 0)
        passive_buy_size = max(0, min(buy_cap, target - position - pending_buy))

        # Passive sell: size = room above scalp_floor
        pending_sell = sum(-o.quantity for o in orders if o.quantity < 0)
        passive_sell_size = max(0, min(sell_cap, position - scalp_floor - pending_sell))

        passive_cap = int(self.params.get("v5_passive_size", 20))
        passive_buy_size = min(passive_buy_size, passive_cap)
        passive_sell_size = min(passive_sell_size, passive_cap)

        if passive_buy_size > 0:
            orders.append(Order(self.product, bid_price, passive_buy_size))
        if passive_sell_size > 0:
            orders.append(Order(self.product, ask_price, -passive_sell_size))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price

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
                "fair_value": round(fv, 2),
                "core_target": target,
                "scalp_floor": scalp_floor,
            },
        )
        return orders, 0
