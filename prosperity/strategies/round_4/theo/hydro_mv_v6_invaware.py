from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.strategies.round_4.theo.hydro_mv_v5_best import BookSnapshot, HydroMVV5


class R4HydroMVV6InvAwareStrategy(HydroMVV5):
    """HYDRO v6: v5 core + trader-aware fair shift + inventory-aware taker edge.

    Key findings from the research loop:
    - The v5 passive core is strong and should remain intact.
    - Hard reversion guards and passive unwind degrade this family.
    - A small counterparty fair shift helps, but only when kept subtle.
    - The real new alpha comes from making AR takers more selective when our
      inventory is already loaded in that direction.
    """

    def _update_m14(self, state: TradingState, memory: Dict[str, object]) -> float:
        decay = float(self.params.get("trader_signal_decay", 0.78))
        alpha = float(self.params.get("trader_signal_alpha", 0.45))
        qty_norm = max(1e-9, float(self.params.get("trader_qty_norm", 10.0)))
        clip = max(1e-9, float(self.params.get("trader_signal_clip", 6.0)))
        buy_weights = self.params.get(
            "trader_buy_weights",
            {"Mark 14": 1.0, "Mark 38": -1.0},
        )
        sell_weights = self.params.get(
            "trader_sell_weights",
            {"Mark 14": -1.0, "Mark 38": 1.0},
        )

        raw = 0.0
        for trade in state.market_trades.get(self.product, []):
            raw += float(buy_weights.get(trade.buyer, 0.0)) * (trade.quantity / qty_norm)
            raw += float(sell_weights.get(trade.seller, 0.0)) * (trade.quantity / qty_norm)

        prev = float(memory.get("_m14_signal", 0.0))
        signal = decay * prev + alpha * raw
        signal = max(-clip, min(clip, signal))
        memory["_m14_signal"] = signal
        return signal

    def _inventory_limit(self) -> int:
        return max(1, int(self.params.get("working_position_limit", self.position_limit())))

    def _update_high_vol_strength(
        self,
        sigma: float,
        memory: Dict[str, object],
    ) -> float:
        start = float(self.params.get("high_vol_sigma_start", 0.0))
        end = float(self.params.get("high_vol_sigma_end", start))
        if start <= 0.0:
            strength = 0.0
        elif end <= start:
            strength = 1.0 if sigma >= start else 0.0
        elif sigma <= start:
            strength = 0.0
        elif sigma >= end:
            strength = 1.0
        else:
            strength = (sigma - start) / max(1e-9, end - start)

        strength = max(0.0, min(1.0, strength))
        memory["_high_vol_strength"] = strength
        memory["_sigma_value"] = float(sigma)
        return strength

    def _blend_high_vol_target(
        self,
        base: float,
        target_key: str,
        vol_strength: float,
    ) -> float:
        if vol_strength <= 0.0 or target_key not in self.params:
            return base
        target = float(self.params.get(target_key, base))
        return base + vol_strength * (target - base)

    def _trader_signal_effect(
        self,
        signal: float,
        *,
        threshold_key: str,
        use_sign_key: str,
    ) -> float:
        threshold = float(self.params.get(threshold_key, 0.0))
        if abs(signal) < threshold:
            return 0.0
        if self.params.get(use_sign_key, False):
            return 1.0 if signal > 0 else -1.0
        return signal

    @staticmethod
    def _signal_conflicts_core(signal: float, dev: float) -> bool:
        return signal != 0.0 and dev != 0.0 and (signal * dev) > 0.0

    def _apply_trader_passive_skew(
        self,
        bid_size: float,
        ask_size: float,
        signal: float,
        dev: float,
    ) -> Tuple[float, float]:
        skew_per_unit = float(self.params.get("trader_passive_skew_per_unit", 0.0))
        if skew_per_unit <= 0.0:
            return bid_size, ask_size

        effect = self._trader_signal_effect(
            signal,
            threshold_key="trader_passive_skew_threshold",
            use_sign_key="trader_passive_skew_use_sign",
        )
        if effect == 0.0:
            return bid_size, ask_size

        skew = min(
            float(self.params.get("trader_passive_skew_max", 0.35)),
            abs(effect) * skew_per_unit,
        )
        if self._signal_conflicts_core(signal, dev):
            skew *= float(self.params.get("trader_passive_skew_conflict_mult", 1.0))
        if skew <= 0.0:
            return bid_size, ask_size

        if effect > 0.0:
            return bid_size * (1.0 + skew), ask_size * max(0.0, 1.0 - skew)
        return bid_size * max(0.0, 1.0 - skew), ask_size * (1.0 + skew)

    def _apply_inventory_taker_block(
        self,
        position: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[int, int]:
        block_ratio = float(self.params.get("inventory_same_side_taker_block_ratio", 0.0))
        vol_strength = float(getattr(self, "_memory", {}).get("_high_vol_strength", 0.0))
        block_ratio = self._blend_high_vol_target(
            block_ratio,
            "high_vol_same_side_taker_block_ratio",
            vol_strength,
        )
        if block_ratio <= 0.0:
            return buy_cap, sell_cap

        limit = self._inventory_limit()
        abs_ratio = abs(position) / limit
        if abs_ratio < block_ratio:
            return buy_cap, sell_cap

        if position > 0:
            buy_cap = 0
        elif position < 0:
            sell_cap = 0
        return buy_cap, sell_cap

    def _apply_inventory_live_fair_shift(
        self,
        mid_s: float,
        fair_value: float,
        position: int,
        memory: Dict[str, object],
    ) -> float:
        limit = self._inventory_limit()
        if limit <= 0 or position == 0:
            memory["_fair_defense_shift"] = 0.0
            return fair_value

        inv_ratio = min(1.0, abs(position) / limit)
        activation_ratio = float(self.params.get("inventory_fair_activation_ratio", 0.0))
        if inv_ratio < activation_ratio:
            memory["_fair_defense_shift"] = 0.0
            return fair_value

        gap_frac = float(self.params.get("inventory_fair_pull_fraction", 0.0))
        mom_gain = float(self.params.get("inventory_fair_ar_mom_cancel", 0.0))
        vol_strength = float(memory.get("_high_vol_strength", 0.0))
        gap_frac += vol_strength * float(self.params.get("high_vol_inventory_fair_pull_add", 0.0))
        mom_gain += vol_strength * float(self.params.get("high_vol_inventory_fair_mom_add", 0.0))
        if gap_frac <= 0.0 and mom_gain <= 0.0:
            memory["_fair_defense_shift"] = 0.0
            return fair_value

        ar_mom = float(memory.get("_ar_momentum", 0.0))
        shift = 0.0
        if position < 0:
            adverse_gap = max(0.0, mid_s - fair_value)
            adverse_mom = max(0.0, ar_mom)
            shift += inv_ratio * gap_frac * adverse_gap
            shift += inv_ratio * mom_gain * adverse_mom
        else:
            adverse_gap = max(0.0, fair_value - mid_s)
            adverse_mom = max(0.0, -ar_mom)
            shift -= inv_ratio * gap_frac * adverse_gap
            shift -= inv_ratio * mom_gain * adverse_mom

        memory["_fair_defense_shift"] = shift
        return fair_value + shift

    def _apply_inventory_same_side_taker_kill(
        self,
        position: int,
        mid_s: float,
        fair_value: float,
        dev: float,
        buy_cap: int,
        sell_cap: int,
        memory: Dict[str, object],
    ) -> Tuple[int, int]:
        limit = self._inventory_limit()
        if limit <= 0 or position == 0:
            memory["_taker_kill_on"] = 0.0
            return buy_cap, sell_cap

        short_ratio = float(self.params.get("inventory_short_taker_kill_ratio", 0.0))
        long_ratio = float(self.params.get("inventory_long_taker_kill_ratio", short_ratio))
        dev_threshold = float(self.params.get("inventory_taker_kill_dev_threshold", 0.0))
        mom_threshold = float(self.params.get("inventory_taker_kill_mom_threshold", 0.0))
        vol_strength = float(memory.get("_high_vol_strength", 0.0))
        short_ratio = self._blend_high_vol_target(
            short_ratio,
            "high_vol_short_taker_kill_ratio",
            vol_strength,
        )
        long_ratio = self._blend_high_vol_target(
            long_ratio,
            "high_vol_long_taker_kill_ratio",
            vol_strength,
        )
        dev_threshold = self._blend_high_vol_target(
            dev_threshold,
            "high_vol_taker_kill_dev_threshold",
            vol_strength,
        )
        mom_threshold = self._blend_high_vol_target(
            mom_threshold,
            "high_vol_taker_kill_mom_threshold",
            vol_strength,
        )
        if short_ratio <= 0.0 and long_ratio <= 0.0:
            memory["_taker_kill_on"] = 0.0
            return buy_cap, sell_cap

        inv_ratio = min(1.0, abs(position) / limit)
        ar_mom = float(memory.get("_ar_momentum", 0.0))
        kill_on = 0.0
        if position < 0 and short_ratio > 0.0 and inv_ratio >= short_ratio:
            if dev >= dev_threshold and ar_mom >= mom_threshold and mid_s >= fair_value:
                sell_cap = 0
                kill_on = -1.0
        elif position > 0 and long_ratio > 0.0 and inv_ratio >= long_ratio:
            if (-dev) >= dev_threshold and (-ar_mom) >= mom_threshold and mid_s <= fair_value:
                buy_cap = 0
                kill_on = 1.0

        memory["_taker_kill_on"] = kill_on
        return buy_cap, sell_cap

    def _apply_inventory_passive_repricing(
        self,
        orders: List[Order],
        position: int,
        *,
        best_bid: Optional[int],
        best_ask: Optional[int],
    ) -> List[Order]:
        if not orders:
            return orders

        limit = self._inventory_limit()
        pos_ratio = position / limit
        abs_ratio = abs(pos_ratio)

        soft_stop_ratio = float(self.params.get("inventory_passive_soft_stop_ratio", 0.0))
        shift_per_full = float(self.params.get("inventory_quote_shift_ticks_per_full", 0.0))
        shift_max = int(self.params.get("inventory_quote_shift_max_ticks", 0))
        unwind_ratio = float(self.params.get("inventory_passive_unwind_ratio", 0.0))
        unwind_ticks = int(self.params.get("inventory_passive_unwind_extra_ticks", 0))
        vol_strength = float(getattr(self, "_memory", {}).get("_high_vol_strength", 0.0))

        shift_per_full += vol_strength * float(self.params.get("high_vol_quote_shift_ticks_per_full", 0.0))
        shift_max += int(round(vol_strength * float(self.params.get("high_vol_quote_shift_max_ticks_add", 0.0))))
        unwind_ticks += int(round(vol_strength * float(self.params.get("high_vol_passive_unwind_ticks_add", 0.0))))

        reservation_shift = 0
        if shift_per_full > 0.0:
            reservation_shift = int(round(-pos_ratio * shift_per_full))
            if shift_max > 0:
                reservation_shift = max(-shift_max, min(shift_max, reservation_shift))

        adjusted: List[Order] = []
        for order in orders:
            if (
                soft_stop_ratio > 0.0
                and abs_ratio >= soft_stop_ratio
                and ((position > 0 and order.quantity > 0) or (position < 0 and order.quantity < 0))
            ):
                continue

            price = int(order.price + reservation_shift)
            if unwind_ticks > 0 and unwind_ratio > 0.0 and abs_ratio >= unwind_ratio:
                if position > 0 and order.quantity < 0:
                    price -= unwind_ticks
                elif position < 0 and order.quantity > 0:
                    price += unwind_ticks

            if order.quantity > 0 and best_ask is not None:
                price = min(price, best_ask - 1)
            if order.quantity < 0 and best_bid is not None:
                price = max(price, best_bid + 1)

            adjusted.append(Order(self.product, price, order.quantity))

        bid_order = next((order for order in adjusted if order.quantity > 0), None)
        ask_order = next((order for order in adjusted if order.quantity < 0), None)
        if bid_order is not None and ask_order is not None and bid_order.price >= ask_order.price:
            if position > 0:
                ask_order.price = bid_order.price + 1
            else:
                bid_order.price = ask_order.price - 1

        return adjusted

    def _passive_sizes(self, position: int) -> Tuple[float, float]:
        official_limit = max(1, self.position_limit())
        inventory_limit = self._inventory_limit()
        base = float(self.params.get("maker_size_base_pct", 0.15)) * official_limit
        vol_strength = float(getattr(self, "_memory", {}).get("_high_vol_strength", 0.0))
        high_vol_maker_mult = float(self.params.get("high_vol_maker_mult", 1.0))
        base *= 1.0 + vol_strength * (high_vol_maker_mult - 1.0)
        if not self.params.get("use_inventory_bias", True):
            return max(0.0, base), max(0.0, base)

        inv_ratio = min(1.0, abs(position) / inventory_limit)
        remaining = max(0.0, 1.0 - inv_ratio)
        same_side_power = float(self.params.get("inventory_same_side_power", 1.0))
        same_side_power += vol_strength * float(self.params.get("high_vol_same_side_power_add", 0.0))
        opposite_side_boost = float(self.params.get("inventory_opposite_side_boost", 1.0))
        opposite_side_cap_mult = float(self.params.get("inventory_opposite_side_cap_mult", 2.0))

        same_side_mult = remaining ** same_side_power if same_side_power > 0.0 else remaining
        opposite_side_mult = 1.0 + opposite_side_boost * (1.0 - same_side_mult)
        opposite_side_mult = min(opposite_side_mult, opposite_side_cap_mult)

        if position > 0:
            bid_size = base * same_side_mult
            ask_size = base * opposite_side_mult
        elif position < 0:
            bid_size = base * opposite_side_mult
            ask_size = base * same_side_mult
        else:
            bid_size = ask_size = base

        return max(0.0, bid_size), max(0.0, ask_size)

    def _ar_takers(
        self,
        book: BookSnapshot,
        order_depth: OrderDepth,
        mid_s: float,
        fair_value: float,
        dev: float,
        signal: float,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int, Set[int], Set[int]]:
        if not self.params.get("use_ar_taker", False):
            return [], buy_cap, sell_cap, set(), set()

        base_edge = float(self.params.get("ar_taker_edge", 1.0))
        taker_size_pct = float(self.params.get("ar_taker_size_pct", 0.3))
        vol_strength = float(getattr(self, "_memory", {}).get("_high_vol_strength", 0.0))
        edge_add = vol_strength * float(self.params.get("high_vol_taker_edge_add", 0.0))
        base_edge += edge_add
        taker_size_pct *= max(
            0.0,
            1.0 + vol_strength * (float(self.params.get("high_vol_taker_size_mult", 1.0)) - 1.0),
        )
        inv_shift = float(self.params.get("inventory_taker_edge_shift", 0.0))

        position = int(getattr(self, "_position_live", 0))
        limit = self._inventory_limit()
        inv_strength = min(1.0, abs(position) / limit)

        buy_edge = base_edge
        sell_edge = base_edge
        if inv_shift > 0.0 and inv_strength > 0.0:
            if position > 0:
                buy_edge += inv_shift * inv_strength
                sell_edge = max(0.5, sell_edge - inv_shift * inv_strength)
            elif position < 0:
                sell_edge += inv_shift * inv_strength
                buy_edge = max(0.5, buy_edge - inv_shift * inv_strength)

        trader_edge_per_unit = float(self.params.get("trader_taker_edge_per_unit", 0.0))
        if trader_edge_per_unit > 0.0:
            trader_effect = self._trader_signal_effect(
                signal,
                threshold_key="trader_taker_edge_threshold",
                use_sign_key="trader_taker_edge_use_sign",
            )
            if trader_effect != 0.0:
                trader_shift = abs(trader_effect) * trader_edge_per_unit
                if self._signal_conflicts_core(signal, dev):
                    trader_shift *= float(self.params.get("trader_taker_edge_conflict_mult", 1.0))
                if trader_effect > 0.0:
                    buy_edge = max(0.5, buy_edge - trader_shift)
                    sell_edge += trader_shift
                else:
                    sell_edge = max(0.5, sell_edge - trader_shift)
                    buy_edge += trader_shift

        buy_cap, sell_cap = self._apply_inventory_taker_block(position, buy_cap, sell_cap)
        buy_cap, sell_cap = self._apply_inventory_same_side_taker_kill(
            position,
            mid_s,
            fair_value,
            dev,
            buy_cap,
            sell_cap,
            memory=self._memory if hasattr(self, "_memory") else {},
        )

        orders: List[Order] = []
        buy_px: Set[int] = set()
        sell_px: Set[int] = set()

        for ask_p in sorted(order_depth.sell_orders):
            if ask_p > fair_value - buy_edge or buy_cap <= 0:
                break
            avail = -order_depth.sell_orders[ask_p]
            qty = min(avail, buy_cap, max(1, int(bid_size * taker_size_pct)))
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                buy_px.add(ask_p)
                buy_cap -= qty

        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            if bid_p < fair_value + sell_edge or sell_cap <= 0:
                break
            avail = order_depth.buy_orders[bid_p]
            qty = min(avail, sell_cap, max(1, int(ask_size * taker_size_pct)))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                sell_px.add(bid_p)
                sell_cap -= qty

        return orders, buy_cap, sell_cap, buy_px, sell_px

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, object],
    ) -> Tuple[List[Order], int]:
        mid = book.mid_price
        if mid is None:
            return [], 0

        mid_s, fair_value, dev = self._update_ar(float(mid), memory)
        sigma = self._update_volatility(float(mid), memory)
        high_vol_strength = self._update_high_vol_strength(sigma, memory)
        signal = self._update_m14(state, memory)
        self._position_live = position

        fair_value = self._apply_inventory_live_fair_shift(mid_s, fair_value, position, memory)
        memory["_fair_value"] = fair_value

        fair_shift = float(self.params.get("trader_fair_shift_per_unit", 0.0))
        if fair_shift:
            fair_effect = signal
            if self._signal_conflicts_core(signal, dev):
                fair_effect *= float(self.params.get("trader_fair_shift_conflict_mult", 1.0))
            fair_value += fair_shift * fair_effect
            memory["_fair_value"] = fair_value

        if book.best_bid is not None:
            memory["_prev_best_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_prev_best_ask"] = book.best_ask

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        base_bid_size, base_ask_size = self._passive_sizes(position)
        bid_size, ask_size = self._apply_trader_passive_skew(base_bid_size, base_ask_size, signal, dev)

        guard_ok = self._guard_allows_taker(float(mid), position, memory)
        if guard_ok:
            taker_orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px = self._ar_takers(
                book,
                order_depth,
                mid_s,
                fair_value,
                dev,
                signal,
                base_bid_size,
                base_ask_size,
                buy_cap,
                sell_cap,
            )
        else:
            taker_orders, taker_buy_px, taker_sell_px = [], set(), set()

        gap_orders, buy_cap, sell_cap, gap_bid, gap_ask = self._gap_exploit(
            order_depth,
            memory,
            base_bid_size,
            base_ask_size,
            buy_cap,
            sell_cap,
            taker_buy_px,
            taker_sell_px,
        )

        class _FakeBook:
            best_bid = gap_bid if gap_bid is not None else book.best_bid
            best_ask = gap_ask if gap_ask is not None else book.best_ask

        passive_orders = self._passive_quotes(
            _FakeBook(),
            bid_size,
            ask_size,
            buy_cap,
            sell_cap,
            position,
            dev,
        )
        passive_orders = self._apply_inventory_passive_repricing(
            passive_orders,
            position,
            best_bid=_FakeBook.best_bid,
            best_ask=_FakeBook.best_ask,
        )

        passive_gated = self._apply_m14_gate(
            passive_orders,
            1 if signal > 0 else (-1 if signal < 0 else 0),
            position,
        )
        all_orders = taker_orders + gap_orders + passive_gated

        taker_sold = sum(-order.quantity for order in taker_orders if order.quantity < 0)
        taker_bought = sum(order.quantity for order in taker_orders if order.quantity > 0)
        anchor_val = float(memory.get("_anchor_ema", memory.get("_fair_base", fair_value)))
        memory["_viz_position"] = float(position)
        memory["_viz_bid_size"] = float(bid_size)
        memory["_viz_ask_size"] = float(ask_size)
        memory["_viz_taker_sell"] = float(taker_sold)
        memory["_viz_taker_buy"] = float(taker_bought)
        memory["_viz_anchor"] = anchor_val

        extras = {
            "position": position,
            "Position": position,
            "mid": round(float(mid), 2),
            "fair_value": round(fair_value, 3),
            "FairValue": round(fair_value, 3),
            "Anchor": round(anchor_val, 3),
            "deviation": round(dev, 3),
            "DevSmooth": round(dev, 3),
            "ar_mom": round(float(memory.get("_ar_momentum", 0.0)), 4),
            "guard": int(guard_ok),
            "Guard": int(guard_ok),
            "m14_signal": round(signal, 3),
            "M14Signal": round(signal, 3),
            "taker_sell": taker_sold,
            "taker_buy": taker_bought,
            "bid_size": int(bid_size),
            "ask_size": int(ask_size),
            "sigma": round(sigma, 4),
            "HighVolStrength": round(high_vol_strength, 4),
        }
        if (fair_base := memory.get("_fair_base")) is not None:
            extras["FairBase"] = round(float(fair_base), 3)
        if (confidence := memory.get("_anchor_confidence")) is not None:
            extras["AnchorConfidence"] = round(float(confidence), 4)
        if (drift := memory.get("_anchor_drift_ewma")) is not None:
            extras["AnchorDriftEwma"] = round(float(drift), 4)
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=None,
            ask_price=None,
            extras=extras,
        )
        return all_orders, 0

    def feature_prices(self, memory: Dict[str, object]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_fair_value")) is not None:
            out["FairValue"] = float(v)
        if (v := memory.get("_dev_smooth")) is not None:
            out["DevSmooth"] = float(v)
        if (v := memory.get("_m14_signal")) is not None:
            out["M14Signal"] = float(v)
        if (v := memory.get("_anchor_ema")) is not None:
            out["Anchor"] = float(v)
        if (v := memory.get("_ar_momentum")) is not None:
            out["ar_mom"] = float(v)
        if (v := memory.get("_guard_on")) is not None:
            out["guard"] = float(v)
        if (v := memory.get("_viz_position")) is not None:
            out["Position"] = float(v)
        if (v := memory.get("_viz_bid_size")) is not None:
            out["bid_size"] = float(v)
        if (v := memory.get("_viz_ask_size")) is not None:
            out["ask_size"] = float(v)
        if (v := memory.get("_viz_taker_sell")) is not None:
            out["taker_sell"] = float(v)
        if (v := memory.get("_viz_taker_buy")) is not None:
            out["taker_buy"] = float(v)
        if (v := memory.get("_fair_base")) is not None:
            out["FairBase"] = float(v)
        if (v := memory.get("_anchor_confidence")) is not None:
            out["AnchorConfidence"] = float(v)
        if (v := memory.get("_anchor_drift_ewma")) is not None:
            out["AnchorDriftEwma"] = float(v)
        if (v := memory.get("_fair_defense_shift")) is not None:
            out["FairDefenseShift"] = float(v)
        if (v := memory.get("_taker_kill_on")) is not None:
            out["TakerKillOn"] = float(v)
        if (v := memory.get("_sigma_value")) is not None:
            out["sigma"] = float(v)
        if (v := memory.get("_high_vol_strength")) is not None:
            out["HighVolStrength"] = float(v)
        return out
