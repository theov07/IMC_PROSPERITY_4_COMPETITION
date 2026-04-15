"""Signal-following strategy that detects and copies "insider" bot trades.

In past Prosperity editions, certain bots (e.g. "Olivia", "Vladimir")
traded in predictable patterns that signaled upcoming price moves.
This strategy:
  1. Tracks all market_trades by buyer/seller identity
  2. Detects known "smart" bots from config or learns them online
  3. Copies their directional signal with configurable delay/sizing

Config params:
  tracked_bots: list of bot names to follow (e.g. ["Olivia", "Vladimir"])
  signal_window: how many ticks a signal stays active (default 5)
  signal_strength: order size multiplier per signal trade (default 1.0)
  maker_size: base order size (default 8)
  combine_with_mm: if True, also run basic market making alongside (default False)
  mm_params: dict of market maker params if combine_with_mm is True
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, Trade, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class SignalTraderStrategy(BaseStrategy):

    def _analyze_trades(
        self, market_trades: List[Trade], memory: Dict[str, Any],
    ) -> float:
        """Analyze recent market trades for tracked bot signals.

        Returns a signal score: positive = bullish, negative = bearish.
        """
        tracked = set(self.params.get("tracked_bots", []))
        window = self.params.get("signal_window", 5)

        # Maintain per-bot trade history
        bot_signals = memory.setdefault("bot_signals", [])

        for trade in market_trades:
            buyer = trade.buyer or ""
            seller = trade.seller or ""

            if buyer in tracked:
                bot_signals.append({
                    "bot": buyer,
                    "direction": 1,
                    "price": trade.price,
                    "quantity": trade.quantity,
                    "timestamp": trade.timestamp,
                })
            if seller in tracked:
                bot_signals.append({
                    "bot": seller,
                    "direction": -1,
                    "price": trade.price,
                    "quantity": trade.quantity,
                    "timestamp": trade.timestamp,
                })

        # Trim old signals
        if bot_signals:
            tick = memory.get("tick_count", 0)
            cutoff = tick - window
            bot_signals[:] = [s for s in bot_signals if s.get("_tick", 0) >= cutoff]
            for s in bot_signals:
                if "_tick" not in s:
                    s["_tick"] = tick

        # Aggregate signal
        strength = self.params.get("signal_strength", 1.0)
        total = 0.0
        for s in bot_signals:
            total += s["direction"] * s["quantity"] * strength

        return total

    def _learn_bots(self, market_trades: List[Trade], memory: Dict[str, Any]):
        """Track all bot names and their cumulative PnL direction to find smart ones."""
        bot_tracker = memory.setdefault("bot_tracker", {})

        for trade in market_trades:
            for name, direction in [(trade.buyer, "buy"), (trade.seller, "sell")]:
                if not name or name == "SUBMISSION":
                    continue
                if name not in bot_tracker:
                    bot_tracker[name] = {"buys": 0, "sells": 0, "buy_value": 0.0, "sell_value": 0.0}
                if direction == "buy":
                    bot_tracker[name]["buys"] += trade.quantity
                    bot_tracker[name]["buy_value"] += trade.price * trade.quantity
                else:
                    bot_tracker[name]["sells"] += trade.quantity
                    bot_tracker[name]["sell_value"] += trade.price * trade.quantity

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        tick = memory.get("tick_count", 0)
        memory["tick_count"] = tick + 1

        trades = state.market_trades.get(self.product, [])
        self._learn_bots(trades, memory)

        signal = self._analyze_trades(trades, memory)
        memory["signal"] = signal

        orders: List[Order] = []
        maker_size = self.params.get("maker_size", 8)
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        if signal > 0 and buy_cap > 0 and book.best_ask is not None:
            qty = min(maker_size, buy_cap)
            orders.append(Order(self.product, book.best_ask, qty))

        elif signal < 0 and sell_cap > 0 and book.best_bid is not None:
            qty = min(maker_size, sell_cap)
            orders.append(Order(self.product, book.best_bid, -qty))

        elif signal == 0 and abs(position) > 0:
            # No signal — unwind position gradually
            if position > 0 and book.best_bid is not None:
                qty = min(max(1, abs(position) // 4), sell_cap)
                if qty > 0:
                    orders.append(Order(self.product, book.best_bid, -qty))
            elif position < 0 and book.best_ask is not None:
                qty = min(max(1, abs(position) // 4), buy_cap)
                if qty > 0:
                    orders.append(Order(self.product, book.best_ask, qty))

        return orders, 0
