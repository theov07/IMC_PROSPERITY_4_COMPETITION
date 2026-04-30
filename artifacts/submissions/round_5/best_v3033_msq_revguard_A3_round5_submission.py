from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order
from datamodel import Order, OrderDepth, TradingState
from datamodel import Order, TradingState
from datamodel import OrderDepth
from typing import Any, Dict
from typing import Any, Dict, List, Tuple
from typing import List, Tuple
import json
import math
PriceLevel = Tuple[int, int]
@dataclass(frozen=True)
class BookSnapshot:
    symbol: str
    bid_levels: List[PriceLevel]
    ask_levels: List[PriceLevel]
    best_bid: int | None
    best_bid_volume: int
    best_ask: int | None
    best_ask_volume: int
    mid_price: float | None
    microprice: float | None
    spread: int | None
    imbalance: float | None
def _sorted_bid_levels(order_depth: OrderDepth) -> List[PriceLevel]:
    return sorted(order_depth.buy_orders.items(), key=lambda item: item[0], reverse=True)
def _sorted_ask_levels(order_depth: OrderDepth) -> List[PriceLevel]:
    return sorted(((price, -volume) for price, volume in order_depth.sell_orders.items()), key=lambda item: item[0])
def snapshot_from_order_depth(symbol: str, order_depth: OrderDepth) -> BookSnapshot:
    bid_levels = _sorted_bid_levels(order_depth)
    ask_levels = _sorted_ask_levels(order_depth)
    best_bid = bid_levels[0][0] if bid_levels else None
    best_bid_volume = bid_levels[0][1] if bid_levels else 0
    best_ask = ask_levels[0][0] if ask_levels else None
    best_ask_volume = ask_levels[0][1] if ask_levels else 0
    mid_price = None
    microprice = None
    spread = None
    imbalance = None
    if best_bid is not None and best_ask is not None:
        spread = best_ask - best_bid
        mid_price = (best_bid + best_ask) / 2.0
        total_top = best_bid_volume + best_ask_volume
        if total_top > 0:
            microprice = (
                best_bid * best_ask_volume + best_ask * best_bid_volume
            ) / total_top
            imbalance = (best_bid_volume - best_ask_volume) / total_top
    return BookSnapshot(
        symbol=symbol,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
        best_bid=best_bid,
        best_bid_volume=best_bid_volume,
        best_ask=best_ask,
        best_ask_volume=best_ask_volume,
        mid_price=mid_price,
        microprice=microprice,
        spread=spread,
        imbalance=imbalance,
    )
def load_state(raw_state: str) -> Dict[str, Any]:
    if not raw_state:
        return {}
    try:
        loaded = json.loads(raw_state)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}
def dump_state(state: Dict[str, Any]) -> str:
    return json.dumps(state, separators=(",", ":"))
