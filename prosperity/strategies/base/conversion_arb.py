"""Conversion arbitrage strategy for cross-market products.

Exploits price differences between the local exchange and the foreign
market accessible via the conversion mechanism.  Accounts for transport
fees, import/export tariffs, and any observation-based signals.

Config params:
  min_edge: minimum profit per unit after all fees to trade (default 1.0)
  maker_size: max order size per tick (default 10)
  use_observations: whether to read ConversionObservation data (default True)
  observation_key: key in conversionObservations (defaults to self.product)
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class ConversionArbStrategy(BaseStrategy):

    def _get_foreign_prices(self, state: TradingState) -> Dict[str, float] | None:
        """Extract foreign bid/ask and fees from ConversionObservation."""
        if not self.params.get("use_observations", True):
            return None

        obs = state.observations
        if obs is None:
            return None

        key = self.params.get("observation_key", self.product)
        conv = getattr(obs, "conversionObservations", {})
        if not isinstance(conv, dict) or key not in conv:
            return None

        co = conv[key]
        return {
            "foreign_bid": co.bidPrice,
            "foreign_ask": co.askPrice,
            "transport": co.transportFees,
            "export_tariff": co.exportTariff,
            "import_tariff": co.importTariff,
        }

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        foreign = self._get_foreign_prices(state)
        orders: List[Order] = []
        conversions = 0

        min_edge = self.params.get("min_edge", 1.0)
        maker_size = self.params.get("maker_size", 10)

        if foreign is None:
            # No conversion data — fall back to basic MM or skip
            return orders, 0

        fb = foreign["foreign_bid"]
        fa = foreign["foreign_ask"]
        transport = foreign["transport"]
        export_t = foreign["export_tariff"]
        import_t = foreign["import_tariff"]

        # ── Strategy 1: Buy local, sell foreign via conversion ──
        # Net revenue = foreign_bid - transport - export_tariff
        # Cost = local ask price
        # Edge = revenue - cost
        if book.best_ask is not None:
            sell_foreign_revenue = fb - transport - export_t
            buy_local_cost = book.best_ask
            edge_buy_local = sell_foreign_revenue - buy_local_cost

            if edge_buy_local > min_edge:
                buy_cap = self.buy_capacity(position)
                qty = min(maker_size, buy_cap)
                if qty > 0:
                    orders.append(Order(self.product, book.best_ask, qty))

        # ── Strategy 2: Buy foreign via conversion, sell local ──
        # Cost = foreign_ask + transport + import_tariff
        # Revenue = local bid price
        # Edge = revenue - cost
        if book.best_bid is not None:
            buy_foreign_cost = fa + transport + import_t
            sell_local_revenue = book.best_bid
            edge_sell_local = sell_local_revenue - buy_foreign_cost

            if edge_sell_local > min_edge:
                sell_cap = self.sell_capacity(position)
                qty = min(maker_size, sell_cap)
                if qty > 0:
                    orders.append(Order(self.product, book.best_bid, -qty))

        # ── Conversion requests to unwind inventory ──
        # If we have a long position, convert (sell abroad)
        # If we have a short position, convert (buy from abroad)
        if position > 0:
            net_sell = fb - transport - export_t
            if book.best_bid is not None and net_sell > book.best_bid:
                conversions = position  # convert all
        elif position < 0:
            net_buy_cost = fa + transport + import_t
            if book.best_ask is not None and net_buy_cost < book.best_ask:
                conversions = position  # negative = buy from abroad

        memory["foreign"] = foreign
        memory["position"] = position

        return orders, conversions
