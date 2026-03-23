import json
from typing import List, Dict

from datamodel import OrderDepth, TradingState, Order, Symbol


class Trader:
    """Basic Round 0 baseline trader (simple fair value + spread capture)."""

    POSITION_LIMITS = {"EMERALDS": 80, "TOMATOES": 80}

    def run(self, state: TradingState):
        # Load simple state
        try:
            saved = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            saved = {}

        result: Dict[Symbol, List[Order]] = {}

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []
            pos = state.position.get(product, 0)

            # Estimate fair value as mid of best bid/ask if available
            if order_depth.buy_orders and order_depth.sell_orders:
                best_bid = max(order_depth.buy_orders.keys())
                best_ask = min(order_depth.sell_orders.keys())
                fair = (best_bid + best_ask) / 2
            else:
                result[product] = orders
                continue

            # Simple spread capture: buy slightly below fair, sell slightly above
            buy_price = int(fair - 1)
            sell_price = int(fair + 1)

            limit = self.POSITION_LIMITS.get(product, 0)
            buy_qty = max(0, limit - pos)
            sell_qty = max(0, limit + pos)

            if buy_qty > 0:
                orders.append(Order(product, buy_price, min(5, buy_qty)))
            if sell_qty > 0:
                orders.append(Order(product, sell_price, -min(5, sell_qty)))

            result[product] = orders

        trader_data = json.dumps(saved)
        conversions = 0
        return result, conversions, trader_data
