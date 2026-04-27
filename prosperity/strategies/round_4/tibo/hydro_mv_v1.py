"""HYDROGEL_PACK mean-reversion — mv_v1: z-score + Mark 14 confirmation gate.

Signal: z-score of EWMA-smoothed mid price over a rolling window.
  z < -entry_z  → price is depressed → BUY signal (expect reversion up)
  z > +entry_z  → price is elevated → SELL signal (expect reversion down)
  |z| < exit_z  → price has normalised → exit current position

Mark 14 gate: directional bets are only executed when Mark 14 confirms.
  Check his net direction over the last `m14_lookback_ticks` ticks.
  If inactive in that window: wait up to `m14_wait_ticks` for him to act.
    Mark 14 acts same direction   → execute immediately
    Mark 14 acts opposite         → discard the pending signal
    Timeout (wait window expires) → discard the pending signal

State machine stored in memory["_mv_state"]:
  "flat"     — no open position, scanning for signals
  "entering" — signal confirmed, building toward entry_size
  "holding"  — at target, waiting for z-score to normalise
  "exiting"  — exit condition met, unwinding position

Config params (all optional, defaults shown):
  zscore_window          — rolling buffer size for z-score (default 50)
  mid_smooth_half_life   — EWMA half-life (ticks) for mid smoothing (default 10)
  entry_z_threshold      — z-score magnitude to trigger entry (default 2.0)
  exit_z_threshold       — z-score magnitude to trigger exit (default 0.5)
  entry_size             — target position size for each bet (default 20)
  informed_trader_name   — counterparty to track (default "Mark 14")
  m14_lookback_ticks     — window to assess Mark 14's recent direction (default 10)
  m14_wait_ticks         — max ticks to wait for Mark 14 confirmation (default 10)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydroMVV1(BaseStrategy):

    # ── Mid price smoothing + z-score ─────────────────────────────────────

    def _update_zscore(self, raw_mid: float, memory: Dict[str, Any]) -> Optional[float]:
        """EWMA-smooth mid price, then compute rolling z-score.

        Step 1: smooth raw mid with EWMA (half-life = mid_smooth_half_life).
        Step 2: push smoothed value into a rolling buffer of length zscore_window.
        Step 3: z = (smoothed_mid - rolling_mean) / rolling_std.
        """
        # EWMA smooth
        hl    = float(self.params.get("mid_smooth_half_life", 10))
        alpha = 1.0 - 0.5 ** (1.0 / hl)
        prev  = memory.get("_mid_smooth")
        mid_s = raw_mid if prev is None else alpha * raw_mid + (1.0 - alpha) * float(prev)
        memory["_mid_smooth"] = mid_s

        # Rolling buffer
        window = int(self.params.get("zscore_window", 50))
        buf: List[float] = memory.setdefault("_zs_buf", [])
        buf.append(mid_s)
        if len(buf) > window:
            buf[:] = buf[-window:]

        if len(buf) < max(3, window // 4):
            memory["_zscore"] = None
            return None

        n    = len(buf)
        mean = sum(buf) / n
        std  = (sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)) ** 0.5
        if std < 1e-9:
            memory["_zscore"] = None
            return None

        z = (mid_s - mean) / std
        memory["_zscore"]  = z
        memory["_zs_mean"] = mean
        memory["_zs_std"]  = std
        return z

    # ── Mark 14 tracking ──────────────────────────────────────────────────

    def _update_m14_history(
        self, state: TradingState, memory: Dict[str, Any],
    ) -> int:
        """Record Mark 14's net direction this tick; return +1 / -1 / 0."""
        trader = str(self.params.get("informed_trader_name", "Mark 14"))
        net = 0
        for trade in state.market_trades.get(self.product, []):
            if trade.buyer == trader:
                net += trade.quantity
            elif trade.seller == trader:
                net -= trade.quantity
        this_tick = 1 if net > 0 else (-1 if net < 0 else 0)
        memory["_m14_this_tick"] = this_tick

        lookback = int(self.params.get("m14_lookback_ticks", 10))
        hist: List[int] = memory.setdefault("_m14_hist", [])
        hist.append(this_tick)
        if len(hist) > lookback:
            hist[:] = hist[-lookback:]
        return this_tick

    def _m14_recent_direction(self, memory: Dict[str, Any]) -> int:
        """Net direction Mark 14 has taken in the lookback window (+1, -1, 0)."""
        hist: List[int] = memory.get("_m14_hist", [])
        net = sum(hist)
        return 1 if net > 0 else (-1 if net < 0 else 0)

    # ── Order helpers ─────────────────────────────────────────────────────

    def _taker_buy(
        self, position: int, book: BookSnapshot, size: int,
    ) -> List[Order]:
        qty = min(self.buy_capacity(position), size)
        if qty > 0 and book.best_ask is not None:
            return [Order(self.product, book.best_ask, qty)]
        return []

    def _taker_sell(
        self, position: int, book: BookSnapshot, size: int,
    ) -> List[Order]:
        qty = min(self.sell_capacity(position), size)
        if qty > 0 and book.best_bid is not None:
            return [Order(self.product, book.best_bid, -qty)]
        return []

    # ── Signal resolution with Mark 14 gate ──────────────────────────────

    def _resolve_signal(
        self,
        raw_signal: int,        # +1 buy / -1 sell / 0 none
        m14_this_tick: int,
        memory: Dict[str, Any],
    ) -> int:
        """Return confirmed signal (±1) or 0 applying the Mark 14 gate.

        Logic:
          No raw signal → clear any pending state, return 0.
          Raw signal present:
            Mark 14 recent direction == signal  → confirm immediately.
            Mark 14 recent direction != 0 (opposing) → discard, return 0.
            Mark 14 inactive (recent == 0):
              Start or advance a pending wait.
              If Mark 14 acts this tick in our direction → confirm.
              If Mark 14 acts this tick opposite        → discard.
              If wait window expired                    → discard.
              Otherwise still waiting                   → return 0.
        """
        if raw_signal == 0:
            memory.pop("_pending", None)
            return 0

        wait_max    = int(self.params.get("m14_wait_ticks", 10))
        m14_recent  = self._m14_recent_direction(memory)
        pending     = memory.get("_pending")  # {"dir": ±1, "ticks": int}

        # Pending already exists for a different direction → replace it
        if pending is not None and pending["dir"] != raw_signal:
            memory.pop("_pending", None)
            pending = None

        # Mark 14 recently confirmed
        if m14_recent == raw_signal:
            memory.pop("_pending", None)
            return raw_signal

        # Mark 14 recently opposed
        if m14_recent != 0 and m14_recent != raw_signal:
            memory.pop("_pending", None)
            return 0

        # Mark 14 inactive in lookback window → pending logic
        if pending is None:
            # Fresh signal, start waiting
            memory["_pending"] = {"dir": raw_signal, "ticks": 0}
            return 0

        # Advance existing pending
        pending["ticks"] += 1

        if m14_this_tick == raw_signal:
            # Confirmed this tick
            memory.pop("_pending", None)
            return raw_signal

        if m14_this_tick != 0:
            # Opposed this tick
            memory.pop("_pending", None)
            return 0

        if pending["ticks"] >= wait_max:
            # Timeout
            memory.pop("_pending", None)
            return 0

        return 0  # still waiting

    # ── Main entry ────────────────────────────────────────────────────────

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:

        mid = book.mid_price
        if mid is None:
            return [], 0

        z            = self._update_zscore(float(mid), memory)
        m14_this_tick = self._update_m14_history(state, memory)

        entry_z = float(self.params.get("entry_z_threshold", 2.0))
        exit_z  = float(self.params.get("exit_z_threshold",  0.5))
        size    = int(self.params.get("entry_size", 20))

        mv_state: str = memory.get("_mv_state", "flat")
        orders: List[Order] = []

        # ── Exit condition (checked before new entries) ───────────────────
        if mv_state in ("holding", "entering") and z is not None:
            intent = memory.get("_intent", 0)
            # Long: exit when price has normalised (z risen back above -exit_z)
            # Short: exit when price has normalised (z fallen back below +exit_z)
            exit_triggered = (
                (intent > 0 and z > -exit_z) or
                (intent < 0 and z <  exit_z)
            )
            if exit_triggered:
                mv_state = "exiting"
                memory["_mv_state"] = "exiting"

        # ── State transitions ─────────────────────────────────────────────

        if mv_state == "flat":
            # Determine raw z-score signal
            if z is None:
                raw_signal = 0
            elif z < -entry_z:
                raw_signal = 1   # depressed → buy
            elif z > entry_z:
                raw_signal = -1  # elevated → sell
            else:
                raw_signal = 0

            confirmed = self._resolve_signal(raw_signal, m14_this_tick, memory)
            if confirmed > 0:
                orders = self._taker_buy(position, book, size)
                memory["_intent"]   = 1
                memory["_mv_state"] = "entering"
            elif confirmed < 0:
                orders = self._taker_sell(position, book, size)
                memory["_intent"]   = -1
                memory["_mv_state"] = "entering"

        elif mv_state == "entering":
            # Keep sending entry orders until we reach the target size
            intent = memory.get("_intent", 0)
            target = size if intent > 0 else -size
            remaining = target - position
            if abs(remaining) <= 0:
                memory["_mv_state"] = "holding"
            elif remaining > 0:
                orders = self._taker_buy(position, book, remaining)
            else:
                orders = self._taker_sell(position, book, abs(remaining))

        elif mv_state == "holding":
            pass  # wait for exit condition (checked above)

        elif mv_state == "exiting":
            # Unwind full position with taker orders
            if position > 0:
                orders = self._taker_sell(position, book, position)
            elif position < 0:
                orders = self._taker_buy(position, book, abs(position))
            else:
                # Fully unwound
                memory["_mv_state"] = "flat"
                memory["_intent"]   = 0
                memory.pop("_pending", None)

        # ── Logging ───────────────────────────────────────────────────────
        pending = memory.get("_pending")
        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":      position,
                "zscore":        round(z, 4) if z is not None else None,
                "mid_smooth":    round(float(memory.get("_mid_smooth", mid)), 4),
                "mv_state":      mv_state,
                "intent":        memory.get("_intent", 0),
                "m14_this_tick": m14_this_tick,
                "m14_recent":    self._m14_recent_direction(memory),
                "pending_dir":   pending["dir"]   if pending else 0,
                "pending_ticks": pending["ticks"] if pending else 0,
            },
        )
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (z  := memory.get("_zscore"))        is not None: out["Z"]          = float(z)
        if (m  := memory.get("_mid_smooth"))     is not None: out["MidSmooth"]  = float(m)
        if (mu := memory.get("_zs_mean"))        is not None: out["ZsMean"]     = float(mu)
        if (sd := memory.get("_zs_std"))         is not None: out["ZsStd"]      = float(sd)
        if (s  := memory.get("_m14_this_tick"))  is not None: out["M14Signal"]  = float(s)
        st = memory.get("_mv_state", "flat")
        out["MvStateN"] = {"flat": 0, "entering": 1, "holding": 2, "exiting": 3}.get(st, -1)
        return out
