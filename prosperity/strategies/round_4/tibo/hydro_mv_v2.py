"""HYDROGEL_PACK mean-reversion — mv_v2: AR model signal.

Signal: deviation of smoothed mid from the AR model's fair value.

  fair_value  = anchor_ema  +  ar_shift
  anchor_ema  = slow EWMA of mid price, bounded to ±anchor_drift_bound of anchor_price
  ar_shift    = -ar_gain × EWMA(Δmid_smooth)   ← contrarian momentum

  deviation   = mid_smooth − fair_value
              = (mid_smooth − anchor_ema)  +  ar_gain × ewma_momentum
                └─ long-run dist from anchor ┘  └─ short-run momentum ┘

  When deviation < −entry_threshold  →  price below fair → BUY
  When deviation > +entry_threshold  →  price above fair → SELL
  When |deviation| < exit_threshold  →  exit current position

The deviation is optionally smoothed with a second EWMA (dev_smooth_half_life)
before the threshold comparison, to cut high-frequency noise.

State machine: flat → entering → holding → exiting  (same as mv_v1).
All orders are taker (best_ask for BUY, best_bid for SELL).

Key params:
  anchor_price          — mean-reversion target (default 10000)
  anchor_alpha          — anchor EMA speed (default 0.02; 0 = fully fixed)
  anchor_drift_bound    — max ticks anchor can drift from anchor_price (default 1.5)
  ar_gain               — momentum correction weight (default 1.0)
  ar_smooth_half_life   — half-life for EWMA of Δmid_smooth (default 5)
  mid_smooth_half_life  — half-life for mid price smoother (default 20)
  dev_smooth_half_life  — half-life for deviation smoother (default 10; 1 = raw)
  entry_threshold       — deviation ticks to enter (default 12.0)
  exit_threshold        — deviation ticks to exit (default 3.0)
  entry_size            — position size per bet (default 20)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydroMVV2(BaseStrategy):

    # ── Signal computation ────────────────────────────────────────────────

    def _update_ar(
        self, raw_mid: float, memory: Dict[str, Any],
    ) -> Tuple[float, float, float]:
        """Compute AR fair value and smoothed deviation.

        Returns (mid_smooth, fair_value, dev_smooth).
        """
        # ── 1. EWMA-smooth mid price ──────────────────────────────────────
        ms_hl   = float(self.params.get("mid_smooth_half_life", 20))
        ms_alpha = 1.0 - 0.5 ** (1.0 / ms_hl)
        prev_ms = memory.get("_mid_smooth")
        mid_s   = raw_mid if prev_ms is None else ms_alpha * raw_mid + (1.0 - ms_alpha) * float(prev_ms)
        memory["_mid_smooth"] = mid_s

        # ── 2. Slow-drift anchor EMA ──────────────────────────────────────
        anchor_fixed = float(self.params.get("anchor_price", 10000))
        anchor_alpha = float(self.params.get("anchor_alpha", 0.02))
        drift_bound  = float(self.params.get("anchor_drift_bound", 1.5))

        anchor_ema = float(memory.get("_anchor_ema", anchor_fixed))
        if anchor_alpha > 0:
            anchor_ema = anchor_alpha * raw_mid + (1.0 - anchor_alpha) * anchor_ema
            if drift_bound > 0:
                anchor_ema = max(anchor_fixed - drift_bound,
                                 min(anchor_fixed + drift_bound, anchor_ema))
        memory["_anchor_ema"] = anchor_ema

        # ── 3. AR momentum: EWMA of Δmid_smooth ──────────────────────────
        ar_hl    = float(self.params.get("ar_smooth_half_life", 5))
        ar_alpha = 1.0 - 0.5 ** (1.0 / ar_hl)
        delta    = 0.0
        if prev_ms is not None:
            delta = mid_s - float(prev_ms)
        ar_mom = float(memory.get("_ar_momentum", 0.0))
        ar_mom = ar_alpha * delta + (1.0 - ar_alpha) * ar_mom
        memory["_ar_momentum"] = ar_mom

        # ── 4. AR fair value ──────────────────────────────────────────────
        ar_gain    = float(self.params.get("ar_gain", 1.0))
        ar_shift   = -ar_gain * ar_mom          # contrarian: up move → fair value down
        fair_value = anchor_ema + ar_shift
        memory["_fair_value"] = fair_value

        # ── 5. Raw deviation ──────────────────────────────────────────────
        raw_dev = mid_s - fair_value
        memory["_dev_raw"] = raw_dev

        # ── 6. Smooth deviation (optional noise filter) ───────────────────
        dev_hl    = float(self.params.get("dev_smooth_half_life", 10))
        dev_alpha = 1.0 - 0.5 ** (1.0 / dev_hl)
        dev_s     = float(memory.get("_dev_smooth", raw_dev))
        dev_s     = dev_alpha * raw_dev + (1.0 - dev_alpha) * dev_s
        memory["_dev_smooth"] = dev_s

        return mid_s, fair_value, dev_s

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

        entry_thresh = float(self.params.get("entry_threshold", 12.0))
        exit_thresh  = float(self.params.get("exit_threshold",  3.0))
        size         = int(self.params.get("entry_size", 20))

        mv_state: str = memory.get("_mv_state", "flat")
        intent:   int = memory.get("_intent",   0)
        orders:   List[Order] = []

        # ── Exit check (always evaluated while in position) ───────────────
        if mv_state in ("entering", "holding"):
            exit_hit = (
                (intent > 0 and dev > -exit_thresh) or   # long: normalised up
                (intent < 0 and dev <  exit_thresh)       # short: normalised down
            )
            if exit_hit:
                mv_state = "exiting"
                memory["_mv_state"] = "exiting"

        # ── State machine ─────────────────────────────────────────────────

        if mv_state == "flat":
            if dev < -entry_thresh:
                orders = self._taker_buy(position, book, size)
                if orders:
                    memory["_intent"]   = 1
                    memory["_mv_state"] = "entering"
            elif dev > entry_thresh:
                orders = self._taker_sell(position, book, size)
                if orders:
                    memory["_intent"]   = -1
                    memory["_mv_state"] = "entering"

        elif mv_state == "entering":
            target    = size if intent > 0 else -size
            remaining = target - position
            if abs(remaining) <= 0:
                memory["_mv_state"] = "holding"
            elif remaining > 0:
                orders = self._taker_buy(position, book, remaining)
            else:
                orders = self._taker_sell(position, book, abs(remaining))

        elif mv_state == "holding":
            pass  # wait for exit condition

        elif mv_state == "exiting":
            if position > 0:
                orders = self._taker_sell(position, book, position)
            elif position < 0:
                orders = self._taker_buy(position, book, abs(position))
            else:
                memory["_mv_state"] = "flat"
                memory["_intent"]   = 0

        # ── Logging ───────────────────────────────────────────────────────
        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":   position,
                "mid_smooth": round(mid_s, 3),
                "fair_value": round(fair_value, 3),
                "deviation":  round(dev, 3),
                "ar_momentum":round(float(memory.get("_ar_momentum", 0)), 4),
                "anchor_ema": round(float(memory.get("_anchor_ema", 10000)), 3),
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
        if (v := memory.get("_dev_raw"))     is not None: out["DevRaw"]     = float(v)
        if (v := memory.get("_ar_momentum")) is not None: out["ARMomentum"] = float(v)
        st = memory.get("_mv_state", "flat")
        out["MvStateN"] = {"flat": 0, "entering": 1, "holding": 2, "exiting": 3}.get(st, -1)
        return out
