"""Low-risk live probes for option microstructure.

This strategy is intentionally diagnostic. It tests event-based hypotheses that
can be invisible in the historical backtest/live-like replay:

- far passive fills away from the visible best bid/ask;
- thin L1 / large L1-L2 gap sweeps;
- market-trade flow follow vs fade.

No timestamp schedule or day-specific oracle is used. Startup behaviour is kept
optional, but the main probes are event/interval based.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class OptionLiveProbeMMStrategy(BaseStrategy):
    """Diagnostic option probe for IMC live-only alpha."""

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None:
            return [], 0

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []

        gap_orders, buy_cap, sell_cap = self._gap_sweep(order_depth, memory, buy_cap, sell_cap)
        orders.extend(gap_orders)

        flow_orders, buy_cap, sell_cap = self._flow_probe(
            state, order_depth, memory, buy_cap, sell_cap
        )
        orders.extend(flow_orders)

        far_orders, buy_cap, sell_cap = self._far_probes(
            state, book, memory, buy_cap, sell_cap
        )
        orders.extend(far_orders)

        memory["_prev_best_bid"] = int(book.best_bid)
        memory["_prev_best_ask"] = int(book.best_ask)
        memory["_last_position"] = int(position)

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=book.best_bid,
            ask_price=book.best_ask,
            extras={
                "position": int(position),
                "gap_bid_streak": int(memory.get("_gap_bid_streak", 0)),
                "gap_ask_streak": int(memory.get("_gap_ask_streak", 0)),
                "flow_score": round(float(memory.get("_flow_score", 0.0)), 3),
                "far_probe": int(bool(far_orders)),
                "gap_sweep": int(bool(gap_orders)),
                "flow_probe": int(bool(flow_orders)),
            },
        )
        return orders, 0

    def _far_probes(
        self,
        state: TradingState,
        book: BookSnapshot,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        distances = self.params.get("far_probe_distances") or []
        if not distances:
            return [], buy_cap, sell_cap

        interval_ticks = int(self.params.get("far_probe_interval_ticks", 200))
        ts_increment = int(self.params.get("ts_increment", 100))
        now = int(state.timestamp)
        last_ts = int(memory.get("_last_far_probe_ts", -10**12))
        if now - last_ts < interval_ticks * ts_increment:
            return [], buy_cap, sell_cap

        qty = max(1, int(self.params.get("far_probe_qty", 1)))
        orders: List[Order] = []
        for dist in distances:
            d = int(dist)
            if d <= 0:
                continue
            if buy_cap > 0:
                bid_px = max(1, int(book.best_bid) - d)
                q = min(qty, buy_cap)
                orders.append(Order(self.product, bid_px, q))
                buy_cap -= q
                memory["_last_far_bid"] = bid_px
            if sell_cap > 0:
                ask_px = int(book.best_ask) + d
                q = min(qty, sell_cap)
                orders.append(Order(self.product, ask_px, -q))
                sell_cap -= q
                memory["_last_far_ask"] = ask_px

        if orders:
            memory["_last_far_probe_ts"] = now
            memory["_far_probe_count"] = int(memory.get("_far_probe_count", 0)) + 1
        return orders, buy_cap, sell_cap

    def _gap_sweep(
        self,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        gap_min = int(self.params.get("gap_sweep_min", 0))
        if gap_min <= 0:
            return [], buy_cap, sell_cap

        max_l1 = int(self.params.get("gap_sweep_max_l1_qty", 6))
        confirm = max(1, int(self.params.get("gap_sweep_confirm_ticks", 1)))
        size = max(1, int(self.params.get("gap_sweep_size", 1)))
        orders: List[Order] = []

        bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        asks = sorted(order_depth.sell_orders.keys())

        bid_ok = False
        if len(bids) >= 2:
            bid1, bid2 = int(bids[0]), int(bids[1])
            bid1_qty = int(order_depth.buy_orders[bid1])
            bid_ok = (bid1 - bid2) >= gap_min and bid1_qty <= max_l1
        bid_streak = int(memory.get("_gap_bid_streak", 0))
        bid_streak = bid_streak + 1 if bid_ok else 0
        memory["_gap_bid_streak"] = bid_streak

        ask_ok = False
        if len(asks) >= 2:
            ask1, ask2 = int(asks[0]), int(asks[1])
            ask1_qty = int(-order_depth.sell_orders[ask1])
            ask_ok = (ask2 - ask1) >= gap_min and ask1_qty <= max_l1
        ask_streak = int(memory.get("_gap_ask_streak", 0))
        ask_streak = ask_streak + 1 if ask_ok else 0
        memory["_gap_ask_streak"] = ask_streak

        if ask_streak >= confirm and ask_ok and buy_cap > 0 and asks:
            ask1 = int(asks[0])
            available = int(-order_depth.sell_orders[ask1])
            q = min(size, buy_cap, available)
            if q > 0:
                orders.append(Order(self.product, ask1, q))
                buy_cap -= q
                memory["_last_gap_side"] = 1
        if bid_streak >= confirm and bid_ok and sell_cap > 0 and bids:
            bid1 = int(bids[0])
            available = int(order_depth.buy_orders[bid1])
            q = min(size, sell_cap, available)
            if q > 0:
                orders.append(Order(self.product, bid1, -q))
                sell_cap -= q
                memory["_last_gap_side"] = -1

        if orders:
            memory["_gap_sweep_count"] = int(memory.get("_gap_sweep_count", 0)) + 1
        return orders, buy_cap, sell_cap

    def _flow_probe(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        mode = str(self.params.get("flow_mode", "off"))
        if mode not in {"follow", "fade"}:
            return [], buy_cap, sell_cap

        prev_bid = memory.get("_prev_best_bid")
        prev_ask = memory.get("_prev_best_ask")
        if prev_bid is None or prev_ask is None:
            return [], buy_cap, sell_cap

        hist = memory.setdefault("_flow_hist", [])
        for trade in state.market_trades.get(self.product, []):
            qty = int(trade.quantity)
            if int(trade.price) >= int(prev_ask):
                hist.append(qty)
            elif int(trade.price) <= int(prev_bid):
                hist.append(-qty)

        window = max(1, int(self.params.get("flow_window", 30)))
        if len(hist) > window:
            del hist[:-window]
        total = sum(abs(x) for x in hist)
        if total <= 0:
            memory["_flow_score"] = 0.0
            return [], buy_cap, sell_cap

        flow = sum(hist) / total
        memory["_flow_score"] = flow
        threshold = float(self.params.get("flow_threshold", 0.75))
        if abs(flow) < threshold:
            return [], buy_cap, sell_cap

        interval_ticks = int(self.params.get("flow_interval_ticks", 20))
        ts_increment = int(self.params.get("ts_increment", 100))
        now = int(state.timestamp)
        last_ts = int(memory.get("_last_flow_probe_ts", -10**12))
        if now - last_ts < interval_ticks * ts_increment:
            return [], buy_cap, sell_cap

        direction = 1 if flow > 0 else -1
        if mode == "fade":
            direction *= -1

        qty = max(1, int(self.params.get("flow_size", 1)))
        orders: List[Order] = []
        if direction > 0 and buy_cap > 0 and order_depth.sell_orders:
            ask = int(min(order_depth.sell_orders))
            available = int(-order_depth.sell_orders[ask])
            q = min(qty, buy_cap, available)
            if q > 0:
                orders.append(Order(self.product, ask, q))
                buy_cap -= q
        elif direction < 0 and sell_cap > 0 and order_depth.buy_orders:
            bid = int(max(order_depth.buy_orders))
            available = int(order_depth.buy_orders[bid])
            q = min(qty, sell_cap, available)
            if q > 0:
                orders.append(Order(self.product, bid, -q))
                sell_cap -= q

        if orders:
            memory["_last_flow_probe_ts"] = now
            memory["_flow_probe_count"] = int(memory.get("_flow_probe_count", 0)) + 1
        return orders, buy_cap, sell_cap

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        out["flow_score"] = float(memory.get("_flow_score", 0.0))
        out["far_probe_count"] = float(memory.get("_far_probe_count", 0))
        out["gap_sweep_count"] = float(memory.get("_gap_sweep_count", 0))
        out["flow_probe_count"] = float(memory.get("_flow_probe_count", 0))
        if memory.get("_last_far_bid") is not None:
            out["last_far_bid"] = float(memory["_last_far_bid"])
        if memory.get("_last_far_ask") is not None:
            out["last_far_ask"] = float(memory["_last_far_ask"])
        if memory.get("_last_gap_side") is not None:
            out["last_gap_side"] = float(memory["_last_gap_side"])
        return out
