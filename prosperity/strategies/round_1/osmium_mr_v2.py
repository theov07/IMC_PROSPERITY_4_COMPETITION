"""Osmium mean-reversion MM v2 — adds tibo-style absolute taker thresholds
and gap exploit on top of osmium_mr's AR1-biased mean-reversion.

New params:
  take_abs_buy   : unconditional buy when best ask <= take_abs_buy (None disables)
  take_abs_sell  : unconditional sell when best bid >= take_abs_sell (None disables)
  gap_trigger_min         : min tick gap L1→L2 to fire gap exploit (default 0 = off)
  gap_trigger_max_vol_pct : L1 thin threshold as % of limit (default 0.15)
  gap_trigger_confirm_ticks : consecutive ticks required before firing (default 1)
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.round_1.osmium_mr_artifact import OsmiumMeanRevStrategy


class OsmiumMeanRevV2Strategy(OsmiumMeanRevStrategy):

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None:
            return [], 0

        limit = self.position_limit()
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        extra_orders: List[Order] = []
        virt_pos = position

        # ── 1. Absolute taker thresholds (mean-reversion edge) ────────────
        take_abs_buy = self.params.get("take_abs_buy")
        take_abs_sell = self.params.get("take_abs_sell")

        if take_abs_buy is not None and buy_cap > 0:
            for ask_p in sorted(order_depth.sell_orders):
                if ask_p > float(take_abs_buy):
                    break
                available = -order_depth.sell_orders[ask_p]
                qty = min(available, buy_cap)
                if qty <= 0:
                    continue
                extra_orders.append(Order(self.product, ask_p, qty))
                order_depth.sell_orders[ask_p] += qty  # reduce toward 0
                if order_depth.sell_orders[ask_p] == 0:
                    del order_depth.sell_orders[ask_p]
                buy_cap -= qty
                virt_pos += qty
                if buy_cap <= 0:
                    break

        if take_abs_sell is not None and sell_cap > 0:
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if bid_p < float(take_abs_sell):
                    break
                volume = order_depth.buy_orders[bid_p]
                qty = min(volume, sell_cap)
                if qty <= 0:
                    continue
                extra_orders.append(Order(self.product, bid_p, -qty))
                order_depth.buy_orders[bid_p] -= qty
                if order_depth.buy_orders[bid_p] == 0:
                    del order_depth.buy_orders[bid_p]
                sell_cap -= qty
                virt_pos -= qty
                if sell_cap <= 0:
                    break

        # ── 2. Gap exploit on thin L1 ─────────────────────────────────────
        gap_min = float(self.params.get("gap_trigger_min", 0))
        if gap_min > 0:
            gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.15))
            gap_max_vol = int(gap_vol_pct * limit) if limit else 0
            gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 1))

            bids = sorted(order_depth.buy_orders.keys(), reverse=True)
            bid_gap_ok = False
            if len(bids) >= 2:
                b1, b2 = bids[0], bids[1]
                b1_vol = order_depth.buy_orders[b1]
                bid_gap_ok = (b1 - b2) >= gap_min and b1_vol <= gap_max_vol
            bs = memory.get("_gap_bid_streak", 0)
            bs = bs + 1 if bid_gap_ok else 0
            memory["_gap_bid_streak"] = bs
            if bs >= gap_confirm and bid_gap_ok and sell_cap > 0:
                b1 = bids[0]
                b1_vol = order_depth.buy_orders[b1]
                qty = min(b1_vol, sell_cap)
                if qty > 0:
                    extra_orders.append(Order(self.product, b1, -qty))
                    order_depth.buy_orders[b1] -= qty
                    if order_depth.buy_orders[b1] == 0:
                        del order_depth.buy_orders[b1]
                    sell_cap -= qty
                    virt_pos -= qty

            asks = sorted(order_depth.sell_orders.keys())
            ask_gap_ok = False
            if len(asks) >= 2:
                a1, a2 = asks[0], asks[1]
                a1_vol = -order_depth.sell_orders[a1]
                ask_gap_ok = (a2 - a1) >= gap_min and a1_vol <= gap_max_vol
            asr = memory.get("_gap_ask_streak", 0)
            asr = asr + 1 if ask_gap_ok else 0
            memory["_gap_ask_streak"] = asr
            if asr >= gap_confirm and ask_gap_ok and buy_cap > 0:
                a1 = asks[0]
                a1_vol = -order_depth.sell_orders[a1]
                qty = min(a1_vol, buy_cap)
                if qty > 0:
                    extra_orders.append(Order(self.product, a1, qty))
                    order_depth.sell_orders[a1] += qty
                    if order_depth.sell_orders[a1] == 0:
                        del order_depth.sell_orders[a1]
                    buy_cap -= qty
                    virt_pos += qty

        # Book may be empty now after aggressive takes
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return extra_orders, 0

        # ── 3. Delegate to parent osmium_mr (AR1 + mean-rev) ──────────────
        sub_orders, conv = super().compute_orders(
            state, book, order_depth, virt_pos, memory,
        )
        return extra_orders + sub_orders, conv
