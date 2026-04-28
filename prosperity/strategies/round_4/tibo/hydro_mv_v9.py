"""HYDROGEL_PACK — mv_v9: v6b + hard cap on ALL orders + M14 cumulative gate

Starting fresh from v6b (178,785 PnL). Fixing two confirmed live failures:

LIVE FAILURE 1 — Hard cap only blocked AR taker, not MM asks (v8 bug):
  In v8, sell_ok=0 blocked the AR taker. But our passive MM still posted asks.
  Mark 14 (a directional buyer) lifted our MM asks continuously, pushing position
  from -77 to -105. The fix: when |position| >= sell_cap, zero ALL selling —
  both taker sells AND MM ask — not just the AR taker.

LIVE FAILURE 2 — Mark 14 signal ignored:
  In the v8 session, Mark 14 was a net buyer of +75 units. Mark 14 bought
  exclusively FROM US (our MM asks), front-running the uptrend. If we had
  tracked M14's CUMULATIVE net purchases and gated selling when M14 was
  consistently buying, we would have stopped selling much earlier.

FIX 1 — Hard cap on all sells AND MM asks:
  sell_allowed = position > -sell_cap_units (default: -140, 70% of 200).
  When sell_allowed=False: taker_sell=0 AND mm_ask_size=0. Position physically
  cannot go further short regardless of who is lifting our asks.

FIX 2 — Cumulative M14 gate (day-scoped):
  Track M14 net = cumulative(M14 buys - M14 sells) since start of day.
  - m14_cum resets to 0 at day boundary (timestamp == 0 or wraps).
  - When m14_cum > m14_bullish_threshold (default 40): M14 is accumulating a
    long position. This is a bullish signal → suppress ALL selling.
  - When m14_cum < -m14_bearish_threshold: M14 is selling → our AR short is
    confirmed → allow taker sells even if they'd normally be smaller.
  - Neutral zone: normal AR logic.

FIX 3 — Inventory-skewed MM bid for recovery:
  When short, raise passive bid by floor(inv_skew_ticks × |pos/limit|) extra
  ticks above best_bid+1. Helps recover inventory faster during pullbacks.

Architecture: identical to v6b otherwise.
  - inv_protected anchor (freezes when |pos| >= anchor_pos_threshold × limit)
  - AR fair value: anchor_ema - ar_gain × ar_momentum
  - Passive MM: bestquote with inventory-adaptive sizing
  - AR taker: fires when |dev| > ar_taker_edge

Expected backtest: ~140k (v6b base 178k × 70% cap) + M14 gate occasional bonus
Expected live: early M14 gate fire + hard cap → never past -100u in most sessions
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydroMVV9(BaseStrategy):

    # ── AR model (v6b inv_protected anchor) ──────────────────────────────

    def _update_ar(
        self, raw_mid: float, position: int, memory: Dict[str, Any],
    ) -> Tuple[float, float, float, float]:
        """Returns (fair_value, anchor_ema, ar_mom, dev_smooth)."""
        ms_hl = float(self.params.get("mid_smooth_half_life", 20))
        ms_alpha = 1.0 - 0.5 ** (1.0 / ms_hl)
        prev_ms = memory.get("_mid_smooth")
        mid_s = raw_mid if prev_ms is None else ms_alpha * raw_mid + (1.0 - ms_alpha) * float(prev_ms)
        memory["_mid_smooth"] = mid_s

        # Anchor — inv_protected: freeze when |pos| >= threshold × limit
        anchor_price = float(self.params.get("anchor_price", 10000))
        anchor_alpha = float(self.params.get("anchor_alpha", 0.005))
        anchor_ema = float(memory.get("_anchor_ema", anchor_price))
        limit = self.position_limit()
        pos_thr = float(self.params.get("anchor_pos_threshold", 0.20))
        if limit > 0 and abs(position) < limit * pos_thr:
            anchor_ema = anchor_alpha * raw_mid + (1.0 - anchor_alpha) * anchor_ema
        memory["_anchor_ema"] = anchor_ema

        ar_hl = float(self.params.get("ar_smooth_half_life", 5))
        ar_alpha = 1.0 - 0.5 ** (1.0 / ar_hl)
        delta = 0.0 if prev_ms is None else mid_s - float(prev_ms)
        ar_mom = float(memory.get("_ar_momentum", 0.0))
        ar_mom = ar_alpha * delta + (1.0 - ar_alpha) * ar_mom
        memory["_ar_momentum"] = ar_mom

        ar_gain = float(self.params.get("ar_gain", 8.0))
        fair_value = anchor_ema - ar_gain * ar_mom
        memory["_fair_value"] = fair_value

        raw_dev = mid_s - fair_value
        dev_hl = float(self.params.get("dev_smooth_half_life", 5))
        dev_alpha = 1.0 - 0.5 ** (1.0 / dev_hl)
        dev_s = float(memory.get("_dev_smooth", raw_dev))
        dev_s = dev_alpha * raw_dev + (1.0 - dev_alpha) * dev_s
        memory["_dev_smooth"] = dev_s

        return fair_value, anchor_ema, ar_mom, dev_s

    # ── M14 cumulative gate ───────────────────────────────────────────────

    def _update_m14_gate(
        self, state: TradingState, memory: Dict[str, Any],
    ) -> Tuple[int, bool, bool]:
        """Track M14 net cumulative position within the session.

        Returns (m14_cum, sell_gated_by_m14, buy_gated_by_m14).

        m14_cum resets whenever timestamp drops (day boundary).
        Sell is gated (suppressed) when M14 is net buyer above threshold.
        Buy is gated when M14 is net seller below negative threshold.
        """
        m14_name = str(self.params.get("m14_trader", "Mark 14"))
        m38_name = str(self.params.get("m38_trader", "Mark 38"))

        # Detect day boundary: new day starts at timestamp 0
        prev_ts = int(memory.get("_prev_timestamp", state.timestamp))
        if state.timestamp < prev_ts:   # timestamp wrapped = new day
            memory["_m14_cum"] = 0
            memory["_m38_cum"] = 0
        memory["_prev_timestamp"] = state.timestamp

        # Accumulate M14 net this tick
        m14_tick = 0
        m38_tick = 0
        for trade in state.market_trades.get(self.product, []):
            if trade.buyer == m14_name:    m14_tick += trade.quantity
            elif trade.seller == m14_name: m14_tick -= trade.quantity
            if trade.buyer == m38_name:    m38_tick += trade.quantity
            elif trade.seller == m38_name: m38_tick -= trade.quantity

        m14_cum = int(memory.get("_m14_cum", 0)) + m14_tick
        m38_cum = int(memory.get("_m38_cum", 0)) + m38_tick
        memory["_m14_cum"] = m14_cum
        memory["_m38_cum"] = m38_cum

        # Combined informed signal: M14 bullish + M38 selling = strongly bullish
        # M14 buying (m14_cum > 0) = M14 thinks price going up = suppress our sells
        # M38 selling (m38_cum < 0) = retail selling = confirms M14 bullish view
        bullish_thr = float(self.params.get("m14_bullish_threshold", 40))
        bearish_thr = float(self.params.get("m14_bearish_threshold", 40))

        # M38 weight: fractional contribution (0 = M14 only, 0.3 = M14 + 30% M38)
        m38_weight = float(self.params.get("m38_weight", 0.0))
        informed_long = m14_cum + m38_weight * (-m38_cum)  # M14_buy + M38_sell = bullish

        # Only gate SELLS when M14 is bullish (front-running uptrend).
        # Never gate BUYS: we always need to recover our short position when price reverts.
        sell_gated = informed_long >= bullish_thr  # >= so threshold=75 catches m14_cum=75 exactly
        buy_gated  = False   # never suppress buys via M14 signal

        memory["_informed_long"] = informed_long
        memory["_sell_gated_m14"] = int(sell_gated)
        return m14_cum, sell_gated, buy_gated

    # ── Position-based sell/buy allowance ────────────────────────────────

    def _position_gates(self, position: int) -> Tuple[bool, bool]:
        """Hard cap: when position is too short, zero ALL sells (taker + MM ask).
        When position is too long, zero ALL buys (taker + MM bid).

        This fixes the v8 bug where only the AR taker was blocked but the MM ask
        kept filling as Mark 14 lifted it into the uptrend.
        """
        limit = self.position_limit()
        sell_cap_pct = float(self.params.get("sell_cap_pct", 0.70))  # -140u default
        buy_cap_pct  = float(self.params.get("buy_cap_pct",  0.70))  # +140u default

        sell_cap = int(sell_cap_pct * limit)
        buy_cap_lim  = int(buy_cap_pct  * limit)

        sell_allowed = position > -sell_cap   # can still sell if not too short
        buy_allowed  = position < buy_cap_lim # can still buy if not too long
        return sell_allowed, buy_allowed

    # ── AR takers ─────────────────────────────────────────────────────────

    def _ar_takers(
        self,
        order_depth: OrderDepth,
        fair_value: float,
        sell_allowed: bool,
        buy_allowed: bool,
        sell_gated: bool,
        buy_gated: bool,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, int, int]:
        take_edge = float(self.params.get("ar_taker_edge", 12.0))
        taker_size_pct = float(self.params.get("ar_taker_size_pct", 0.30))
        taker_size = max(1, int(taker_size_pct * self.position_limit()))

        orders: List[Order] = []
        bought = sold = 0

        # Taker BUY: price far below fair value → expect reversion up
        if buy_allowed and not buy_gated:
            for ask_p in sorted(order_depth.sell_orders):
                if ask_p > fair_value - take_edge or buy_cap <= 0:
                    break
                avail = -order_depth.sell_orders[ask_p]
                qty = min(avail, buy_cap, taker_size)
                if qty > 0:
                    orders.append(Order(self.product, ask_p, qty))
                    buy_cap -= qty
                    bought += qty

        # Taker SELL: price far above fair value → expect reversion down
        if sell_allowed and not sell_gated:
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if bid_p < fair_value + take_edge or sell_cap <= 0:
                    break
                avail = order_depth.buy_orders[bid_p]
                qty = min(avail, sell_cap, taker_size)
                if qty > 0:
                    orders.append(Order(self.product, bid_p, -qty))
                    sell_cap -= qty
                    sold += qty

        return orders, buy_cap, sell_cap, bought, sold

    # ── Passive MM with inventory skew and hard cap ───────────────────────

    def _mm_passive(
        self,
        book: BookSnapshot,
        position: int,
        sell_allowed: bool,
        buy_allowed: bool,
        sell_gated: bool,
        buy_gated: bool,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        limit = self.position_limit()
        base_size   = float(self.params.get("maker_size_base_pct", 0.15)) * limit
        inv_skew_max = float(self.params.get("inv_skew_ticks", 4))

        inv_ratio = position / max(1, limit)
        bid_size = max(0.0, base_size * (1.0 - inv_ratio))
        ask_size = max(0.0, base_size * (1.0 + inv_ratio))

        # Gate: suppress selling (taker + MM ask) when M14 is accumulating long
        # or when position hard cap is hit. Buys always allowed.
        if not sell_allowed or sell_gated:
            ask_size = 0.0
        if not buy_allowed or buy_gated:
            bid_size = 0.0

        # Inventory skew: make bid more competitive when short (or ask when long)
        if position < 0:
            skew = int(inv_skew_max * abs(inv_ratio))
            bid_px = (book.best_bid + 1 + skew) if book.best_bid is not None else None
            ask_px = (book.best_ask - 1)         if book.best_ask is not None else None
        elif position > 0:
            skew = int(inv_skew_max * abs(inv_ratio))
            bid_px = (book.best_bid + 1)         if book.best_bid is not None else None
            ask_px = (book.best_ask - 1 - skew)  if book.best_ask is not None else None
        else:
            bid_px = (book.best_bid + 1) if book.best_bid is not None else None
            ask_px = (book.best_ask - 1) if book.best_ask is not None else None

        # Prevent self-crossing
        if bid_px is not None and ask_px is not None and bid_px >= ask_px:
            bid_px = book.best_bid if book.best_bid is not None else (ask_px - 1 if ask_px else None)
            if bid_px is not None and ask_px is not None and bid_px >= ask_px:
                bid_px = ask_px - 1

        orders: List[Order] = []
        qty_bid = min(buy_cap,  int(bid_size))
        qty_ask = min(sell_cap, int(ask_size))
        if qty_bid > 0 and bid_px is not None:
            orders.append(Order(self.product, bid_px,  qty_bid))
        if qty_ask > 0 and ask_px is not None:
            orders.append(Order(self.product, ask_px, -qty_ask))

        return orders, qty_bid, qty_ask

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

        fair_value, anchor_val, ar_mom, dev = self._update_ar(float(mid), position, memory)
        m14_cum, sell_gated, buy_gated = self._update_m14_gate(state, memory)
        sell_allowed, buy_allowed = self._position_gates(position)

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        taker_orders, buy_cap, sell_cap, t_bought, t_sold = self._ar_takers(
            order_depth, fair_value,
            sell_allowed, buy_allowed, sell_gated, buy_gated,
            buy_cap, sell_cap,
        )

        mm_orders, mm_bid_qty, mm_ask_qty = self._mm_passive(
            book, position,
            sell_allowed, buy_allowed, sell_gated, buy_gated,
            buy_cap, sell_cap,
        )

        all_orders = taker_orders + mm_orders

        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":      position,
                "mid":           round(float(mid), 2),
                "FairValue":     round(fair_value, 2),
                "Anchor":        round(anchor_val, 2),
                "DevSmooth":     round(dev, 3),
                "ar_mom":        round(ar_mom, 4),
                "m14_cum":       m14_cum,
                "sell_gated":    int(sell_gated),
                "sell_allowed":  int(sell_allowed),
                "taker_buy":     t_bought,
                "taker_sell":    t_sold,
                "mm_bid_qty":    mm_bid_qty,
                "mm_ask_qty":    mm_ask_qty,
            },
        )

        return all_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value"))       is not None: out["FairValue"]    = float(v)
        if (v := memory.get("_dev_smooth"))       is not None: out["DevSmooth"]    = float(v)
        if (v := memory.get("_anchor_ema"))       is not None: out["Anchor"]       = float(v)
        if (v := memory.get("_ar_momentum"))      is not None: out["ar_mom"]       = float(v)
        if (v := memory.get("_m14_cum"))          is not None: out["M14Cum"]       = float(v)
        if (v := memory.get("_informed_long"))    is not None: out["InformedLong"] = float(v)
        if (v := memory.get("_sell_gated_m14"))   is not None: out["SellGated"]    = float(v)
        return out
