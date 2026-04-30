from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class TrendFollowRevGuardA3(BaseStrategy):
    """
    Small extension of trend_follow_v2 aimed at products that have one clean
    regime on some days but painful mid-session flip-flops on others.

    Two extra controls:
      - reverse_threshold: stronger signal required to flip from long->short or
        short->long than the one needed to enter from flat.
      - reentry_cooldown_ticks: after an exit to flat, wait a few ticks before
        re-entering. This reduces churn around violent reversals.
    """

    def compute_orders(
        self,
        state,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.mid_price is None:
            return [], 0

        mid = book.mid_price
        limit = int(self.params.get("position_limit", 10))
        hl = float(self.params.get("ema_half_life", 100))
        entry_thr = float(self.params.get("threshold", 80))
        exit_thr = float(self.params.get("exit_threshold", 30))
        trail_stop = float(self.params.get("trail_stop_thr", 0))
        ref_interval = int(self.params.get("reference_update_interval", 0))
        min_tick = int(self.params.get("warmup_ticks", 0))
        direction = int(self.params.get("direction", 0))
        reverse_thr = float(self.params.get("reverse_threshold", entry_thr))
        cooldown_ticks = int(self.params.get("reentry_cooldown_ticks", 0))

        alpha = 1.0 - 0.5 ** (1.0 / hl)

        if "start_price" not in memory:
            memory["start_price"] = mid
        if "ema" not in memory:
            memory["ema"] = mid
        tick = memory.get("tick", 0)
        memory["tick"] = tick + 1

        ema = alpha * mid + (1.0 - alpha) * memory["ema"]
        memory["ema"] = ema

        if ref_interval > 0:
            if position == 0:
                flat_ticks = memory.get("flat_ticks", 0) + 1
                memory["flat_ticks"] = flat_ticks
                if flat_ticks >= ref_interval:
                    memory["start_price"] = ema
                    memory["flat_ticks"] = 0
            else:
                memory["flat_ticks"] = 0

        if tick < min_tick:
            return [], 0

        signal = ema - memory["start_price"]
        memory["signal"] = signal

        if position > 0:
            memory["peak_signal"] = max(memory.get("peak_signal", signal), signal)
        elif position < 0:
            memory["trough_signal"] = min(memory.get("trough_signal", signal), signal)
        else:
            memory.pop("peak_signal", None)
            memory.pop("trough_signal", None)

        def _trail_long() -> bool:
            if trail_stop <= 0:
                return False
            return signal < memory.get("peak_signal", signal) - trail_stop

        def _trail_short() -> bool:
            if trail_stop <= 0:
                return False
            return signal > memory.get("trough_signal", signal) + trail_stop

        def _in_cooldown() -> bool:
            until = int(memory.get("cooldown_until_tick", -1))
            return position == 0 and tick < until

        target = position
        exited_to_flat = False

        if direction > 0:
            if position > 0 and (_trail_long() or signal < -exit_thr):
                target = 0
                exited_to_flat = True
            elif position > 0 and signal > -exit_thr:
                target = limit
            elif position == 0 and not _in_cooldown() and signal > entry_thr:
                target = limit
        elif direction < 0:
            if position < 0 and (_trail_short() or signal > exit_thr):
                target = 0
                exited_to_flat = True
            elif position < 0 and signal < exit_thr:
                target = -limit
            elif position == 0 and not _in_cooldown() and signal < -entry_thr:
                target = -limit
        else:
            if position > 0:
                if signal < -reverse_thr:
                    target = -limit
                elif _trail_long() or signal < -exit_thr:
                    target = 0
                    exited_to_flat = True
                else:
                    target = limit
            elif position < 0:
                if signal > reverse_thr:
                    target = limit
                elif _trail_short() or signal > exit_thr:
                    target = 0
                    exited_to_flat = True
                else:
                    target = -limit
            else:
                if not _in_cooldown():
                    if signal > entry_thr:
                        target = limit
                    elif signal < -entry_thr:
                        target = -limit

        if exited_to_flat and cooldown_ticks > 0:
            memory["cooldown_until_tick"] = tick + cooldown_ticks

        return self._reach_target(order_depth, position, target, limit), 0

    def _reach_target(self, order_depth, position: int, target: int, limit: int) -> List[Order]:
        delta = target - position
        if delta == 0:
            return []
        orders = []
        if delta > 0 and order_depth.sell_orders:
            ask = min(order_depth.sell_orders.keys())
            avail = -order_depth.sell_orders[ask]
            qty = min(delta, avail, limit - position)
            if qty > 0:
                orders.append(Order(self.product, ask, qty))
        elif delta < 0 and order_depth.buy_orders:
            bid = max(order_depth.buy_orders.keys())
            avail = order_depth.buy_orders[bid]
            qty = min(-delta, avail, limit + position)
            if qty > 0:
                orders.append(Order(self.product, bid, -qty))
        return orders

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if "signal" in memory:
            out["signal"] = round(float(memory["signal"]), 2)
        return out
