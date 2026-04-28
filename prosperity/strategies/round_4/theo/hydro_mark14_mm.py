from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class R4HydroMark14MMStrategy(BaseStrategy):
    """HYDROGEL market maker inspired by Mark 14's passive style.

    Core idea:
      - keep quotes passive near the top of book
      - use very small size, like Mark 14's observed fills
      - let inventory skew and counterparty flow decide which side stays active
      - avoid complicated taker logic unless inventory gets stretched
    """

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

        bb = int(book.best_bid)
        ba = int(book.best_ask)
        mid = float(book.mid_price)
        spread = float(book.spread or (ba - bb))

        fair = self._update_ema("fair_ema", mid, float(self.params.get("ema_alpha", 0.02)), memory)
        fast = self._update_ema("fast_ema", mid, float(self.params.get("fast_alpha", 0.08)), memory)
        micro = self._microprice(book)
        signal = self._counterparty_signal(state, memory)

        micro_shift = float(self.params.get("micro_alpha", 0.0)) * (micro - mid)
        signal_shift = float(self.params.get("signal_fair_shift", 0.0)) * signal
        reservation = fair + micro_shift + signal_shift - float(self.params.get("inventory_gamma", 0.03)) * position
        edge = reservation - mid
        trend = fast - fair

        bid_price, ask_price = self._quote_prices(bb, ba, spread)
        bid_size, ask_size = self._quote_sizes(
            position=position,
            edge=edge,
            trend=trend,
            signal=signal,
        )

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        if bid_size > 0 and buy_cap > 0:
            orders.append(Order(self.product, bid_price, min(bid_size, buy_cap)))
        if ask_size > 0 and sell_cap > 0:
            orders.append(Order(self.product, ask_price, -min(ask_size, sell_cap)))

        taker = self._inventory_relief_order(
            position=position,
            buy_cap=buy_cap,
            sell_cap=sell_cap,
            bb=bb,
            ba=ba,
            edge=edge,
            signal=signal,
        )
        if taker is not None:
            orders.append(Order(self.product, taker[0], taker[1]))
        else:
            directional = self._directional_take_order(
                state=state,
                memory=memory,
                position=position,
                buy_cap=buy_cap,
                sell_cap=sell_cap,
                bb=bb,
                ba=ba,
                edge=edge,
                trend=trend,
            )
            if directional is not None:
                orders.append(Order(self.product, directional[0], directional[1]))

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price if bid_size > 0 else None,
            ask_price=ask_price if ask_size > 0 else None,
            extras={
                "fair": round(fair, 2),
                "micro": round(micro, 2),
                "signal": round(signal, 2),
                "trend": round(trend, 2),
                "edge": round(edge, 2),
                "reservation": round(reservation, 2),
                "bid_size": bid_size,
                "ask_size": ask_size,
            },
        )
        return orders, 0

    def _update_ema(self, key: str, value: float, alpha: float, memory: Dict[str, Any]) -> float:
        prev = memory.get(key)
        if prev is None:
            ema = value
        else:
            ema = alpha * value + (1.0 - alpha) * float(prev)
        memory[key] = ema
        return ema

    def _counterparty_signal(self, state: TradingState, memory: Dict[str, Any]) -> float:
        alpha = float(self.params.get("signal_alpha", 0.45))
        decay = float(self.params.get("signal_decay", 0.82))
        qty_norm = max(1.0, float(self.params.get("signal_qty_norm", 6.0)))
        clip = max(0.0, float(self.params.get("signal_clip", 6.0)))

        raw = 0.0
        mark14_w = float(self.params.get("mark14_weight", 0.35))
        mark38_w = float(self.params.get("mark38_weight", 0.75))
        for trade in state.market_trades.get(self.product, []):
            qty = float(trade.quantity)
            if getattr(trade, "buyer", None) == "Mark 14":
                raw += mark14_w * qty
            if getattr(trade, "seller", None) == "Mark 14":
                raw -= mark14_w * qty
            if getattr(trade, "buyer", None) == "Mark 38":
                raw -= mark38_w * qty
            if getattr(trade, "seller", None) == "Mark 38":
                raw += mark38_w * qty

        raw /= qty_norm
        prev = float(memory.get("_signal", 0.0))
        signal = prev * decay if abs(raw) < 1e-9 else alpha * raw + (1.0 - alpha) * prev
        if clip > 0.0:
            signal = max(-clip, min(clip, signal))
        memory["_signal"] = signal
        return signal

    def _quote_prices(self, bb: int, ba: int, spread: float) -> tuple[int, int]:
        improve_ticks = int(self.params.get("improve_ticks", 0))
        min_spread_to_improve = float(self.params.get("min_spread_to_improve", 100.0))
        if improve_ticks <= 0 or spread < min_spread_to_improve:
            return bb, ba
        bid = min(bb + improve_ticks, ba - 1)
        ask = max(ba - improve_ticks, bb + 1)
        return int(bid), int(ask)

    def _quote_sizes(self, position: int, edge: float, trend: float, signal: float) -> tuple[int, int]:
        limit = max(1, int(self.position_limit()))
        base = float(self.params.get("base_size", 6))
        min_size = int(self.params.get("min_size", 2))
        max_size = int(self.params.get("max_size", 12))
        quote_edge = float(self.params.get("quote_edge", 0.8))
        edge_boost = int(self.params.get("edge_boost", 4))
        signal_size_skew = float(self.params.get("signal_size_skew", 0.45))
        trend_guard = float(self.params.get("trend_guard", 2.5))
        trend_soft = bool(self.params.get("trend_soft", True))
        trend_position_gate = int(self.params.get("trend_position_gate", 20))
        inv_reduce = float(self.params.get("inventory_reduce_per_unit", 0.08))
        inv_unwind = float(self.params.get("inventory_unwind_per_unit", 0.05))
        dynamic_inventory_sizing = bool(self.params.get("dynamic_inventory_sizing", False))

        if dynamic_inventory_sizing:
            inventory_ratio = max(-1.0, min(1.0, position / limit))
            bid_size = base * (1.0 - inventory_ratio)
            ask_size = base * (1.0 + inventory_ratio)
        else:
            bid_size = base
            ask_size = base

        if edge > quote_edge:
            bid_size += edge_boost
            ask_size -= edge_boost // 2
        elif edge < -quote_edge:
            ask_size += edge_boost
            bid_size -= edge_boost // 2

        skew = max(-1.0, min(1.0, signal / max(1e-9, float(self.params.get("signal_clip", 6.0)))))
        if skew > 0.0:
            bid_size += int(round(base * signal_size_skew * skew))
            ask_size -= int(round(base * 0.5 * signal_size_skew * skew))
        elif skew < 0.0:
            ask_size += int(round(base * signal_size_skew * -skew))
            bid_size -= int(round(base * 0.5 * signal_size_skew * -skew))

        if trend > trend_guard and position <= trend_position_gate:
            ask_size = max(0, ask_size // 2) if trend_soft else 0
        elif trend < -trend_guard and position >= -trend_position_gate:
            bid_size = max(0, bid_size // 2) if trend_soft else 0

        if not dynamic_inventory_sizing:
            if position > 0:
                bid_size -= position * inv_reduce
                ask_size += position * inv_unwind
            elif position < 0:
                ask_size -= (-position) * inv_reduce
                bid_size += (-position) * inv_unwind

        bid_size = max(0, min(max_size, int(round(bid_size))))
        ask_size = max(0, min(max_size, int(round(ask_size))))
        if 0 < bid_size < min_size:
            bid_size = min_size
        if 0 < ask_size < min_size:
            ask_size = min_size
        return bid_size, ask_size

    def _inventory_relief_order(
        self,
        *,
        position: int,
        buy_cap: int,
        sell_cap: int,
        bb: int,
        ba: int,
        edge: float,
        signal: float,
    ) -> tuple[int, int] | None:
        hard_cap = int(self.params.get("relief_position_threshold", 60))
        relief_size = int(self.params.get("relief_size", 2))
        edge_gate = float(self.params.get("relief_edge_gate", 1.0))
        signal_gate = float(self.params.get("relief_signal_gate", 1.0))

        if position >= hard_cap and (edge < -edge_gate or signal < -signal_gate) and sell_cap > 0:
            return bb, -min(relief_size, sell_cap)
        if position <= -hard_cap and (edge > edge_gate or signal > signal_gate) and buy_cap > 0:
            return ba, min(relief_size, buy_cap)
        return None

    def _directional_take_order(
        self,
        *,
        state: TradingState,
        memory: Dict[str, Any],
        position: int,
        buy_cap: int,
        sell_cap: int,
        bb: int,
        ba: int,
        edge: float,
        trend: float,
    ) -> tuple[int, int] | None:
        take_edge = float(self.params.get("take_edge", 0.0))
        if take_edge <= 0.0:
            return None

        take_trend_guard = float(self.params.get("take_trend_guard", 3.0))
        take_position_gate = int(self.params.get("take_position_gate", 20))
        take_size = int(self.params.get("take_size", 1))
        cooldown = int(self.params.get("take_cooldown_ts", 0))
        last_take = int(memory.get("_last_take_ts", -10**9))
        if cooldown > 0 and int(state.timestamp) - last_take < cooldown:
            return None
        if abs(trend) > take_trend_guard:
            return None

        if edge >= take_edge and position < take_position_gate and buy_cap > 0:
            memory["_last_take_ts"] = int(state.timestamp)
            return ba, min(take_size, buy_cap)
        if edge <= -take_edge and position > -take_position_gate and sell_cap > 0:
            memory["_last_take_ts"] = int(state.timestamp)
            return bb, -min(take_size, sell_cap)
        return None

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (fair := memory.get("fair_ema")) is not None:
            out["fair"] = float(fair)
        if (signal := memory.get("_signal")) is not None:
            out["signal"] = float(signal)
        return out
