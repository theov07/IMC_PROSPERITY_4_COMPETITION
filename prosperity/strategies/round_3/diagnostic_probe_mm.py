"""Diagnostic probe — minimal trading, MAX logging for live alpha discovery.

Tests two hypotheses that can only be measured in IMC live:

G1 (Named participants): Track buyer/seller of every market trade. In live IMC
some rounds expose participant names (Caesar/Valentina/...). If certain names
correlate with adverse selection, we can follow/fade them. In the current 3-day
backtest data and the recent live logs we collected, all market_trades show
empty buyer/seller, but the probe logs them anyway in case live exposes names.

G2 (Adverse selection): For every one of OUR fills, record the mid price at
fill time. After N ticks (default 5), check if mid moved AGAINST our position.
A high "adverse rate" per product means we're being picked off — informed
counterparties are taking the other side and the price moves against us.

The probe trades minimally (1 lot every interval ticks, far passive only) so
the PnL is small but the data collection is comprehensive. Read the quote
trace afterwards to extract the adverse-selection rate per product.

Params:
  far_probe_distances     : [25, 50, 100] — distances from mid for passive ladders
  far_probe_interval_ticks: 200 — minimum ticks between probe rounds
  far_probe_qty           : 1 — qty per ladder rung
  adverse_horizon_ticks   : 5 — how many ticks to wait before measuring mid move
  adverse_max_window      : 50 — max fills tracked at once (memory bound)
  participant_log_max     : 30 — last N market trades with named buyer/seller
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class DiagnosticProbeMMStrategy(BaseStrategy):
    """Live-only alpha discovery: participant tracking + adverse selection."""

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

        ts = int(state.timestamp)
        mid = float(book.mid_price)

        # G1: Track named participants in market_trades
        self._track_participants(state, memory)

        # G2: Track adverse selection on our fills
        self._track_adverse_selection(state, memory, mid, ts)

        # Issue minimal far-quote probes to generate data
        orders, buy_cap, sell_cap = self._far_probes(
            state, book, memory,
            self.buy_capacity(position),
            self.sell_capacity(position),
        )

        memory["_prev_best_bid"] = int(book.best_bid)
        memory["_prev_best_ask"] = int(book.best_ask)
        memory["_last_mid"] = mid

        # Emit detailed trace for log analysis
        adverse_stats = memory.get("_adverse_stats", {})
        avg_adv = adverse_stats.get("avg_signed_mtm", 0.0)
        adverse_count = adverse_stats.get("adverse_count", 0)
        total_count = adverse_stats.get("total_count", 0)

        named_count = memory.get("_named_participant_count", 0)
        last_buyer = memory.get("_last_named_buyer", "")
        last_seller = memory.get("_last_named_seller", "")

        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=book.best_bid,
            ask_price=book.best_ask,
            extras={
                "position": int(position),
                "fills_tracked": int(total_count),
                "adverse_count": int(adverse_count),
                "adverse_rate": round(adverse_count / total_count, 3) if total_count else 0.0,
                "avg_signed_mtm": round(avg_adv, 3),
                "named_market_trades": int(named_count),
                "last_buyer_hash": _str_hash(last_buyer),
                "last_seller_hash": _str_hash(last_seller),
                "n_far_probes": int(memory.get("_far_probe_count", 0)),
                "session_phase": _session_phase(ts),
            },
        )

        return orders, 0

    # ─── G1: Named participant tracking ───────────────────────────────────────
    def _track_participants(self, state: TradingState, memory: Dict[str, Any]) -> None:
        """Log every market_trade with non-empty buyer/seller string."""
        trades = state.market_trades.get(self.product, [])
        if not trades:
            return

        named_log: List[str] = memory.setdefault("_named_participants", [])
        max_log = int(self.params.get("participant_log_max", 30))

        for t in trades:
            buyer = str(getattr(t, "buyer", "") or "")
            seller = str(getattr(t, "seller", "") or "")
            if buyer:
                named_log.append(f"B:{buyer}@{t.timestamp}:{t.quantity}@{t.price}")
                memory["_last_named_buyer"] = buyer
                memory["_named_participant_count"] = int(memory.get("_named_participant_count", 0)) + 1
            if seller:
                named_log.append(f"S:{seller}@{t.timestamp}:{t.quantity}@{t.price}")
                memory["_last_named_seller"] = seller
                memory["_named_participant_count"] = int(memory.get("_named_participant_count", 0)) + 1

        # Bound memory
        if len(named_log) > max_log:
            del named_log[:-max_log]

    # ─── G2: Adverse selection tracking ───────────────────────────────────────
    def _track_adverse_selection(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        current_mid: float,
        ts: int,
    ) -> None:
        """For each of our fills, record (fill_price, side, ts). After
        adverse_horizon_ticks, compute signed_mtm = side * (current_mid - fill_price).
        Negative = adverse to us.
        """
        horizon_ticks = int(self.params.get("adverse_horizon_ticks", 5))
        ts_increment = int(self.params.get("ts_increment", 100))
        horizon_us = horizon_ticks * ts_increment
        max_window = int(self.params.get("adverse_max_window", 50))

        # 1) Add new own_trades to pending
        pending: List[Tuple[int, int, float, int]] = memory.setdefault("_pending_fills", [])
        for trade in state.own_trades.get(self.product, []):
            if trade.timestamp != state.timestamp - ts_increment:
                # Only fills from the IMMEDIATELY previous tick (avoid double-counting)
                continue
            side = 1 if trade.buyer == "SUBMISSION" else -1
            pending.append((int(trade.timestamp), side, float(trade.price), int(trade.quantity)))

        # 2) Resolve pending fills whose horizon has elapsed
        adverse_stats = memory.setdefault("_adverse_stats", {
            "total_signed_mtm": 0.0,
            "total_count": 0,
            "adverse_count": 0,
            "avg_signed_mtm": 0.0,
            "by_horizon_signed": [],  # list of (horizon_passed_ts, signed_mtm)
        })

        still_pending: List[Tuple[int, int, float, int]] = []
        for fill_ts, side, price, qty in pending:
            if ts >= fill_ts + horizon_us:
                signed_mtm = side * (current_mid - price) * qty
                adverse_stats["total_signed_mtm"] += signed_mtm
                adverse_stats["total_count"] += 1
                if signed_mtm < 0:
                    adverse_stats["adverse_count"] += 1
                # Bounded history
                hist = adverse_stats["by_horizon_signed"]
                hist.append([ts, round(signed_mtm, 2)])
                if len(hist) > max_window:
                    del hist[: len(hist) - max_window]
            else:
                still_pending.append((fill_ts, side, price, qty))
        memory["_pending_fills"] = still_pending

        if adverse_stats["total_count"] > 0:
            adverse_stats["avg_signed_mtm"] = (
                adverse_stats["total_signed_mtm"] / adverse_stats["total_count"]
            )

    # ─── Minimal far-quote probes (data generation only) ──────────────────────
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
            if sell_cap > 0:
                ask_px = int(book.best_ask) + d
                q = min(qty, sell_cap)
                orders.append(Order(self.product, ask_px, -q))
                sell_cap -= q

        if orders:
            memory["_last_far_probe_ts"] = now
            memory["_far_probe_count"] = int(memory.get("_far_probe_count", 0)) + 1
        return orders, buy_cap, sell_cap

    # ─── Feature snapshot for downstream tools ────────────────────────────────
    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        adv = memory.get("_adverse_stats", {})
        out["fills_tracked"] = float(adv.get("total_count", 0))
        out["adverse_count"] = float(adv.get("adverse_count", 0))
        out["avg_signed_mtm"] = float(adv.get("avg_signed_mtm", 0.0))
        if adv.get("total_count", 0):
            out["adverse_rate"] = float(adv["adverse_count"]) / float(adv["total_count"])
        out["named_market_trades"] = float(memory.get("_named_participant_count", 0))
        return out


def _session_phase(ts: int) -> int:
    """Return 0/1/2 for early/mid/late phase of a 100k-ts session."""
    if ts < 33_000:
        return 0
    elif ts < 66_000:
        return 1
    return 2


def _str_hash(s: str) -> int:
    """Stable short hash for log compression. Returns 0 for empty strings."""
    if not s:
        return 0
    h = 0
    for c in s:
        h = (h * 31 + ord(c)) & 0xFFFF
    return h
