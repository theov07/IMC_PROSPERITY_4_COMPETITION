"""Round 5 passive MM with post-fill adverse-selection diagnostics.

Keeps the existing passive logic family per product, then monitors markout on
recent fills. If a side repeatedly gets filled before price moves against us,
that side is paused or widened for a few ticks, and inventory can be unwound.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class FillGuardedMMStrategy(BaseStrategy):
    def _online_z(self, value: float, key: str, memory: Dict[str, Any], window: int) -> float:
        buf = memory.setdefault(key, [])
        buf.append(value)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(30, window // 8):
            return 0.0
        n = len(buf)
        mu = sum(buf) / n
        var = sum((x - mu) ** 2 for x in buf) / max(n - 1, 1)
        std = math.sqrt(var)
        if std < 1e-9:
            return 0.0
        return (value - mu) / std

    def _trend(self, mid: float, memory: Dict[str, Any], key: str, half_life: int) -> float:
        alpha = 2.0 / (half_life + 1.0)
        ema = memory.get(key, mid)
        ema = alpha * mid + (1.0 - alpha) * ema
        memory[key] = ema
        return mid - ema

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None or book.mid_price is None:
            return [], 0

        p = self.params
        mode = str(p.get("mode", "naive"))
        size = int(p.get("maker_size", 5))
        tighten = int(p.get("tighten_ticks", 1))
        hard_pause = int(p.get("hard_pause_at", 9))
        trend_hl = int(p.get("trend_hl", 120))
        carry_min_pos = int(p.get("carry_pause_min_pos", 3))
        pair_thresh = float(p.get("pair_thresh", 1.5))
        z_window = int(p.get("z_window", 300))

        markout_horizon = int(p.get("markout_horizon_ts", 500))
        adverse_ticks = float(p.get("adverse_ticks", 1.0))
        favorable_ticks = float(p.get("favorable_ticks", adverse_ticks))
        toxicity_threshold = float(p.get("toxicity_threshold", 3.0))
        toxicity_decay = float(p.get("toxicity_decay", 0.95))
        pause_ticks = int(p.get("pause_ticks", 4))
        widen_ticks = int(p.get("widen_ticks", 1))
        max_events = int(p.get("max_fill_events", 8))
        unwind_min_pos = int(p.get("unwind_min_pos", hard_pause + 1))
        unwind_size = int(p.get("unwind_size", size))

        mid = float(book.mid_price)
        spread = int(book.best_ask - book.best_bid)
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask
        trend = self._trend(mid, memory, "_ema_mid", trend_hl)

        toxic_bid = float(memory.get("_toxic_bid", 0.0)) * toxicity_decay
        toxic_ask = float(memory.get("_toxic_ask", 0.0)) * toxicity_decay
        fill_events = memory.setdefault("_fill_events", [])
        now_ts = int(state.timestamp)
        remaining = []
        for event in fill_events:
            if now_ts - int(event["ts"]) < markout_horizon:
                remaining.append(event)
                continue
            price = float(event["price"])
            qty = int(event["qty"])
            if event["side"] == "B":
                markout = mid - price
                if markout <= -adverse_ticks:
                    toxic_bid += qty
                elif markout >= favorable_ticks:
                    toxic_bid = max(0.0, toxic_bid - qty)
            else:
                markout = price - mid
                if markout <= -adverse_ticks:
                    toxic_ask += qty
                elif markout >= favorable_ticks:
                    toxic_ask = max(0.0, toxic_ask - qty)
        memory["_fill_events"] = remaining[-max_events:]

        last_position = int(memory.get("_last_position", position))
        delta_pos = position - last_position
        if delta_pos > 0:
            fill_events = memory.setdefault("_fill_events", [])
            fill_events.append(
                {
                    "ts": now_ts,
                    "side": "B",
                    "price": float(memory.get("_prev_bid_quote", mid)),
                    "qty": abs(delta_pos),
                }
            )
            memory["_fill_events"] = fill_events[-max_events:]
        elif delta_pos < 0:
            fill_events = memory.setdefault("_fill_events", [])
            fill_events.append(
                {
                    "ts": now_ts,
                    "side": "S",
                    "price": float(memory.get("_prev_ask_quote", mid)),
                    "qty": abs(delta_pos),
                }
            )
            memory["_fill_events"] = fill_events[-max_events:]
        memory["_last_position"] = position

        bid_pause = max(0, int(memory.get("_bid_pause", 0)) - 1)
        ask_pause = max(0, int(memory.get("_ask_pause", 0)) - 1)
        if toxic_bid >= toxicity_threshold:
            bid_pause = max(bid_pause, pause_ticks)
        if toxic_ask >= toxicity_threshold:
            ask_pause = max(ask_pause, pause_ticks)
        memory["_bid_pause"] = bid_pause
        memory["_ask_pause"] = ask_pause
        memory["_toxic_bid"] = toxic_bid
        memory["_toxic_ask"] = toxic_ask
        memory["_trend"] = trend

        post_bid = position < hard_pause
        post_ask = position > -hard_pause
        pair_z = 0.0

        if mode == "pair":
            partner = p.get("partner")
            partner_sign = float(p.get("partner_sign", -1.0))
            self_z = self._online_z(mid, "_pair_self_z", memory, z_window)
            partner_mid = None
            if partner in state.order_depths:
                pdepth = state.order_depths[partner]
                if pdepth.buy_orders and pdepth.sell_orders:
                    partner_mid = (max(pdepth.buy_orders) + min(pdepth.sell_orders)) / 2.0
            if partner_mid is not None:
                partner_z = self._online_z(partner_mid, "_pair_partner_z", memory, z_window)
                pair_z = self_z - partner_sign * partner_z
            if pair_z > pair_thresh:
                post_bid = False
            elif pair_z < -pair_thresh:
                post_ask = False
        elif mode == "carry":
            if abs(position) >= carry_min_pos:
                if position > 0 and trend < 0:
                    post_bid = False
                elif position < 0 and trend > 0:
                    post_ask = False
        elif mode == "naive":
            reversal_eps = float(p.get("reversal_eps", 0.75))
            last_mid = float(memory.get("_last_mid", mid))
            last_ret = mid - last_mid
            memory["_last_mid"] = mid
            memory["_last_ret"] = last_ret
            if last_ret > reversal_eps:
                post_bid = False
            elif last_ret < -reversal_eps:
                post_ask = False

        if bid_pause > 0:
            post_bid = False
            bid_p -= widen_ticks
        if ask_pause > 0:
            post_ask = False
            ask_p += widen_ticks

        if bid_p >= ask_p:
            bid_p = min(bid_p, book.best_ask - 1)
            ask_p = max(ask_p, book.best_bid + 1)
            if bid_p >= ask_p:
                bid_p = book.best_bid
                ask_p = book.best_ask

        orders: List[Order] = []
        buy_room = self.buy_capacity(position)
        sell_room = self.sell_capacity(position)
        if post_bid and buy_room > 0:
            orders.append(Order(self.product, int(bid_p), min(size, buy_room)))
        if post_ask and sell_room > 0:
            orders.append(Order(self.product, int(ask_p), -min(size, sell_room)))

        if toxic_bid >= toxicity_threshold and position > unwind_min_pos and sell_room > 0 and trend <= 0:
            qty = min(unwind_size, position, sell_room, max(book.best_bid_volume, 1))
            if qty > 0:
                orders.append(Order(self.product, int(book.best_bid), -qty))
                self.log_taker_fill(state=state, memory=memory, side="SELL", price=int(book.best_bid), quantity=qty)
        elif toxic_ask >= toxicity_threshold and position < -unwind_min_pos and buy_room > 0 and trend >= 0:
            qty = min(unwind_size, -position, buy_room, max(book.best_ask_volume, 1))
            if qty > 0:
                orders.append(Order(self.product, int(book.best_ask), qty))
                self.log_taker_fill(state=state, memory=memory, side="BUY", price=int(book.best_ask), quantity=qty)

        memory["_prev_bid_quote"] = int(bid_p)
        memory["_prev_ask_quote"] = int(ask_p)
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_p if post_bid else None,
            ask_price=ask_p if post_ask else None,
            extras={
                "tb": round(toxic_bid, 2),
                "ta": round(toxic_ask, 2),
                "pair_z": round(pair_z, 3),
            },
        )
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if "_toxic_bid" in memory:
            out["toxic_bid"] = round(memory["_toxic_bid"], 2)
        if "_toxic_ask" in memory:
            out["toxic_ask"] = round(memory["_toxic_ask"], 2)
        if "_trend" in memory:
            out["trend"] = round(memory["_trend"], 2)
        return out
