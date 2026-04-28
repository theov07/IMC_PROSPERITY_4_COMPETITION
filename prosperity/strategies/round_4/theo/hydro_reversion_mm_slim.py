from datamodel import Order, TradingState

from prosperity.strategies.base.base import BaseStrategy


class R4HydroReversionMMSlimStrategy(BaseStrategy):
    def compute_orders(self, state, book, order_depth, position, memory):
        bb = book.best_bid
        ba = book.best_ask
        mid = book.mid_price
        if bb is None or ba is None or mid is None:
            return [], 0

        ema = memory.get("ema")
        fema = memory.get("fast_ema")
        ema = mid if ema is None else 0.006 * mid + 0.994 * float(ema)
        fema = mid if fema is None else 0.025 * mid + 0.975 * float(fema)
        memory["ema"] = ema
        memory["fast_ema"] = fema

        dev = mid - ema
        trend = fema - ema
        memory["prev_trend"] = trend

        bid = min(int(bb) + 1, int(ba) - 1) if book.spread is not None and book.spread >= 2 else int(bb)
        ask = max(int(ba) - 1, int(bb) + 1) if book.spread is not None and book.spread >= 2 else int(ba)

        bid_size = 22
        ask_size = 22
        if abs(trend) < 8.0:
            if dev > 6.0 and position > -12:
                bid_size = 0
                ask_size = 22 + min(12, int(abs(dev) // 4))
            elif dev < -6.0 and position < 12:
                ask_size = 0
                bid_size = 22 + min(12, int(abs(dev) // 4))

        if position > 0:
            bid_size = max(0, bid_size - int(position * 0.4))
            ask_size += min(20, int(position * 0.2))
        elif position < 0:
            ask_size = max(0, ask_size - int(-position * 0.4))
            bid_size += min(20, int(-position * 0.2))

        if 0 < bid_size < 3:
            bid_size = 3
        if 0 < ask_size < 3:
            ask_size = 3

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders = []

        if bid_size > 0 and buy_cap > 0:
            orders.append(Order(self.product, bid, min(bid_size, buy_cap)))
        if ask_size > 0 and sell_cap > 0:
            orders.append(Order(self.product, ask, -min(ask_size, sell_cap)))

        last_take = int(memory.get("last_take_ts", -10**9))
        if int(state.timestamp) - last_take >= 2000 and abs(trend) < 8.0:
            if dev > 13.0 and position > -12 and sell_cap > 0:
                qty = min(2, sell_cap, 12 + position)
                if qty > 0:
                    memory["last_take_ts"] = int(state.timestamp)
                    orders.append(Order(self.product, int(bb), -qty))
            elif dev < -13.0 and position < 12 and buy_cap > 0:
                qty = min(2, buy_cap, 12 - position)
                if qty > 0:
                    memory["last_take_ts"] = int(state.timestamp)
                    orders.append(Order(self.product, int(ba), qty))

        return orders, 0
