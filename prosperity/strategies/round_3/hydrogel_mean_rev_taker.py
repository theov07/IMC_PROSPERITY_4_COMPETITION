"""HydrogelMeanRevTaker — mean-rev taker on HYDROGEL using rolling z-score.

Based on ACF/PACF analysis:
  Tick returns AR(1) φ = -0.13 (pure bid-ask bounce, no edge).
  Aggregated returns show real mean-reversion:
    100-tick:  ACF(1) = -0.155
    500-tick:  ACF(1) = -0.199
    1000-tick: ACF(1) = -0.215

At window=500 ticks (~5% of session), 2σ = ~57 ticks, expected reversion
= ~11 ticks. Crossing spread costs ~7 ticks → ~4 ticks net edge per trade.

Signal:
  rolling_mean = EWMA of mid (alpha = 2/(window+1))
  rolling_std  = EWMA of squared residuals
  z_score      = (mid - rolling_mean) / rolling_std

Rules (taker + passive overlay):
  |z| > entry_z  → SELL (z > 0) / BUY (z < 0) at market touch, size scaled by z
  |z| < exit_z   → flatten position passively
  |z| between    → passive MM only (naive_tight_mm behavior)

Params:
  window               : EWMA window for mean/std (default 500)
  entry_z              : z-score magnitude to fire taker (default 2.0)
  exit_z               : z-score magnitude to start flattening (default 0.5)
  taker_size_base      : base qty per taker entry (default 20)
  taker_size_per_z     : additional qty per |z|-1 (default 10)
  max_taker_position   : cap on directional position from takers (default 150)
  passive_l1_size      : MM size at best±1 (default 30)
  inventory_aversion   : shrink size on worsening side (default 0.5)
  enable_passive_mm    : keep passive MM always on (default True)
  min_samples          : ticks before signal valid (default 100)
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelMeanRevTakerStrategy(BaseStrategy):
    """Mean-rev taker + passive MM overlay, tuned for wide-spread HYDROGEL_PACK."""

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

        p = self._read_params()
        mid = 0.5 * (book.best_bid + book.best_ask)

        # EWMA mean + variance (incremental)
        alpha = 2.0 / (p["window"] + 1)
        mean_prev = memory.get("_ewma_mean", mid)
        var_prev = memory.get("_ewma_var", 0.0)
        tick_count = memory.get("_tick_count", 0) + 1
        delta = mid - mean_prev
        new_mean = mean_prev + alpha * delta
        # Variance: Welford-style EWMA
        new_var = (1 - alpha) * (var_prev + alpha * delta * delta)
        memory["_ewma_mean"] = new_mean
        memory["_ewma_var"] = new_var
        memory["_tick_count"] = tick_count

        std = (new_var ** 0.5) if new_var > 0 else 0.0
        z = (mid - new_mean) / std if std > 1e-6 else 0.0
        memory["_z"] = z
        memory["_ewma_std"] = std

        limit = self.position_limit()
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        orders: List[Order] = []
        mode = "warmup"

        # Only use signal after warmup
        if tick_count >= p["min_samples"] and std > 1e-6:
            abs_z = abs(z)

            # ── Entry / taker mode ──
            # Only fires if taker_size_base > 0 AND |z| >= entry_z.
            taker_position = memory.get("_taker_position", 0)
            if p["taker_size_base"] > 0 and abs_z >= p["entry_z"]:
                mode = "taker_entry"
                target_qty = int(p["taker_size_base"] + p["taker_size_per_z"] * max(0, abs_z - 1.0))
                if z > 0 and sell_cap > 0 and taker_position > -p["max_taker_position"]:
                    bid_px = book.best_bid
                    max_sell = min(sell_cap, p["max_taker_position"] + taker_position, target_qty)
                    avail = order_depth.buy_orders.get(bid_px, 0)
                    qty = min(max_sell, avail)
                    if qty > 0:
                        orders.append(Order(self.product, bid_px, -qty))
                        sell_cap -= qty
                        memory["_taker_position"] = taker_position - qty
                elif z < 0 and buy_cap > 0 and taker_position < p["max_taker_position"]:
                    ask_px = book.best_ask
                    max_buy = min(buy_cap, p["max_taker_position"] - taker_position, target_qty)
                    avail = -order_depth.sell_orders.get(ask_px, 0)
                    qty = min(max_buy, avail)
                    if qty > 0:
                        orders.append(Order(self.product, ask_px, qty))
                        buy_cap -= qty
                        memory["_taker_position"] = taker_position + qty

            # ── Exit mode: flatten ONLY the taker_position (not passive fills) ──
            # If z is back near 0 and we have an active taker position, unwind it.
            elif p["taker_size_base"] > 0 and abs_z <= p["exit_z"] and taker_position != 0:
                mode = "exit"
                if taker_position > 0 and sell_cap > 0:
                    bid_px = book.best_bid
                    avail = order_depth.buy_orders.get(bid_px, 0)
                    qty = min(sell_cap, taker_position, avail, p["exit_chunk_size"])
                    if qty > 0:
                        orders.append(Order(self.product, bid_px, -qty))
                        sell_cap -= qty
                        memory["_taker_position"] = taker_position - qty
                elif taker_position < 0 and buy_cap > 0:
                    ask_px = book.best_ask
                    avail = -order_depth.sell_orders.get(ask_px, 0)
                    qty = min(buy_cap, -taker_position, avail, p["exit_chunk_size"])
                    if qty > 0:
                        orders.append(Order(self.product, ask_px, qty))
                        buy_cap -= qty
                        memory["_taker_position"] = taker_position + qty

            else:
                mode = "neutral"

        # ── Passive MM overlay (always on by default) ──
        # NEW: z-score skew — if mid is above rolling mean (z>0, "rich"), shrink
        # bid and grow ask (fade upward excursion passively, no spread cost).
        if p["enable_passive_mm"] and buy_cap > 0 and sell_cap > 0:
            # Inventory aversion
            inv_bid_mult = 1.0 - max(0.0, p["inventory_aversion"] * position / max(1, limit))
            inv_ask_mult = 1.0 - max(0.0, p["inventory_aversion"] * (-position) / max(1, limit))
            # z-score passive skew (|z| large → asymmetric sizes)
            z_clamp = max(-3.0, min(3.0, z))
            z_skew_gain = p["z_passive_skew_gain"]
            # Long delta in market (z>0 = we think it will fall):
            #   grow ask_size (sell more when market is high), shrink bid
            z_bid_mult = max(0.0, 1.0 - z_skew_gain * max(0.0, z_clamp))
            z_ask_mult = max(0.0, 1.0 + z_skew_gain * max(0.0, z_clamp))
            # z<0 (market low, should rise): grow bid, shrink ask
            z_bid_mult *= max(0.0, 1.0 + z_skew_gain * max(0.0, -z_clamp))
            z_ask_mult *= max(0.0, 1.0 - z_skew_gain * max(0.0, -z_clamp))

            bid_l1 = book.best_bid + 1
            ask_l1 = book.best_ask - 1
            if bid_l1 < book.best_ask:
                q = int(round(p["passive_l1_size"] * inv_bid_mult * z_bid_mult))
                q = min(q, buy_cap)
                if q > 0:
                    orders.append(Order(self.product, bid_l1, q))
            if ask_l1 > book.best_bid:
                q = int(round(p["passive_l1_size"] * inv_ask_mult * z_ask_mult))
                q = min(q, sell_cap)
                if q > 0:
                    orders.append(Order(self.product, ask_l1, -q))

        memory["_mode"] = mode
        return orders, 0

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "window": int(params.get("window", 500)),
            "entry_z": float(params.get("entry_z", 2.0)),
            "exit_z": float(params.get("exit_z", 0.5)),
            "taker_size_base": int(params.get("taker_size_base", 20)),
            "taker_size_per_z": int(params.get("taker_size_per_z", 10)),
            "max_taker_position": int(params.get("max_taker_position", 150)),
            "exit_chunk_size": int(params.get("exit_chunk_size", 30)),
            "passive_l1_size": int(params.get("passive_l1_size", 30)),
            "inventory_aversion": float(params.get("inventory_aversion", 0.5)),
            "enable_passive_mm": bool(params.get("enable_passive_mm", True)),
            "min_samples": int(params.get("min_samples", 100)),
            "z_passive_skew_gain": float(params.get("z_passive_skew_gain", 0.25)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("_ewma_mean")) is not None:
            out["ewma_mean"] = m
        if (s := memory.get("_ewma_std")) is not None:
            out["ewma_std"] = s
        if (z := memory.get("_z")) is not None:
            out["z"] = z
        if (mo := memory.get("_mode")) is not None:
            out["mode_code"] = {"warmup": 0, "neutral": 1, "taker_entry": 2, "exit": 3}.get(mo, -1)
        return out
