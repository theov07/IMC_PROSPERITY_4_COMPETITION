from __future__ import annotations
from typing import Any, Dict, List, Tuple
from datamodel import Order
from prosperity.strategies.base import BaseStrategy
from prosperity.market import BookSnapshot


class TrendFollowV2(BaseStrategy):
    """
    Level-based trend following for Round 5 products.

    Signal = EMA(mid) - reference_price

    The reference_price starts as the session open but can be periodically
    updated while flat (reference_update_interval > 0). This lets the strategy
    catch trends that start mid-session after a counter-move, without being
    fooled by that counter-move. In backtest where the trend is already
    established when we enter position, the reference is never updated (we're
    in position before the interval fires) — so backtest behaviour is unchanged.

    Direction lock:
        direction = 0  : bidirectional (default)
        direction = +1 : long only  — skips short entries
        direction = -1 : short only — skips long entries

    Exit logic (evaluated in order):
        1. Trailing stop: if trail_stop_thr > 0
              LONG  → exit when signal < peak_signal_while_long  - trail_stop_thr
              SHORT → exit when signal > trough_signal_while_short + trail_stop_thr
        2. Absolute reversal: signal crosses -exit_thr (long) or +exit_thr (short)

    Params:
        ema_half_life             : EMA half-life in ticks (default 100)
        threshold                 : signal deviation from reference to enter (default 80)
        exit_threshold            : reversal deviation to force-exit (default 30)
        trail_stop_thr            : trailing stop distance from extremum (0=off, default 0)
        reference_update_interval : ticks while flat before reference resets (0=off, default 0)
        warmup_ticks              : ticks before any entry allowed (default 0)
        position_limit            : 10 for all R5 products
        direction                 : 0/+1/-1 (see above)
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

        alpha = 1.0 - 0.5 ** (1.0 / hl)

        if "start_price" not in memory:
            memory["start_price"] = mid
        if "ema" not in memory:
            memory["ema"] = mid
        tick = memory.get("tick", 0)
        memory["tick"] = tick + 1

        ema = alpha * mid + (1.0 - alpha) * memory["ema"]
        memory["ema"] = ema

        # ── reference update while flat ────────────────────────────────────────
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

        # ── track extrema while in position (for trail stop) ──────────────────
        if position > 0:
            memory["peak_signal"] = max(memory.get("peak_signal", signal), signal)
        elif position < 0:
            memory["trough_signal"] = min(memory.get("trough_signal", signal), signal)
        else:
            memory.pop("peak_signal", None)
            memory.pop("trough_signal", None)

        # ── exit helpers ───────────────────────────────────────────────────────
        def _trail_long() -> bool:
            if trail_stop <= 0:
                return False
            return signal < memory.get("peak_signal", signal) - trail_stop

        def _trail_short() -> bool:
            if trail_stop <= 0:
                return False
            return signal > memory.get("trough_signal", signal) + trail_stop

        # ── target logic ───────────────────────────────────────────────────────
        if direction > 0:
            if signal > entry_thr:
                target = limit
            elif position > 0 and (_trail_long() or signal < -exit_thr):
                target = 0
            else:
                target = position
        elif direction < 0:
            if signal < -entry_thr:
                target = -limit
            elif position < 0 and (_trail_short() or signal > exit_thr):
                target = 0
            else:
                target = position
        else:
            if signal > entry_thr:
                target = limit
            elif signal < -entry_thr:
                target = -limit
            elif position > 0 and (_trail_long() or signal < -exit_thr):
                target = 0
            elif position < 0 and (_trail_short() or signal > exit_thr):
                target = 0
            else:
                target = position

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
