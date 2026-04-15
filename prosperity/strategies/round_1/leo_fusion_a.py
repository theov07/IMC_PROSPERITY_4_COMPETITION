"""Fusion A — V22 book-following + opp_sell, driven by V5 block-OLS signal.

Squelette V22 (follow-book quoting, unwind doux, micro trim a plein inventaire)
avec le signal trend_ticks/confidence/residual_z du block-OLS V5 comme moteur
du regime bullish/neutral.

IPR uniquement.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_1.regression_mm_v5 import Round1RegressionMMV5Strategy


class LeoFusionAStrategy(Round1RegressionMMV5Strategy):

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

        trend_ticks = stats["trend_ticks"]
        confidence = stats["confidence"]
        residual_z = stats["residual_z"]
        fv = stats["fair_value"]

        bull_threshold = float(self.params.get("bull_threshold", 1.0))
        min_confidence = float(self.params.get("bull_min_confidence", 0.4))
        bullish = trend_ticks > bull_threshold and confidence >= min_confidence

        target_bull = int(self.params.get("target_bull", 50))
        inv_target = target_bull if bullish else 0

        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        ask_spread_bull = float(self.params.get("ask_spread_bull", 7.0))
        neut_spread = float(self.params.get("neut_spread", 3.0))

        if bullish:
            raw_bid = round(fv - bid_spread_bull)
            raw_ask = round(fv + ask_spread_bull)
            bid_price = max(raw_bid, book.best_bid)
            bid_price = min(bid_price, book.best_ask - 1)
            ask_price = min(raw_ask, book.best_ask)
            ask_price = max(ask_price, book.best_bid + 1)
        else:
            raw_bid = round(fv - neut_spread)
            raw_ask = round(fv + neut_spread)
            bid_price = min(raw_bid, book.best_ask - 1)
            ask_price = max(raw_ask, book.best_bid + 1)
        if bid_price >= ask_price:
            bid_price = ask_price - 1

        take_buy_edge_bull = float(self.params.get("take_buy_edge_bull", -2.0))
        take_sell_edge_bull = float(self.params.get("take_sell_edge_bull", 12.0))
        take_buy_edge_neut = float(self.params.get("take_buy_edge_neut", 2.0))
        take_sell_edge_neut = float(self.params.get("take_sell_edge_neut", 2.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 8.0))
        unwind_min_position = int(self.params.get("unwind_min_position", 20))
        rich_block_z = float(self.params.get("rich_block_residual_z", 0.9))

        if bullish:
            buy_edge = take_buy_edge_bull
            sell_edge = take_sell_edge_bull
            if residual_z >= rich_block_z:
                buy_edge = take_buy_edge_neut
        else:
            buy_edge = take_buy_edge_neut
            sell_edge = take_sell_edge_neut

        limit = self.position_limit()
        if (not bullish) and position > max(inv_target, unwind_min_position):
            pressure = min(1.0, (position - inv_target) / max(1.0, float(limit)))
            sell_edge = sell_edge - unwind_take_edge * pressure

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        opp_sell_edge = float(self.params.get("opp_sell_edge", 1.0))
        opp_sell_min_position = int(self.params.get("opp_sell_min_position", 80))
        opp_sell_take_size = int(self.params.get("opp_sell_take_size", 2))
        opp_sell_cooldown_ticks = int(self.params.get("opp_sell_cooldown_ticks", 10))

        opp_sell = (
            bullish
            and position >= opp_sell_min_position
            and book.best_bid >= fv + opp_sell_edge
        )
        last_opp_sell_ts = int(memory.get("last_opp_sell_ts", -10**9))
        if opp_sell and state.timestamp - last_opp_sell_ts >= opp_sell_cooldown_ticks * 100:
            sell_edge = min(sell_edge, opp_sell_edge)
            sell_cap = min(sell_cap, opp_sell_take_size)

        take_orders: List[Order] = []
        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fv - buy_edge or buy_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_p]
            qty = min(available, buy_cap)
            if qty <= 0:
                continue
            take_orders.append(Order(self.product, ask_p, qty))
            buy_cap -= qty
        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            if bid_p < fv + sell_edge or sell_cap <= 0:
                break
            volume = order_depth.buy_orders[bid_p]
            qty = min(volume, sell_cap)
            if qty <= 0:
                continue
            take_orders.append(Order(self.product, bid_p, -qty))
            sell_cap -= qty
        orders.extend(take_orders)

        if any(o.quantity < 0 for o in take_orders):
            memory["last_opp_sell_ts"] = state.timestamp

        maker_size = int(self.params.get("maker_size", self.position_limit()))
        buy_size = min(buy_cap, maker_size)
        sell_size = min(sell_cap, maker_size)

        soft_ratio = float(self.params.get("inventory_soft_ratio", 0.40))
        aggravate_min = float(self.params.get("aggravate_min_frac", 0.20))
        unwind_boost = float(self.params.get("unwind_boost_frac", 0.40))
        inv_pressure = abs(position - inv_target) / max(1.0, float(limit))
        if inv_pressure > soft_ratio and soft_ratio < 1.0:
            scaled = min(1.0, (inv_pressure - soft_ratio) / max(1e-9, 1.0 - soft_ratio))
            agg_frac = 1.0 - (1.0 - aggravate_min) * scaled
            boost = 1.0 + unwind_boost * scaled
            if position > inv_target:
                buy_size = max(1, int(round(buy_size * agg_frac)))
                sell_size = min(sell_cap, max(1, int(round(sell_size * boost))))
            elif position < inv_target:
                sell_size = max(1, int(round(sell_size * agg_frac)))
                buy_size = min(buy_cap, max(1, int(round(buy_size * boost))))

        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["inv_target"] = inv_target
        memory["bullish"] = int(bullish)
        return orders, 0
