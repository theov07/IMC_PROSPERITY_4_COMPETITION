from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List

class Trader:
    POSITION_LIMITS = {
        "EMERALDS": 80,
        "TOMATOES": 80
    }

    def run(self, state: TradingState):
        result = {}

        for product in state.order_depths:
            order_depth = state.order_depths[product]
            orders: List[Order] = []

            position = state.position.get(product, 0)
            limit = self.POSITION_LIMITS.get(product)
            if limit is None:
                continue

            if product == "EMERALDS":
                fair_value = 10000
                orders += self.trade_stable_product(product, order_depth, position, limit, fair_value)

            elif product == "TOMATOES":
                orders += self.trade_tomatoes(product, order_depth, position, limit)

            result[product] = orders

        return result, 0, ""

    def trade_stable_product(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        limit: int,
        fair_value: int
    ) -> List[Order]:
        orders: List[Order] = []

        # BUY from the market if asks are below fair value
        if order_depth.sell_orders:
            best_ask = min(order_depth.sell_orders.keys())
            best_ask_volume = order_depth.sell_orders[best_ask]  # usually negative

            if best_ask < fair_value:
                buy_qty = min(-best_ask_volume, limit - position)
                if buy_qty > 0:
                    orders.append(Order(product, best_ask, buy_qty))
                    position += buy_qty

        # SELL to the market if bids are above fair value
        if order_depth.buy_orders:
            best_bid = max(order_depth.buy_orders.keys())
            best_bid_volume = order_depth.buy_orders[best_bid]

            if best_bid > fair_value:
                sell_qty = min(best_bid_volume, limit + position)
                if sell_qty > 0:
                    orders.append(Order(product, best_bid, -sell_qty))
                    position -= sell_qty

        # Passive market making around fair value
        buy_quote = fair_value - 1
        sell_quote = fair_value + 1

        remaining_buy = limit - position
        remaining_sell = limit + position

        if remaining_buy > 0:
            orders.append(Order(product, buy_quote, min(10, remaining_buy)))

        if remaining_sell > 0:
            orders.append(Order(product, sell_quote, -min(10, remaining_sell)))

        return orders

    def trade_tomatoes(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        limit: int
    ) -> List[Order]:
        orders: List[Order] = []

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        best_bid_volume = order_depth.buy_orders[best_bid]
        best_ask_volume = order_depth.sell_orders[best_ask]  # negative

        mid_price = (best_bid + best_ask) / 2

        # Aggressive fills if price looks favorable
        if best_ask < mid_price:
            buy_qty = min(-best_ask_volume, limit - position)
            if buy_qty > 0:
                orders.append(Order(product, best_ask, buy_qty))
                position += buy_qty

        if best_bid > mid_price:
            sell_qty = min(best_bid_volume, limit + position)
            if sell_qty > 0:
                orders.append(Order(product, best_bid, -sell_qty))
                position -= sell_qty

        # Passive quotes around the mid
        buy_quote = int(mid_price - 1)
        sell_quote = int(mid_price + 1)

        remaining_buy = limit - position
        remaining_sell = limit + position

        if remaining_buy > 0:
            orders.append(Order(product, buy_quote, min(10, remaining_buy)))

        if remaining_sell > 0:
            orders.append(Order(product, sell_quote, -min(10, remaining_sell)))

        return orders