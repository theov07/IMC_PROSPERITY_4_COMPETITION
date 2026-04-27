"""HYDROGEL_PACK mean-reversion — mv_v3: AR signal + Mark 14 integration.

Built on mv_v2's AR model (fair_value = anchor_ema + ar_shift, deviation smoothing).
Adds Mark 14's informed-trading signal in four integration modes (mark14_mode param):

  "gate"      — AR fires, then Mark 14 must confirm within m14_wait_ticks.
                 Both signals must agree to enter. Most conservative.

  "scale"     — AR decides entry direction; Mark 14 scales position size.
                 M14 agrees  → size × m14_agree_factor.
                 M14 opposes → skip entry entirely.
                 M14 silent  → base entry_size.

  "primary"   — Mark 14 is the primary trigger; AR must confirm direction.
                 M14 buys  → enter only if dev < -ar_confirm_threshold.
                 M14 sells → enter only if dev > +ar_confirm_threshold.
                 M14 silent → no entry.

  "threshold" — M14 dynamically adjusts the AR entry threshold.
                 M14 agrees  → threshold × (1 − m14_threshold_factor).
                 M14 opposes → threshold × (1 + m14_threshold_factor).
                 M14 silent  → base threshold.

Exit: identical to mv_v2 — exit when |dev_smooth| < exit_threshold.
State machine: flat → entering → holding → exiting.
All orders are taker. Self-contained (BaseStrategy only).

Key params (v2 AR params plus):
  mark14_mode             — integration mode (default "gate")
  informed_trader_name    — counterparty name (default "Mark 14")
  m14_lookback_ticks      — window for M14 recent direction (default 10)
  m14_wait_ticks          — max ticks to wait in gate mode (default 10)
  m14_agree_factor        — size multiplier in scale mode (default 2.0)
  ar_confirm_threshold    — min |dev| for primary mode (default 5.0)
  m14_threshold_factor    — threshold adjustment in threshold mode (default 0.3)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydroMVV3(BaseStrategy):

    # ── AR model (identical to mv_v2) ─────────────────────────────────────

    def _update_ar(
        self, raw_mid: float, memory: Dict[str, Any],
    ) -> Tuple[float, float, float]:
        """Return (mid_smooth, fair_value, dev_smooth)."""
        ms_hl    = float(self.params.get("mid_smooth_half_life", 20))
        ms_alpha = 1.0 - 0.5 ** (1.0 / ms_hl)
        prev_ms  = memory.get("_mid_smooth")
        mid_s    = raw_mid if prev_ms is None else ms_alpha * raw_mid + (1.0 - ms_alpha) * float(prev_ms)
        memory["_mid_smooth"] = mid_s

        anchor_fixed = float(self.params.get("anchor_price", 10000))
        anchor_alpha = float(self.params.get("anchor_alpha", 0.02))
        drift_bound  = float(self.params.get("anchor_drift_bound", 1.5))
        anchor_ema   = float(memory.get("_anchor_ema", anchor_fixed))
        if anchor_alpha > 0:
            anchor_ema = anchor_alpha * raw_mid + (1.0 - anchor_alpha) * anchor_ema
            if drift_bound > 0:
                anchor_ema = max(anchor_fixed - drift_bound,
                                 min(anchor_fixed + drift_bound, anchor_ema))
        memory["_anchor_ema"] = anchor_ema

        ar_hl    = float(self.params.get("ar_smooth_half_life", 5))
        ar_alpha = 1.0 - 0.5 ** (1.0 / ar_hl)
        delta    = 0.0 if prev_ms is None else mid_s - float(prev_ms)
        ar_mom   = float(memory.get("_ar_momentum", 0.0))
        ar_mom   = ar_alpha * delta + (1.0 - ar_alpha) * ar_mom
        memory["_ar_momentum"] = ar_mom

        ar_gain    = float(self.params.get("ar_gain", 8.0))
        fair_value = anchor_ema - ar_gain * ar_mom
        memory["_fair_value"] = fair_value

        raw_dev = mid_s - fair_value
        memory["_dev_raw"] = raw_dev

        dev_hl    = float(self.params.get("dev_smooth_half_life", 5))
        dev_alpha = 1.0 - 0.5 ** (1.0 / dev_hl)
        dev_s     = float(memory.get("_dev_smooth", raw_dev))
        dev_s     = dev_alpha * raw_dev + (1.0 - dev_alpha) * dev_s
        memory["_dev_smooth"] = dev_s

        return mid_s, fair_value, dev_s

    # ── Mark 14 tracking ──────────────────────────────────────────────────

    def _update_m14(
        self, state: TradingState, memory: Dict[str, Any],
    ) -> int:
        """Record M14's net direction this tick; return +1 / -1 / 0."""
        trader = str(self.params.get("informed_trader_name", "Mark 14"))
        net = 0
        for trade in state.market_trades.get(self.product, []):
            if trade.buyer == trader:
                net += trade.quantity
            elif trade.seller == trader:
                net -= trade.quantity
        this_tick = 1 if net > 0 else (-1 if net < 0 else 0)
        memory["_m14_this"] = this_tick

        lookback = int(self.params.get("m14_lookback_ticks", 10))
        hist: List[int] = memory.setdefault("_m14_hist", [])
        hist.append(this_tick)
        if len(hist) > lookback:
            hist[:] = hist[-lookback:]
        return this_tick

    def _m14_recent(self, memory: Dict[str, Any]) -> int:
        hist = memory.get("_m14_hist", [])
        net  = sum(hist)
        return 1 if net > 0 else (-1 if net < 0 else 0)

    # ── Order helpers ─────────────────────────────────────────────────────

    def _taker_buy(self, position: int, book: BookSnapshot, size: int) -> List[Order]:
        qty = min(self.buy_capacity(position), size)
        if qty > 0 and book.best_ask is not None:
            return [Order(self.product, book.best_ask, qty)]
        return []

    def _taker_sell(self, position: int, book: BookSnapshot, size: int) -> List[Order]:
        qty = min(self.sell_capacity(position), size)
        if qty > 0 and book.best_bid is not None:
            return [Order(self.product, book.best_bid, -qty)]
        return []

    # ── Entry resolution (mode-specific) ─────────────────────────────────

    def _resolve_entry(
        self,
        dev: float,
        m14_recent: int,
        m14_this: int,
        memory: Dict[str, Any],
    ) -> Tuple[int, int]:
        """Return (direction, size) or (0, 0) for no entry."""
        mode       = str(self.params.get("mark14_mode", "gate"))
        base_size  = int(self.params.get("entry_size", 20))
        base_thresh = float(self.params.get("entry_threshold", 20.0))

        if mode == "gate":
            raw_dir = 0
            if dev < -base_thresh: raw_dir = 1
            elif dev > base_thresh: raw_dir = -1
            return self._entry_gate(raw_dir, m14_recent, m14_this, base_size, memory)

        elif mode == "scale":
            raw_dir = 0
            if dev < -base_thresh: raw_dir = 1
            elif dev > base_thresh: raw_dir = -1
            return self._entry_scale(raw_dir, m14_recent, base_size)

        elif mode == "primary":
            return self._entry_primary(dev, m14_recent, base_size)

        elif mode == "threshold":
            return self._entry_threshold(dev, m14_recent, base_size, base_thresh)

        else:  # pure AR fallback
            if dev < -base_thresh: return 1, base_size
            if dev > base_thresh: return -1, base_size
            return 0, 0

    def _entry_gate(
        self, ar_dir: int, m14_recent: int, m14_this: int,
        size: int, memory: Dict[str, Any],
    ) -> Tuple[int, int]:
        if ar_dir == 0:
            memory.pop("_pending", None)
            return 0, 0
        if m14_recent == ar_dir:
            memory.pop("_pending", None)
            return ar_dir, size
        if m14_recent != 0:  # opposing
            memory.pop("_pending", None)
            return 0, 0
        # M14 silent → wait
        wait_max = int(self.params.get("m14_wait_ticks", 10))
        pending  = memory.get("_pending")
        if pending is None or pending.get("dir") != ar_dir:
            memory["_pending"] = {"dir": ar_dir, "ticks": 0}
            return 0, 0
        pending["ticks"] += 1
        if m14_this == ar_dir:
            memory.pop("_pending", None)
            return ar_dir, size
        if m14_this != 0:
            memory.pop("_pending", None)
            return 0, 0
        if pending["ticks"] >= wait_max:
            memory.pop("_pending", None)
            return 0, 0
        return 0, 0

    def _entry_scale(
        self, ar_dir: int, m14_recent: int, base_size: int,
    ) -> Tuple[int, int]:
        if ar_dir == 0:
            return 0, 0
        if m14_recent != 0 and m14_recent != ar_dir:
            return 0, 0  # M14 opposes → skip
        factor = float(self.params.get("m14_agree_factor", 2.0))
        size   = int(base_size * factor) if m14_recent == ar_dir else base_size
        return ar_dir, size

    def _entry_primary(
        self, dev: float, m14_recent: int, base_size: int,
    ) -> Tuple[int, int]:
        if m14_recent == 0:
            return 0, 0
        confirm = float(self.params.get("ar_confirm_threshold", 5.0))
        if m14_recent > 0 and dev < -confirm:
            return 1, base_size
        if m14_recent < 0 and dev > confirm:
            return -1, base_size
        return 0, 0

    def _entry_threshold(
        self, dev: float, m14_recent: int, base_size: int, base_thresh: float,
    ) -> Tuple[int, int]:
        factor = float(self.params.get("m14_threshold_factor", 0.3))
        if m14_recent > 0:
            buy_t  = base_thresh * (1.0 - factor)
            sell_t = base_thresh * (1.0 + factor)
        elif m14_recent < 0:
            buy_t  = base_thresh * (1.0 + factor)
            sell_t = base_thresh * (1.0 - factor)
        else:
            buy_t = sell_t = base_thresh
        if dev < -buy_t:  return 1, base_size
        if dev >  sell_t: return -1, base_size
        return 0, 0

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

        mid_s, fair_value, dev = self._update_ar(float(mid), memory)
        m14_this   = self._update_m14(state, memory)
        m14_recent = self._m14_recent(memory)

        exit_thresh = float(self.params.get("exit_threshold", 2.0))
        mv_state    = memory.get("_mv_state", "flat")
        intent      = memory.get("_intent",   0)
        orders: List[Order] = []

        # ── Exit check ────────────────────────────────────────────────────
        if mv_state in ("entering", "holding"):
            if (intent > 0 and dev > -exit_thresh) or (intent < 0 and dev < exit_thresh):
                mv_state = "exiting"
                memory["_mv_state"] = "exiting"

        # ── State machine ─────────────────────────────────────────────────
        if mv_state == "flat":
            direction, size = self._resolve_entry(dev, m14_recent, m14_this, memory)
            if direction > 0:
                orders = self._taker_buy(position, book, size)
                if orders:
                    memory["_intent"]        = 1
                    memory["_entry_target"]  = size
                    memory["_mv_state"]      = "entering"
            elif direction < 0:
                orders = self._taker_sell(position, book, size)
                if orders:
                    memory["_intent"]        = -1
                    memory["_entry_target"]  = size
                    memory["_mv_state"]      = "entering"

        elif mv_state == "entering":
            target_abs = memory.get("_entry_target",
                                    int(self.params.get("entry_size", 20)))
            target     = target_abs if intent > 0 else -target_abs
            remaining  = target - position
            if abs(remaining) <= 0:
                memory["_mv_state"] = "holding"
            elif remaining > 0:
                orders = self._taker_buy(position, book, remaining)
            else:
                orders = self._taker_sell(position, book, abs(remaining))

        elif mv_state == "holding":
            pass

        elif mv_state == "exiting":
            if position > 0:
                orders = self._taker_sell(position, book, position)
            elif position < 0:
                orders = self._taker_buy(position, book, abs(position))
            else:
                memory["_mv_state"] = "flat"
                memory["_intent"]   = 0
                memory.pop("_pending", None)

        # ── Logging ───────────────────────────────────────────────────────
        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":   position,
                "mid_smooth": round(mid_s, 3),
                "fair_value": round(fair_value, 3),
                "deviation":  round(dev, 3),
                "m14_this":   m14_this,
                "m14_recent": m14_recent,
                "mv_state":   mv_state,
                "intent":     intent,
            },
        )
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value"))  is not None: out["FairValue"]  = float(v)
        if (v := memory.get("_anchor_ema"))  is not None: out["AnchorEMA"]  = float(v)
        if (v := memory.get("_mid_smooth"))  is not None: out["MidSmooth"]  = float(v)
        if (v := memory.get("_dev_smooth"))  is not None: out["DevSmooth"]  = float(v)
        if (v := memory.get("_m14_this"))    is not None: out["M14This"]    = float(v)
        st = memory.get("_mv_state", "flat")
        out["MvStateN"] = {"flat": 0, "entering": 1, "holding": 2, "exiting": 3}.get(st, -1)
        return out
