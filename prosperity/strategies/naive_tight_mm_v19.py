"""Book-Following Trend Market Maker V19.

Root cause identified in V18:
    ask_spread_bull=9.0 → raw_ask = FV+9 ≈ best_ask+1.5 (ABOVE market)
    Buyers prefer the existing best_ask → we never sell (only 1 fill in live).

THE FIX (two lines):
    Bull ask  = min(round(fv + ask_spread_bull), book.best_ask)  → inside/at market
    Bull bid  = max(round(fv - bid_spread_bull), book.best_bid)  → at/above best bid

This guarantees we are always inside the book on both sides → fills happen.

Architecture:
─────────────────────────────────────────────────────────────────────
1. FV  = EWM(mid, fv_alpha=0.05)
2. Slope = FV[t] - FV[t-slope_window]
   Bullish when slope > bull_threshold.

3. Quote prices:
   ┌──────────┬────────────────────────────────┬──────────────────────────────────────┐
   │ Mode     │ bid                            │ ask                                  │
   ├──────────┼────────────────────────────────┼──────────────────────────────────────┤
   │ Bullish  │ max(FV-bid_spread_bull,        │ min(FV+ask_spread_bull, best_ask)    │
   │          │     best_bid)                  │   → AT or INSIDE the ask queue       │
   ├──────────┼────────────────────────────────┼──────────────────────────────────────┤
   │ Neutral  │ FV - neut_spread               │ FV + neut_spread                     │
   │          │ (clamped < best_ask)           │ (clamped > best_bid)                 │
   └──────────┴────────────────────────────────┴──────────────────────────────────────┘

4. Takes:
   - Bull: take best_ask when ask ≤ FV + take_buy_edge_bull (negative = take above FV)
   - Neutral + long: aggressive sell-take with unwind_take_edge.

5. Inventory target: +target_bull when bull, 0 when neutral.
   Sizing skewed via soft_ratio / aggravate / boost (never blocks both sides).

No hold, no block, no trim.  Always quotes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base import BaseStrategy


class BookFollowingTrendMMV19Strategy(BaseStrategy):

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
        """Aggressive order taking.

        Buy  when ask_price <= fv - buy_edge   (negative buy_edge → take above FV)
        Sell when bid_price >= fv + sell_edge  (high sell_edge → conservative)
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
        unwind_boost = float(self.params.get("unwind_boost_frac", 0.40))
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
        ask_spread_bull = float(self.params.get("ask_spread_bull", 7.0))
        neut_spread = float(self.params.get("neut_spread", 3.0))

        take_buy_edge_bull = float(self.params.get("take_buy_edge_bull", -2.0))
        take_sell_edge_bull = float(self.params.get("take_sell_edge_bull", 12.0))
        take_buy_edge_neut = float(self.params.get("take_buy_edge_neut", 2.0))
        take_sell_edge_neut = float(self.params.get("take_sell_edge_neut", 2.0))
        unwind_take_edge = float(self.params.get("unwind_take_edge", 8.0))

        target_bull = int(self.params.get("target_bull", 50))

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

        # ── Quote prices ──────────────────────────────────────────────
        if bullish:
            # THE FIX: cap ask at best_ask → always inside the market
            raw_bid = round(fv - bid_spread_bull)
            raw_ask = round(fv + ask_spread_bull)

            bid_price = max(raw_bid, book.best_bid)        # at least at best_bid
            bid_price = min(bid_price, book.best_ask - 1)  # never cross

            ask_price = min(raw_ask, book.best_ask)        # NEVER above best_ask
            ask_price = max(ask_price, book.best_bid + 1)  # never cross
        else:
            # Neutral: symmetric, clamped inside book
            raw_bid = round(fv - neut_spread)
            raw_ask = round(fv + neut_spread)
            bid_price = min(raw_bid, book.best_ask - 1)
            ask_price = max(raw_ask, book.best_bid + 1)

        if bid_price >= ask_price:
            bid_price = ask_price - 1

        # ── Take edges ────────────────────────────────────────────────
        if bullish:
            buy_edge = take_buy_edge_bull
            sell_edge = take_sell_edge_bull
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
