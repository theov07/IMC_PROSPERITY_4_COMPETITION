"""HydrogelOracleInspired — generalizable rules distilled from Codex's day-2 oracle.

Origin:
  Reverse-engineered 176 HYDROGEL trades from r3_oracle_day2_l1 (day 2 overfit
  that scored 154k live). Pattern analysis in FINDINGS.md.

Oracle BUY pattern (96 trades, 100% aggressive at best_ask):
  - z-score (window=500) = -1.94 avg, q25=-2.25, q75=-1.60
  - trend_100 = -37 ticks avg (market just fell)
  - trend_500 = -75 ticks avg (longer downtrend)
  Forward: 83% profit in 1000 ticks, 84% by EOD, median +33 ticks EOD.

Oracle SELL pattern (80 trades, 100% aggressive at best_bid):
  - z-score = +0.68 avg (q25=+0.01, q75=+1.61)
  - trend_100 = +19 ticks avg (recent uptick / local rebound)
  - Less extreme trigger than BUY, works because underlying market is
    slightly downward-biased so selling a rebound is safe.

Forward-computable rules (distilled):
  BUY  = z < buy_z_threshold   AND trend_100 < buy_trend_threshold
  SELL = z > sell_z_threshold  AND trend_100 > sell_trend_threshold

Default thresholds (conservative, capture cluster center):
  buy_z_threshold       = -1.6   (oracle q75)
  buy_trend_threshold   = -20    (oracle avg ~-37, leave margin)
  sell_z_threshold      = +0.5   (oracle avg +0.68, slightly tighter)
  sell_trend_threshold  = +10    (oracle avg +19)

Net edge: median forward move 33 ticks - 15-tick spread = ~18 ticks per trade.

Design:
  - Take aggressively at best_ask/best_bid (like the oracle) to get clean edge.
  - Cap position to max_position to avoid unbounded exposure.
  - Passive MM overlay (optional) for extra fills between signals.
  - Unwind mode when z crosses back to 0 AND position != 0.

Params:
  window                  : EWMA window for z-score (default 500, per ACF/PACF)
  trend_lookback          : ticks to compute trend_N (default 100)
  buy_z_threshold         : fire BUY when z below this (default -1.6)
  buy_trend_threshold     : fire BUY when trend below this (default -20)
  sell_z_threshold        : fire SELL when z above this (default +0.5)
  sell_trend_threshold    : fire SELL when trend above this (default +10)
  taker_size              : qty per taker signal (default 15)
  max_position            : cap on directional position (default 100)
  unwind_z_threshold      : exit signal when |z| below this (default 0.3)
  unwind_chunk_size       : qty per unwind tick (default 10)
  passive_l1_size         : size of passive MM overlay at best±1 (default 15)
  enable_passive_mm       : keep passive MM alive (default True)
  min_samples             : warmup ticks before signal fires (default 200)
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydrogelOracleInspiredStrategy(BaseStrategy):
    """Mean-rev taker with z-score + trend_100 gate, from oracle reverse-engineering."""

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

        # ── EWMA mean + variance (incremental) ──
        alpha = 2.0 / (p["window"] + 1)
        mean_prev = memory.get("_ewma_mean", mid)
        var_prev = memory.get("_ewma_var", 0.0)
        tick_count = memory.get("_tick_count", 0) + 1
        delta = mid - mean_prev
        new_mean = mean_prev + alpha * delta
        new_var = (1 - alpha) * (var_prev + alpha * delta * delta)
        memory["_ewma_mean"] = new_mean
        memory["_ewma_var"] = new_var
        memory["_tick_count"] = tick_count
        std = (new_var ** 0.5) if new_var > 0 else 0.0
        z = (mid - new_mean) / std if std > 1e-6 else 0.0

        # ── Trend = mid - mid[trend_lookback ago] (ring buffer) ──
        buf: List[float] = memory.setdefault("_mid_buf", [])
        buf.append(mid)
        lookback = p["trend_lookback"]
        if len(buf) > lookback + 1:
            del buf[:-lookback - 1]
        trend = (mid - buf[0]) if len(buf) >= lookback + 1 else 0.0

        memory["_z"] = z
        memory["_trend"] = trend
        memory["_ewma_std"] = std

        # Warmup guard
        if tick_count < p["min_samples"] or std < 1e-6:
            memory["_mode"] = "warmup"
            return self._post_passive_only(book, position, p), 0

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []
        mode = "neutral"
        ts_now = int(state.timestamp)
        last_signal_ts = memory.get("_last_signal_ts", -10 ** 9)
        cooldown_ts = int(p["cooldown_ticks"]) * 100  # ticks × ts_increment
        cooling_down = (ts_now - last_signal_ts) < cooldown_ts

        # ── BUY signal: z below threshold AND trend is sharply down ──
        if not cooling_down and z < p["buy_z_threshold"] and trend < p["buy_trend_threshold"] \
                and buy_cap > 0 and position < p["max_position"]:
            mode = "buy_signal"
            ask_px = book.best_ask
            avail = -order_depth.sell_orders.get(ask_px, 0)
            headroom = p["max_position"] - position
            qty = min(p["taker_size"], buy_cap, headroom, avail)
            if qty > 0:
                orders.append(Order(self.product, ask_px, qty))
                buy_cap -= qty
                memory["_last_signal_ts"] = ts_now

        # ── SELL signal: z above threshold AND trend up ──
        elif not cooling_down and z > p["sell_z_threshold"] and trend > p["sell_trend_threshold"] \
                and sell_cap > 0 and position > -p["max_position"]:
            mode = "sell_signal"
            bid_px = book.best_bid
            avail = order_depth.buy_orders.get(bid_px, 0)
            headroom = p["max_position"] + position
            qty = min(p["taker_size"], sell_cap, headroom, avail)
            if qty > 0:
                orders.append(Order(self.product, bid_px, -qty))
                sell_cap -= qty
                memory["_last_signal_ts"] = ts_now

        # ── Unwind mode: |z| near zero, reduce position ──
        elif abs(z) < p["unwind_z_threshold"] and position != 0:
            mode = "unwind"
            if position > 0 and sell_cap > 0:
                bid_px = book.best_bid
                avail = order_depth.buy_orders.get(bid_px, 0)
                qty = min(p["unwind_chunk_size"], sell_cap, position, avail)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, -qty))
                    sell_cap -= qty
            elif position < 0 and buy_cap > 0:
                ask_px = book.best_ask
                avail = -order_depth.sell_orders.get(ask_px, 0)
                qty = min(p["unwind_chunk_size"], buy_cap, -position, avail)
                if qty > 0:
                    orders.append(Order(self.product, ask_px, qty))
                    buy_cap -= qty

        memory["_mode"] = mode

        # ── Passive MM overlay (always on, captures passive fills between signals) ──
        if p["enable_passive_mm"]:
            orders.extend(self._post_passive(book, position, buy_cap, sell_cap, p))

        return orders, 0

    def _post_passive(self, book, position, buy_cap, sell_cap, p):
        orders = []
        bid_l1 = book.best_bid + 1
        ask_l1 = book.best_ask - 1
        if bid_l1 < book.best_ask and buy_cap > 0:
            q = min(p["passive_l1_size"], buy_cap)
            if q > 0:
                orders.append(Order(self.product, bid_l1, q))
        if ask_l1 > book.best_bid and sell_cap > 0:
            q = min(p["passive_l1_size"], sell_cap)
            if q > 0:
                orders.append(Order(self.product, ask_l1, -q))
        return orders

    def _post_passive_only(self, book, position, p):
        """Warmup mode: just passive MM."""
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        return self._post_passive(book, position, buy_cap, sell_cap, p) if p["enable_passive_mm"] else []

    def _read_params(self) -> Dict[str, Any]:
        params = self.params
        return {
            "window": int(params.get("window", 500)),
            "trend_lookback": int(params.get("trend_lookback", 100)),
            "buy_z_threshold": float(params.get("buy_z_threshold", -1.6)),
            "buy_trend_threshold": float(params.get("buy_trend_threshold", -20.0)),
            "sell_z_threshold": float(params.get("sell_z_threshold", 0.5)),
            "sell_trend_threshold": float(params.get("sell_trend_threshold", 10.0)),
            "taker_size": int(params.get("taker_size", 15)),
            "max_position": int(params.get("max_position", 100)),
            "unwind_z_threshold": float(params.get("unwind_z_threshold", 0.3)),
            "unwind_chunk_size": int(params.get("unwind_chunk_size", 10)),
            "passive_l1_size": int(params.get("passive_l1_size", 15)),
            "enable_passive_mm": bool(params.get("enable_passive_mm", True)),
            "min_samples": int(params.get("min_samples", 200)),
            "cooldown_ticks": int(params.get("cooldown_ticks", 50)),
        }

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for k in ("_ewma_mean","_ewma_std","_z","_trend"):
            if (v := memory.get(k)) is not None:
                out[k.lstrip("_")] = v
        if (m := memory.get("_mode")) is not None:
            out["mode_code"] = {"warmup":0,"neutral":1,"buy_signal":2,"sell_signal":3,"unwind":4}.get(m, -1)
        return out
