"""HYDROGEL_PACK mean-reversion — mv_v4: best v3 + optional v200 features.

Core: AR model + Mark 14 scale mode (best v3 config).
Additional features from v200, each independently toggled via params:

  1. trend_guard_threshold > 0
       Block entries when a fast EWMA of recent mid-price changes is
       trending against the intended direction.
       EWMA(Δmid, alpha=trend_alpha): negative → price falling.
       Block BUY  when trend_ema < -trend_guard_threshold.
       Block SELL when trend_ema >  trend_guard_threshold.

  2. stop_loss_mult > 0
       Force exit when the smoothed deviation has moved
       stop_loss_mult × entry_threshold FURTHER against our position.
       (i.e. entered long at dev=-20, stop at dev=-20-mult×20)

  3. toxic_flow_threshold > 0
       Skip entry when recent market trade flow is strongly one-sided
       against our intended direction.
       flow_score = net_signed_vol / total_vol over toxic_window ticks.
       Block BUY  when flow_score < -toxic_flow_threshold.
       Block SELL when flow_score >  toxic_flow_threshold.

  4. dev_size_scale > 0
       Scale entry size by deviation magnitude above the threshold.
       size = min(max_position, base_size × (1 + dev_size_scale
              × (|dev| − entry_threshold) / entry_threshold))
       Larger deviations → more confident signal → bigger position.

  5. vol_thresh_scale > 0
       Scale entry threshold up with realized volatility.
       effective_threshold = entry_threshold × (1 + vol_thresh_scale
                             × sigma / vol_ref)
       High-vol → harder to enter → fewer but higher-quality trades.

All features default OFF (threshold=0 / scale=0).
Self-contained (BaseStrategy only). State machine: flat→entering→holding→exiting.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydroMVV4(BaseStrategy):

    # ── AR model (same as v2/v3) ──────────────────────────────────────────

    def _update_ar(
        self, raw_mid: float, memory: Dict[str, Any],
    ) -> Tuple[float, float, float]:
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
        dev_hl    = float(self.params.get("dev_smooth_half_life", 5))
        dev_alpha = 1.0 - 0.5 ** (1.0 / dev_hl)
        dev_s     = float(memory.get("_dev_smooth", raw_dev))
        dev_s     = dev_alpha * raw_dev + (1.0 - dev_alpha) * dev_s
        memory["_dev_smooth"] = dev_s
        memory["_dev_raw"]    = raw_dev
        return mid_s, fair_value, dev_s

    # ── Mark 14 tracking ──────────────────────────────────────────────────

    def _update_m14(
        self, state: TradingState, memory: Dict[str, Any],
    ) -> int:
        trader = str(self.params.get("informed_trader_name", "Mark 14"))
        net = 0
        for trade in state.market_trades.get(self.product, []):
            if trade.buyer == trader:   net += trade.quantity
            elif trade.seller == trader: net -= trade.quantity
        this_tick = 1 if net > 0 else (-1 if net < 0 else 0)
        memory["_m14_this"] = this_tick
        lookback = int(self.params.get("m14_lookback_ticks", 20))
        hist: List[int] = memory.setdefault("_m14_hist", [])
        hist.append(this_tick)
        if len(hist) > lookback:
            hist[:] = hist[-lookback:]
        return this_tick

    def _m14_recent(self, memory: Dict[str, Any]) -> int:
        hist = memory.get("_m14_hist", [])
        net  = sum(hist)
        return 1 if net > 0 else (-1 if net < 0 else 0)

    # ── Feature 1: Trend guard ────────────────────────────────────────────

    def _update_trend(self, raw_mid: float, memory: Dict[str, Any]) -> float:
        alpha    = float(self.params.get("trend_alpha", 0.3))
        prev_mid = memory.get("_trend_prev_mid", raw_mid)
        delta    = raw_mid - float(prev_mid)
        trend    = float(memory.get("_trend_ema", 0.0))
        trend    = alpha * delta + (1.0 - alpha) * trend
        memory["_trend_ema"]      = trend
        memory["_trend_prev_mid"] = raw_mid
        return trend

    def _trend_blocks(self, direction: int, memory: Dict[str, Any]) -> bool:
        thresh = float(self.params.get("trend_guard_threshold", 0.0))
        if thresh <= 0:
            return False
        trend = float(memory.get("_trend_ema", 0.0))
        if direction > 0 and trend < -thresh:   return True   # BUY blocked: falling
        if direction < 0 and trend >  thresh:   return True   # SELL blocked: rising
        return False

    # ── Feature 3: Toxic flow gate ────────────────────────────────────────

    def _update_flow(self, state: TradingState, memory: Dict[str, Any]) -> float:
        thresh = float(self.params.get("toxic_flow_threshold", 0.0))
        if thresh <= 0:
            return 0.0
        window   = int(self.params.get("toxic_window", 8))
        prev_bid = memory.get("_prev_best_bid")
        prev_ask = memory.get("_prev_best_ask")
        hist: List[float] = memory.setdefault("_flow_hist", [])
        if prev_bid is not None and prev_ask is not None:
            for trade in state.market_trades.get(self.product, []):
                if trade.price >= prev_ask:   hist.append(trade.quantity)
                elif trade.price <= prev_bid:  hist.append(-trade.quantity)
        if len(hist) > window:
            hist[:] = hist[-window:]
        if not hist:
            return 0.0
        total  = sum(abs(x) for x in hist)
        score  = sum(hist) / total if total > 0 else 0.0
        memory["_flow_score"] = score
        return score

    def _flow_blocks(self, direction: int, memory: Dict[str, Any]) -> bool:
        thresh = float(self.params.get("toxic_flow_threshold", 0.0))
        if thresh <= 0:
            return False
        score = float(memory.get("_flow_score", 0.0))
        if direction > 0 and score < -thresh:  return True   # buying into selling flow
        if direction < 0 and score >  thresh:  return True   # selling into buying flow
        return False

    # ── Feature 4: Deviation size scaling ────────────────────────────────

    def _scaled_size(self, dev: float, entry_thresh: float) -> int:
        base      = int(self.params.get("entry_size", 20))
        scale_f   = float(self.params.get("dev_size_scale", 0.0))
        if scale_f <= 0:
            return base
        max_mult  = float(self.params.get("dev_size_max_mult", 3.0))
        excess    = max(0.0, abs(dev) - entry_thresh)
        mult      = min(max_mult, 1.0 + scale_f * excess / entry_thresh)
        return int(base * mult)

    # ── Feature 5: Vol-scaled threshold ──────────────────────────────────

    def _effective_threshold(self, memory: Dict[str, Any]) -> float:
        base = float(self.params.get("entry_threshold", 20.0))
        scale_v = float(self.params.get("vol_thresh_scale", 0.0))
        if scale_v <= 0:
            return base
        sigma   = float(memory.get("sigma_smoothed", 0.0))
        vol_ref = float(self.params.get("vol_ref", 3.0))
        return base * (1.0 + scale_v * sigma / max(vol_ref, 1e-6))

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
        m14_this   = self._update_m14(state, memory)
        m14_recent = self._m14_recent(memory)
        trend      = self._update_trend(float(mid), memory)
        flow       = self._update_flow(state, memory)
        sigma      = self._update_volatility(float(mid), memory)

        # Store book prices for flow detector
        if book.best_bid is not None: memory["_prev_best_bid"] = book.best_bid
        if book.best_ask is not None: memory["_prev_best_ask"] = book.best_ask

        entry_thresh = self._effective_threshold(memory)
        exit_thresh  = float(self.params.get("exit_threshold", 2.0))
        base_size    = int(self.params.get("entry_size", 20))
        stop_mult    = float(self.params.get("stop_loss_mult", 0.0))

        mv_state = memory.get("_mv_state", "flat")
        intent   = memory.get("_intent",   0)
        orders: List[Order] = []

        # ── Stop loss (feature 2) ─────────────────────────────────────────
        if mv_state in ("entering", "holding") and stop_mult > 0:
            entry_dev = float(memory.get("_entry_dev", 0.0))
            stop_hit  = (
                (intent > 0 and dev > entry_dev + stop_mult * entry_thresh) or
                (intent < 0 and dev < entry_dev - stop_mult * entry_thresh)
            )
            if stop_hit:
                mv_state = "exiting"
                memory["_mv_state"] = "exiting"
                memory["_stop_hit"] = 1

        # ── Normal exit ───────────────────────────────────────────────────
        if mv_state in ("entering", "holding"):
            if (intent > 0 and dev > -exit_thresh) or (intent < 0 and dev < exit_thresh):
                mv_state = "exiting"
                memory["_mv_state"] = "exiting"

        # ── State machine ─────────────────────────────────────────────────
        if mv_state == "flat":
            direction = 0
            if dev < -entry_thresh:   direction = 1
            elif dev > entry_thresh:  direction = -1

            if direction != 0:
                # Mark 14: agree → scale up, oppose → skip
                agree_factor = float(self.params.get("m14_agree_factor", 3.0))
                if m14_recent != 0 and m14_recent != direction:
                    direction = 0  # M14 opposes → cancel entry

            if direction != 0 and not self._trend_blocks(direction, memory) \
                    and not self._flow_blocks(direction, memory):
                # Size: base × dev_scale × m14_scale
                size = self._scaled_size(dev, entry_thresh)  # feature 4 (dev scaling)
                if m14_recent == direction:
                    size = int(size * agree_factor)           # M14 agrees → amplify

                if direction > 0:
                    orders = self._taker_buy(position, book, size)
                    if orders:
                        memory["_intent"]       = 1
                        memory["_entry_target"] = size
                        memory["_entry_dev"]    = dev
                        memory["_mv_state"]     = "entering"
                else:
                    orders = self._taker_sell(position, book, size)
                    if orders:
                        memory["_intent"]       = -1
                        memory["_entry_target"] = size
                        memory["_entry_dev"]    = dev
                        memory["_mv_state"]     = "entering"

        elif mv_state == "entering":
            target_abs = memory.get("_entry_target", int(self.params.get("entry_size", 20)))
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
                memory.pop("_stop_hit", None)

        # ── Logging ───────────────────────────────────────────────────────
        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":   position,
                "deviation":  round(dev, 3),
                "trend_ema":  round(trend, 4),
                "flow_score": round(float(memory.get("_flow_score", 0)), 4),
                "m14_recent": m14_recent,
                "mv_state":   mv_state,
                "entry_thresh": round(entry_thresh, 2),
            },
        )
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value"))  is not None: out["FairValue"]  = float(v)
        if (v := memory.get("_dev_smooth"))  is not None: out["DevSmooth"]  = float(v)
        if (v := memory.get("_trend_ema"))   is not None: out["TrendEMA"]   = float(v)
        if (v := memory.get("_flow_score"))  is not None: out["FlowScore"]  = float(v)
        if (v := memory.get("_m14_this"))    is not None: out["M14This"]    = float(v)
        st = memory.get("_mv_state", "flat")
        out["MvStateN"] = {"flat": 0, "entering": 1, "holding": 2, "exiting": 3}.get(st, -1)
        return out
