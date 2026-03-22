import json
from datamodel import OrderDepth, TradingState, Order
from typing import List


class Trader:
    POSITION_LIMITS = {"EMERALDS": 80, "TOMATOES": 80}
    # EMA smoothing: ~7-period half-life — reacts fast enough to create
    # real aggressive fill opportunities when price deviates from fair value
    TOM_ALPHA = 0.15

    def run(self, state: TradingState):
        # Restore persisted state (EMA value survives across ticks)
        try:
            saved = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            saved = {}

        tom_ema: float | None = saved.get("tom_ema")

        result = {}

        for product in state.order_depths:
            limit = self.POSITION_LIMITS.get(product)
            if limit is None:
                continue

            order_depth = state.order_depths[product]
            position = state.position.get(product, 0)

            if product == "EMERALDS":
                # Rock-stable fair value: passive market-make at ±1
                result[product] = self._market_make(
                    "EMERALDS", order_depth, position, limit, 10000.0, skew=False
                )

            elif product == "TOMATOES":
                if not order_depth.buy_orders or not order_depth.sell_orders:
                    continue
                best_bid = max(order_depth.buy_orders)
                best_ask = min(order_depth.sell_orders)
                mid = (best_bid + best_ask) / 2.0

                # Update EMA: when price is above EMA → sell aggressively;
                # when price is below EMA → buy aggressively (mean-reversion)
                tom_ema = mid if tom_ema is None else self.TOM_ALPHA * mid + (1 - self.TOM_ALPHA) * tom_ema

                result[product] = self._market_make(
                    "TOMATOES", order_depth, position, limit, tom_ema, skew=True
                )

        # Persist EMA so it survives to the next tick
        return result, 0, json.dumps({"tom_ema": tom_ema})

    def _market_make(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        limit: int,
        fair_value: float,
        skew: bool,
    ) -> List[Order]:
        orders: List[Order] = []

        # Inventory skew: when long, shift quotes down to encourage sells;
        # when short, shift quotes up to encourage buys. Only for volatile products.
        inv_skew = round((position / limit) * 2) if skew else 0

        adjusted = fair_value - inv_skew

        # Aggressive: sweep all levels strictly better than our adjusted fair value
        for ask in sorted(order_depth.sell_orders):
            if ask >= adjusted:
                break
            qty = min(-order_depth.sell_orders[ask], limit - position)
            if qty > 0:
                orders.append(Order(product, ask, qty))
                position += qty

        for bid in sorted(order_depth.buy_orders, reverse=True):
            if bid <= adjusted:
                break
            qty = min(order_depth.buy_orders[bid], limit + position)
            if qty > 0:
                orders.append(Order(product, bid, -qty))
                position -= qty

        # Passive: full remaining capacity at adjusted fair value ± 1
        buy_p  = round(adjusted) - 1
        sell_p = round(adjusted) + 1
        if sell_p <= buy_p:
            sell_p = buy_p + 1

        remaining_buy  = limit - position
        remaining_sell = limit + position

        if remaining_buy > 0:
            orders.append(Order(product, buy_p, remaining_buy))
        if remaining_sell > 0:
            orders.append(Order(product, sell_p, -remaining_sell))

        return orders