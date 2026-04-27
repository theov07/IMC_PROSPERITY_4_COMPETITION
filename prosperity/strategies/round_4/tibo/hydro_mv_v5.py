"""HYDROGEL_PACK — mv_v5: Passive MM + AR signal + v201 features, ablation study.

Diagnosis: mv_v4 (22k PnL) vs v201 (114k PnL).
  v4 has 184 trades, 99.9% aggressive (pays ~8 ticks/leg = 16 ticks per round trip).
  v201 has 4001 trades, 93% passive (earns ~8 ticks per fill).
  Root cause: v4 is a directional strategy that costs the spread;
              v201 is a MM that earns the spread + uses AR for timing.

v5 adds passive quoting as the core (earning the spread), then layers v201 features
one at a time via toggleable params to measure each contribution:

  Feature A — passive_quoting=True (default ON)
    Post bid at best_bid+1 and ask at best_ask-1 every tick.
    Inventory-adaptive: sizes shrink as position grows.

  Feature B — use_ar_taker=True (default OFF)
    Use the AR deviation signal to fire taker orders when deviation is large.
    Same AR model as v4: fair_value = anchor_ema - ar_gain × ewma_momentum.
    Fires when |dev| > ar_taker_threshold. Like v201's _fire_takers().

  Feature C — use_gap_exploit=True (default OFF)
    Gap exploit: when best bid/ask is thin and there's a big gap to L2,
    sweep the thin level aggressively. Like v201's _gap_exploit().

  Feature D — use_m14_gate=True (default OFF)
    Mark 14 gate: strip one side and scale up the other when M14 is active.
    Like v201's _apply_gate().

  Feature E — use_ar_quote_bias=True (default OFF)
    Bias passive quotes toward AR fair value. When dev is positive (price above
    fair), raise ask closer to best; when negative, lower bid.
    This skews quotes to be more aggressive in the predicted direction.

  Feature F — use_inventory_bias=True (default ON)
    Inventory-adaptive sizing: bid_size = base × (1 - pos/limit),
    ask_size = base × (1 + pos/limit). Always recommended.

Ablation configs:
  v5_mm_only    — passive quoting + inventory bias only
  v5_mm_ar      — + AR taker signal
  v5_mm_gap     — + gap exploit
  v5_mm_m14     — + M14 gate
  v5_mm_ar_bias — + AR quote bias
  v5_full       — all features enabled

Self-contained (BaseStrategy only).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.strategies.base.base import BaseStrategy


class HydroMVV5(BaseStrategy):

    # ── AR model (from v4) ────────────────────────────────────────────────

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

    # ── Mark 14 tracking ─────────────────────────────────────────────────

    def _update_m14(self, state: TradingState, memory: Dict[str, Any]) -> int:
        trader = str(self.params.get("informed_trader_name", "Mark 14"))
        net = 0
        for trade in state.market_trades.get(self.product, []):
            if trade.buyer == trader:    net += trade.quantity
            elif trade.seller == trader: net -= trade.quantity
        signal = 1 if net > 0 else (-1 if net < 0 else 0)
        memory["_m14_signal"] = signal
        return signal

    # ── Sizing ────────────────────────────────────────────────────────────

    def _passive_sizes(self, position: int) -> Tuple[float, float]:
        limit   = self.position_limit()
        base    = float(self.params.get("maker_size_base_pct", 0.15)) * limit
        inv_bias = self.params.get("use_inventory_bias", True)
        if inv_bias and limit > 0:
            bid_size = base * (1.0 - position / limit)
            ask_size = base * (1.0 + position / limit)
        else:
            bid_size = ask_size = base
        return max(0.0, bid_size), max(0.0, ask_size)

    # ── Feature A: Passive quoting ────────────────────────────────────────

    def _passive_quotes(
        self,
        book: BookSnapshot,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        position: int,
        dev: float,
    ) -> List[Order]:
        if not self.params.get("passive_quoting", True):
            return []

        bid_price = (book.best_bid + 1) if book.best_bid is not None else None
        ask_price = (book.best_ask - 1) if book.best_ask is not None else None

        # Feature E: AR quote bias — shift quote prices toward fair value
        if self.params.get("use_ar_quote_bias", False) and bid_price and ask_price:
            bias_ticks = int(self.params.get("ar_quote_bias_ticks", 2))
            if dev > 0:   # price above fair → make ask more aggressive
                ask_price = max(book.best_bid + 1 if book.best_bid else ask_price,
                                ask_price - bias_ticks)
            elif dev < 0: # price below fair → make bid more aggressive
                bid_price = min(book.best_ask - 1 if book.best_ask else bid_price,
                                bid_price + bias_ticks)

        # Guard: don't cross
        if bid_price is not None and ask_price is not None and bid_price >= ask_price:
            bid_price = ask_price - 1

        # Hard stop: don't quote accumulating side near position limit
        limit    = self.position_limit()
        hard_pct = float(self.params.get("pct_kept_for_takers", 0.2))
        if abs(position) >= limit * (1.0 - hard_pct):
            if position > 0: bid_size  = 0.0
            else:            ask_size  = 0.0

        orders: List[Order] = []
        qty_bid = min(buy_cap,  int(bid_size))
        qty_ask = min(sell_cap, int(ask_size))
        if qty_bid > 0 and bid_price is not None:
            orders.append(Order(self.product, bid_price,  qty_bid))
        if qty_ask > 0 and ask_price is not None:
            orders.append(Order(self.product, ask_price, -qty_ask))
        return orders

    # ── Feature B: AR taker orders ────────────────────────────────────────

    def _ar_takers(
        self,
        book: BookSnapshot,
        order_depth: OrderDepth,
        fair_value: float,
        dev: float,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, Set[int], Set[int]]:
        if not self.params.get("use_ar_taker", False):
            return [], buy_cap, sell_cap, set(), set()

        take_edge = float(self.params.get("ar_taker_edge", 1.0))
        taker_size_pct = float(self.params.get("ar_taker_size_pct", 0.3))
        orders: List[Order] = []
        buy_px:  Set[int] = set()
        sell_px: Set[int] = set()

        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fair_value - take_edge or buy_cap <= 0:
                break
            avail = -order_depth.sell_orders[ask_p]
            qty   = min(avail, buy_cap, max(1, int(bid_size * taker_size_pct)))
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            if bid_p < fair_value + take_edge or sell_cap <= 0:
                break
            avail = order_depth.buy_orders[bid_p]
            qty   = min(avail, sell_cap, max(1, int(ask_size * taker_size_pct)))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                sell_px.add(bid_p)
                sell_cap -= qty

        return orders, buy_cap, sell_cap, buy_px, sell_px

    # ── Feature B2: Anchor guard (like v201's _use_anchor) ───────────────
    # Disable AR taker when price is trending AWAY from anchor.
    # This prevents accumulating bad positions when price is trending.

    def _guard_allows_taker(
        self, raw_mid: float, position: int, memory: Dict[str, Any],
    ) -> bool:
        if not self.params.get("use_anchor_guard", False):
            return True  # guard off → always allow
        anchor    = float(self.params.get("anchor_price", 10000))
        prev_mid  = memory.get("_guard_prev_mid", raw_mid)
        memory["_guard_prev_mid"] = raw_mid
        raw_delta = raw_mid - float(prev_mid)
        alpha     = float(self.params.get("guard_trend_alpha", 0.3))
        trend_ema = float(memory.get("_guard_trend_ema", raw_delta))
        trend_ema = alpha * raw_delta + (1.0 - alpha) * trend_ema
        memory["_guard_trend_ema"] = trend_ema
        dist      = raw_mid - anchor
        threshold = float(self.params.get("guard_reversion_threshold", 3.0))
        max_dist  = float(self.params.get("guard_max_dist", 80.0))
        # reverting: dist × trend ≤ -threshold (price moving back toward anchor)
        reverting = abs(dist) <= max_dist and (dist * trend_ema <= -threshold)
        near      = abs(dist) <= float(self.params.get("guard_near_band", 0.5))
        # also stop taker if position is already far in the trending direction
        inv_dist  = float(self.params.get("guard_inventory_dist", 40.0))
        wrong_way = (position > 0 and dist < -inv_dist) or (position < 0 and dist > inv_dist)
        guard_on  = (near or reverting) and not wrong_way
        memory["_guard_on"] = int(guard_on)
        return guard_on

    # ── Feature C: Gap exploit ────────────────────────────────────────────

    def _gap_exploit(
        self,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        taker_buy_px: Set[int],
        taker_sell_px: Set[int],
    ) -> Tuple[List[Order], int, int, Optional[int], Optional[int]]:
        if not self.params.get("use_gap_exploit", False):
            return [], buy_cap, sell_cap, None, None

        gap_min     = float(self.params.get("gap_trigger_min", 8))
        gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.10))
        gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 1))
        limit       = self.position_limit()
        gap_max_vol = int(gap_vol_pct * limit)

        all_bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        all_asks = sorted(order_depth.sell_orders.keys())
        if all_bids: memory["_last_best_bid"] = all_bids[0]
        if all_asks: memory["_last_best_ask"] = all_asks[0]
        last_bid = memory.get("_last_best_bid")
        last_ask = memory.get("_last_best_ask")

        rem_bids = [p for p in all_bids if p not in taker_sell_px]
        rem_asks = [p for p in all_asks if p not in taker_buy_px]

        orders:    List[Order] = []
        gap_swept_bids: Set[int] = set()
        gap_swept_asks: Set[int] = set()

        if gap_min > 0 and gap_max_vol > 0:
            bid_gap_ok = False
            bid1 = bid1_vol = None
            if len(rem_bids) >= 2:
                bid1, bid2 = rem_bids[0], rem_bids[1]
                bid1_vol   = order_depth.buy_orders[bid1]
                bid_gap_ok = (bid1 - bid2) >= gap_min and bid1_vol <= gap_max_vol
            streak = memory.get("_gap_bid_streak", 0)
            streak = streak + 1 if bid_gap_ok else 0
            memory["_gap_bid_streak"] = streak
            if streak >= gap_confirm and bid_gap_ok and sell_cap > 0:
                qty = min(bid1_vol, sell_cap, int(ask_size))
                if qty > 0:
                    orders.append(Order(self.product, bid1, -qty))
                    sell_cap -= qty
                    if qty >= bid1_vol: gap_swept_bids.add(bid1)

            ask_gap_ok = False
            ask1 = ask1_vol = None
            if len(rem_asks) >= 2:
                ask1, ask2 = rem_asks[0], rem_asks[1]
                ask1_vol   = -order_depth.sell_orders[ask1]
                ask_gap_ok = (ask2 - ask1) >= gap_min and ask1_vol <= gap_max_vol
            streak = memory.get("_gap_ask_streak", 0)
            streak = streak + 1 if ask_gap_ok else 0
            memory["_gap_ask_streak"] = streak
            if streak >= gap_confirm and ask_gap_ok and buy_cap > 0:
                qty = min(ask1_vol, buy_cap, int(bid_size))
                if qty > 0:
                    orders.append(Order(self.product, ask1, qty))
                    buy_cap -= qty
                    if qty >= ask1_vol: gap_swept_asks.add(ask1)

        final_bids = [p for p in rem_bids if p not in gap_swept_bids]
        final_asks = [p for p in rem_asks if p not in gap_swept_asks]
        shift = float(self.params.get("OB_cleared_shift", 8))
        new_bid = (final_bids[0] + 1) if final_bids else (
            (last_bid - int(shift)) if last_bid else None)
        new_ask = (final_asks[0] - 1) if final_asks else (
            (last_ask + int(shift)) if last_ask else None)

        return orders, buy_cap, sell_cap, new_bid, new_ask

    # ── Feature D: M14 gate ───────────────────────────────────────────────

    def _apply_m14_gate(
        self,
        orders: List[Order],
        signal: int,
        position: int,
    ) -> List[Order]:
        if not self.params.get("use_m14_gate", False) or signal == 0:
            return orders
        factor = float(self.params.get("m14_agree_factor", 2.0))
        limit  = self.position_limit()
        if signal > 0:
            cap = self.buy_capacity(position)
            return [
                Order(self.product, o.price,
                      min(cap, max(1, int(o.quantity * factor))))
                for o in orders if o.quantity > 0
            ]
        else:
            cap = self.sell_capacity(position)
            return [
                Order(self.product, o.price,
                      -min(cap, max(1, int(abs(o.quantity) * factor))))
                for o in orders if o.quantity < 0
            ]

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
        sigma  = self._update_volatility(float(mid), memory)
        signal = self._update_m14(state, memory)

        # Store book for next-tick references
        if book.best_bid is not None: memory["_prev_best_bid"] = book.best_bid
        if book.best_ask is not None: memory["_prev_best_ask"] = book.best_ask

        limit    = self.position_limit()
        buy_cap  = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        bid_size, ask_size = self._passive_sizes(position)

        # Feature B2: guard check — skip AR taker when price trending away
        guard_ok = self._guard_allows_taker(float(mid), position, memory)

        # Feature B: AR taker orders (fire first, consume capacity)
        taker_orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px = (
            self._ar_takers(book, order_depth, fair_value, dev,
                            bid_size, ask_size, buy_cap, sell_cap)
            if guard_ok else ([], buy_cap, sell_cap, set(), set())
        )

        # Feature C: Gap exploit (may adjust bid_price, ask_price)
        gap_orders, buy_cap, sell_cap, gap_bid, gap_ask = self._gap_exploit(
            order_depth, memory, bid_size, ask_size, buy_cap, sell_cap,
            taker_buy_px, taker_sell_px,
        )

        # Feature A: Passive quoting (use gap-adjusted prices if available)
        if gap_bid is not None:
            book_bid_override = gap_bid
        else:
            book_bid_override = book.best_bid
        if gap_ask is not None:
            book_ask_override = gap_ask
        else:
            book_ask_override = book.best_ask

        # Build a temporary book-like object for passive quoting
        class _FakeBook:
            best_bid = book_bid_override
            best_ask = book_ask_override

        passive_orders = self._passive_quotes(
            _FakeBook(), bid_size, ask_size, buy_cap, sell_cap, position, dev,
        )

        # Combine
        all_orders = taker_orders + gap_orders + passive_orders

        # Feature D: M14 gate (applied to passive orders only, like v201)
        passive_gated = self._apply_m14_gate(passive_orders, signal, position)
        all_orders    = taker_orders + gap_orders + passive_gated

        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=None, ask_price=None,
            extras={
                "position":   position,
                "deviation":  round(dev, 3),
                "fair_value": round(fair_value, 3),
                "m14_signal": signal,
                "bid_size":   int(bid_size),
                "ask_size":   int(ask_size),
                "sigma":      round(sigma, 4),
            },
        )
        return all_orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value")) is not None: out["FairValue"] = float(v)
        if (v := memory.get("_dev_smooth")) is not None: out["DevSmooth"] = float(v)
        if (v := memory.get("_m14_signal")) is not None: out["M14Signal"] = float(v)
        return out
