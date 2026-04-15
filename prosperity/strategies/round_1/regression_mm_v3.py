"""Advanced round-1 regression market maker for INTARIAN_PEPPER_ROOT.

This strategy is intentionally trend-aware:

- fits a rolling linear regression on the mid price
- measures fit quality (R²) and residual volatility (RMSE)
- derives a trend score from slope × horizon × confidence
- turns that into a directional inventory target
- skews top-of-book quotes and sizes around that target
- can become effectively one-sided while building toward the target

The goal is not to predict every tick. The goal is to keep harvesting spread
while letting the inventory lean with the very persistent trend visible in the
round-1 product.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class Round1RegressionMMV3Strategy(BaseStrategy):
    def _update_regression(
        self,
        *,
        mid: float,
        memory: Dict[str, Any],
    ) -> Dict[str, float]:
        window = int(self.params.get("reg_window", 120))
        min_points = int(self.params.get("reg_min_points", max(20, window // 2)))
        horizon = int(self.params.get("reg_horizon", 25))
        r2_floor = float(self.params.get("reg_r2_floor", 0.30))
        r2_cap = float(self.params.get("reg_r2_cap", 0.85))

        mids = memory.setdefault("mid_history", [])
        mids.append(mid)
        if len(mids) > window:
            del mids[:-window]

        if len(mids) < min_points:
            stats = {
                "slope": 0.0,
                "intercept": mid,
                "fitted_now": mid,
                "forecast": mid,
                "residual": 0.0,
                "rmse": 1.0,
                "r2": 0.0,
                "confidence": 0.0,
                "trend_ticks": 0.0,
                "fair_value": mid,
                "residual_z": 0.0,
            }
            memory["regression_stats"] = stats
            return stats

        y = mids
        n = len(y)
        mean_x = (n - 1) / 2.0
        mean_y = sum(y) / n

        ss_xx = 0.0
        ss_xy = 0.0
        for idx, price in enumerate(y):
            dx = idx - mean_x
            dy = price - mean_y
            ss_xx += dx * dx
            ss_xy += dx * dy

        slope = ss_xy / ss_xx if ss_xx > 0 else 0.0
        intercept = mean_y - slope * mean_x
        fitted = [intercept + slope * idx for idx in range(n)]
        fitted_now = fitted[-1]
        forecast = intercept + slope * ((n - 1) + horizon)
        residual = mid - fitted_now

        ss_tot = sum((price - mean_y) ** 2 for price in y)
        ss_res = sum((price - fit) ** 2 for price, fit in zip(y, fitted))
        r2 = 0.0 if ss_tot <= 1e-9 else max(0.0, 1.0 - ss_res / ss_tot)
        rmse = math.sqrt(ss_res / max(1, n))
        rmse = max(rmse, float(self.params.get("reg_rmse_floor", 0.5)))

        if r2_cap <= r2_floor:
            confidence = 1.0 if r2 > r2_floor else 0.0
        else:
            confidence = max(0.0, min(1.0, (r2 - r2_floor) / (r2_cap - r2_floor)))

        trend_ticks = slope * horizon * confidence
        residual_z = residual / rmse
        mean_revert_weight = float(self.params.get("reg_residual_reversion", 0.35))
        fair_value = forecast - mean_revert_weight * residual

        stats = {
            "slope": slope,
            "intercept": intercept,
            "fitted_now": fitted_now,
            "forecast": forecast,
            "residual": residual,
            "rmse": rmse,
            "r2": r2,
            "confidence": confidence,
            "trend_ticks": trend_ticks,
            "fair_value": fair_value,
            "residual_z": residual_z,
        }
        memory["regression_stats"] = stats
        return stats

    def _inventory_target(
        self,
        *,
        state: TradingState,
        stats: Dict[str, float],
        position: int,
    ) -> int:
        trend_inv_per_tick = float(self.params.get("trend_inv_per_tick", 24.0))
        resid_inv_per_z = float(self.params.get("resid_inv_per_z", 8.0))
        inv_cap = int(self.params.get("trend_inventory_cap", 70))

        target = stats["trend_ticks"] * trend_inv_per_tick
        target -= stats["residual_z"] * resid_inv_per_z

        startup_target = int(self.params.get("startup_target", 32))
        startup_end_ts = int(self.params.get("startup_end_ts", 25000))
        if int(state.timestamp) <= startup_end_ts and stats["trend_ticks"] >= 0.0:
            target = max(target, startup_target)

        target = max(-inv_cap, min(inv_cap, target))
        return int(round(target))

    def _size_from_target(
        self,
        *,
        position: int,
        inv_target: int,
        stats: Dict[str, float],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        min_quote_size = int(self.params.get("min_quote_size", 1))
        base_buy = min(buy_cap, maker_size)
        base_sell = min(sell_cap, maker_size)

        if base_buy <= 0 and base_sell <= 0:
            return 0, 0

        gap = inv_target - position
        gap_scale = max(1.0, float(self.params.get("target_gap_scale", 30.0)))
        bullish_boost = max(0.0, stats["trend_ticks"]) * float(self.params.get("trend_buy_boost_per_tick", 0.20))
        bearish_boost = max(0.0, -stats["trend_ticks"]) * float(self.params.get("trend_sell_boost_per_tick", 0.20))
        cheap_boost = max(0.0, -stats["residual_z"]) * float(self.params.get("cheap_buy_boost_per_z", 0.12))
        rich_boost = max(0.0, stats["residual_z"]) * float(self.params.get("rich_sell_boost_per_z", 0.12))

        buy_mult = 1.0 + max(0.0, gap) / gap_scale + bullish_boost + cheap_boost
        sell_mult = 1.0 + max(0.0, -gap) / gap_scale + bearish_boost + rich_boost

        aggravate_cut = float(self.params.get("aggravate_cut", 0.08))
        if gap > 0:
            sell_mult *= aggravate_cut
        elif gap < 0:
            buy_mult *= aggravate_cut

        one_sided_gap = int(self.params.get("one_sided_target_gap", 28))
        strong_trend = float(self.params.get("strong_trend_ticks", 0.8))
        if gap >= one_sided_gap and stats["trend_ticks"] >= strong_trend:
            sell_mult = 0.0
        elif gap <= -one_sided_gap and stats["trend_ticks"] <= -strong_trend:
            buy_mult = 0.0

        buy_size = 0 if buy_mult <= 0.0 else min(buy_cap, max(min_quote_size, int(round(base_buy * buy_mult))))
        sell_size = 0 if sell_mult <= 0.0 else min(sell_cap, max(min_quote_size, int(round(base_sell * sell_mult))))
        return buy_size, sell_size

    def _quote_prices(
        self,
        *,
        book: BookSnapshot,
        stats: Dict[str, float],
        position: int,
        inv_target: int,
    ) -> Tuple[int, int, int, int]:
        best_bid = int(book.best_bid)
        best_ask = int(book.best_ask)
        tighten_ticks = int(self.params.get("tighten_ticks", 1))

        spread = best_ask - best_bid
        if spread >= 2:
            bid_price = min(best_bid + tighten_ticks, best_ask - 1)
            ask_price = max(best_ask - tighten_ticks, best_bid + 1)
        else:
            bid_price = best_bid
            ask_price = best_ask

        bid_extra = 0
        ask_relax = 0
        if stats["trend_ticks"] >= float(self.params.get("strong_trend_ticks", 0.8)):
            bid_extra += 1
            ask_relax += 1
        if stats["residual_z"] <= -float(self.params.get("cheap_residual_z", 0.8)):
            bid_extra += 1
        if stats["residual_z"] >= float(self.params.get("rich_residual_z", 0.8)):
            ask_relax = max(0, ask_relax - 1)

        if position < inv_target:
            ask_relax = max(ask_relax, 1)
        elif position > inv_target:
            bid_extra = max(0, bid_extra - 1)

        max_bid_extra = int(self.params.get("max_bid_extra_ticks", 2))
        max_ask_relax = int(self.params.get("max_ask_relax_ticks", 2))
        bid_extra = max(0, min(max_bid_extra, bid_extra))
        ask_relax = max(0, min(max_ask_relax, ask_relax))

        bid_price = min(best_ask - 1, bid_price + bid_extra)
        ask_price = min(best_ask, ask_price + ask_relax)
        ask_price = max(ask_price, best_bid + 1)

        if bid_price >= ask_price:
            bid_price = min(best_ask - 1, best_bid + 1)
            ask_price = max(best_bid + 1, bid_price + 1)

        return bid_price, ask_price, bid_extra, ask_relax

    def _selective_take(
        self,
        *,
        order_depth: OrderDepth,
        fair_value: float,
        position: int,
        inv_target: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []

        take_edge = float(self.params.get("take_edge", 6.0))
        max_take = int(self.params.get("max_take_size", 10))
        take_only_toward_target = bool(self.params.get("take_only_toward_target", True))

        if buy_cap > 0:
            for ask_price in sorted(order_depth.sell_orders):
                if ask_price > fair_value - take_edge:
                    break
                if take_only_toward_target and position >= inv_target:
                    break
                qty = min(-order_depth.sell_orders[ask_price], buy_cap, max_take)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, ask_price, qty))
                buy_cap -= qty
                position += qty
                if buy_cap <= 0:
                    break

        if sell_cap > 0:
            for bid_price in sorted(order_depth.buy_orders, reverse=True):
                if bid_price < fair_value + take_edge:
                    break
                if take_only_toward_target and position <= inv_target:
                    break
                qty = min(order_depth.buy_orders[bid_price], sell_cap, max_take)
                if qty <= 0:
                    continue
                orders.append(Order(self.product, bid_price, -qty))
                sell_cap -= qty
                position -= qty
                if sell_cap <= 0:
                    break

        return orders, buy_cap, sell_cap

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
        stats = self._update_regression(mid=mid, memory=memory)
        inv_target = self._inventory_target(state=state, stats=stats, position=position)

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if bool(self.params.get("enable_selective_take", False)):
            take_orders, buy_cap, sell_cap = self._selective_take(
                order_depth=order_depth,
                fair_value=stats["fair_value"],
                position=position,
                inv_target=inv_target,
                buy_cap=buy_cap,
                sell_cap=sell_cap,
            )
            orders.extend(take_orders)

        bid_price, ask_price, bid_extra, ask_relax = self._quote_prices(
            book=book,
            stats=stats,
            position=position,
            inv_target=inv_target,
        )
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
        memory["last_spread"] = book.spread

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "buy_size": buy_size,
                "sell_size": sell_size,
                "reg_slope": round(stats["slope"], 4),
                "reg_r2": round(stats["r2"], 3),
                "trend_ticks": round(stats["trend_ticks"], 2),
                "residual_z": round(stats["residual_z"], 2),
                "fair_value": round(stats["fair_value"], 2),
                "inv_target": inv_target,
                "bid_extra": bid_extra,
                "ask_relax": ask_relax,
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        stats = memory.get("regression_stats")
        if not stats:
            return {}
        return {
            "reg_fitted_now": float(stats["fitted_now"]),
            "reg_forecast": float(stats["forecast"]),
            "reg_fair_value": float(stats["fair_value"]),
        }
