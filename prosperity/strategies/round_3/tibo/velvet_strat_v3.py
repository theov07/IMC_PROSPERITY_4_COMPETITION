"""velvet_strat_v3 — Signal-gated option accumulation using VELVETFRUIT z-score.

Builds on v2 logic. The key addition: instead of accumulating VEV calls blindly,
we gate accumulation on VELVETFRUIT's 500-tick rolling z-score.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WHY Z-SCORE MATTERS FOR OPTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VELVETFRUIT is strongly mean-reverting at 500-tick horizon (ACF ≈ -0.3 to -0.5).
  When z < -threshold: VELVETFRUIT is CHEAP → likely to rise soon.
    → BUY MORE calls (larger bid_size): directional bet + long vol both aligned.
  When z > +threshold: VELVETFRUIT is EXPENSIVE → likely to fall soon.
    → BUY LESS (shrink bid_size). Optionally SELL some calls (tighten ask_offset)
      to reduce delta exposure before the expected reversal.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CLASSES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VelvetMMV3      — VELVETFRUIT MM (same as v2) + computes z-score + writes to shared.
  VEVOptionMMV3   — VEV option MM (same as v2) + reads z-score + signal-gated sizing.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  EXECUTION APPROACHES (selectable via zscore_exec_mode param)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  "none"      — z-score off, pure passive MM (same as v2)
  "bid_only"  — scale bid_size up when cheap, down when expensive
  "ask_adapt" — also tighten ask when z > threshold (reduce exposure actively)
  "both"      — bid scale AND ask adaptation

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  KEY PARAMS (VEVOptionMMV3)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  zscore_exec_mode    "bid_only" | "ask_adapt" | "both" | "none"  (default "bid_only")
  zscore_window       rolling window for VELVETFRUIT z-score (default 500)
  zscore_threshold    |z| must exceed this to activate (default 1.0)
  zscore_bid_scale    slope: bid_factor = 1 + zscore_bid_scale × excess_|z|
                      excess_|z| = max(0, |z| - threshold)             (default 2.0)
  zscore_bid_max      cap on bid_size multiplier (default 4.0)
  ask_offset_neutral  ask offset when z is neutral (default 10, rarely fills)
  ask_offset_sell     ask offset when z > threshold (default 1, inside spread → sells)

  KEY PARAMS (VelvetMMV3) — same as VelvetMMV2 plus:
  zscore_window       window for z-score (default 500)

  Shared params (same as v2):
  strike, tte_days_initial, historical_tte_by_day, ticks_per_day, ts_increment,
  underlying_symbol, delta_sigma, min_quote_price, maker_size_bid, maker_size_ask

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  EXECUTION ORDER (important for z-score sharing)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Tick T: VEV options run first → read shared["velvet_zscore"] (from tick T-1)
           → publish vev_total_delta to shared
  Tick T: VelvetMMV3 runs last → computes z-score → writes shared["velvet_zscore"]
                                → reads vev_total_delta for implicit delta hedge
  The 1-tick lag on z-score is negligible for a 500-tick window.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.black_scholes import call_delta
from prosperity.options.time import (
    resolve_initial_tte_days,
    time_to_expiry_days,
    timestamp_units_per_day_from_params,
)
from prosperity.strategies.base.base import BaseStrategy


# ══════════════════════════════════════════════════════════════════════════════
#  CLASS 1 — VELVETFRUIT MM v3 (same as v2 + z-score write to shared)
# ══════════════════════════════════════════════════════════════════════════════

class VelvetMMV3(BaseStrategy):
    """VELVETFRUIT MM: penny-improve + delta hedge + writes z-score to shared."""

    def _compute_zscore(self, mid: float, memory: Dict[str, Any]) -> Optional[float]:
        """Rolling 500-tick z-score of VELVETFRUIT mid. Stored in memory + shared."""
        window = int(self.params.get("zscore_window", 500))
        buf: List[float] = memory.setdefault("_zs_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            return None
        n    = len(buf)
        mean = sum(buf) / n
        var  = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std  = var ** 0.5
        if std < 1e-9:
            return None
        return (mid - mean) / std

    def _compute_quote_prices(self, book: BookSnapshot) -> Tuple[Optional[int], Optional[int]]:
        bid = (book.best_bid + 1) if book.best_bid is not None else None
        ask = (book.best_ask - 1) if book.best_ask is not None else None
        if bid is not None and ask is not None and bid >= ask:
            ask = bid + 1
        return bid, ask

    def _compute_sizes(self, effective_pos: int, limit: int) -> Tuple[float, float]:
        base     = float(self.params.get("maker_size_base_pct", 0.30)) * limit
        bid_size = max(0.0, base * (1.0 - effective_pos / limit))
        ask_size = max(0.0, base * (1.0 + effective_pos / limit))
        return bid_size, ask_size

    def _passive_quotes(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        position: int,
        limit: int,
    ) -> List[Order]:
        quote_buy  = min(buy_cap,  max(0, int(bid_size)))
        quote_sell = min(sell_cap, max(0, int(ask_size)))
        hard_stop  = 1.0 - float(self.params.get("pct_kept_for_takers", 0.15))
        inv_abs    = abs(position) / float(limit) if limit else 0.0
        if inv_abs >= hard_stop:
            if position > 0:
                quote_buy  = 0
            elif position < 0:
                quote_sell = 0
        orders: List[Order] = []
        if quote_buy > 0 and bid_price is not None:
            orders.append(Order(self.product, bid_price, quote_buy))
        if quote_sell > 0 and ask_price is not None:
            orders.append(Order(self.product, ask_price, -quote_sell))
        return orders

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None and book.best_ask is None:
            if memory.get("_last_mid") is None:
                return [], 0

        raw_mid = book.mid_price or float(book.best_bid or book.best_ask or 0)
        mid = raw_mid if raw_mid else memory.get("_last_mid", 0.0)
        if raw_mid:
            memory["_last_mid"] = raw_mid

        self._smooth_mid(mid, memory)

        # ── Z-score: compute and share for VEV option strategies ──────────────
        z = self._compute_zscore(mid, memory)
        shared = memory.get("_shared", {})
        shared["velvet_zscore"] = z   # VEV strategies read this on NEXT tick

        # ── Delta hedge from VEV options ──────────────────────────────────────
        vev_delta     = float(shared.get("vev_total_delta", 0.0)) if bool(self.params.get("use_delta_hedge", True)) else 0.0
        effective_pos = position + int(round(vev_delta))

        limit    = self.position_limit()
        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        bid_price, ask_price = self._compute_quote_prices(book)
        bid_size, ask_size   = self._compute_sizes(effective_pos, limit)
        orders = self._passive_quotes(bid_price, ask_price, bid_size, ask_size, buy_cap, sell_cap, position, limit)

        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=bid_price, ask_price=ask_price,
            extras={
                "position":   position,
                "zscore":     round(z, 3) if z is not None else None,
                "vev_delta":  round(vev_delta, 1),
                "mid_smooth": round(memory.get("mid_smoothed", mid), 2),
            },
        )
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("mid_smoothed")) is not None:
            out["MidSmooth"] = m
        z = memory.get("_zs_buf")
        # surface current z if already computed
        buf = memory.get("_zs_buf", [])
        if len(buf) > 4:
            n = len(buf); mean = sum(buf)/n
            var = sum((x-mean)**2 for x in buf)/max(n-1,1); std = var**0.5
            if std > 1e-9:
                out["Z_velvet"] = (buf[-1] - mean) / std
        return out


# ══════════════════════════════════════════════════════════════════════════════
#  CLASS 2 — VEV option MM v3 (signal-gated sizing)
# ══════════════════════════════════════════════════════════════════════════════

class VEVOptionMMV3(BaseStrategy):
    """VEV option MM with VELVETFRUIT z-score-gated sizing and ask adaptation."""

    # ── Z-score (self-contained, from VELVETFRUIT spot) ──────────────────────

    def _compute_zscore(self, state: TradingState, memory: Dict[str, Any]) -> Optional[float]:
        """Rolling z-score of VELVETFRUIT spot, computed independently per VEV strategy.

        Each VEV strategy maintains its own 500-price buffer in its own memory.
        No dependency on VelvetMMV3 or shared dict — robust against tick ordering.
        """
        S = self._get_spot(state)
        if S is None:
            return None
        window = int(self.params.get("zscore_window", 500))
        buf: List[float] = memory.setdefault("_velvet_buf", [])
        buf.append(S)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            return None
        n    = len(buf)
        mean = sum(buf) / n
        var  = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std  = var ** 0.5
        if std < 1e-9:
            return None
        return (S - mean) / std

    def _get_zscore(self, state: TradingState, memory: Dict[str, Any]) -> Optional[float]:
        """Alias: compute z-score and store in memory for logging."""
        z = self._compute_zscore(state, memory)
        memory["_zscore"] = z
        return z

    def _signal_state(self, z: Optional[float]) -> str:
        """Map z-score to 'cheap' | 'neutral' | 'expensive'."""
        if z is None:
            return "neutral"
        threshold = float(self.params.get("zscore_threshold", 1.0))
        if z < -threshold:
            return "cheap"
        if z > threshold:
            return "expensive"
        return "neutral"

    def _quote_bid(self, book: BookSnapshot, signal: str, mode: str) -> Optional[int]:
        """Bid price based on signal + execution mode.

        Execution approaches:
          "none" / "ask_adapt": always penny-improve with crossing prevention.
          "bid_only" / "both":
            cheap     → intentional cross: bid at best_ask (taker, fills immediately)
            neutral   → penny-improve (with crossing prevention)
            expensive → skip: return None (no bid → zero passive fills this tick)

        Crossing prevention applies to ALL non-intentional cases:
          On 1-tick spreads (bid=X, ask=X+1), bid+1 would = ask and become an
          unintentional taker. We fall back to bid=best_bid (join queue, passive).
          Only the explicit "cheap" signal is allowed to cross the spread.
        """
        if book.best_bid is None:
            return None

        if mode in ("bid_only", "both"):
            if signal == "cheap" and bool(self.params.get("allow_taker", True)):
                # Intentional taker: cross the spread (active buy, fills immediately)
                return book.best_ask if book.best_ask is not None else book.best_bid + 1
            if signal == "expensive":
                return None   # skip bid: don't accumulate when expensive

        # Default: penny-improve. Optional crossing prevention (per-strike param).
        # For strikes with persistently 1-tick spreads (VEV_5400), set
        # prevent_crossing=True to avoid unintentional taker fills that hurt PnL.
        # For wider-spread strikes (VEV_5200/5300), leave False to allow the
        # occasional crossing when the spread narrows — on average profitable.
        bid = book.best_bid + 1
        if bool(self.params.get("prevent_crossing", False)):
            if book.best_ask is not None and bid >= book.best_ask:
                bid = book.best_ask - 1   # join bid (passive)
        return bid

    def _quote_ask(self, book: BookSnapshot, signal: str, mode: str) -> Optional[int]:
        """Ask price based on signal + execution mode.

        "ask_adapt" / "both":
          expensive → penny-improve ask (best_ask-1): willing to sell at elevated price
          neutral   → wide ask (best_ask + ask_offset_neutral): rarely fills
          cheap     → very wide ask (hold longs, don't sell into dip)
        "none" / "bid_only": always wide ask
        """
        if book.best_ask is None:
            return None

        neutral_offset = int(self.params.get("ask_offset_neutral", 10))

        if mode in ("ask_adapt", "both"):
            if signal == "expensive":
                return book.best_ask - 1   # penny-improve: sell some at peak
            if signal == "cheap":
                return book.best_ask + neutral_offset + 5   # extra wide: don't sell dip
        return book.best_ask - 1 + neutral_offset   # default: wide, rarely fills

    # ── Time to expiry ────────────────────────────────────────────────────────

    def _resolve_tte(self, state: TradingState) -> float:
        tte0 = resolve_initial_tte_days(
            state.traderData,
            float(self.params.get("tte_days_initial", 5.0)),
            self.params.get("historical_tte_by_day"),
        )
        ts_per_day = timestamp_units_per_day_from_params(self.params)
        return max(0.01, time_to_expiry_days(int(state.timestamp), tte0, timestamp_units_per_day=ts_per_day))

    # ── Spot from order depths ────────────────────────────────────────────────

    def _get_spot(self, state: TradingState) -> Optional[float]:
        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
        od = state.order_depths.get(underlying)
        if od is None:
            return None
        bids = od.buy_orders
        asks = od.sell_orders
        bb = max(bids.keys()) if bids else None
        ba = min(asks.keys()) if asks else None
        if bb is not None and ba is not None:
            return (bb + ba) / 2.0
        return float(bb or ba or 0) or None

    # ── Quoting ───────────────────────────────────────────────────────────────

    def _post_orders(
        self,
        bid_px: Optional[int],
        ask_px: Optional[int],
        buy_cap: int,
        sell_cap: int,
    ) -> List[Order]:
        size_bid = int(self.params.get("maker_size_bid", 20))
        size_ask = int(self.params.get("maker_size_ask", 5))
        orders: List[Order] = []
        if bid_px is not None and bid_px > 0 and buy_cap > 0:
            orders.append(Order(self.product, bid_px, min(size_bid, buy_cap)))
        if ask_px is not None and ask_px > 0 and sell_cap > 0 and size_ask > 0:
            orders.append(Order(self.product, ask_px, -min(size_ask, sell_cap)))
        return orders

    def _publish_delta(self, memory: Dict[str, Any], position: int, S: float, K: float, T: float) -> None:
        sigma = float(self.params.get("delta_sigma", 0.022))
        delta = call_delta(S, K, T, sigma)
        shared = memory.get("_shared", {})
        shared["vev_total_delta"] = shared.get("vev_total_delta", 0.0) + position * delta

    # ── Main tick ─────────────────────────────────────────────────────────────

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

        mid = 0.5 * (book.best_bid + book.best_ask)
        if mid < float(self.params.get("min_quote_price", 2.0)):
            return [], 0

        T = self._resolve_tte(state)
        K = float(self.params["strike"])
        S = self._get_spot(state)
        if S is not None:
            self._publish_delta(memory, position, S, K, T)

        # ── Z-score signal → bid/ask prices ──────────────────────────────────
        z      = self._get_zscore(state, memory)
        mode   = str(self.params.get("zscore_exec_mode", "bid_only"))
        signal = self._signal_state(z)

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        bid_px = self._quote_bid(book, signal, mode)
        ask_px = self._quote_ask(book, signal, mode)

        # Safety: prevent crossing
        if bid_px is not None and ask_px is not None and ask_px <= bid_px:
            ask_px = bid_px + 1

        orders = self._post_orders(bid_px, ask_px, buy_cap, sell_cap)
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        z = memory.get("_zscore")
        return {"z_velvet": round(z, 3)} if z is not None else {}
