"""Fusion B — V18 trend-biased always-quote + V5 dynamic inventory target.

Mecanique V18 (toujours quoter, ask tres large en bullish, take aggressif)
mais la cible d'inventaire et l'ajustement du price step viennent du signal
block-OLS V5 (`trend_ticks*26 - residual_z*7`, `bid_extra/ask_relax`).

IPR uniquement.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_1.regression_mm_v5 import Round1RegressionMMV5Strategy


class LeoFusionBStrategy(Round1RegressionMMV5Strategy):

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
        residual_z = stats["residual_z"]
        fv = stats["fair_value"]

        inv_target = self._inventory_target(state=state, stats=stats, position=position)

        bull_threshold = float(self.params.get("bull_threshold", 1.0))
        bullish = trend_ticks > bull_threshold

        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        ask_spread_bull = float(self.params.get("ask_spread_bull", 9.0))
        neut_spread_bid = float(self.params.get("neut_spread_bid", 2.0))
        neut_spread_ask = float(self.params.get("neut_spread_ask", 5.0))

        if bullish:
            raw_bid = round(fv - bid_spread_bull)
            raw_ask = round(fv + ask_spread_bull)
        else:
            raw_bid = round(fv - neut_spread_bid)
            raw_ask = round(fv + neut_spread_ask)

        bid_price = min(max(raw_bid, 1), book.best_ask - 1)
        ask_price = max(raw_ask, book.best_bid + 1)
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # V5-style additional price step based on trend / residual
        bid_extra = 0
        ask_relax = 0
        strong = float(self.params.get("strong_trend_ticks", 1.1))
        very_strong = float(self.params.get("very_strong_trend_ticks", 2.0))
        cheap_z = float(self.params.get("cheap_residual_z", 0.9))
        rich_z = float(self.params.get("rich_residual_z", 1.0))
        if trend_ticks >= strong:
            bid_extra += 1
        if trend_ticks >= very_strong:
            bid_extra += 1
        if residual_z <= -cheap_z:
            bid_extra += 1
        if residual_z >= rich_z:
            ask_relax -= 1
        max_bid_extra = int(self.params.get("max_bid_extra_ticks", 2))
        max_ask_relax = int(self.params.get("max_ask_relax_ticks", 2))
        bid_extra = max(0, min(max_bid_extra, bid_extra))
        ask_relax = max(-max_ask_relax, min(max_ask_relax, ask_relax))
        bid_price = min(book.best_ask - 1, bid_price + bid_extra)
        ask_price = max(book.best_bid + 1, ask_price + ask_relax)
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        take_buy_edge_bull = float(self.params.get("take_buy_edge_bull", -8.0))
        take_sell_edge_bull = float(self.params.get("take_sell_edge_bull", 6.0))
        take_buy_edge_neut = float(self.params.get("take_buy_edge_neut", 2.0))
        take_sell_edge_neut = float(self.params.get("take_sell_edge_neut", 2.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 10.0))

        if bullish:
            buy_edge = take_buy_edge_bull
            sell_edge = take_sell_edge_bull
            if residual_z >= rich_z:
                # mid already rich vs trend -> do not chase
                buy_edge = take_buy_edge_neut
        else:
            buy_edge = take_buy_edge_neut
            sell_edge = take_sell_edge_neut

        limit = self.position_limit()
        if (not bullish) and position > inv_target:
            pressure = min(1.0, (position - inv_target) / max(1.0, float(limit)))
            sell_edge = sell_edge - unwind_take_edge * pressure

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # Takes
        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fv - buy_edge or buy_cap <= 0:
                break
            qty = min(-order_depth.sell_orders[ask_p], buy_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_p, qty))
            buy_cap -= qty
        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            if bid_p < fv + sell_edge or sell_cap <= 0:
                break
            qty = min(order_depth.buy_orders[bid_p], sell_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, bid_p, -qty))
            sell_cap -= qty

        # Passive sizing: reuse V5 size_from_target (already uses stats/gap/trend)
        buy_size, sell_size = self._size_from_target(
            position=position,
            inv_target=inv_target,
            stats=stats,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["inv_target"] = inv_target
        memory["bullish"] = int(bullish)
        return orders, 0
