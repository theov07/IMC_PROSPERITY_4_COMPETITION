"""Round 1 hybrid top-of-book strategy.

Two behaviors are supported through params:

- ``mode="regression_mm"``:
  for trend-like products, fit a rolling linear regression on the mid price,
  infer a directional signal from the projected price, and keep quoting at the
  top of the book with a small price skew plus an inventory target.

- ``mode="toxic_mm"``:
  for noisier products, stay top-of-book and only modulate quote sizes using a
  simple toxicity filter based on recent market-order flow and one-tick jumps.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class Round1RegressionTopBookStrategy(BaseStrategy):
    def _rolling_regression_signal(
        self,
        mid: float,
        memory: Dict[str, Any],
    ) -> Tuple[float, float, float, float]:
        window = int(self.params.get("reg_window", 80))
        min_points = int(self.params.get("reg_min_points", max(10, window // 2)))
        horizon = int(self.params.get("reg_horizon", 20))

        mids = memory.setdefault("mid_history", [])
        mids.append(mid)
        if len(mids) > window:
            del mids[:-window]

        if len(mids) < min_points:
            memory["reg_slope"] = 0.0
            memory["reg_fitted_now"] = mid
            memory["reg_forecast"] = mid
            memory["reg_signal"] = 0.0
            return 0.0, mid, mid, 0.0

        n = len(mids)
        sum_x = n * (n - 1) / 2.0
        sum_x2 = n * (n - 1) * (2 * n - 1) / 6.0
        sum_y = sum(mids)
        sum_xy = sum(idx * price for idx, price in enumerate(mids))
        denom = n * sum_x2 - sum_x * sum_x

        if denom == 0:
            slope = 0.0
        else:
            slope = (n * sum_xy - sum_x * sum_y) / denom

        intercept = (sum_y - slope * sum_x) / n
        fitted_now = intercept + slope * (n - 1)
        forecast = intercept + slope * ((n - 1) + horizon)
        signal = forecast - mid

        memory["reg_slope"] = slope
        memory["reg_fitted_now"] = fitted_now
        memory["reg_forecast"] = forecast
        memory["reg_signal"] = signal
        return slope, fitted_now, forecast, signal

    def _apply_inventory_target_sizing(
        self,
        position: int,
        inv_target: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        buy_size = min(buy_cap, maker_size)
        sell_size = min(sell_cap, maker_size)

        soft_ratio = float(self.params.get("inventory_soft_ratio", 0.5))
        aggravate_min_frac = float(self.params.get("aggravate_min_frac", 0.25))
        unwind_boost_frac = float(self.params.get("unwind_boost_frac", 0.3))

        limit = float(self.position_limit())
        pressure = abs(position - inv_target) / max(1.0, limit)

        if pressure <= soft_ratio or soft_ratio >= 1.0:
            return buy_size, sell_size

        scaled = min(1.0, (pressure - soft_ratio) / max(1e-9, 1.0 - soft_ratio))
        aggravate_frac = 1.0 - (1.0 - aggravate_min_frac) * scaled
        unwind_mult = 1.0 + unwind_boost_frac * scaled

        if position > inv_target:
            if buy_size > 0:
                buy_size = max(1, int(round(buy_size * aggravate_frac)))
            if sell_size > 0:
                sell_size = min(sell_cap, max(1, int(round(sell_size * unwind_mult))))
        elif position < inv_target:
            if sell_size > 0:
                sell_size = max(1, int(round(sell_size * aggravate_frac)))
            if buy_size > 0:
                buy_size = min(buy_cap, max(1, int(round(buy_size * unwind_mult))))

        return buy_size, sell_size

    def _apply_toxicity_filter(
        self,
        *,
        state: TradingState,
        memory: Dict[str, Any],
        best_bid: int,
        best_ask: int,
        buy_size: int,
        sell_size: int,
    ) -> Tuple[int, int, float]:
        toxic_window = int(self.params.get("toxic_window", 8))
        toxic_threshold = float(self.params.get("toxic_threshold", 0.6))
        toxic_size_frac = float(self.params.get("toxic_size_frac", 0.6))
        jump_size_frac = float(self.params.get("jump_size_frac", 0.5))

        prev_best_bid = memory.get("prev_best_bid")
        prev_best_ask = memory.get("prev_best_ask")

        flow_history = memory.setdefault("flow_history", [])
        trades = state.market_trades.get(self.product, [])
        if toxic_window > 0 and prev_best_bid is not None and prev_best_ask is not None and trades:
            for trade in trades:
                if trade.price >= prev_best_ask:
                    flow_history.append(trade.quantity)
                elif trade.price <= prev_best_bid:
                    flow_history.append(-trade.quantity)
            if len(flow_history) > toxic_window:
                del flow_history[:-toxic_window]

        flow_score = 0.0
        if flow_history:
            signed = sum(flow_history)
            total = sum(abs(x) for x in flow_history)
            if total > 0:
                flow_score = signed / total

        bid_jumped = bool(prev_best_bid is not None and best_bid == prev_best_bid + 1)
        ask_jumped = bool(prev_best_ask is not None and best_ask == prev_best_ask - 1)

        if flow_score > toxic_threshold and sell_size > 0:
            sell_size = max(1, int(round(sell_size * toxic_size_frac)))
        elif flow_score < -toxic_threshold and buy_size > 0:
            buy_size = max(1, int(round(buy_size * toxic_size_frac)))

        if bid_jumped and sell_size > 0:
            sell_size = max(1, int(round(sell_size * jump_size_frac)))
        if ask_jumped and buy_size > 0:
            buy_size = max(1, int(round(buy_size * jump_size_frac)))

        return buy_size, sell_size, flow_score

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

        mode = str(self.params.get("mode", "toxic_mm"))
        tighten_ticks = int(self.params.get("tighten_ticks", 1))
        best_bid = book.best_bid
        best_ask = book.best_ask
        mid = book.mid_price if book.mid_price is not None else (best_bid + best_ask) / 2.0

        spread = best_ask - best_bid
        if spread >= 2:
            base_bid = min(best_bid + tighten_ticks, best_ask - 1)
            base_ask = max(best_ask - tighten_ticks, best_bid + 1)
        else:
            base_bid = best_bid
            base_ask = best_ask

        slope = 0.0
        signal = 0.0
        price_shift = 0
        inv_target = 0
        fitted_now = mid
        forecast = mid

        if mode == "regression_mm":
            slope, fitted_now, forecast, signal = self._rolling_regression_signal(mid, memory)
            shift_mult = float(self.params.get("reg_signal_to_shift", 0.5))
            shift_cap = int(self.params.get("reg_max_price_shift", 1))
            raw_shift = signal * shift_mult
            price_shift = int(round(max(-shift_cap, min(shift_cap, raw_shift))))

            inv_mult = float(self.params.get("reg_inventory_per_price", 16.0))
            inv_cap = int(self.params.get("reg_inventory_cap", self.position_limit() // 2))
            raw_target = signal * inv_mult
            inv_target = int(round(max(-inv_cap, min(inv_cap, raw_target))))

        bid_price = min(max(base_bid + price_shift, best_bid), best_ask - 1)
        ask_price = max(min(base_ask + price_shift, best_ask), best_bid + 1)
        if bid_price >= ask_price:
            bid_price = min(base_bid, best_ask - 1)
            ask_price = max(base_ask, best_bid + 1)

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        buy_size, sell_size = self._apply_inventory_target_sizing(
            position=position,
            inv_target=inv_target,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        flow_score = 0.0
        if bool(self.params.get("toxic_filter", False)):
            buy_size, sell_size, flow_score = self._apply_toxicity_filter(
                state=state,
                memory=memory,
                best_bid=best_bid,
                best_ask=best_ask,
                buy_size=buy_size,
                sell_size=sell_size,
            )

        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        memory["prev_best_bid"] = best_bid
        memory["prev_best_ask"] = best_ask
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_spread"] = spread
        memory["last_price_shift"] = price_shift
        memory["inv_target"] = inv_target
        memory["last_flow_score"] = flow_score
        memory["last_mode"] = mode

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "buy_size": buy_size,
                "sell_size": sell_size,
                "mode": mode,
                "reg_slope": round(slope, 4),
                "reg_signal": round(signal, 2),
                "reg_forecast": round(forecast, 2),
                "inv_target": inv_target,
                "flow_score": round(flow_score, 3),
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        features: Dict[str, float] = {}
        if "reg_fitted_now" in memory:
            features["reg_fitted_now"] = float(memory["reg_fitted_now"])
        if "reg_forecast" in memory:
            features["reg_forecast"] = float(memory["reg_forecast"])
        return features
