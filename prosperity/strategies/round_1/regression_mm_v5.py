"""Block-smoothed regression market maker for INTARIAN_PEPPER_ROOT.

This V5 keeps the V3 market-making mechanics, but changes the signal model.

Why:
- tick-by-tick linear fits on INTARIAN_PEPPER_ROOT are visibly trending, but
  still noisy at the micro level
- when we aggregate mids in blocks of 100 ticks, the observed line quality is
  dramatically higher: the day-level fit reaches roughly 0.97+ R^2
- for market making, that smoother line is more useful than a noisy per-tick
  regression because we want a stable directional fair value, not a twitchy
  micro predictor

How it works:
- bootstrap with a prior slope early in the session
- maintain completed 100-tick block means of the mid price
- fit OLS on block centers instead of raw ticks
- project the smoothed trend back to the current tick
- quote top of book asymmetrically around that smoothed trend line
- keep a positive inventory bias while the trend remains clean
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class Round1RegressionMMV5Strategy(BaseStrategy):
    def _update_regression(
        self,
        *,
        state: TradingState,
        mid: float,
        memory: Dict[str, Any],
    ) -> Dict[str, float]:
        ts_increment = max(1, int(self.params.get("ts_increment", 100)))
        seed_slope = float(self.params.get("seed_slope", 0.1015))
        block_size = max(1, int(self.params.get("block_size", 100)))
        min_completed_blocks = max(1, int(self.params.get("min_completed_blocks", 5)))
        horizon = int(self.params.get("reg_horizon", 25))
        r2_floor = float(self.params.get("reg_r2_floor", 0.85))
        r2_cap = float(self.params.get("reg_r2_cap", 0.98))
        rmse_floor = float(self.params.get("reg_rmse_floor", 1.0))
        mean_revert_weight = float(self.params.get("reg_residual_reversion", 0.25))

        anchor_ts = memory.setdefault("line_anchor_ts", int(state.timestamp))
        anchor_mid = memory.setdefault("line_anchor_mid", mid)
        tick_index = max(0, int(round((int(state.timestamp) - anchor_ts) / ts_increment)))

        completed_means = memory.setdefault("block_means", [])
        completed_centers = memory.setdefault("block_centers", [])
        current_block_index = int(memory.get("current_block_index", 0))
        block_sum = float(memory.get("current_block_sum", 0.0))
        block_count = int(memory.get("current_block_count", 0))

        target_block_index = tick_index // block_size
        if target_block_index != current_block_index and block_count > 0:
            start_tick = current_block_index * block_size
            end_tick = start_tick + block_count - 1
            completed_means.append(block_sum / block_count)
            completed_centers.append((start_tick + end_tick) / 2.0)
            current_block_index = target_block_index
            block_sum = 0.0
            block_count = 0

        block_sum += mid
        block_count += 1
        memory["current_block_index"] = current_block_index
        memory["current_block_sum"] = block_sum
        memory["current_block_count"] = block_count

        current_block_mean = block_sum / max(1, block_count)
        current_block_start = current_block_index * block_size
        current_block_center = current_block_start + (block_count - 1) / 2.0

        xs: List[float] = list(completed_centers)
        ys: List[float] = list(completed_means)
        if block_count > 0:
            xs.append(current_block_center)
            ys.append(current_block_mean)

        if len(completed_means) < min_completed_blocks:
            slope = seed_slope
            intercept = anchor_mid
            fit_r2 = 0.0
            fitted_now = anchor_mid + slope * tick_index
            residual = mid - fitted_now
            rmse = max(abs(residual), rmse_floor)
            confidence = float(self.params.get("bootstrap_confidence", 0.55))
        else:
            n = len(xs)
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n

            ss_xx = 0.0
            ss_xy = 0.0
            for x, y in zip(xs, ys):
                dx = x - mean_x
                dy = y - mean_y
                ss_xx += dx * dx
                ss_xy += dx * dy

            slope = ss_xy / ss_xx if ss_xx > 0 else seed_slope
            intercept = mean_y - slope * mean_x
            fitted_points = [intercept + slope * x for x in xs]
            fitted_now = intercept + slope * tick_index
            residual = mid - fitted_now

            ss_tot = sum((y - mean_y) ** 2 for y in ys)
            ss_res = sum((y - fit) ** 2 for y, fit in zip(ys, fitted_points))
            fit_r2 = 0.0 if ss_tot <= 1e-9 else max(0.0, 1.0 - ss_res / ss_tot)
            rmse = max(math.sqrt(ss_res / max(1, n)), rmse_floor)

            if r2_cap <= r2_floor:
                confidence = 1.0 if fit_r2 > r2_floor else 0.0
            else:
                confidence = max(0.0, min(1.0, (fit_r2 - r2_floor) / (r2_cap - r2_floor)))

        trend_ticks = slope * horizon * confidence
        residual_z = residual / rmse if rmse > 0 else 0.0
        forecast = intercept + slope * (tick_index + horizon)
        fair_value = forecast - mean_revert_weight * residual

        stats = {
            "slope": slope,
            "intercept": intercept,
            "fitted_now": fitted_now,
            "forecast": forecast,
            "residual": residual,
            "rmse": rmse,
            "r2": fit_r2,
            "confidence": confidence,
            "trend_ticks": trend_ticks,
            "fair_value": fair_value,
            "residual_z": residual_z,
            "block_count": float(len(completed_means)),
            "current_block_mean": current_block_mean,
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
        trend_inv_per_tick = float(self.params.get("trend_inv_per_tick", 26.0))
        resid_inv_per_z = float(self.params.get("resid_inv_per_z", 7.0))
        inv_cap = int(self.params.get("trend_inventory_cap", 74))

        target = stats["trend_ticks"] * trend_inv_per_tick
        target -= stats["residual_z"] * resid_inv_per_z

        startup_target = int(self.params.get("startup_target", 40))
        startup_end_ts = int(self.params.get("startup_end_ts", 30000))
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
        gap_scale = max(1.0, float(self.params.get("target_gap_scale", 26.0)))
        bullish_boost = max(0.0, stats["trend_ticks"]) * float(self.params.get("trend_buy_boost_per_tick", 0.24))
        bearish_boost = max(0.0, -stats["trend_ticks"]) * float(self.params.get("trend_sell_boost_per_tick", 0.20))
        cheap_boost = max(0.0, -stats["residual_z"]) * float(self.params.get("cheap_buy_boost_per_z", 0.18))
        rich_boost = max(0.0, stats["residual_z"]) * float(self.params.get("rich_sell_boost_per_z", 0.14))

        buy_mult = 1.0 + max(0.0, gap) / gap_scale + bullish_boost + cheap_boost
        sell_mult = 1.0 + max(0.0, -gap) / gap_scale + bearish_boost + rich_boost

        aggravate_cut = float(self.params.get("aggravate_cut", 0.04))
        if gap > 0:
            sell_mult *= aggravate_cut
        elif gap < 0:
            buy_mult *= aggravate_cut

        one_sided_gap = int(self.params.get("one_sided_target_gap", 24))
        strong_trend = float(self.params.get("strong_trend_ticks", 1.1))
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
        if stats["trend_ticks"] >= float(self.params.get("strong_trend_ticks", 1.1)):
            bid_extra += 1
            ask_relax += 1
        if stats["trend_ticks"] >= float(self.params.get("very_strong_trend_ticks", 2.0)):
            bid_extra += 1
        if stats["residual_z"] <= -float(self.params.get("cheap_residual_z", 0.9)):
            bid_extra += 1
        if stats["residual_z"] >= float(self.params.get("rich_residual_z", 1.0)):
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

        take_edge = float(self.params.get("take_edge", 8.0))
        max_take = int(self.params.get("max_take_size", 8))
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
        stats = self._update_regression(state=state, mid=mid, memory=memory)
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
                "block_count": int(stats["block_count"]),
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
