"""HYDROGEL_PACK — mv_v13: dual-gate = v9 M14-HYDRO gate + v12 VEV_4000 hedge gate

MOTIVATION:
  v9 M14 HYDRO gate (cumulative, fires 8% of ticks):
    ✓ Works great in BACKTEST: M14 accumulates buys when M38 sells into M14's bids.
      When cum>=75, M38 has sold ~75 units = price was falling = oversold setup.
      Gate fires at the oversold bottom → prevents selling into the bounce. Correct!
    ✗ FAILS IN LIVE: when M38 was BUYING (live failure session), M14 was a net SELLER
      (m14_cum = -4260). The gate threshold (cum >= +75) never fires. No protection.

  v12 VEV_4000 gate (decayed signal, fires 1.97% of ticks):
    ✗ Weaker in BACKTEST: fires rarely, misses the oversold-reversion benefit of v9 gate.
      Removing the M14-HYDRO gate costs ~11k PnL in 3-day backtest.
    ✓ WORKS IN LIVE FAILURE SCENARIO:
      M38 buys HYDROGEL → M14 (passive MM) gets SHORT HYDROGEL → M14 hedges by
      buying VEV_4000 → vev_hedge_sig rises above threshold → gate fires.
      This WOULD have fired in the v9 live failure (where m14_cum = -4260 but
      M14 was simultaneously buying VEV_4000 to hedge the short).

DUAL GATE DESIGN:
  sell_gated = (m14_hydro_cum >= m14_hydro_threshold)   ← v9 gate
               OR (vev_hedge_sig >= vev_gate_threshold)   ← v12 gate

  - Both gates gate ALL sells (AR taker + MM ask)
  - The two gates are largely complementary: only 6/30000 ticks overlap in 3-day data
  - Combined: ~10% of ticks gated (vs 8% for v9 alone, vs 2% for v12 alone)

EXPECTED PERFORMANCE:
  Backtest: ~172k (identical to v9 — M14-HYDRO gate preserved)
            + small improvement from VEV gate blocking the 585 additional bad sells
  Live: + VEV_4000 gate fires in the dangerous scenario (M38 buying)
          where v9's gate was silent

PARAMS vs v9: same M14 gate params + new VEV_4000 gate params from v12.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydroMVV13(BaseStrategy):

    # ── AR model (v6b inv_protected — unchanged) ──────────────────────────

    def _update_ar(
        self, raw_mid: float, position: int, memory: Dict[str, Any],
    ) -> Tuple[float, float, float, float]:
        ms_hl = float(self.params.get("mid_smooth_half_life", 20))
        ms_alpha = 1.0 - 0.5 ** (1.0 / ms_hl)
        prev_ms = memory.get("_mid_smooth")
        mid_s = raw_mid if prev_ms is None else ms_alpha * raw_mid + (1.0 - ms_alpha) * float(prev_ms)
        memory["_mid_smooth"] = mid_s

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

    # ── Gate 1: M14 HYDROGEL cumulative (from v9) ─────────────────────────

    def _update_m14_hydro_gate(
        self, state: TradingState, memory: Dict[str, Any],
    ) -> Tuple[int, bool]:
        """v9 gate: cumulative M14 HYDROGEL net since day start.

        When M38 has been selling heavily → M14 accumulates buys → cum goes HIGH.
        Gate fires at cum >= threshold (oversold setup, price about to bounce up).
        Fires 8% of ticks in 3-day backtest with conditional return +0.27 (vs base +0.05).
        """
        m14_name = str(self.params.get("m14_trader", "Mark 14"))

        prev_ts = int(memory.get("_prev_ts_m14", state.timestamp))
        if state.timestamp < prev_ts:
            memory["_m14_hydro_cum"] = 0
        memory["_prev_ts_m14"] = state.timestamp

        cum = int(memory.get("_m14_hydro_cum", 0))
        for trade in state.market_trades.get(self.product, []):
            if trade.buyer == m14_name:   cum += trade.quantity
            elif trade.seller == m14_name: cum -= trade.quantity
        memory["_m14_hydro_cum"] = cum

        threshold = float(self.params.get("m14_hydro_threshold", 75.0))
        gated = cum >= threshold
        memory["_m14_hydro_gated"] = int(gated)
        return cum, gated

    # ── Gate 2: M14 VEV_4000 cross-asset hedge (from v12) ─────────────────

    def _update_vev_hedge_gate(
        self, state: TradingState, memory: Dict[str, Any],
    ) -> Tuple[float, bool]:
        """v12 gate: M14 hedging short HYDROGEL by buying VEV_4000.

        When M38 buys HYDROGEL → M14 gets short → M14 buys VEV_4000 to hedge.
        Fires 1.97% of ticks with conditional HYDRO return +1.29 (vs base +0.05).
        SPECIFICALLY catches the live failure scenario where M14_cum is very negative.
        """
        vev_prod  = str(self.params.get("vev_gate_product", "VEV_4000"))
        m14_name  = str(self.params.get("vev_gate_trader",  "Mark 14"))
        hl        = float(self.params.get("vev_gate_hl",    100.0))
        threshold = float(self.params.get("vev_gate_threshold", 5.0))

        prev_ts = int(memory.get("_prev_ts_vev", state.timestamp))
        if state.timestamp < prev_ts:
            memory["_vev_hedge_sig"] = 0.0
        memory["_prev_ts_vev"] = state.timestamp

        decay = 0.5 ** (1.0 / max(hl, 1.0))
        sig = float(memory.get("_vev_hedge_sig", 0.0)) * decay

        for trade in state.market_trades.get(vev_prod, []):
            if trade.buyer == m14_name:    sig += trade.quantity
            elif trade.seller == m14_name: sig -= trade.quantity

        memory["_vev_hedge_sig"] = sig
        gated = sig > threshold
        memory["_vev_hedge_gated"] = int(gated)
        return sig, gated

    # ── Position gates ─────────────────────────────────────────────────────

    def _position_gates(self, position: int) -> Tuple[bool, bool]:
        limit = self.position_limit()
        sell_allowed = position > -int(float(self.params.get("sell_cap_pct", 1.0)) * limit)
        buy_allowed  = position <  int(float(self.params.get("buy_cap_pct",  1.0)) * limit)
        return sell_allowed, buy_allowed

    # ── AR takers ─────────────────────────────────────────────────────────

    def _ar_takers(
        self,
        order_depth: OrderDepth,
        fair_value: float,
        sell_allowed: bool,
        buy_allowed: bool,
        sell_gated: bool,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, int, int]:
        take_edge  = float(self.params.get("ar_taker_edge", 12.0))
        taker_size = max(1, int(float(self.params.get("ar_taker_size_pct", 0.30)) * self.position_limit()))

        orders: List[Order] = []
        bought = sold = 0

        if buy_allowed:
            for ask_p in sorted(order_depth.sell_orders):
                if ask_p > fair_value - take_edge or buy_cap <= 0: break
                qty = min(-order_depth.sell_orders[ask_p], buy_cap, taker_size)
                if qty > 0:
                    orders.append(Order(self.product, ask_p, qty))
                    buy_cap -= qty; bought += qty

        if sell_allowed and not sell_gated:
            for bid_p in sorted(order_depth.buy_orders, reverse=True):
                if bid_p < fair_value + take_edge or sell_cap <= 0: break
                qty = min(order_depth.buy_orders[bid_p], sell_cap, taker_size)
                if qty > 0:
                    orders.append(Order(self.product, bid_p, -qty))
                    sell_cap -= qty; sold += qty

        return orders, buy_cap, sell_cap, bought, sold

    # ── Passive MM ─────────────────────────────────────────────────────────

    def _mm_passive(
        self,
        book: BookSnapshot,
        position: int,
        sell_allowed: bool,
        sell_gated: bool,
        buy_allowed: bool,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        limit = self.position_limit()
        base_size    = float(self.params.get("maker_size_base_pct", 0.15)) * limit
        inv_skew_max = float(self.params.get("inv_skew_ticks", 4))
        inv_ratio    = position / max(1, limit)

        bid_size = max(0.0, base_size * (1.0 - inv_ratio))
        ask_size = max(0.0, base_size * (1.0 + inv_ratio))

        if not sell_allowed or sell_gated: ask_size = 0.0
        if not buy_allowed:                bid_size = 0.0

        if position < 0:
            skew   = int(inv_skew_max * abs(inv_ratio))
            bid_px = (book.best_bid + 1 + skew) if book.best_bid is not None else None
            ask_px = (book.best_ask - 1)         if book.best_ask is not None else None
        elif position > 0:
            skew   = int(inv_skew_max * abs(inv_ratio))
            bid_px = (book.best_bid + 1)         if book.best_bid is not None else None
            ask_px = (book.best_ask - 1 - skew)  if book.best_ask is not None else None
        else:
            bid_px = (book.best_bid + 1) if book.best_bid is not None else None
            ask_px = (book.best_ask - 1) if book.best_ask is not None else None

        if bid_px is not None and ask_px is not None and bid_px >= ask_px:
            bid_px = book.best_bid if book.best_bid is not None else (ask_px - 1 if ask_px else None)
            if bid_px is not None and ask_px is not None and bid_px >= ask_px:
                bid_px = ask_px - 1

        qty_bid = min(buy_cap,  int(bid_size))
        qty_ask = min(sell_cap, int(ask_size))
        orders: List[Order] = []
        if qty_bid > 0 and bid_px is not None:
            orders.append(Order(self.product, bid_px,  qty_bid))
        if qty_ask > 0 and ask_px is not None:
            orders.append(Order(self.product, ask_px, -qty_ask))
        return orders, qty_bid, qty_ask

    # ── Main entry ─────────────────────────────────────────────────────────

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
        m14_cum, m14_gated   = self._update_m14_hydro_gate(state, memory)
        vev_sig, vev_gated   = self._update_vev_hedge_gate(state, memory)
        sell_allowed, buy_allowed = self._position_gates(position)

        sell_gated = m14_gated or vev_gated   # either gate suppresses sells

        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        taker_orders, buy_cap, sell_cap, t_bought, t_sold = self._ar_takers(
            order_depth, fair_value,
            sell_allowed, buy_allowed, sell_gated,
            buy_cap, sell_cap,
        )
        mm_orders, mm_bid_qty, mm_ask_qty = self._mm_passive(
            book, position,
            sell_allowed, sell_gated, buy_allowed,
            buy_cap, sell_cap,
        )

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
                "m14_hydro_cum": m14_cum,
                "vev_hedge_sig": round(vev_sig, 2),
                "m14_gated":     int(m14_gated),
                "vev_gated":     int(vev_gated),
                "sell_gated":    int(sell_gated),
                "sell_allowed":  int(sell_allowed),
                "taker_buy":     t_bought,
                "taker_sell":    t_sold,
                "mm_bid_qty":    mm_bid_qty,
                "mm_ask_qty":    mm_ask_qty,
            },
        )

        return taker_orders + mm_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value"))       is not None: out["FairValue"]    = float(v)
        if (v := memory.get("_dev_smooth"))       is not None: out["DevSmooth"]    = float(v)
        if (v := memory.get("_anchor_ema"))       is not None: out["Anchor"]       = float(v)
        if (v := memory.get("_ar_momentum"))      is not None: out["ar_mom"]       = float(v)
        if (v := memory.get("_m14_hydro_cum"))    is not None: out["M14HydroCum"]  = float(v)
        if (v := memory.get("_vev_hedge_sig"))    is not None: out["VevHedgeSig"]  = float(v)
        if (v := memory.get("_m14_hydro_gated"))  is not None: out["M14Gated"]     = float(v)
        if (v := memory.get("_vev_hedge_gated"))  is not None: out["VevGated"]     = float(v)
        return out
