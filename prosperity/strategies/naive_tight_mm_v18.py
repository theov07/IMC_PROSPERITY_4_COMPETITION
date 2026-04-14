"""Trend-Biased Market Maker V18.

Complete rewrite based on one core lesson from V10-V17:
    the strategy was quoting on only 7-15 ticks per session (out of ~1000)
    because complex hold/block logic silenced both sides.
    Meanwhile, when it DID quote, bid-fill-rate was 1.73-2.14 per tick.
    → The right fix is: ALWAYS QUOTE.  Just change the asymmetry.

Architecture (biased MM with trend filter):
──────────────────────────────────────────
1. Fair Value  = EWM of mid-price (alpha = fv_alpha).
2. Slope       = FV[t] - FV[t - slope_window].
   Bullish when slope > bull_threshold (default 1.0).

3. Quote prices (relative to FV, not the book):
   ┌──────────┬─────────────────────────────────────────┐
   │ Mode     │ bid          │ ask                       │
   ├──────────┼──────────────┼───────────────────────────┤
   │ Bullish  │ FV - 1       │ FV + ask_spread_bull (≥9) │
   │ Neutral  │ FV - neut_sp │ FV + neut_sp              │
   └──────────┴──────────────┴───────────────────────────┘
   The bullish ask is placed ABOVE the current best_ask so it waits
   for price to rise to our level rather than selling early.
   Both prices are clamped inside the book so we never cross.

4. Takes:
   - Bullish + below target inventory: take best_ask aggressively
     (take_buy_edge_bull is negative so the threshold covers the spread).
   - Neutral + excess long inventory: take best_bid aggressively to unwind.
   - Standard take_edge otherwise.

5. Inventory target: +target_bull when bullish, 0 when neutral.
   Passive sizing is skewed toward the target via the standard
   aggravate/unwind sizing logic (no blocking, never silences both sides).

No "hold" logic, no "block_rebuy", no trim regime — just always quote.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class TrendBiasedMMV18Strategy(BaseStrategy):

    # ------------------------------------------------------------------
    def _take_orders(
        self,
        order_depth: OrderDepth,
        fv: float,
        buy_edge: float,
        sell_edge: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, int]:
        """Take aggressively-priced orders.

        Buy  if ask_price <= fv - buy_edge   (negative buy_edge = buy above FV)
        Sell if bid_price >= fv + sell_edge  (negative sell_edge = sell below FV)
        """
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
        """Inventory-aware passive sizing.  Never returns (0, 0)."""
        maker_size = int(self.params.get("maker_size", self.position_limit()))
        buy_size = min(buy_cap, maker_size)
        sell_size = min(sell_cap, maker_size)

        soft_ratio = float(self.params.get("inventory_soft_ratio", 0.40))
        aggravate_min = float(self.params.get("aggravate_min_frac", 0.20))
        unwind_boost = float(self.params.get("unwind_boost_frac", 0.30))
        limit = float(self.position_limit())

        pressure = abs(position - inv_target) / max(1.0, limit)
        if pressure <= soft_ratio or soft_ratio >= 1.0:
            return buy_size, sell_size

        scaled = min(1.0, (pressure - soft_ratio) / max(1e-9, 1.0 - soft_ratio))
        agg_frac = 1.0 - (1.0 - aggravate_min) * scaled
        boost = 1.0 + unwind_boost * scaled

        if position > inv_target:
            buy_size = max(1, int(round(buy_size * agg_frac)))
            sell_size = min(sell_cap, max(1, int(round(sell_size * boost))))
        elif position < inv_target:
            sell_size = max(1, int(round(sell_size * agg_frac)))
            buy_size = min(buy_cap, max(1, int(round(buy_size * boost))))

        return buy_size, sell_size

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

        # ── Params ────────────────────────────────────────────────────
        fv_alpha = float(self.params.get("fv_alpha", 0.05))
        slope_window = int(self.params.get("slope_window", 20))
        bull_threshold = float(self.params.get("bull_threshold", 1.0))

        bid_spread_bull = float(self.params.get("bid_spread_bull", 1.0))
        ask_spread_bull = float(self.params.get("ask_spread_bull", 9.0))
        neut_spread_bid = float(self.params.get("neut_spread_bid", 2.0))
        neut_spread_ask = float(self.params.get("neut_spread_ask", 5.0))

        # Take edges (negative = take above/below FV in that direction)
        take_buy_edge_bull = float(self.params.get("take_buy_edge_bull", -8.0))
        take_sell_edge_bull = float(self.params.get("take_sell_edge_bull", 6.0))
        take_buy_edge_neut = float(self.params.get("take_buy_edge_neut", 2.0))
        take_sell_edge_neut = float(self.params.get("take_sell_edge_neut", 2.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 10.0))

        target_bull = int(self.params.get("target_bull", 40))

        # ── Guard ─────────────────────────────────────────────────────
        if book.best_bid is None or book.best_ask is None:
            return orders, 0

        mid = (book.best_bid + book.best_ask) / 2.0

        # ── Fair Value (EWM) ──────────────────────────────────────────
        fv = float(memory.get("fv", mid))
        fv = fv_alpha * mid + (1.0 - fv_alpha) * fv
        memory["fv"] = fv

        # ── Slope ─────────────────────────────────────────────────────
        fv_hist = memory.setdefault("fv_hist", [])
        fv_hist.append(fv)
        if len(fv_hist) > slope_window + 1:
            del fv_hist[:-(slope_window + 1)]

        slope = 0.0
        if len(fv_hist) >= slope_window:
            slope = fv_hist[-1] - fv_hist[-slope_window]
        memory["slope"] = slope

        bullish = slope > bull_threshold
        inv_target = target_bull if bullish else 0

        # ── Quote prices (FV-based, clamped to book) ──────────────────
        if bullish:
            raw_bid = round(fv - bid_spread_bull)
            raw_ask = round(fv + ask_spread_bull)
        else:
            raw_bid = round(fv - neut_spread_bid)
            raw_ask = round(fv + neut_spread_ask)

        # Clamp: bid must be < best_ask; ask must be > best_bid
        bid_price = min(max(raw_bid, 1), book.best_ask - 1)
        ask_price = max(raw_ask, book.best_bid + 1)
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        # ── Take edges ────────────────────────────────────────────────
        if bullish:
            buy_edge = take_buy_edge_bull   # negative → take best_ask
            sell_edge = take_sell_edge_bull  # positive → conservative sell
        else:
            buy_edge = take_buy_edge_neut
            sell_edge = take_sell_edge_neut

        # Aggressive unwind when long and not bullish
        limit = self.position_limit()
        if not bullish and position > inv_target:
            pressure = min(1.0, (position - inv_target) / max(1.0, float(limit)))
            sell_edge = sell_edge - unwind_take_edge * pressure

        # ── Takes ─────────────────────────────────────────────────────
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        take_orders, buy_cap, sell_cap, take_count = self._take_orders(
            order_depth=order_depth,
            fv=fv,
            buy_edge=buy_edge,
            sell_edge=sell_edge,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )
        orders.extend(take_orders)

        # ── Passive sizing ────────────────────────────────────────────
        buy_size, sell_size = self._size_quotes(
            position=position,
            inv_target=inv_target,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
        )

        # ── Emit passive orders (ALWAYS, never block) ─────────────────
        if buy_size > 0:
            orders.append(Order(self.product, bid_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.product, ask_price, -sell_size))

        # ── Bookkeeping ───────────────────────────────────────────────
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
                "takes": take_count,
            },
        )

        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if memory.get("fv") is not None:
            out["fv"] = memory["fv"]
        return out
