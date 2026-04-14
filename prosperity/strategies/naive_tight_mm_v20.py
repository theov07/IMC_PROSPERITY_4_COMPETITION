"""Book-Following Trend Market Maker V20.

V20 keeps the V19 idea set but fixes two live issues from official run 118950:
1. We still miss too many rare sell-opportunity windows while already long.
2. We keep re-buying late after small trims, so good sells do not stick.

Changes vs V19:
- Add explicit trim sells when best_bid is rich vs fair and inventory is already high.
- Improve the passive ask to best_bid + 1 during those trim windows.
- Block or shrink rebuys when we are already long and the ask is extended.
- Prevent tiny neutral unwinds from flipping us short early.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class BookFollowingTrendMMV20Strategy(BaseStrategy):

    def _take_orders(
        self,
        order_depth: OrderDepth,
        fv: float,
        buy_edge: float,
        sell_edge: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, int]:
        """Aggressive order taking around fair value thresholds."""
        orders: List[Order] = []
        take_count = 0

        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > fv - buy_edge or buy_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_price]
            qty = min(available, buy_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_price, qty))
            buy_cap -= qty
            take_count += 1

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < fv + sell_edge or sell_cap <= 0:
                break
            volume = order_depth.buy_orders[bid_price]
            qty = min(volume, sell_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, bid_price, -qty))
            sell_cap -= qty
            take_count += 1

        return orders, buy_cap, sell_cap, take_count

    def _size_quotes(
        self,
        position: int,
        inv_target: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        """Inventory-aware passive sizing with independent buy/sell base sizes."""
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        maker_buy_size = int(self.params.get("maker_buy_size", maker_size))
        maker_sell_size = int(self.params.get("maker_sell_size", maker_size))

        buy_size = min(buy_cap, maker_buy_size)
        sell_size = min(sell_cap, maker_sell_size)

        soft_ratio = float(self.params.get("inventory_soft_ratio", 0.40))
        aggravate_min = float(self.params.get("aggravate_min_frac", 0.20))
        unwind_boost = float(self.params.get("unwind_boost_frac", 0.40))
        limit = float(self.position_limit())

        pressure = abs(position - inv_target) / max(1.0, limit)
        if pressure <= soft_ratio or soft_ratio >= 1.0:
            return buy_size, sell_size

        scaled = min(1.0, (pressure - soft_ratio) / max(1e-9, 1.0 - soft_ratio))
        agg_frac = 1.0 - (1.0 - aggravate_min) * scaled
        boost = 1.0 + unwind_boost * scaled

        if position > inv_target:
            buy_size = max(1, int(round(buy_size * agg_frac))) if buy_size > 0 else 0
            sell_size = min(sell_cap, max(1, int(round(sell_size * boost)))) if sell_size > 0 else 0
        elif position < inv_target:
            sell_size = max(1, int(round(sell_size * agg_frac))) if sell_size > 0 else 0
            buy_size = min(buy_cap, max(1, int(round(buy_size * boost)))) if buy_size > 0 else 0

        return buy_size, sell_size

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        fv_alpha = float(self.params.get("fv_alpha", 0.05))
        slope_window = int(self.params.get("slope_window", 20))
        bull_threshold = float(self.params.get("bull_threshold", 1.0))

        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        ask_spread_bull = float(self.params.get("ask_spread_bull", 7.0))
        neut_spread = float(self.params.get("neut_spread", 3.0))

        take_buy_edge_bull = float(self.params.get("take_buy_edge_bull", -2.0))
        take_sell_edge_bull = float(self.params.get("take_sell_edge_bull", 12.0))
        take_buy_edge_neut = float(self.params.get("take_buy_edge_neut", 2.0))
        take_sell_edge_neut = float(self.params.get("take_sell_edge_neut", 2.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 8.0))
        unwind_min_position = int(self.params.get("unwind_min_position", 20))

        target_bull = int(self.params.get("target_bull", 50))

        sell_opp_edge = float(self.params.get("sell_opp_edge", 1.0))
        sell_opp_min_position = int(self.params.get("sell_opp_min_position", 60))
        sell_opp_take_size = int(self.params.get("sell_opp_take_size", 4))
        sell_opp_quote_offset = int(self.params.get("sell_opp_quote_offset", 1))
        sell_opp_cooldown_ticks = int(self.params.get("sell_opp_cooldown_ticks", 6))

        rebuy_block_min_position = int(self.params.get("rebuy_block_min_position", 60))
        rebuy_block_extension = float(self.params.get("rebuy_block_extension", 1.0))
        rebuy_block_take_cap = int(self.params.get("rebuy_block_take_cap", 0))
        rebuy_block_quote_frac = float(self.params.get("rebuy_block_quote_frac", 0.25))

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        mid = (book.best_bid + book.best_ask) / 2.0

        fv = float(memory.get("fv", mid))
        fv = fv_alpha * mid + (1.0 - fv_alpha) * fv
        memory["fv"] = fv

        fv_hist = memory.setdefault("fv_hist", [])
        fv_hist.append(fv)
        if len(fv_hist) > slope_window + 1:
            del fv_hist[: -(slope_window + 1)]

        slope = 0.0
        if len(fv_hist) >= slope_window:
            slope = fv_hist[-1] - fv_hist[-slope_window]
        memory["slope"] = slope

        bullish = slope > bull_threshold
        inv_target = target_bull if bullish else 0

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

        if bullish:
            buy_edge = take_buy_edge_bull
            sell_edge = take_sell_edge_bull
        else:
            buy_edge = take_buy_edge_neut
            sell_edge = take_sell_edge_neut

        limit = self.position_limit()
        if (not bullish) and position > max(inv_target, unwind_min_position):
            pressure = min(1.0, (position - inv_target) / max(1.0, float(limit)))
            sell_edge = sell_edge - unwind_take_edge * pressure

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        buy_blocked = (
            bullish
            and position >= rebuy_block_min_position
            and book.best_ask >= fv + rebuy_block_extension
        )
        if buy_blocked:
            buy_cap = min(buy_cap, max(0, rebuy_block_take_cap))

        sell_opp = bullish and position >= sell_opp_min_position and book.best_bid >= fv + sell_opp_edge
        last_trim_ts = int(memory.get("last_trim_ts", -10**9))
        trim_ready = state.timestamp - last_trim_ts >= sell_opp_cooldown_ticks * 100
        trim_active = sell_opp and trim_ready

        if trim_active:
            sell_edge = min(sell_edge, sell_opp_edge)
            sell_cap = min(sell_cap, sell_opp_take_size)

        take_orders, buy_cap, sell_cap, take_count = self._take_orders(
            order_depth=order_depth,
            fv=fv,
            buy_edge=buy_edge,
            sell_edge=sell_edge,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )
        orders.extend(take_orders)

        if trim_active and any(order.quantity < 0 for order in take_orders):
            memory["last_trim_ts"] = state.timestamp

        buy_size, sell_size = self._size_quotes(
            position=position,
            inv_target=inv_target,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        if buy_blocked and buy_size > 0:
            buy_size = max(1, int(round(buy_size * rebuy_block_quote_frac)))

        if sell_opp and sell_size > 0:
            ask_price = max(book.best_bid + sell_opp_quote_offset, book.best_bid + 1)
            ask_price = min(ask_price, book.best_ask)
            if bid_price >= ask_price:
                ask_price = bid_price + 1

        if buy_size > 0 and bid_price < ask_price:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0 and ask_price > bid_price:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["inv_target"] = inv_target
        memory["bullish"] = int(bullish)

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "buy_size": buy_size,
                "sell_size": sell_size,
                "fv": round(fv, 1),
                "slope": round(slope, 2),
                "bullish": int(bullish),
                "inv_target": inv_target,
                "sell_opp": int(sell_opp),
                "trim_active": int(trim_active),
                "buy_blocked": int(buy_blocked),
                "takes": take_count,
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if memory.get("fv") is not None:
            out["fv"] = memory["fv"]
        return out
