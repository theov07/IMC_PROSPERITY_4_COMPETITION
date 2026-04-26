"""HYDROGEL_PACK market maker — v201: Mark 14 informed-trader gate.

Three variants built on top of HydroMMV200 (v200's guard + AR logic),
each wiring in Mark 14's observed trades as an additional signal.

Market trades arrive 1 tick delayed: what Mark 14 did at T-1 influences
our orders at T.  The signal is stored in memory["_mark14_signal"]
(+1 buy, -1 sell, 0 silent) for logging.

Variant 1 — HydroMMV201Ruled:
  Mark 14 active  → ignore our fair-value model; fire an aggressive taker
                    in his direction (follow at market).
  Mark 14 silent  → normal v200 MM logic.

Variant 2 — HydroMMV201Influenced:
  Always run normal v200 logic, then:
    Mark 14 bought → strip sell orders, scale up buy order sizes by
                     `mark14_agree_factor` (default 2.0).
    Mark 14 sold   → strip buy orders, scale up sell order sizes.
    Mark 14 silent → no change.

Variant 3 — HydroMMV201CancelAgainst:
  Always run normal v200 logic, then:
    Mark 14 bought → strip ONLY sell orders (cancel those opposing him).
    Mark 14 sold   → strip ONLY buy orders.
    Mark 14 silent → no change.

Config params (in addition to all v200 params):
  informed_trader_name  — counterparty name to track (default "Mark 14")
  follow_size           — taker size for Ruled variant (default 20)
  mark14_agree_factor   — size multiplier for Influenced variant (default 2.0)
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_4.tibo.hydro_strat_v200 import HydroMMV200


class HydroMMV201Base(HydroMMV200):
    """Extends HydroMMV200 with a Mark 14 signal helper."""

    def _get_mark14_signal(
        self, state: TradingState, memory: Dict[str, Any],
    ) -> int:
        """Read market_trades for the product and compute Mark 14's net direction.

        Returns +1 if Mark 14 net-bought, -1 if net-sold, 0 if not active.
        """
        trader = str(self.params.get("informed_trader_name", "Mark 14"))
        net = 0
        for trade in state.market_trades.get(self.product, []):
            if trade.buyer == trader:
                net += trade.quantity
            elif trade.seller == trader:
                net -= trade.quantity
        signal = 1 if net > 0 else (-1 if net < 0 else 0)
        memory["_mark14_signal"]  = signal
        memory["_mark14_net_vol"] = net
        return signal


class HydroMMV201Ruled(HydroMMV201Base):
    """Mark 14 fully rules: follow him aggressively when active, MM when silent."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        signal = self._get_mark14_signal(state, memory)

        if signal == 0:
            # Mark 14 silent → normal v200 logic
            return super().compute_orders(state, book, order_depth, position, memory)

        # Mark 14 active → ignore fair-value model, fire a taker in his direction
        follow_size = int(self.params.get("follow_size", 20))
        orders: List[Order] = []

        if signal > 0 and book.best_ask is not None:
            qty = min(self.buy_capacity(position), follow_size)
            if qty > 0:
                orders.append(Order(self.product, book.best_ask, qty))

        elif signal < 0 and book.best_bid is not None:
            qty = min(self.sell_capacity(position), follow_size)
            if qty > 0:
                orders.append(Order(self.product, book.best_bid, -qty))

        return orders, 0


class HydroMMV201Influenced(HydroMMV201Base):
    """Mark 14 influences: suppress opposing orders, scale up agreeing orders."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        signal = self._get_mark14_signal(state, memory)

        # Always run the full v200 strategy first
        orders, conv = super().compute_orders(state, book, order_depth, position, memory)

        if signal == 0:
            return orders, conv

        factor = float(self.params.get("mark14_agree_factor", 2.0))

        if signal > 0:
            # Mark 14 bought → remove sells, scale up buys
            scaled: List[Order] = []
            for o in orders:
                if o.quantity > 0:
                    new_qty = min(
                        self.buy_capacity(position),
                        int(o.quantity * factor),
                    )
                    scaled.append(Order(self.product, o.price, max(1, new_qty)))
            return scaled, conv

        else:
            # Mark 14 sold → remove buys, scale up sells
            scaled = []
            for o in orders:
                if o.quantity < 0:
                    new_qty = min(
                        self.sell_capacity(position),
                        int(abs(o.quantity) * factor),
                    )
                    scaled.append(Order(self.product, o.price, -max(1, new_qty)))
            return scaled, conv


class HydroMMV201CancelAgainst(HydroMMV201Base):
    """Mark 14 gate: only cancel orders that go against him, keep agreeing ones."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        signal = self._get_mark14_signal(state, memory)

        # Always run the full v200 strategy
        orders, conv = super().compute_orders(state, book, order_depth, position, memory)

        if signal == 0:
            return orders, conv

        if signal > 0:
            # Mark 14 bought → only strip sell orders (quantity < 0)
            orders = [o for o in orders if o.quantity > 0]
        else:
            # Mark 14 sold → only strip buy orders (quantity > 0)
            orders = [o for o in orders if o.quantity < 0]

        return orders, conv