class BaseStrategy(ABC):
    def __init__(self, product: str, params: Dict[str, Any]):
        self.product = product
        self.params = params
    def on_tick(
        self,
        state: TradingState,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        self._memory = memory  # available to all helper methods via self._memory
        order_depth = state.order_depths.get(self.product)
        if order_depth is None:
            return [], 0
        position = state.position.get(self.product, 0)
        book = snapshot_from_order_depth(self.product, order_depth)
        orders, conversions = self.compute_orders(
            state=state,
            book=book,
            order_depth=order_depth,
            position=position,
            memory=memory,
        )
        orders = self._apply_obi_size_tilt(state, position, orders, book, memory)
        orders = self._apply_vol_size_cut(state, position, orders, book, memory)
        orders = self._apply_cp_bias(state, position, orders, book, memory)
        orders = self._apply_xa(state, position, orders, book, memory)
        orders = self._apply_inventory_unwind(state, position, orders, book, memory)
        return orders, conversions
    def _apply_xa(self, state, position, orders, book, memory):
        p = self.params
        if not bool(p.get("cross_asset_enabled", False)) or not orders:
            return orders
        ss = p.get("cross_asset_source_symbol", "")
        st = p.get("cross_asset_source_trader", "")
        if not ss or not st:
            return orders
        ts = int(getattr(state, "timestamp", 0))
        buf = memory.setdefault("_xa_buf", [])
        for t in ((state.market_trades or {}).get(ss) or []):
            q = float(getattr(t, "quantity", 0))
            if q <= 0:
                continue
            if getattr(t, "buyer", "") == st:
                buf.append([ts, q])
            elif getattr(t, "seller", "") == st:
                buf.append([ts, -q])
        cut = ts - int(p.get("cross_asset_window_ts", 10000))
        while buf and buf[0][0] < cut:
            buf.pop(0)
        sig = float(p.get("cross_asset_weight", 0.0)) * sum(q for _, q in buf)
        if abs(sig) <= float(p.get("cross_asset_threshold", 5.0)):
            return orders
        mx = float(p.get("cross_asset_max_offset", 2.0))
        off = int(round(max(-mx, min(mx, sig * float(p.get("cross_asset_scale", 0.05))))))
        if off == 0:
            return orders
        bb, ba = book.best_bid, book.best_ask
        out = []
        for o in orders:
            np_ = int(o.price) + off
            if o.quantity > 0 and ba is not None and np_ >= ba:
                np_ = int(ba) - 1
            elif o.quantity < 0 and bb is not None and np_ <= bb:
                np_ = int(bb) + 1
            out.append(Order(o.symbol, np_, o.quantity))
        return out
    def _apply_vol_size_cut(self, state, position, orders, book, memory):
        p = self.params
        if not bool(p.get("vol_size_cut_enabled", False)) or not orders or book.mid_price is None:
            return orders
        buf = memory.setdefault("_vol_buf", [])
        buf.append(float(book.mid_price))
        max_n = int(p.get("vol_size_cut_window", 50))
        if len(buf) > max_n:
            del buf[: len(buf) - max_n]
        if len(buf) < 10:
            return orders
        rets = [(buf[i] - buf[i-1]) / max(buf[i-1], 1e-9) for i in range(1, len(buf))]
        mean = sum(rets) / len(rets)
        std = (sum((r - mean) ** 2 for r in rets) / len(rets)) ** 0.5
        if std <= float(p.get("vol_size_cut_threshold", 0.005)):
            return orders
        cut = float(p.get("vol_size_cut_factor", 0.5))
        return [Order(o.symbol, o.price, int(o.quantity * cut))
                for o in orders if int(o.quantity * cut) != 0]
    def _apply_inventory_unwind(self, state, position, orders, book, memory):
        p = self.params
        if not bool(p.get("inv_unwind_enabled", False)):
            return orders
        limit = self.position_limit()
        if limit <= 0:
            return orders
        if abs(position) < float(p.get("inv_unwind_threshold_pct", 0.8)) * limit:
            return orders
        excess = abs(position) - int(float(p.get("inv_unwind_target_pct", 0.5)) * limit)
        if excess <= 0:
            return orders
        mode = str(p.get("inv_unwind_mode", "taker")).lower()
        new_orders = list(orders)
        if mode in ("taker", "both"):
            delta = min(excess, int(p.get("inv_unwind_max_per_tick", 10)))
            if position > 0 and book.best_bid is not None:
                qty = -min(delta, int(book.best_bid_volume or 0))
                if qty < 0:
                    new_orders.append(Order(self.product, int(book.best_bid), qty))
            elif position < 0 and book.best_ask is not None:
                qty = min(delta, int(book.best_ask_volume or 0))
                if qty > 0:
                    new_orders.append(Order(self.product, int(book.best_ask), qty))
        if mode in ("passive", "both"):
            psize = min(int(p.get("inv_unwind_passive_size", 20)), excess)
            offset = int(p.get("inv_unwind_passive_offset", 0))
            if position > 0 and book.best_ask is not None:
                price = int(book.best_ask) + offset
                if book.best_bid is not None and price <= int(book.best_bid):
                    price = int(book.best_bid) + 1
                new_orders.append(Order(self.product, price, -psize))
            elif position < 0 and book.best_bid is not None:
                price = int(book.best_bid) - offset
                if book.best_ask is not None and price >= int(book.best_ask):
                    price = int(book.best_ask) - 1
                new_orders.append(Order(self.product, price, psize))
        return new_orders
    def _apply_cp_bias(self, state, position, orders, book, memory):
        p = self.params
        if not bool(p.get("counterparty_bias_enabled", False)):
            return orders
        if bool(p.get("_cp_bias_handled_internally", False)):
            return orders
        if not orders:
            return orders
        cp_signal = self._counterparty_signal(state, memory)
        cp_threshold = float(p.get("cp_signal_threshold", 5.0))
        if abs(cp_signal) <= cp_threshold:
            return orders
        cp_max = float(p.get("cp_max_anchor_offset", 3.0))
        cp_scale = float(p.get("cp_anchor_scale_per_unit", 0.10))
        cp_offset = int(round(max(-cp_max, min(cp_max, cp_signal * cp_scale))))
        if cp_offset == 0:
            return orders
        shifted = []
        bb, ba = book.best_bid, book.best_ask
        for o in orders:
            np_ = int(o.price) + cp_offset
            if o.quantity > 0 and ba is not None and np_ >= ba:
                np_ = int(ba) - 1
            elif o.quantity < 0 and bb is not None and np_ <= bb:
                np_ = int(bb) + 1
            shifted.append(Order(o.symbol, np_, o.quantity))
        return shifted
    @abstractmethod
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        ...
    def _microprice(self, book: "BookSnapshot") -> float:
        bid_total = sum(v for _, v in book.bid_levels)
        ask_total = sum(v for _, v in book.ask_levels)
        prev = self._memory.get("_microprice_last", 0.0)
        if bid_total == 0 or ask_total == 0:
            return float(prev)
        bid_vwap = sum(p * v for p, v in book.bid_levels) / bid_total
        ask_vwap = sum(p * v for p, v in book.ask_levels) / ask_total
        result = (bid_vwap * ask_total + ask_vwap * bid_total) / (bid_total + ask_total)
        self._memory["_microprice_last"] = result
        return result
    def _smooth_mid(self, mid: float, memory: Dict[str, Any]) -> float:
        window = int(self.params.get("mid_smooth_window", 20))
        if window <= 0:
            return mid
        half_life = float(self.params.get("mid_smooth_half_life", window / 2.0))
        buf = memory.setdefault("mid_smooth_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < 2:
            return mid
        alpha = 1.0 - 2.0 ** (-1.0 / half_life) if half_life > 0 else 1.0
        smoothed = buf[0]
        for p in buf[1:]:
            smoothed = alpha * p + (1.0 - alpha) * smoothed
        memory["mid_smoothed"] = smoothed
        return smoothed
    def _update_volatility(self, mid: float, memory: Dict[str, Any]) -> float:
        window = int(self.params.get("sigma_window", 50))
        prices = memory.setdefault("mid_history", [])
        prices.append(mid)
        if len(prices) > window + 1:
            prices[:] = prices[-(window + 1):]
        if len(prices) < 3:
            return float(self.params.get("sigma_default", 1.0))
        returns = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        n = len(returns)
        mean_r = sum(returns) / n
        var = sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1)
        sigma_raw = math.sqrt(var) if var > 0 else float(self.params.get("sigma_default", 1.0))
        half_life = float(self.params.get("sigma_half_life", 60))
        alpha = 2.0 / (half_life + 1.0)
        sigma_prev = memory.get("sigma_smoothed", sigma_raw)
        sigma_smoothed = alpha * sigma_raw + (1.0 - alpha) * sigma_prev
        memory["sigma_smoothed"] = sigma_smoothed
        return max(sigma_smoothed, float(self.params.get("sigma_floor", 0.5)))
    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        return {}
    def runtime_trace_enabled(self) -> bool:
        enabled = self.params.get("runtime_trace_enabled")
        if enabled is not None:
            return bool(enabled)
        return not bool(False)
    def log_quote_snapshot(
        self,
        *,
        state: TradingState,
        memory: Dict[str, Any],
        bid_price: int | float | None,
        ask_price: int | float | None,
        extras: Dict[str, Any] | None = None,
    ) -> None:
        if not self.params.get("quote_trace_enabled", False) or not self.runtime_trace_enabled():
            return
        row: Dict[str, Any] = {
            "timestamp": int(state.timestamp),
            "bid_price": bid_price,
            "ask_price": ask_price,
        }
        if extras:
            row.update(extras)
        columns = memory.setdefault("_quote_trace_columns", list(row.keys()))
        for key in row.keys():
            if key not in columns:
                columns.append(key)
        rows = memory.setdefault("_quote_trace_rows", [])
        rows.append(row)
        flush_ts = int(self.params.get("log_flush_ts", 10000))
        last_tick_ts = self.params.get("last_ts_value")
        if last_tick_ts is None:
            last_tick_ts = int(self.params.get("total_ticks", 200000)) - 100
        else:
            last_tick_ts = int(last_tick_ts)
        end_of_sim = int(state.timestamp) >= last_tick_ts
        checkpoint = flush_ts > 0 and (int(state.timestamp) % flush_ts) == (flush_ts - 100)
        if not (end_of_sim or checkpoint):
            return
        print(json.dumps({
            "product": self.product,
            "trace": "quote_trace",
            "chunk_end": int(state.timestamp),
            "columns": columns,
            "log": [[row.get(column) for column in columns] for row in rows],
        }))
        memory["_quote_trace_rows"] = []
    def log_taker_fill(
        self,
        *,
        state: TradingState,
        memory: Dict[str, Any],
        side: str,
        price: int,
        quantity: int,
        gap_exploit: bool = False,
    ) -> None:
        if not self.runtime_trace_enabled():
            return
        taker_log = memory.setdefault("_taker_log", [])
        entry = [int(state.timestamp), side, price, quantity]
        if gap_exploit:
            entry.append(1)
        taker_log.append(entry)
        flush_ts = int(self.params.get("log_flush_ts", 10000))
        ts_increment = int(self.params.get("ts_increment", 100))
        last_ts = int(self.params.get("last_ts_value", 199900))
        second_to_last = last_ts - ts_increment
        is_quote_flush = flush_ts > 0 and (int(state.timestamp) % flush_ts) == (flush_ts - 100)
        deferred = memory.get("_taker_flush_deferred", False)
        if len(taker_log) >= 20 and is_quote_flush and not deferred:
            memory["_taker_flush_deferred"] = True
            return
        should_flush = (
            deferred
            or int(state.timestamp) >= second_to_last
            or (len(taker_log) >= 20 and not is_quote_flush)
        )
        if not should_flush:
            return
        print(json.dumps({
            "product": self.product,
            "trace": "taker_fills",
            "chunk_end": int(state.timestamp),
            "log": taker_log,
        }))
        memory["_taker_log"] = []
        memory["_taker_flush_deferred"] = False
    def position_limit(self) -> int:
        return self.params.get("position_limit", 20)
    def buy_capacity(self, position: int) -> int:
        return max(0, self.position_limit() - position)
    def sell_capacity(self, position: int) -> int:
        return max(0, self.position_limit() + position)
    def _apply_obi_size_tilt(self, state, position, orders, book, memory):
        p = self.params
        if not bool(p.get("obi_size_enabled", False)):
            return orders
        levels = int(p.get("obi_size_levels", 3))
        bid_total = sum(v for _, v in (book.bid_levels or [])[:levels])
        ask_total = sum(v for _, v in (book.ask_levels or [])[:levels])
        total = bid_total + ask_total
        if total == 0:
            return orders
        obi = (bid_total - ask_total) / total
        if abs(obi) < float(p.get("obi_size_threshold", 0.005)):
            return orders
        boost = float(p.get("obi_size_boost_factor", 1.5))
        reduce = float(p.get("obi_size_reduce_factor", 0.7))
        bullish = obi > 0
        adjusted = []
        for o in orders:
            if o.quantity > 0:
                factor = boost if bullish else reduce
            elif o.quantity < 0:
                factor = reduce if bullish else boost
            else:
                adjusted.append(o); continue
            new_qty = int(o.quantity * factor)
            if new_qty > 0:
                new_qty = min(new_qty, max(0, self.position_limit() - position))
            elif new_qty < 0:
                new_qty = max(new_qty, -max(0, self.position_limit() + position))
            if new_qty != 0:
                adjusted.append(Order(o.symbol, o.price, new_qty))
        return adjusted
    def _counterparty_signal(
        self,
        state: TradingState,
        memory: Dict[str, Any],
    ) -> float:
        window_ts = int(self.params.get("cp_window_ts", 10000))
        weights = self.params.get("cp_trader_weights", {
            "Mark 55": +1.0, "Mark 67": +1.0,
            "Mark 01": -1.0, "Mark 14": -1.0,
        })
        cond_traders = set(self.params.get("cp_conditional_traders", []) or [])
        cond_zthresh = float(self.params.get("cp_conditional_zthresh", 2.0))
        cond_stats_ts = int(self.params.get("cp_conditional_stats_window_ts", 50000))
        cond_min_samples = int(self.params.get("cp_conditional_min_samples", 50))
        cond_baseline = float(self.params.get("cp_conditional_baseline_weight", 0.0))
        ts_now = int(getattr(state, "timestamp", 0))
        buf = memory.setdefault("_cp_buf", [])  # list of [ts, trader, signed_qty]
        try:
            mt = state.market_trades
            trades = (mt or {}).get(self.product, []) or []
        except Exception:
            trades = []
        for t in trades:
            buyer = getattr(t, "buyer", None) or ""
            seller = getattr(t, "seller", None) or ""
            qty = float(getattr(t, "quantity", 0))
            if qty <= 0:
                continue
            if buyer:
                buf.append([ts_now, buyer, qty])
            if seller:
                buf.append([ts_now, seller, -qty])
        cutoff = ts_now - window_ts
        if buf and buf[0][0] < cutoff:
            i = 0
            while i < len(buf) and buf[i][0] < cutoff:
                i += 1
            del buf[:i]
        per_trader = {}
        for _, trader, signed in buf:
            per_trader[trader] = per_trader.get(trader, 0.0) + signed
        gates = {}  # trader -> effective weight multiplier (1.0 = full, baseline/w otherwise)
        if cond_traders:
            stats_buf = memory.setdefault("_cp_stats_buf", {})
            cond_cut = ts_now - cond_stats_ts
            for trader in cond_traders:
                cur_abs = abs(per_trader.get(trader, 0.0))
                hist = stats_buf.setdefault(trader, [])
                hist.append([ts_now, cur_abs])
                while hist and hist[0][0] < cond_cut:
                    hist.pop(0)
                if len(hist) < cond_min_samples:
                    gates[trader] = 1.0  # not enough data → behave as v5 (always-on)
                    continue
                vols = [s[1] for s in hist]
                n = len(vols)
                mean = sum(vols) / n
                var = sum((v - mean) ** 2 for v in vols) / n
                std = math.sqrt(var) if var > 0 else 0.0
                z = (cur_abs - mean) / std if std > 0 else (cond_zthresh + 1 if cur_abs > 0 else 0.0)
                gates[trader] = 1.0 if z >= cond_zthresh else 0.0
        signal = 0.0
        for trader, net in per_trader.items():
            w = weights.get(trader, 0.0)
            if trader in cond_traders:
                g = gates.get(trader, 1.0)
                w = g * w + (1.0 - g) * cond_baseline
            signal += w * net
        memory["_cp_signal"] = signal
        memory["_cp_per_trader"] = per_trader
        if cond_traders:
            memory["_cp_gates"] = gates
        return signal
class AR1MeanRevV1(BaseStrategy):
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        p = self.params
        limit = int(p.get("position_limit", 10))
        entry_thresh = float(p.get("entry_threshold", 20.0))
        taker_size = int(p.get("taker_size", 10))
        exit_ticks = int(p.get("exit_ticks", 0))    # 0 = hold until reverse signal
        passive_size = int(p.get("passive_size", 0))  # optional passive MM alongside
        mid = book.mid_price
        if mid is None:
            return [], 0
        prev_mid = memory.get("prev_mid")
        memory["prev_mid"] = mid
        if prev_mid is None:
            return [], 0
        ret = mid - prev_mid  # this tick's return
        orders: List[Order] = []
        bb = book.best_bid
        ba = book.best_ask
        buy_room = limit - position
        sell_room = limit + position
        if ret >= entry_thresh and sell_room > 0 and bb is not None:
            qty = min(taker_size, sell_room)
            orders.append(Order(self.product, bb, -qty))
            sell_room -= qty
        elif ret <= -entry_thresh and buy_room > 0 and ba is not None:
            qty = min(taker_size, buy_room)
            orders.append(Order(self.product, ba, qty))
            buy_room -= qty
        if exit_ticks > 0:
            ticks_held = memory.get("ticks_held", 0)
            if position != 0:
                ticks_held += 1
                if ticks_held >= exit_ticks:
                    if position > 0 and bb is not None and sell_room > 0:
                        orders.append(Order(self.product, bb, -min(position, sell_room)))
                    elif position < 0 and ba is not None and buy_room > 0:
                        orders.append(Order(self.product, ba, min(-position, buy_room)))
                    ticks_held = 0
            else:
                ticks_held = 0
            memory["ticks_held"] = ticks_held
        if passive_size > 0:
            passive_half = float(p.get("passive_half_spread", 4.0))
            if buy_room > 0 and bb is not None:
                orders.append(Order(self.product, bb + 1, min(passive_size, buy_room)))
            if sell_room > 0 and ba is not None:
                orders.append(Order(self.product, ba - 1, -min(passive_size, sell_room)))
        return orders, 0
class CointMMV1(BaseStrategy):
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        p = self.params
        partner = str(p["partner_product"])
        mean_hl = float(p.get("mean_half_life", 5000))
        z_win = int(p.get("z_window", 1000))
        entry_z = float(p.get("entry_z", 1.5))
        exit_z = float(p.get("exit_z", 0.0))
        taker_size = int(p.get("taker_size", 10))
        limit = int(p.get("position_limit", 10))
        passive_size = int(p.get("passive_size", 3))
        tighten = int(p.get("tighten_ticks", 1))
        mid_A = book.mid_price
        if mid_A is None:
            return [], 0
        pod = state.order_depths.get(partner)
        if pod is None:
            return [], 0
        pb = list(pod.buy_orders.keys())
        pa = list(pod.sell_orders.keys())
        if not pb or not pa:
            return [], 0
        mid_B = (max(pb) + min(pa)) / 2.0
        bb = book.best_bid
        ba = book.best_ask
        alpha_m = 1.0 - math.exp(-1.0 / mean_hl)
        mean_A = memory.get("mean_A", mid_A)
        mean_B = memory.get("mean_B", mid_B)
        mean_A = alpha_m * mid_A + (1 - alpha_m) * mean_A
        mean_B = alpha_m * mid_B + (1 - alpha_m) * mean_B
        memory["mean_A"] = mean_A
        memory["mean_B"] = mean_B
        if mean_A == 0 or mean_B == 0:
            return [], 0
        spread = mid_A / mean_A - mid_B / mean_B
        alpha_z = 2.0 / (z_win + 1)
        n_ticks = memory.get("n_ticks", 0) + 1
        memory["n_ticks"] = n_ticks
        mu_z = memory.get("mu_z", spread)
        var_z = memory.get("var_z", 1e-6)
        delta = spread - mu_z
        mu_z = mu_z + alpha_z * delta
        var_z = (1.0 - alpha_z) * (var_z + alpha_z * delta * delta)
        memory["mu_z"] = mu_z
        memory["var_z"] = var_z
        orders: List[Order] = []
        buy_room = limit - position
        sell_room = limit + position
        if n_ticks >= z_win // 2:
            sd_z = math.sqrt(var_z) if var_z > 0 else 1e-9
            z = (spread - mu_z) / sd_z
            memory["last_z"] = z
            bid_A = bb if bb is not None else int(mid_A - 4)
            ask_A = ba if ba is not None else int(mid_A + 4)
            if position < 0 and z < exit_z and buy_room > 0:
                qty = min(-position, buy_room)
                orders.append(Order(self.product, int(ask_A), qty))
                buy_room -= qty
            elif position > 0 and z > -exit_z and sell_room > 0:
                qty = min(position, sell_room)
                orders.append(Order(self.product, int(bid_A), -qty))
                sell_room -= qty
            if position == 0:
                if z > entry_z and sell_room > 0:
                    qty = min(taker_size, sell_room)
                    orders.append(Order(self.product, int(bid_A), -qty))
                    sell_room -= qty
                elif z < -entry_z and buy_room > 0:
                    qty = min(taker_size, buy_room)
                    orders.append(Order(self.product, int(ask_A), qty))
                    buy_room -= qty
        if passive_size > 0 and bb is not None and ba is not None:
            bid_px = bb + tighten
            ask_px = ba - tighten
            if bid_px < ask_px:
                if buy_room > 0:
                    orders.append(Order(self.product, int(bid_px), min(passive_size, buy_room)))
                if sell_room > 0:
                    orders.append(Order(self.product, int(ask_px), -min(passive_size, sell_room)))
        return orders, 0
class CrossGroupTrendA2(BaseStrategy):
    def _group_mid(self, state: TradingState, products: List[str]) -> float | None:
        mids = []
        for sym in products:
            od = state.order_depths.get(sym)
            if od is None:
                continue
            bids = list(od.buy_orders.keys())
            asks = list(od.sell_orders.keys())
            if bids and asks:
                mids.append((max(bids) + min(asks)) / 2.0)
        return sum(mids) / len(mids) if mids else None
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        p = self.params
        signal_products = list(p["signal_products"])
        signal2_products = list(p.get("signal2_products", []))
        sp_ema_hl = float(p.get("signal_ema_hl", 100))
        sp_thr = float(p.get("signal_threshold", 150))
        sp2_thr = float(p.get("signal2_threshold", 0))
        sp_exit = float(p.get("signal_exit", sp_thr / 3))
        taker_size = int(p.get("taker_size", 10))
        passive_size = int(p.get("passive_size", 3))
        limit = int(p.get("position_limit", 10))
        mid = book.mid_price
        bb = book.best_bid
        ba = book.best_ask
        if mid is None or bb is None or ba is None:
            return [], 0
        sp_avg = self._group_mid(state, signal_products)
        if sp_avg is None:
            return [], 0
        if "sp_start" not in memory:
            memory["sp_start"] = sp_avg
        sp_dev = sp_avg - memory["sp_start"]
        alpha = 1.0 - math.exp(-1.0 / sp_ema_hl)
        sp_ema = memory.get("sp_ema", 0.0)
        sp_ema = alpha * sp_dev + (1.0 - alpha) * sp_ema
        memory["sp_ema"] = sp_ema
        rb_ema = None
        if signal2_products and sp2_thr > 0:
            rb_avg = self._group_mid(state, signal2_products)
            if rb_avg is not None:
                if "rb_start" not in memory:
                    memory["rb_start"] = rb_avg
                rb_dev = rb_avg - memory["rb_start"]
                rb_ema_v = memory.get("rb_ema", 0.0)
                rb_ema_v = alpha * rb_dev + (1.0 - alpha) * rb_ema_v
                memory["rb_ema"] = rb_ema_v
                rb_ema = rb_ema_v
        sp2_bull = rb_ema is None or rb_ema < -sp2_thr
        sp2_bear = rb_ema is None or rb_ema > sp2_thr
        is_bull = sp_ema > sp_thr and sp2_bull
        is_bear = sp_ema < -sp_thr and sp2_bear
        is_exit_bull = sp_ema < sp_exit
        is_exit_bear = sp_ema > -sp_exit
        if bool(p.get("invert_signal", False)):
            is_bull, is_bear = is_bear, is_bull
            is_exit_bull, is_exit_bear = is_exit_bear, is_exit_bull
        buy_room = limit - position
        sell_room = limit + position
        orders: List[Order] = []
        if position == 0:
            if is_bull and buy_room > 0:
                qty = min(taker_size, buy_room)
                orders.append(Order(self.product, int(ba), qty))
                buy_room -= qty
            elif is_bear and sell_room > 0:
                qty = min(taker_size, sell_room)
                orders.append(Order(self.product, int(bb), -qty))
                sell_room -= qty
        elif position > 0 and is_exit_bull:
            qty = min(position, sell_room)
            orders.append(Order(self.product, int(bb), -qty))
            sell_room -= qty
            position -= qty  # update for passive logic below
        elif position < 0 and is_exit_bear:
            qty = min(-position, buy_room)
            orders.append(Order(self.product, int(ba), qty))
            buy_room -= qty
            position += qty
        if passive_size > 0 and bb is not None and ba is not None:
            bid_px = bb + 1
            ask_px = ba - 1
            if bid_px < ask_px:
                if is_bull or (not is_bear):
                    if buy_room > 0:
                        orders.append(Order(self.product, int(bid_px), min(passive_size, buy_room)))
                if is_bear or (not is_bull):
                    if sell_room > 0:
                        orders.append(Order(self.product, int(ask_px), -min(passive_size, sell_room)))
        return orders, 0
class InventoryCarryMMStrategy(BaseStrategy):
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
        size = int(self.params.get("maker_size", 5))
        tighten = int(self.params.get("tighten_ticks", 1))
        trend_hl = int(self.params.get("trend_hl", 200))
        carry_min_pos = int(self.params.get("carry_pause_min_pos", 3))
        hard_pause = int(self.params.get("hard_pause_at", 9))
        carry_trend_min = float(self.params.get("carry_trend_min_abs", 0.0))
        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask
        mid = (book.best_bid + book.best_ask) / 2.0
        alpha = 2.0 / (trend_hl + 1.0)
        ema_mid = memory.get("_ema_mid", mid)
        ema_mid = alpha * mid + (1 - alpha) * ema_mid
        memory["_ema_mid"] = ema_mid
        trend = mid - ema_mid
        memory["_trend"] = trend
        post_bid = position < hard_pause
        post_ask = position > -hard_pause
        if abs(position) >= carry_min_pos:
            if position > 0 and trend < -carry_trend_min:
                post_bid = False  # don't add to long when trending down
            elif position < 0 and trend > carry_trend_min:
                post_ask = False  # don't add to short when trending up
        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(size, sell_cap)))
        return orders, 0
    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out = {}
        if "_trend" in memory:
            out["trend"] = round(memory["_trend"], 2)
        return out
