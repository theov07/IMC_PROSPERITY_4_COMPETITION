"""Naive passive market maker V9.

V9 extends V8 with a trend-following layer:

4. Trend signal (enabled when trend_alpha > 0):
   - Tracks a slow EMA of the mid price.
   - trend_signal = mid - trend_ema: positive means price above its slow
     average → uptrend; negative → downtrend.
   - Three adjustments flow from the signal:
     a) adjusted_mid = mid + trend_shift used as the reference for take
        decisions — we become opportunistic buyers in uptrends, sellers in
        downtrends, without paying up in the passive quote.
     b) Inventory target = round(trend_shift × trend_inv_target_per_tick):
        the _apply_inventory_sizing logic boosts size on the side that moves
        us toward the target position, which is long in uptrends.
     c) Take-edge boost: buy_edge is reduced by trend_shift × trend_take_boost
        in uptrends (and symmetrically for sell_edge in downtrends), making
        us more willing to cross the spread in the trend direction.
   - trend_alpha = 0 → no trend logic at all (identical to V8).

New params (all default to 0 / disabled):
  trend_alpha              : EMA decay factor per tick, e.g. 0.005
  trend_sensitivity        : price-ticks-of-signal → shift-ticks multiplier
  trend_max_shift          : absolute cap on the shift (ticks)
  trend_inv_target_per_tick: inventory units per shift tick, e.g. 6
  trend_take_boost         : take_edge reduction per shift tick, e.g. 0.3
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class NaiveTightMarketMakerV9Strategy(BaseStrategy):

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _take_orders(
        self,
        order_depth: OrderDepth,
        adjusted_mid: float,
        buy_edge: float,
        sell_edge: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, int]:
        """Take aggressively-priced orders on both sides.

        We buy  if ask_price <= adjusted_mid - buy_edge
        We sell if bid_price >= adjusted_mid + sell_edge
        """
        orders: List[Order] = []
        take_count = 0

        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > adjusted_mid - buy_edge or buy_cap <= 0:
                break
            available = -order_depth.sell_orders[ask_price]
            qty = min(available, buy_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, ask_price, qty))
            buy_cap -= qty
            take_count += 1

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < adjusted_mid + sell_edge or sell_cap <= 0:
                break
            volume = order_depth.buy_orders[bid_price]
            qty = min(volume, sell_cap)
            if qty <= 0:
                continue
            orders.append(Order(self.product, bid_price, -qty))
            sell_cap -= qty
            take_count += 1

        return orders, buy_cap, sell_cap, take_count

    def _apply_inventory_sizing(
        self,
        position: int,
        inv_target: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        """Size passive quotes relative to inv_target (0 when no trend)."""
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        buy_size = min(buy_cap, maker_size)
        sell_size = min(sell_cap, maker_size)

        soft_ratio = float(self.params.get("inventory_soft_ratio", 0.35))
        aggravate_min_frac = float(self.params.get("aggravate_min_frac", 0.25))
        unwind_boost_frac = float(self.params.get("unwind_boost_frac", 0.25))

        limit = float(self.position_limit())
        pressure = abs(position - inv_target) / max(1.0, limit)

        if pressure <= soft_ratio or soft_ratio >= 1.0:
            return buy_size, sell_size

        scaled = min(1.0, (pressure - soft_ratio) / max(1e-9, 1.0 - soft_ratio))
        aggravate_frac = 1.0 - (1.0 - aggravate_min_frac) * scaled
        unwind_mult = 1.0 + unwind_boost_frac * scaled

        if position > inv_target:
            # Above target: buying aggravates, selling unwinds
            if buy_size > 0:
                buy_size = max(1, int(round(buy_size * aggravate_frac)))
            if sell_size > 0:
                sell_size = min(sell_cap, max(1, int(round(sell_size * unwind_mult))))
        elif position < inv_target:
            # Below target: selling aggravates, buying unwinds
            if sell_size > 0:
                sell_size = max(1, int(round(sell_size * aggravate_frac)))
            if buy_size > 0:
                buy_size = min(buy_cap, max(1, int(round(buy_size * unwind_mult))))

        return buy_size, sell_size

    # ------------------------------------------------------------------
    # Main
    # ------------------------------------------------------------------

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []

        tighten_ticks = int(self.params.get("tighten_ticks", 1))
        take_edge = float(self.params.get("take_edge", 1.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 0.0))
        toxic_window = int(self.params.get("toxic_window", 6))
        toxic_threshold = float(self.params.get("toxic_threshold", 0.6))
        toxic_size_frac = float(self.params.get("toxic_size_frac", 0.5))
        jump_size_frac = float(self.params.get("jump_size_frac", 0.5))

        trend_alpha = float(self.params.get("trend_alpha", 0.0))
        trend_sensitivity = float(self.params.get("trend_sensitivity", 1.0))
        trend_max_shift = float(self.params.get("trend_max_shift", 5.0))
        trend_inv_target_per_tick = float(self.params.get("trend_inv_target_per_tick", 0.0))
        trend_take_boost = float(self.params.get("trend_take_boost", 0.0))

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        mid = (book.best_bid + book.best_ask) / 2.0

        # ── Trend signal ───────────────────────────────────────────────
        trend_shift = 0.0
        inv_target = 0
        if trend_alpha > 0.0:
            trend_ema = memory.get("trend_ema")
            if trend_ema is None:
                trend_ema = mid
            trend_ema = trend_alpha * mid + (1.0 - trend_alpha) * trend_ema
            memory["trend_ema"] = trend_ema

            raw_signal = mid - trend_ema
            trend_shift = max(
                -trend_max_shift,
                min(trend_max_shift, raw_signal * trend_sensitivity),
            )
            limit = self.position_limit()
            inv_target = int(round(
                max(-limit, min(limit, trend_shift * trend_inv_target_per_tick))
            ))

        # Adjusted mid: our perceived fair value including trend bias
        adjusted_mid = mid + trend_shift

        # ── Compute take edges ─────────────────────────────────────────
        # Base edges (symmetric)
        buy_edge = take_edge
        sell_edge = take_edge

        # Unwind relaxation (same as V8)
        pressure = abs(position - inv_target) / max(1.0, float(self.position_limit()))
        if position < inv_target:
            buy_edge = max(0.0, buy_edge - unwind_take_edge * pressure)
        elif position > inv_target:
            sell_edge = max(0.0, sell_edge - unwind_take_edge * pressure)

        # Trend boost: lower edge in the trend direction
        if trend_shift > 0.0:
            buy_edge = buy_edge - trend_shift * trend_take_boost
        elif trend_shift < 0.0:
            sell_edge = sell_edge - (-trend_shift) * trend_take_boost

        # ── Selective takes ────────────────────────────────────────────
        take_orders, buy_cap, sell_cap, take_count = self._take_orders(
            order_depth=order_depth,
            adjusted_mid=adjusted_mid,
            buy_edge=buy_edge,
            sell_edge=sell_edge,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )
        orders.extend(take_orders)

        swept_ask_prices = {o.price for o in take_orders if o.quantity > 0}
        swept_bid_prices = {o.price for o in take_orders if o.quantity < 0}

        real_best_ask = book.best_ask
        for ask_price, _ in book.ask_levels:
            if ask_price not in swept_ask_prices:
                real_best_ask = ask_price
                break

        real_best_bid = book.best_bid
        for bid_price, _ in book.bid_levels:
            if bid_price not in swept_bid_prices:
                real_best_bid = bid_price
                break

        # ── Passive quote prices ───────────────────────────────────────
        spread = real_best_ask - real_best_bid
        if spread >= 2:
            bid_price = min(real_best_bid + tighten_ticks, real_best_ask - 1)
            ask_price = max(real_best_ask - tighten_ticks, real_best_bid + 1)
        else:
            bid_price = real_best_bid
            ask_price = real_best_ask

        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # ── Passive quote sizes ────────────────────────────────────────
        buy_size, sell_size = self._apply_inventory_sizing(
            position=position,
            inv_target=inv_target,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        # ── Toxicity filter ────────────────────────────────────────────
        prev_best_bid = memory.get("prev_best_bid")
        prev_best_ask = memory.get("prev_best_ask")
        bid_jumped = bool(prev_best_bid is not None and real_best_bid == prev_best_bid + 1)
        ask_jumped = bool(prev_best_ask is not None and real_best_ask == prev_best_ask - 1)

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

        # In a trending market, flow_score will naturally be high; only apply
        # the filter if the trend agrees with the flow direction, otherwise
        # the "toxicity" is actually just trend continuation we want to ride.
        suppress_toxic = trend_alpha > 0.0 and (
            (flow_score > 0 and trend_shift > 1.0)
            or (flow_score < 0 and trend_shift < -1.0)
        )

        if not suppress_toxic:
            if flow_score > toxic_threshold and sell_size > 0:
                sell_size = max(1, int(round(sell_size * toxic_size_frac)))
            elif flow_score < -toxic_threshold and buy_size > 0:
                buy_size = max(1, int(round(buy_size * toxic_size_frac)))

        if bid_jumped and sell_size > 0:
            sell_size = max(1, int(round(sell_size * jump_size_frac)))
        if ask_jumped and buy_size > 0:
            buy_size = max(1, int(round(buy_size * jump_size_frac)))

        # ── Emit passive orders ────────────────────────────────────────
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        # ── State bookkeeping ──────────────────────────────────────────
        memory["prev_best_bid"] = real_best_bid
        memory["prev_best_ask"] = real_best_ask
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_flow_score"] = flow_score
        memory["last_take_count"] = take_count
        memory["inv_target"] = inv_target
        memory["trend_shift"] = trend_shift

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
            extras={
                "position": position,
                "buy_size": buy_size,
                "sell_size": sell_size,
                "flow_score": flow_score,
                "takes": take_count,
                "trend_shift": round(trend_shift, 2),
                "inv_target": inv_target,
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if memory.get("trend_ema") is not None:
            out["trend_ema"] = memory["trend_ema"]
        if memory.get("trend_shift") is not None:
            trend_shift = memory["trend_shift"]
            prev_bid = memory.get("last_bid_price")
            prev_ask = memory.get("last_ask_price")
            if prev_bid is not None and prev_ask is not None:
                out["adjusted_mid"] = (prev_bid + prev_ask) / 2.0 + trend_shift
        return out