class NaiveTightMarketMakerStrategy(BaseStrategy):
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []
        maker_size = int(self.params.get("maker_size", 10))
        tighten_ticks = int(self.params.get("tighten_ticks", 1))
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        bid_price = None
        ask_price = None
        if book.best_bid is not None:
            bid_price = book.best_bid
        if book.best_ask is not None:
            ask_price = book.best_ask
        if book.best_bid is not None and book.best_ask is not None:
            spread = book.best_ask - book.best_bid
            if spread >= 2:
                bid_price = min(book.best_bid + tighten_ticks, book.best_ask - 0.1)
                ask_price = max(book.best_ask - tighten_ticks, book.best_bid + 0.1)
        if bid_price is not None and buy_cap > 0:
            orders.append(Order(self.product, bid_price, min(maker_size, buy_cap)))
        if ask_price is not None and sell_cap > 0:
            orders.append(Order(self.product, ask_price, -min(maker_size, sell_cap)))
        memory["last_bid_price"] = bid_price
        memory["last_ask_price"] = ask_price
        memory["last_spread"] = book.spread
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_price,
            ask_price=ask_price,
        )
        return orders, 0
class OpportunisticTakerMMStrategy(BaseStrategy):
    def _clamp(self, value: float, limit: float) -> float:
        return max(-limit, min(limit, value))
    def _online_z(self, value: float, key: str, memory: Dict[str, Any], window: int) -> float:
        buf = memory.setdefault(key, [])
        buf.append(value)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(30, window // 8):
            return 0.0
        n = len(buf)
        mu = sum(buf) / n
        var = sum((x - mu) ** 2 for x in buf) / max(n - 1, 1)
        std = math.sqrt(var)
        if std < 1e-9:
            return 0.0
        return (value - mu) / std
    def _trend(self, mid: float, memory: Dict[str, Any], key: str, half_life: int) -> float:
        alpha = 2.0 / (half_life + 1.0)
        ema = memory.get(key, mid)
        ema = alpha * mid + (1.0 - alpha) * ema
        memory[key] = ema
        return mid - ema
    def _coint_signal(
        self,
        *,
        state: TradingState,
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> Tuple[float, int]:
        p = self.params
        partner = str(p["partner_product"])
        mean_hl = float(p.get("mean_half_life", 5000))
        z_win = int(p.get("z_window", 1000))
        pod = state.order_depths.get(partner)
        if pod is None or not pod.buy_orders or not pod.sell_orders or book.mid_price is None:
            return 0.0, 0
        mid_a = float(book.mid_price)
        mid_b = (max(pod.buy_orders) + min(pod.sell_orders)) / 2.0
        alpha_m = 1.0 - math.exp(-1.0 / mean_hl)
        mean_a = memory.get("_coint_mean_a", mid_a)
        mean_b = memory.get("_coint_mean_b", mid_b)
        mean_a = alpha_m * mid_a + (1.0 - alpha_m) * mean_a
        mean_b = alpha_m * mid_b + (1.0 - alpha_m) * mean_b
        memory["_coint_mean_a"] = mean_a
        memory["_coint_mean_b"] = mean_b
        if mean_a == 0 or mean_b == 0:
            return 0.0, 0
        spread = mid_a / mean_a - mid_b / mean_b
        alpha_z = 2.0 / (z_win + 1)
        n_ticks = int(memory.get("_coint_ticks", 0)) + 1
        memory["_coint_ticks"] = n_ticks
        mu_z = memory.get("_coint_mu", spread)
        var_z = memory.get("_coint_var", 1e-6)
        delta = spread - mu_z
        mu_z = mu_z + alpha_z * delta
        var_z = (1.0 - alpha_z) * (var_z + alpha_z * delta * delta)
        memory["_coint_mu"] = mu_z
        memory["_coint_var"] = var_z
        if n_ticks < z_win // 2:
            return 0.0, n_ticks
        sd_z = math.sqrt(var_z) if var_z > 0 else 1e-9
        if sd_z < 1e-9:
            return 0.0, n_ticks
        return (spread - mu_z) / sd_z, n_ticks
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None or book.mid_price is None:
            return [], 0
        p = self.params
        mode = str(p.get("mode", "naive"))
        maker_size = int(p.get("maker_size", 5))
        passive_size = int(p.get("passive_size", maker_size))
        tighten = int(p.get("tighten_ticks", 1))
        hard_pause = int(p.get("hard_pause_at", 9))
        limit = self.position_limit()
        opportunity_size = int(p.get("opportunity_taker_size", 0))
        opportunity_edge = float(p.get("taker_threshold", 1.5))
        opportunity_gate = float(p.get("min_opportunity_ticks", 0.75))
        taker_pos_cap = int(p.get("taker_position_cap", max(limit - 1, 1)))
        taker_cooldown = int(p.get("taker_cooldown_ts", 0))
        min_spread = int(p.get("min_spread_for_taker", 1))
        unwind_min_pos = int(p.get("unwind_min_pos", limit + 1))
        unwind_size = int(p.get("unwind_size", maker_size))
        unwind_edge = float(p.get("unwind_edge", 1.0))
        signal_shift_per_unit = float(p.get("signal_shift_per_unit", 0.0))
        signal_shift_clamp = float(p.get("signal_shift_clamp", 3.0))
        microprice_weight = float(p.get("microprice_weight", 0.0))
        microprice_clamp = float(p.get("microprice_clamp", 2.0))
        trend_weight = float(p.get("trend_weight", 0.0))
        trend_clamp = float(p.get("trend_clamp", 2.0))
        trend_hl = int(p.get("trend_hl", 120))
        inv_skew_thresh = int(p.get("inv_skew_thresh", limit + 1))
        inv_skew_ticks = int(p.get("inv_skew_ticks", 0))
        size_inv_factor = float(p.get("size_inv_factor", 0.0))
        carry_min_pos = int(p.get("carry_pause_min_pos", 3))
        mid = float(book.mid_price)
        spread = int(book.best_ask - book.best_bid)
        micro = book.microprice if book.microprice is not None else mid
        micro_ticks = self._clamp((micro - mid) * microprice_weight, microprice_clamp)
        trend = self._trend(mid, memory, "_ema_mid", trend_hl)
        trend_ticks = self._clamp(trend * trend_weight, trend_clamp)
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask
        post_bid = position < hard_pause
        post_ask = position > -hard_pause
        signal_value = 0.0
        signal_ticks = 0.0
        coint_z = 0.0
        pair_z = 0.0
        if mode == "pair":
            partner = p.get("partner")
            partner_sign = float(p.get("partner_sign", -1.0))
            pair_thresh = float(p.get("pair_thresh", 1.5))
            z_window = int(p.get("z_window", 300))
            self_z = self._online_z(mid, "_pair_self_z", memory, z_window)
            partner_mid = None
            if partner in state.order_depths:
                pdepth = state.order_depths[partner]
                if pdepth.buy_orders and pdepth.sell_orders:
                    partner_mid = (max(pdepth.buy_orders) + min(pdepth.sell_orders)) / 2.0
            if partner_mid is not None:
                partner_z = self._online_z(partner_mid, "_pair_partner_z", memory, z_window)
                pair_z = self_z - partner_sign * partner_z
                signal_value = pair_z
                signal_ticks = self._clamp(-pair_z * signal_shift_per_unit, signal_shift_clamp)
            if pair_z > pair_thresh:
                post_bid = False
            elif pair_z < -pair_thresh:
                post_ask = False
        elif mode == "carry":
            signal_value = trend
            signal_ticks = self._clamp(-trend * signal_shift_per_unit, signal_shift_clamp)
            if abs(position) >= carry_min_pos:
                if position > 0 and trend < 0:
                    post_bid = False
                elif position < 0 and trend > 0:
                    post_ask = False
        elif mode == "coint":
            coint_z, _ = self._coint_signal(state=state, book=book, memory=memory)
            signal_value = coint_z
            signal_ticks = self._clamp(-coint_z * signal_shift_per_unit, signal_shift_clamp)
        else:
            signal_value = micro - mid
            signal_ticks = 0.0
        fair_anchor = mid + signal_ticks + micro_ticks + trend_ticks
        opportunity_score = max(abs(signal_ticks), abs(micro_ticks), abs(trend_ticks))
        memory["_fair_anchor"] = fair_anchor
        memory["_trend"] = trend
        memory["_pair_z"] = pair_z
        memory["_coint_z"] = coint_z
        bid_shift = 0
        ask_shift = 0
        if abs(position) >= inv_skew_thresh and inv_skew_ticks > 0:
            if position > 0:
                bid_shift -= inv_skew_ticks
                ask_shift -= inv_skew_ticks
            else:
                bid_shift += inv_skew_ticks
                ask_shift += inv_skew_ticks
        bid_p += bid_shift
        ask_p += ask_shift
        if bid_p >= ask_p:
            bid_p = min(bid_p, book.best_ask - 1)
            ask_p = max(ask_p, book.best_bid + 1)
            if bid_p >= ask_p:
                bid_p = book.best_bid
                ask_p = book.best_ask
        orders: List[Order] = []
        buy_room = self.buy_capacity(position)
        sell_room = self.sell_capacity(position)
        if mode == "coint":
            entry_z = float(p.get("entry_z", 1.5))
            exit_z = float(p.get("exit_z", 0.0))
            entry_size = int(p.get("taker_size", opportunity_size))
            if position < 0 and coint_z < exit_z and buy_room > 0:
                qty = min(-position, buy_room, max(book.best_ask_volume, 1))
                if qty > 0:
                    orders.append(Order(self.product, int(book.best_ask), qty))
                    buy_room -= qty
            elif position > 0 and coint_z > -exit_z and sell_room > 0:
                qty = min(position, sell_room, max(book.best_bid_volume, 1))
                if qty > 0:
                    orders.append(Order(self.product, int(book.best_bid), -qty))
                    sell_room -= qty
            if position == 0:
                if coint_z > entry_z and sell_room > 0:
                    qty = min(entry_size, sell_room, max(book.best_bid_volume, 1))
                    if qty > 0:
                        orders.append(Order(self.product, int(book.best_bid), -qty))
                        sell_room -= qty
                elif coint_z < -entry_z and buy_room > 0:
                    qty = min(entry_size, buy_room, max(book.best_ask_volume, 1))
                    if qty > 0:
                        orders.append(Order(self.product, int(book.best_ask), qty))
                        buy_room -= qty
        last_taker_ts = int(memory.get("_last_taker_ts", -10**9))
        can_taker = (
            opportunity_size > 0
            and spread >= min_spread
            and opportunity_score >= opportunity_gate
            and int(state.timestamp) - last_taker_ts >= taker_cooldown
        )
        did_taker = False
        if can_taker:
            if (
                book.best_ask <= fair_anchor - opportunity_edge
                and buy_room > 0
                and position < taker_pos_cap
            ):
                qty = min(opportunity_size, buy_room, max(book.best_ask_volume, 1), taker_pos_cap - position)
                if qty > 0:
                    orders.append(Order(self.product, int(book.best_ask), qty))
                    buy_room -= qty
                    memory["_last_taker_ts"] = int(state.timestamp)
                    did_taker = True
            elif (
                book.best_bid >= fair_anchor + opportunity_edge
                and sell_room > 0
                and position > -taker_pos_cap
            ):
                qty = min(opportunity_size, sell_room, max(book.best_bid_volume, 1), taker_pos_cap + position)
                if qty > 0:
                    orders.append(Order(self.product, int(book.best_bid), -qty))
                    sell_room -= qty
                    memory["_last_taker_ts"] = int(state.timestamp)
                    did_taker = True
        if not did_taker and abs(position) >= unwind_min_pos:
            if position > 0 and sell_room > 0 and book.best_bid >= fair_anchor + unwind_edge:
                qty = min(unwind_size, sell_room, position, max(book.best_bid_volume, 1))
                if qty > 0:
                    orders.append(Order(self.product, int(book.best_bid), -qty))
                    sell_room -= qty
            elif position < 0 and buy_room > 0 and book.best_ask <= fair_anchor - unwind_edge:
                qty = min(unwind_size, buy_room, -position, max(book.best_ask_volume, 1))
                if qty > 0:
                    orders.append(Order(self.product, int(book.best_ask), qty))
                    buy_room -= qty
        if limit > 0 and size_inv_factor > 0.0:
            bid_size = max(1, int(round(passive_size * (1.0 - size_inv_factor * max(position, 0) / limit))))
            ask_size = max(1, int(round(passive_size * (1.0 - size_inv_factor * max(-position, 0) / limit))))
        else:
            bid_size = passive_size
            ask_size = passive_size
        if post_bid and buy_room > 0:
            orders.append(Order(self.product, int(bid_p), min(bid_size, buy_room)))
        if post_ask and sell_room > 0:
            orders.append(Order(self.product, int(ask_p), -min(ask_size, sell_room)))
        return orders, 0
    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if "_fair_anchor" in memory:
            out["fair"] = round(memory["_fair_anchor"], 2)
        if "_pair_z" in memory:
            out["pair_z"] = round(memory["_pair_z"], 3)
        if "_coint_z" in memory:
            out["coint_z"] = round(memory["_coint_z"], 3)
        if "_trend" in memory:
            out["trend"] = round(memory["_trend"], 2)
        return out
class PairSkipMMStrategy(BaseStrategy):
    def _online_z(self, value: float, key_prefix: str, memory: Dict[str, Any], window: int) -> float:
        buf = memory.setdefault(key_prefix, [])
        buf.append(value)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < 30:
            return 0.0
        n = len(buf)
        mu = sum(buf) / n
        var = sum((x - mu) ** 2 for x in buf) / max(n - 1, 1)
        std = math.sqrt(var)
        if std < 1e-9:
            return 0.0
        return (value - mu) / std
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
        size = int(self.params.get("maker_size", 5))
        tighten = int(self.params.get("tighten_ticks", 1))
        pair_thresh = float(self.params.get("pair_thresh", 1.5))
        partner = self.params.get("partner")
        partner_sign = float(self.params.get("partner_sign", -1.0))  # -1 = inverse
        hard_pause = int(self.params.get("hard_pause_at", 9))
        z_window = int(self.params.get("z_window", 300))
        skip_size = int(self.params.get("skip_size", 0))
        spread = book.best_ask - book.best_bid
        bid_p = book.best_bid + tighten if spread >= 2 else book.best_bid
        ask_p = book.best_ask - tighten if spread >= 2 else book.best_ask
        post_bid = position < hard_pause
        post_ask = position > -hard_pause
        pair_z = 0.0
        if partner is not None:
            mid = (book.best_bid + book.best_ask) / 2.0
            partner_mid = None
            if partner in state.order_depths:
                pdepth = state.order_depths[partner]
                if pdepth.buy_orders and pdepth.sell_orders:
                    pbb = max(pdepth.buy_orders.keys())
                    pba = min(pdepth.sell_orders.keys())
                    partner_mid = (pbb + pba) / 2.0
            zp = self._online_z(mid, "_z_self", memory, z_window)
            if partner_mid is not None:
                zq = self._online_z(partner_mid, "_z_partner", memory, z_window)
                pair_z = zp - partner_sign * zq  # if partner_sign=-1, pair_z = zp + zq
        memory["_pair_z"] = pair_z
        bid_size = size
        ask_size = size
        if pair_z > pair_thresh:
            if skip_size > 0:
                bid_size = skip_size  # soft skip: reduced size
            else:
                post_bid = False      # hard skip
        elif pair_z < -pair_thresh:
            if skip_size > 0:
                ask_size = skip_size  # soft skip: reduced size
            else:
                post_ask = False      # hard skip
        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if post_bid and bid_p is not None and buy_cap > 0:
            orders.append(Order(self.product, int(bid_p), min(bid_size, buy_cap)))
        if post_ask and ask_p is not None and sell_cap > 0:
            orders.append(Order(self.product, int(ask_p), -min(ask_size, sell_cap)))
        return orders, 0
    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        z = memory.get("_pair_z")
        return {"pair_z": round(z, 3)} if z is not None else {}
class PebblesArbV1(BaseStrategy):
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        p = self.params
        limit = int(p.get("position_limit", 10))
        partners: List[str] = list(p["partner_products"])
        sum_target = float(p.get("sum_target", 50000.0))
        edge = float(p.get("edge_ticks", 6.0))
        passive_half = float(p.get("passive_half_spread", 7.0))
        taker_size = int(p.get("taker_size", 10))
        passive_size = int(p.get("passive_size", 5))
        partners_sum = 0.0
        available = 0
        for sym in partners:
            od = state.order_depths.get(sym)
            if od is None:
                continue
            pb = list(od.buy_orders.keys())
            pa = list(od.sell_orders.keys())
            if not pb or not pa:
                continue
            partners_sum += (max(pb) + min(pa)) / 2.0
            available += 1
        if available < len(partners):
            mid = book.mid_price
            if mid is None:
                return [], 0
            ewma = memory.get("fair_ewma", mid)
            alpha = float(p.get("ewma_alpha", 0.01))
            ewma = alpha * mid + (1 - alpha) * ewma
            memory["fair_ewma"] = ewma
            fair_value = ewma
        else:
            fair_value = sum_target - partners_sum
            alpha = float(p.get("ewma_alpha", 0.01))
            memory["fair_ewma"] = alpha * fair_value + (1 - alpha) * memory.get("fair_ewma", fair_value)
        orders: List[Order] = []
        bb = book.best_bid
        ba = book.best_ask
        buy_room = limit - position
        sell_room = limit + position
        if ba is not None and ba <= fair_value - edge and buy_room > 0:
            qty = min(taker_size, buy_room)
            orders.append(Order(self.product, ba, qty))
            buy_room -= qty
        if bb is not None and bb >= fair_value + edge and sell_room > 0:
            qty = min(taker_size, sell_room)
            orders.append(Order(self.product, bb, -qty))
            sell_room -= qty
        if buy_room > 0:
            bid_px = int(fair_value - passive_half)
            if bb is not None:
                bid_px = max(bid_px, bb)
            orders.append(Order(self.product, bid_px, min(passive_size, buy_room)))
        if sell_room > 0:
            ask_px = int(fair_value + passive_half) + 1
            if ba is not None:
                ask_px = min(ask_px, ba)
            orders.append(Order(self.product, ask_px, -min(passive_size, sell_room)))
        return orders, 0
class SnackpackCrossMMV1_A1(BaseStrategy):
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        p = self.params
        partner = str(p["partner_product"])
        z_win = int(p.get("z_window", 300))
        shift_per_z = float(p.get("shift_per_z", 1.0))
        z_clamp = float(p.get("z_clamp", 3.0))
        maker_size = int(p.get("maker_size", 5))
        tighten = int(p.get("tighten_ticks", 1))
        limit = int(p.get("position_limit", 10))
        mid_A = book.mid_price
        if mid_A is None:
            return [], 0
        pod = state.order_depths.get(partner)
        if pod and pod.buy_orders and pod.sell_orders:
            mid_B = (max(pod.buy_orders) + min(pod.sell_orders)) / 2.0
            memory["mid_B_prev"] = mid_B
        else:
            mid_B = memory.get("mid_B_prev")
            if mid_B is None:
                return [], 0
        current_sum = mid_A + mid_B
        alpha_z = 2.0 / (z_win + 1)
        n_ticks = memory.get("n_ticks", 0) + 1
        memory["n_ticks"] = n_ticks
        mu_sum = memory.get("mu_sum", current_sum)
        var_sum = memory.get("var_sum", 1e-6)
        delta = current_sum - mu_sum
        mu_sum = mu_sum + alpha_z * delta
        var_sum = (1.0 - alpha_z) * (var_sum + alpha_z * delta * delta)
        memory["mu_sum"] = mu_sum
        memory["var_sum"] = var_sum
        bb = book.best_bid
        ba = book.best_ask
        if bb is None or ba is None:
            return [], 0
        orders: List[Order] = []
        buy_room = limit - position
        sell_room = limit + position
        quote_shift = 0
        if n_ticks >= z_win // 2 and var_sum > 1e-9:
            sd_sum = math.sqrt(var_sum)
            z = (current_sum - mu_sum) / sd_sum
            z_clamped = max(-z_clamp, min(z_clamp, z))
            quote_shift = -int(round(shift_per_z * z_clamped))
            memory["last_z"] = z
        spread = ba - bb
        if spread >= 2:
            bid_px = bb + tighten + quote_shift
            ask_px = ba - tighten + quote_shift
        else:
            bid_px = bb + quote_shift
            ask_px = ba + quote_shift
        if bid_px >= ask_px:
            bid_px = ask_px - 1
        if buy_room > 0:
            orders.append(Order(self.product, int(bid_px), min(maker_size, buy_room)))
        if sell_room > 0:
            orders.append(Order(self.product, int(ask_px), -min(maker_size, sell_room)))
        self.log_quote_snapshot(
            state=state,
            memory=memory,
            bid_price=bid_px,
            ask_price=ask_px,
            extras={"z": memory.get("last_z", 0.0), "shift": quote_shift},
        )
        return orders, 0
class TrendFollowRevGuardA3(BaseStrategy):
    def compute_orders(
        self,
        state,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.mid_price is None:
            return [], 0
        mid = book.mid_price
        limit = int(self.params.get("position_limit", 10))
        hl = float(self.params.get("ema_half_life", 100))
        entry_thr = float(self.params.get("threshold", 80))
        exit_thr = float(self.params.get("exit_threshold", 30))
        trail_stop = float(self.params.get("trail_stop_thr", 0))
        ref_interval = int(self.params.get("reference_update_interval", 0))
        min_tick = int(self.params.get("warmup_ticks", 0))
        direction = int(self.params.get("direction", 0))
        reverse_thr = float(self.params.get("reverse_threshold", entry_thr))
        cooldown_ticks = int(self.params.get("reentry_cooldown_ticks", 0))
        alpha = 1.0 - 0.5 ** (1.0 / hl)
        if "start_price" not in memory:
            memory["start_price"] = mid
        if "ema" not in memory:
            memory["ema"] = mid
        tick = memory.get("tick", 0)
        memory["tick"] = tick + 1
        ema = alpha * mid + (1.0 - alpha) * memory["ema"]
        memory["ema"] = ema
        if ref_interval > 0:
            if position == 0:
                flat_ticks = memory.get("flat_ticks", 0) + 1
                memory["flat_ticks"] = flat_ticks
                if flat_ticks >= ref_interval:
                    memory["start_price"] = ema
                    memory["flat_ticks"] = 0
            else:
                memory["flat_ticks"] = 0
        if tick < min_tick:
            return [], 0
        signal = ema - memory["start_price"]
        memory["signal"] = signal
        if position > 0:
            memory["peak_signal"] = max(memory.get("peak_signal", signal), signal)
        elif position < 0:
            memory["trough_signal"] = min(memory.get("trough_signal", signal), signal)
        else:
            memory.pop("peak_signal", None)
            memory.pop("trough_signal", None)
        def _trail_long() -> bool:
            if trail_stop <= 0:
                return False
            return signal < memory.get("peak_signal", signal) - trail_stop
        def _trail_short() -> bool:
            if trail_stop <= 0:
                return False
            return signal > memory.get("trough_signal", signal) + trail_stop
        def _in_cooldown() -> bool:
            until = int(memory.get("cooldown_until_tick", -1))
            return position == 0 and tick < until
        target = position
        exited_to_flat = False
        if direction > 0:
            if position > 0 and (_trail_long() or signal < -exit_thr):
                target = 0
                exited_to_flat = True
            elif position > 0 and signal > -exit_thr:
                target = limit
            elif position == 0 and not _in_cooldown() and signal > entry_thr:
                target = limit
        elif direction < 0:
            if position < 0 and (_trail_short() or signal > exit_thr):
                target = 0
                exited_to_flat = True
            elif position < 0 and signal < exit_thr:
                target = -limit
            elif position == 0 and not _in_cooldown() and signal < -entry_thr:
                target = -limit
        else:
            if position > 0:
                if signal < -reverse_thr:
                    target = -limit
                elif _trail_long() or signal < -exit_thr:
                    target = 0
                    exited_to_flat = True
                else:
                    target = limit
            elif position < 0:
                if signal > reverse_thr:
                    target = limit
                elif _trail_short() or signal > exit_thr:
                    target = 0
                    exited_to_flat = True
                else:
                    target = -limit
            else:
                if not _in_cooldown():
                    if signal > entry_thr:
                        target = limit
                    elif signal < -entry_thr:
                        target = -limit
        if exited_to_flat and cooldown_ticks > 0:
            memory["cooldown_until_tick"] = tick + cooldown_ticks
        return self._reach_target(order_depth, position, target, limit), 0
    def _reach_target(self, order_depth, position: int, target: int, limit: int) -> List[Order]:
        delta = target - position
        if delta == 0:
            return []
        orders = []
        if delta > 0 and order_depth.sell_orders:
            ask = min(order_depth.sell_orders.keys())
            avail = -order_depth.sell_orders[ask]
            qty = min(delta, avail, limit - position)
            if qty > 0:
                orders.append(Order(self.product, ask, qty))
        elif delta < 0 and order_depth.buy_orders:
            bid = max(order_depth.buy_orders.keys())
            avail = order_depth.buy_orders[bid]
            qty = min(-delta, avail, limit + position)
            if qty > 0:
                orders.append(Order(self.product, bid, -qty))
        return orders
    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if "signal" in memory:
            out["signal"] = round(float(memory["signal"]), 2)
        return out
class TrendFollowV2(BaseStrategy):
    def compute_orders(
        self,
        state,
        book: BookSnapshot,
        order_depth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.mid_price is None:
            return [], 0
        mid = book.mid_price
        limit = int(self.params.get("position_limit", 10))
        hl = float(self.params.get("ema_half_life", 100))
        entry_thr = float(self.params.get("threshold", 80))
        exit_thr = float(self.params.get("exit_threshold", 30))
        trail_stop = float(self.params.get("trail_stop_thr", 0))
        ref_interval = int(self.params.get("reference_update_interval", 0))
        min_tick = int(self.params.get("warmup_ticks", 0))
        direction = int(self.params.get("direction", 0))
        alpha = 1.0 - 0.5 ** (1.0 / hl)
        if "start_price" not in memory:
            memory["start_price"] = mid
        if "ema" not in memory:
            memory["ema"] = mid
        tick = memory.get("tick", 0)
        memory["tick"] = tick + 1
        ema = alpha * mid + (1.0 - alpha) * memory["ema"]
        memory["ema"] = ema
        if ref_interval > 0:
            if position == 0:
                flat_ticks = memory.get("flat_ticks", 0) + 1
                memory["flat_ticks"] = flat_ticks
                if flat_ticks >= ref_interval:
                    memory["start_price"] = ema
                    memory["flat_ticks"] = 0
            else:
                memory["flat_ticks"] = 0
        if tick < min_tick:
            return [], 0
        signal = ema - memory["start_price"]
        if position > 0:
            memory["peak_signal"] = max(memory.get("peak_signal", signal), signal)
        elif position < 0:
            memory["trough_signal"] = min(memory.get("trough_signal", signal), signal)
        else:
            memory.pop("peak_signal", None)
            memory.pop("trough_signal", None)
        def _trail_long() -> bool:
            if trail_stop <= 0:
                return False
            return signal < memory.get("peak_signal", signal) - trail_stop
        def _trail_short() -> bool:
            if trail_stop <= 0:
                return False
            return signal > memory.get("trough_signal", signal) + trail_stop
        if direction > 0:
            if signal > entry_thr:
                target = limit
            elif position > 0 and (_trail_long() or signal < -exit_thr):
                target = 0
            else:
                target = position
        elif direction < 0:
            if signal < -entry_thr:
                target = -limit
            elif position < 0 and (_trail_short() or signal > exit_thr):
                target = 0
            else:
                target = position
        else:
            if signal > entry_thr:
                target = limit
            elif signal < -entry_thr:
                target = -limit
            elif position > 0 and (_trail_long() or signal < -exit_thr):
                target = 0
            elif position < 0 and (_trail_short() or signal > exit_thr):
                target = 0
            else:
                target = position
        return self._reach_target(order_depth, position, target, limit), 0
    def _reach_target(self, order_depth, position: int, target: int, limit: int) -> List[Order]:
        delta = target - position
        if delta == 0:
            return []
        orders = []
        if delta > 0 and order_depth.sell_orders:
            ask = min(order_depth.sell_orders.keys())
            avail = -order_depth.sell_orders[ask]
            qty = min(delta, avail, limit - position)
            if qty > 0:
                orders.append(Order(self.product, ask, qty))
        elif delta < 0 and order_depth.buy_orders:
            bid = max(order_depth.buy_orders.keys())
            avail = order_depth.buy_orders[bid]
            qty = min(-delta, avail, limit + position)
            if qty > 0:
                orders.append(Order(self.product, bid, -qty))
        return orders
PRODUCTS = {'GALAXY_SOUNDS_BLACK_HOLES': {'last_ts_value': 999900,
                               'passive_size': 3,
                               'position_limit': 10,
                               'signal2_products': ['ROBOT_VACUUMING',
                                                    'ROBOT_MOPPING',
                                                    'ROBOT_DISHES',
                                                    'ROBOT_LAUNDRY',
                                                    'ROBOT_IRONING'],
                               'signal2_threshold': 30,
                               'signal_ema_hl': 100,
                               'signal_exit': 26.666666666666668,
                               'signal_products': ['SLEEP_POD_SUEDE',
                                                   'SLEEP_POD_LAMB_WOOL',
                                                   'SLEEP_POD_POLYESTER',
                                                   'SLEEP_POD_NYLON',
                                                   'SLEEP_POD_COTTON'],
                               'signal_threshold': 80,
                               'strategy': 'cross_group_trend_A2',
                               'taker_size': 10},
 'GALAXY_SOUNDS_DARK_MATTER': {'last_ts_value': 999900,
                               'passive_size': 3,
                               'position_limit': 10,
                               'signal_ema_hl': 100,
                               'signal_exit': 100.0,
                               'signal_products': ['SLEEP_POD_SUEDE',
                                                   'SLEEP_POD_LAMB_WOOL',
                                                   'SLEEP_POD_POLYESTER',
                                                   'SLEEP_POD_NYLON',
                                                   'SLEEP_POD_COTTON'],
                               'signal_threshold': 300,
                               'strategy': 'cross_group_trend_A2',
                               'taker_size': 10},
 'GALAXY_SOUNDS_PLANETARY_RINGS': {'carry_pause_min_pos': 3,
                                   'hard_pause_at': 9,
                                   'last_ts_value': 999900,
                                   'log_flush_ts': 1000,
                                   'maker_size': 5,
                                   'position_limit': 10,
                                   'strategy': 'inventory_carry_mm',
                                   'tighten_ticks': 1,
                                   'trend_hl': 200,
                                   'ts_increment': 100},
 'GALAXY_SOUNDS_SOLAR_FLAMES': {'carry_pause_min_pos': 3,
                                'hard_pause_at': 9,
                                'last_ts_value': 999900,
                                'log_flush_ts': 1000,
                                'maker_size': 5,
                                'position_limit': 10,
                                'strategy': 'inventory_carry_mm',
                                'tighten_ticks': 1,
                                'trend_hl': 200,
                                'ts_increment': 100},
 'GALAXY_SOUNDS_SOLAR_WINDS': {'carry_pause_min_pos': 2,
                               'carry_trend_min_abs': 100.0,
                               'hard_pause_at': 9,
                               'last_ts_value': 999900,
                               'log_flush_ts': 1000,
                               'maker_size': 5,
                               'position_limit': 10,
                               'strategy': 'inventory_carry_mm',
                               'tighten_ticks': 1,
                               'trend_hl': 50,
                               'ts_increment': 100},
 'MICROCHIP_CIRCLE': {'invert_signal': True,
                      'last_ts_value': 999900,
                      'passive_size': 5,
                      'position_limit': 10,
                      'signal_ema_hl': 100,
                      'signal_exit': 70.0,
                      'signal_products': ['MICROCHIP_SQUARE'],
                      'signal_threshold': 200.0,
                      'strategy': 'cross_group_trend_A2',
                      'taker_size': 10},
 'MICROCHIP_OVAL': {'hard_pause_at': 9,
                    'last_ts_value': 999900,
                    'log_flush_ts': 1000,
                    'maker_size': 5,
                    'pair_thresh': 1.25,
                    'partner': 'MICROCHIP_TRIANGLE',
                    'partner_sign': -1.0,
                    'position_limit': 10,
                    'strategy': 'pair_skip_mm',
                    'tighten_ticks': 1,
                    'ts_increment': 100,
                    'z_window': 300},
 'MICROCHIP_RECTANGLE': {'hard_pause_at': 9,
                         'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size': 5,
                         'pair_thresh': 1.25,
                         'partner': 'MICROCHIP_SQUARE',
                         'partner_sign': -1.0,
                         'position_limit': 10,
                         'strategy': 'pair_skip_mm',
                         'tighten_ticks': 1,
                         'ts_increment': 100,
                         'z_window': 300},
 'MICROCHIP_SQUARE': {'direction': 0,
                      'ema_half_life': 30,
                      'exit_threshold': 150,
                      'last_ts_value': 999900,
                      'log_flush_ts': 1000,
                      'position_limit': 10,
                      'reentry_cooldown_ticks': 400,
                      'reverse_threshold': 300,
                      'strategy': 'trend_follow_revguard_A3',
                      'threshold': 200,
                      'ts_increment': 100},
 'MICROCHIP_TRIANGLE': {'last_ts_value': 999900,
                        'log_flush_ts': 1000,
                        'maker_size': 3,
                        'position_limit': 10,
                        'strategy': 'naive_tight_mm',
                        'tighten_ticks': 1,
                        'ts_increment': 100},
 'OXYGEN_SHAKE_CHOCOLATE': {'last_ts_value': 999900,
                            'log_flush_ts': 1000,
                            'maker_size': 5,
                            'position_limit': 10,
                            'strategy': 'naive_tight_mm',
                            'tighten_ticks': 1,
                            'ts_increment': 100},
 'OXYGEN_SHAKE_EVENING_BREATH': {'last_ts_value': 999900,
                                 'log_flush_ts': 1000,
                                 'maker_size': 5,
                                 'position_limit': 10,
                                 'strategy': 'naive_tight_mm',
                                 'tighten_ticks': 1,
                                 'ts_increment': 100},
 'OXYGEN_SHAKE_GARLIC': {'direction': 1,
                         'ema_half_life': 50,
                         'exit_threshold': 20,
                         'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'position_limit': 10,
                         'reference_update_interval': 800,
                         'strategy': 'trend_follow_v2',
                         'threshold': 80,
                         'trail_stop_thr': 100,
                         'ts_increment': 100},
 'OXYGEN_SHAKE_MORNING_BREATH': {'carry_pause_min_pos': 3,
                                 'hard_pause_at': 9,
                                 'last_ts_value': 999900,
                                 'log_flush_ts': 1000,
                                 'maker_size': 5,
                                 'position_limit': 10,
                                 'strategy': 'inventory_carry_mm',
                                 'tighten_ticks': 1,
                                 'trend_hl': 200,
                                 'ts_increment': 100},
 'PANEL_1X2': {'ema_half_life': 100,
               'exit_threshold': 30,
               'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'position_limit': 10,
               'strategy': 'trend_follow_v2',
               'threshold': 80,
               'ts_increment': 100,
               'warmup_ticks': 0},
 'PANEL_1X4': {'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'maker_size': 5,
               'position_limit': 10,
               'strategy': 'naive_tight_mm',
               'tighten_ticks': 1,
               'ts_increment': 100},
 'PANEL_2X2': {'carry_pause_min_pos': 3,
               'hard_pause_at': 9,
               'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'maker_size': 5,
               'position_limit': 10,
               'strategy': 'inventory_carry_mm',
               'tighten_ticks': 1,
               'trend_hl': 200,
               'ts_increment': 100},
 'PANEL_2X4': {'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'maker_size': 5,
               'position_limit': 10,
               'strategy': 'naive_tight_mm',
               'tighten_ticks': 1,
               'ts_increment': 100},
 'PANEL_4X4': {'carry_pause_min_pos': 3,
               'hard_pause_at': 9,
               'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'maker_size': 5,
               'position_limit': 10,
               'strategy': 'inventory_carry_mm',
               'tighten_ticks': 1,
               'trend_hl': 200,
               'ts_increment': 100},
 'PEBBLES_L': {'carry_pause_min_pos': 3,
               'hard_pause_at': 9,
               'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'maker_size': 5,
               'position_limit': 10,
               'strategy': 'inventory_carry_mm',
               'tighten_ticks': 1,
               'trend_hl': 200,
               'ts_increment': 100},
 'PEBBLES_S': {'hard_pause_at': 9,
               'last_ts_value': 999900,
               'log_flush_ts': 1000,
               'maker_size': 5,
               'pair_thresh': 1.25,
               'partner': 'PEBBLES_XL',
               'partner_sign': -1.0,
               'position_limit': 10,
               'strategy': 'pair_skip_mm',
               'tighten_ticks': 1,
               'ts_increment': 100,
               'z_window': 300},
 'PEBBLES_XL': {'edge_ticks': 7.0,
                'ewma_alpha': 0.05,
                'last_ts_value': 999900,
                'partner_products': ['PEBBLES_L', 'PEBBLES_M', 'PEBBLES_S', 'PEBBLES_XS'],
                'passive_half_spread': 6.0,
                'passive_size': 5,
                'position_limit': 10,
                'strategy': 'pebbles_arb_v1',
                'sum_target': 50000.0,
                'taker_size': 10},
 'PEBBLES_XS': {'direction': -1,
                'ema_half_life': 150,
                'exit_threshold': 30,
                'last_ts_value': 999900,
                'log_flush_ts': 1000,
                'position_limit': 10,
                'strategy': 'trend_follow_v2',
                'threshold': 100,
                'ts_increment': 100},
 'ROBOT_DISHES': {'entry_threshold': 20.0,
                  'exit_ticks': 0,
                  'last_ts_value': 999900,
                  'passive_size': 0,
                  'position_limit': 10,
                  'strategy': 'ar1_mean_rev_v1',
                  'taker_size': 10},
 'ROBOT_IRONING': {'direction': 0,
                   'ema_half_life': 100,
                   'exit_threshold': 20,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'position_limit': 10,
                   'strategy': 'trend_follow_v2',
                   'threshold': 50,
                   'ts_increment': 100},
 'ROBOT_LAUNDRY': {'entry_z': 1.5,
                   'exit_z': 0.0,
                   'last_ts_value': 999900,
                   'mean_half_life': 5000,
                   'partner_product': 'ROBOT_VACUUMING',
                   'passive_size': 1,
                   'position_limit': 10,
                   'strategy': 'coint_mm_v1',
                   'taker_size': 10,
                   'tighten_ticks': 1,
                   'z_window': 2000},
 'ROBOT_MOPPING': {'ema_half_life': 150,
                   'exit_threshold': 40,
                   'last_ts_value': 999900,
                   'log_flush_ts': 1000,
                   'position_limit': 10,
                   'strategy': 'trend_follow_v2',
                   'threshold': 100,
                   'ts_increment': 100,
                   'warmup_ticks': 0},
 'ROBOT_VACUUMING': {'entry_z': 1.5,
                     'exit_z': 0.0,
                     'last_ts_value': 999900,
                     'mean_half_life': 5000,
                     'partner_product': 'ROBOT_LAUNDRY',
                     'passive_size': 3,
                     'position_limit': 10,
                     'strategy': 'coint_mm_v1',
                     'taker_size': 10,
                     'tighten_ticks': 1,
                     'z_window': 2000},
 'SLEEP_POD_COTTON': {'hard_pause_at': 9,
                      'last_ts_value': 999900,
                      'log_flush_ts': 1000,
                      'maker_size': 5,
                      'pair_thresh': 1.25,
                      'partner': 'SLEEP_POD_NYLON',
                      'partner_sign': -1.0,
                      'position_limit': 10,
                      'strategy': 'pair_skip_mm',
                      'tighten_ticks': 1,
                      'ts_increment': 100,
                      'z_window': 300},
 'SLEEP_POD_NYLON': {'ema_half_life': 100,
                     'exit_threshold': 30,
                     'last_ts_value': 999900,
                     'log_flush_ts': 1000,
                     'position_limit': 10,
                     'strategy': 'trend_follow_v2',
                     'threshold': 80,
                     'ts_increment': 100,
                     'warmup_ticks': 0},
 'SLEEP_POD_POLYESTER': {'ema_half_life': 150,
                         'exit_threshold': 150,
                         'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'position_limit': 10,
                         'strategy': 'trend_follow_v2',
                         'threshold': 600,
                         'ts_increment': 100,
                         'warmup_ticks': 0},
 'SLEEP_POD_SUEDE': {'hard_pause_at': 9,
                     'inv_skew_thresh': 6,
                     'inv_skew_ticks': 1,
                     'last_ts_value': 999900,
                     'log_flush_ts': 1000,
                     'maker_size': 5,
                     'microprice_clamp': 1.0,
                     'microprice_weight': 0.5,
                     'min_opportunity_ticks': 0.9,
                     'min_spread_for_taker': 1,
                     'mode': 'pair',
                     'opportunity_taker_size': 2,
                     'pair_thresh': 1.25,
                     'partner': 'SLEEP_POD_NYLON',
                     'partner_sign': -1.0,
                     'passive_size': 5,
                     'position_limit': 10,
                     'signal_shift_clamp': 2.0,
                     'signal_shift_per_unit': 0.9,
                     'size_inv_factor': 0.35,
                     'strategy': 'opportunistic_taker_mm',
                     'taker_cooldown_ts': 300,
                     'taker_position_cap': 7,
                     'taker_threshold': 1.25,
                     'tighten_ticks': 1,
                     'trend_clamp': 0.5,
                     'trend_hl': 150,
                     'trend_weight': 0.03,
                     'ts_increment': 100,
                     'unwind_edge': 1.0,
                     'unwind_min_pos': 5,
                     'unwind_size': 3,
                     'z_window': 300},
 'SNACKPACK_CHOCOLATE': {'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size': 5,
                         'position_limit': 10,
                         'strategy': 'naive_tight_mm',
                         'tighten_ticks': 1,
                         'ts_increment': 100},
 'SNACKPACK_PISTACHIO': {'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size': 5,
                         'position_limit': 10,
                         'strategy': 'naive_tight_mm',
                         'tighten_ticks': 1,
                         'ts_increment': 100},
 'SNACKPACK_RASPBERRY': {'hard_pause_at': 9,
                         'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size': 5,
                         'pair_thresh': 1.25,
                         'partner': 'SNACKPACK_STRAWBERRY',
                         'partner_sign': -1.0,
                         'position_limit': 10,
                         'strategy': 'pair_skip_mm',
                         'tighten_ticks': 1,
                         'ts_increment': 100,
                         'z_window': 300},
 'SNACKPACK_STRAWBERRY': {'last_ts_value': 999900,
                          'log_flush_ts': 1000,
                          'maker_size': 5,
                          'position_limit': 10,
                          'strategy': 'naive_tight_mm',
                          'tighten_ticks': 1,
                          'ts_increment': 100},
 'SNACKPACK_VANILLA': {'last_ts_value': 999900,
                       'log_flush_ts': 1000,
                       'maker_size': 5,
                       'partner_product': 'SNACKPACK_CHOCOLATE',
                       'position_limit': 10,
                       'shift_per_z': 1.0,
                       'strategy': 'snackpack_cross_mm_v1_A1',
                       'tighten_ticks': 1,
                       'ts_increment': 100,
                       'z_clamp': 3.0,
                       'z_window': 1900},
 'TRANSLATOR_ASTRO_BLACK': {'last_ts_value': 999900,
                            'log_flush_ts': 1000,
                            'maker_size': 5,
                            'position_limit': 10,
                            'strategy': 'naive_tight_mm',
                            'tighten_ticks': 1,
                            'ts_increment': 100},
 'TRANSLATOR_ECLIPSE_CHARCOAL': {'last_ts_value': 999900,
                                 'log_flush_ts': 1000,
                                 'maker_size': 3,
                                 'position_limit': 10,
                                 'strategy': 'naive_tight_mm',
                                 'tighten_ticks': 1,
                                 'ts_increment': 100},
 'TRANSLATOR_GRAPHITE_MIST': {'carry_pause_min_pos': 3,
                              'hard_pause_at': 9,
                              'last_ts_value': 999900,
                              'log_flush_ts': 1000,
                              'maker_size': 5,
                              'position_limit': 10,
                              'strategy': 'inventory_carry_mm',
                              'tighten_ticks': 1,
                              'trend_hl': 200,
                              'ts_increment': 100},
 'TRANSLATOR_VOID_BLUE': {'last_ts_value': 999900,
                          'log_flush_ts': 1000,
                          'maker_size': 5,
                          'position_limit': 10,
                          'strategy': 'naive_tight_mm',
                          'tighten_ticks': 1,
                          'ts_increment': 100},
 'UV_VISOR_AMBER': {'ema_half_life': 100,
                    'exit_threshold': 30,
                    'last_ts_value': 999900,
                    'log_flush_ts': 1000,
                    'position_limit': 10,
                    'strategy': 'trend_follow_v2',
                    'threshold': 80,
                    'ts_increment': 100,
                    'warmup_ticks': 0},
 'UV_VISOR_ORANGE': {'hard_pause_at': 9,
                     'last_ts_value': 999900,
                     'log_flush_ts': 1000,
                     'maker_size': 5,
                     'pair_thresh': 1.25,
                     'partner': 'UV_VISOR_YELLOW',
                     'partner_sign': -1.0,
                     'position_limit': 10,
                     'strategy': 'pair_skip_mm',
                     'tighten_ticks': 1,
                     'ts_increment': 100,
                     'z_window': 300},
 'UV_VISOR_RED': {'hard_pause_at': 9,
                  'last_ts_value': 999900,
                  'log_flush_ts': 1000,
                  'maker_size': 5,
                  'pair_thresh': 1.25,
                  'partner': 'UV_VISOR_AMBER',
                  'partner_sign': -1.0,
                  'position_limit': 10,
                  'strategy': 'pair_skip_mm',
                  'tighten_ticks': 1,
                  'ts_increment': 100,
                  'z_window': 300},
 'UV_VISOR_YELLOW': {'ema_half_life': 100,
                     'exit_threshold': 150,
                     'last_ts_value': 999900,
                     'log_flush_ts': 1000,
                     'position_limit': 10,
                     'strategy': 'trend_follow_v2',
                     'threshold': 700,
                     'ts_increment': 100,
                     'warmup_ticks': 0}}
STRATEGY_CLASSES = {"ar1_mean_rev_v1": AR1MeanRevV1, "coint_mm_v1": CointMMV1, "cross_group_trend_A2": CrossGroupTrendA2, "inventory_carry_mm": InventoryCarryMMStrategy, "naive_tight_mm": NaiveTightMarketMakerStrategy, "opportunistic_taker_mm": OpportunisticTakerMMStrategy, "pair_skip_mm": PairSkipMMStrategy, "pebbles_arb_v1": PebblesArbV1, "snackpack_cross_mm_v1_A1": SnackpackCrossMMV1_A1, "trend_follow_revguard_A3": TrendFollowRevGuardA3, "trend_follow_v2": TrendFollowV2}
class Trader:
    def __init__(self):
        self.strategies = {}
        for symbol, cfg in PRODUCTS.items():
            strat_name = cfg["strategy"]
            params = {k: v for k, v in cfg.items() if k != "strategy"}
            cls = STRATEGY_CLASSES[strat_name]
            self.strategies[symbol] = cls(product=symbol, params=params)
    def bid(self) -> int:
        return 15
    def run(self, state: TradingState):
        saved = load_state(state.traderData)
        product_memories = saved.setdefault("products", {})
        shared = {"timestamp": state.timestamp}
        result = {}
        total_conversions = 0
        for product, strategy in self.strategies.items():
            if product not in state.order_depths:
                continue
            memory = product_memories.setdefault(product, {})
            memory["_shared"] = shared
            orders, conversions = strategy.on_tick(state, memory)
            result[product] = orders
            total_conversions += conversions
        for memory in product_memories.values():
            if isinstance(memory, dict):
                memory.pop("_shared", None)
        saved["last_timestamp"] = state.timestamp
        return result, total_conversions, dump_state(saved)
