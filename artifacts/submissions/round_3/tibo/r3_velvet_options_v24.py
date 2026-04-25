from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datamodel import Order, OrderDepth, TradingState
from datamodel import OrderDepth
from datamodel import TradingState
from typing import Any, Dict
from typing import Any, Dict, List, Optional
from typing import Any, Dict, List, Optional, Set, Tuple
from typing import Any, Dict, List, Optional, Tuple
from typing import Any, Dict, List, Tuple
from typing import Any, Mapping
from typing import List, Sequence, Tuple, Optional
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
        return self.compute_orders(
            state=state,
            book=book,
            order_depth=order_depth,
            position=position,
            memory=memory,
        )
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
class GammaScalpZGatedStrategy(BaseStrategy):
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
        p = self._read_params(state)
        ts = int(state.timestamp)
        publish_position(ts, self.product, position)
        S = get_spot(state, underlying=p["underlying_symbol"])
        if S is None:
            return [], 0
        z = self._update_zscore(S, memory, p)
        memory["_velvet_z"] = z
        fair = call_price(S, p["K"], p["T"], p["implied_vol_prior"])
        gamma = call_gamma(S, p["K"], p["T"], p["implied_vol_prior"])
        delta = call_delta(S, p["K"], p["T"], p["implied_vol_prior"])
        memory["_gamma"] = gamma
        memory["_delta"] = delta
        memory["_fair_iv"] = fair
        memory["_spot"] = S
        memory["_T"] = p["T"]
        if fair < p["min_quote_price"]:
            return [], 0
        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        if p["T"] < p["unwind_tte_threshold"] or position >= p["target_qty"]:
            if sell_cap > 0 and position > 0:
                ask_px = book.best_ask - 1
                if ask_px <= book.best_bid:
                    ask_px = book.best_bid + 1
                qty = min(p["passive_bid_size"], sell_cap, position)
                if qty > 0:
                    orders.append(Order(self.product, ask_px, -qty))
            memory["_mode"] = "unwind"
            return orders, 0
        if (p["sell_when_very_expensive"] and z is not None
                and z > p["zscore_sell_threshold"] and position > 0
                and sell_cap > 0):
            ask_px = book.best_ask - 1
            if ask_px <= book.best_bid:
                ask_px = book.best_bid + 1
            sell_qty = max(1, int(round(position * p["sell_size_pct"])))
            qty = min(sell_qty, sell_cap, position, p["passive_bid_size"])
            if qty > 0:
                orders.append(Order(self.product, ask_px, -qty))
                sell_cap -= qty
            memory["_mode"] = "z_profit_take"
            return orders, 0
        skip_entries = False
        if p["skip_when_expensive"] and z is not None and z > p["zscore_skip_threshold"]:
            skip_entries = True
            memory["_mode"] = "z_skipped_expensive"
        else:
            memory["_mode"] = "accumulate"
        if skip_entries:
            return orders, 0
        size_mult = 1.0
        if p["boost_when_cheap"] and z is not None and z < -p["zscore_boost_threshold"]:
            size_mult = p["entry_size_boost"]
            memory["_mode"] = "z_boost_cheap"
        eff_entry_size = max(1, int(round(p["entry_size"] * size_mult)))
        eff_passive_size = max(1, int(round(p["passive_bid_size"] * size_mult)))
        if buy_cap > 0 and position < p["target_qty"]:
            ask = book.best_ask
            if ask is not None and ask <= fair + p["edge_ticks"]:
                ask_qty = -order_depth.sell_orders.get(ask, 0)
                headroom = p["target_qty"] - position
                take_qty = min(ask_qty, buy_cap, eff_entry_size, headroom)
                if take_qty > 0:
                    orders.append(Order(self.product, ask, take_qty))
                    buy_cap -= take_qty
        if buy_cap > 0 and position < p["target_qty"]:
            bid_px = book.best_bid + 1
            if bid_px < book.best_ask:
                qty = min(eff_passive_size, buy_cap, p["target_qty"] - position)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))
        return orders, 0
    def _update_zscore(self, S: float, memory: Dict[str, Any], p: Dict[str, Any]) -> Optional[float]:
        window = p["zscore_window"]
        buf: List[float] = memory.setdefault("_velvet_buf", [])
        buf.append(S)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            return None
        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std = var ** 0.5
        if std < 1e-9:
            return None
        return (S - mean) / std
    def _read_params(self, state: TradingState) -> Dict[str, Any]:
        params = self.params
        tte0 = resolve_initial_tte_days(
            state.traderData,
            float(params.get("tte_days_initial", 5.0)),
            params.get("historical_tte_by_day"),
        )
        ts = int(state.timestamp)
        ts_per_day = timestamp_units_per_day_from_params(params)
        T = time_to_expiry_days(ts, tte0, timestamp_units_per_day=ts_per_day)
        return {
            "K": float(params["strike"]),
            "T": max(0.01, T),
            "implied_vol_prior": float(params.get("implied_vol_prior", 0.0125)),
            "edge_ticks": float(params.get("edge_ticks", 0.0)),
            "target_qty": int(params.get("target_qty", 100)),
            "entry_size": int(params.get("entry_size", 10)),
            "passive_bid_size": int(params.get("passive_bid_size", 10)),
            "unwind_tte_threshold": float(params.get("unwind_tte_threshold", 1.5)),
            "min_quote_price": float(params.get("min_quote_price", 2.0)),
            "underlying_symbol": params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"),
            "zscore_window": int(params.get("zscore_window", 500)),
            "zscore_skip_threshold": float(params.get("zscore_skip_threshold", 1.0)),
            "zscore_boost_threshold": float(params.get("zscore_boost_threshold", 1.0)),
            "skip_when_expensive": bool(params.get("skip_when_expensive", True)),
            "boost_when_cheap": bool(params.get("boost_when_cheap", False)),
            "entry_size_boost": float(params.get("entry_size_boost", 1.5)),
            "sell_when_very_expensive": bool(params.get("sell_when_very_expensive", False)),
            "zscore_sell_threshold": float(params.get("zscore_sell_threshold", 1.5)),
            "sell_size_pct": float(params.get("sell_size_pct", 0.10)),
        }
    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (g := memory.get("_gamma")) is not None: out["gamma"] = g
        if (d := memory.get("_delta")) is not None: out["delta"] = d
        if (f := memory.get("_fair_iv")) is not None: out["fair_iv"] = f
        if (z := memory.get("_velvet_z")) is not None: out["velvet_z"] = z
        if (m := memory.get("_mode")) is not None:
            out["mode"] = {"accumulate": 1.0, "unwind": 0.0,
                           "z_skipped_expensive": -1.0, "z_boost_cheap": 2.0}.get(m, 0.5)
        return out
class MMFirstV4ComboStrategy(BaseStrategy):
    def _compute_quote_prices(
        self,
        book: BookSnapshot,
        inventory_ratio: float,
        mid_smooth: float,
    ) -> Tuple[Optional[int], Optional[int], str]:
        bid_price: Optional[int] = (book.best_bid + 1) if book.best_bid is not None else None
        ask_price: Optional[int] = (book.best_ask - 1) if book.best_ask is not None else None
        return bid_price, ask_price, "L1"
    def _compute_zscore(self, mid: float, memory: Dict[str, Any]) -> Optional[float]:
        window = int(self.params.get("zscore_window", 50))
        buf: List[float] = memory.setdefault("_zscore_buf", [])
        buf.append(mid)
        if len(buf) > window:
            buf[:] = buf[-window:]
        if len(buf) < max(3, window // 4):
            memory["zscore"] = None
            return None
        n = len(buf)
        mean = sum(buf) / n
        var = sum((x - mean) ** 2 for x in buf) / max(n - 1, 1)
        std = var ** 0.5
        if std < 1e-9:
            memory["zscore"] = None
            return None
        z = (mid - mean) / std
        memory["zscore"] = z
        memory["_zs_mean"] = mean
        memory["_zs_std"] = std
        return z
    def _zscore_size_factors(self, memory: Dict[str, Any]) -> Tuple[float, float]:
        z = memory.get("zscore")
        if z is None:
            return 1.0, 1.0
        threshold = float(self.params.get("zscore_threshold", 1.0))
        size_scale = float(self.params.get("zscore_size_scale", 0.5))
        max_scale = float(self.params.get("zscore_max_scale", 3.0))
        excess = max(0.0, abs(z) - threshold)
        scale = min(max_scale, 1.0 + size_scale * excess)
        if z > threshold:
            return 1.0 / scale, scale
        if z < -threshold:
            return scale, 1.0 / scale
        return 1.0, 1.0
    def _compute_sizes(self, position: int, limit: int) -> Tuple[float, float]:
        base = float(self.params.get("maker_size_base_pct", 0.2)) * limit
        bid_size = base * (1.0 - position / limit)
        ask_size = base * (1.0 + position / limit)
        return bid_size, ask_size
    def _dynamic_take_edge(self, memory: Dict[str, Any]) -> float:
        lo = self.params.get("take_edge_lo")
        hi = self.params.get("take_edge_hi")
        if lo is None or hi is None:
            return float(self.params.get("take_edge", 1.0))
        sigma = memory.get("sigma_smoothed")
        if sigma is None:
            return float(lo)
        vol_lo = float(self.params.get("take_edge_vol_lo", 2.0))
        vol_hi = float(self.params.get("take_edge_vol_hi", 5.0))
        if sigma <= vol_lo:
            return float(lo)
        if sigma >= vol_hi:
            return float(hi)
        t = (sigma - vol_lo) / (vol_hi - vol_lo)
        return float(lo) + t * (float(hi) - float(lo))
    def _compute_anchor_signal(
        self,
        mid: float,
        book: BookSnapshot,
        mid_smooth: float,
        memory: Dict[str, Any],
    ) -> float:
        anchor_price = self.params.get("anchor_price")
        if anchor_price is None:
            return mid_smooth
        anchor_fixed = float(anchor_price)
        anchor_alpha = float(self.params.get("anchor_alpha", 0.0))
        if anchor_alpha > 0.0:
            ema = memory.get("_anchor_ema", anchor_fixed)
            ema = anchor_alpha * mid + (1.0 - anchor_alpha) * ema
            drift_bound = float(self.params.get("anchor_drift_bound", 0.0))
            if drift_bound > 0:
                ema = max(anchor_fixed - drift_bound,
                          min(anchor_fixed + drift_bound, ema))
            memory["_anchor_ema"] = ema
            anchor_value = ema
        else:
            anchor_value = anchor_fixed
        ar_gain = float(self.params.get("ar_gain", 0.0))
        ar_shift = 0.0
        if ar_gain > 0.0:
            source = str(self.params.get("ar_shift_source", "mid"))
            if source == "microprice":
                current = self._microprice(book)
            elif source == "mid_smooth":
                current = mid_smooth
            else:
                current = mid
            prev = memory.get("_ar_prev_signal")
            if prev is not None:
                ar_shift = -ar_gain * (current - prev)
            memory["_ar_prev_signal"] = current
        return anchor_value + ar_shift
    def _compute_asym_take_edges(
        self,
        base_edge: float,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[float, float]:
        unwind = float(self.params.get("unwind_take_edge", 0.0))
        if unwind <= 0:
            return base_edge, base_edge
        limit = self.position_limit()
        pressure = abs(position) / max(1.0, float(limit))
        if position > 0:
            sell_edge = max(0.0, base_edge - unwind * pressure)
            buy_edge = base_edge + unwind * pressure
        elif position < 0:
            buy_edge = max(0.0, base_edge - unwind * pressure)
            sell_edge = base_edge + unwind * pressure
        else:
            return base_edge, base_edge
        return buy_edge, sell_edge
    def _fire_takers(
        self,
        order_depth: OrderDepth,
        fair_value: float,
        bid_size: float,
        ask_size: float,
        buy_cap: int,
        sell_cap: int,
        buy_edge: float,
        sell_edge: float,
    ) -> Tuple[List[Order], int, int, Set[int], Set[int]]:
        taker_buy_threshold = self.params.get("taker_buy_threshold")
        taker_sell_threshold = self.params.get("taker_sell_threshold")
        orders: List[Order] = []
        taker_buy_px: Set[int] = set()
        taker_sell_px: Set[int] = set()
        for ask_p in sorted(order_depth.sell_orders):
            available = -order_depth.sell_orders[ask_p]
            mid_signal = ask_p <= fair_value - buy_edge
            abs_signal = taker_buy_threshold is not None and ask_p <= taker_buy_threshold
            if not (mid_signal or abs_signal) or buy_cap <= 0:
                break
            qty = min(available, buy_cap, int(bid_size * 0.3))
            if qty > 0:
                orders.append(Order(self.product, ask_p, qty))
                taker_buy_px.add(ask_p)
                buy_cap -= qty
        for bid_p in sorted(order_depth.buy_orders, reverse=True):
            volume = order_depth.buy_orders[bid_p]
            mid_signal = bid_p >= fair_value + sell_edge
            abs_signal = taker_sell_threshold is not None and bid_p >= taker_sell_threshold
            if not (mid_signal or abs_signal) or sell_cap <= 0:
                break
            qty = min(volume, sell_cap, int(ask_size * 0.3))
            if qty > 0:
                orders.append(Order(self.product, bid_p, -qty))
                taker_sell_px.add(bid_p)
                sell_cap -= qty
        return orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px
    def _gap_exploit(
        self,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        limit: int,
        bid_size: float,
        ask_size: float,
        bid_price: Optional[int],
        ask_price: Optional[int],
        buy_cap: int,
        sell_cap: int,
        taker_buy_px: Set[int],
        taker_sell_px: Set[int],
    ) -> Tuple[List[Order], int, int, Optional[int], Optional[int]]:
        gap_min = float(self.params.get("gap_trigger_min", 10))
        shift = float(self.params.get("OB_cleared_shift", 10))
        gap_vol_pct = float(self.params.get("gap_trigger_max_vol_pct", 0.10))
        gap_max_vol = int(gap_vol_pct * limit) if limit else 0
        gap_confirm = int(self.params.get("gap_trigger_confirm_ticks", 1))
        z = memory.get("zscore")
        gap_gate = float(self.params.get("zscore_gap_gate", self.params.get("zscore_threshold", 1.0)))
        bid_z_ok = z is None or z >= -gap_gate
        ask_z_ok = z is None or z <= gap_gate
        orders: List[Order] = []
        memory["_gap_buy_px"] = []
        memory["_gap_sell_px"] = []
        all_bids = sorted(order_depth.buy_orders.keys(), reverse=True)
        all_asks = sorted(order_depth.sell_orders.keys())
        if all_bids:
            memory["_last_best_bid"] = all_bids[0]
        if all_asks:
            memory["_last_best_ask"] = all_asks[0]
        last_best_bid = memory.get("_last_best_bid")
        last_best_ask = memory.get("_last_best_ask")
        remaining_bids = [p for p in all_bids if p not in taker_sell_px]
        remaining_asks = [p for p in all_asks if p not in taker_buy_px]
        gap_swept_bids: Set[int] = set()
        gap_swept_asks: Set[int] = set()
        if gap_min > 0 and gap_max_vol > 0:
            bid_gap_ok = False
            bid1 = bid2 = bid1_vol = None
            if len(remaining_bids) >= 2:
                bid1, bid2 = remaining_bids[0], remaining_bids[1]
                bid1_vol = order_depth.buy_orders[bid1]
                bid_gap_ok = (bid1 - bid2) >= gap_min and bid1_vol <= gap_max_vol
            bid_streak = memory.get("_gap_bid_streak", 0)
            bid_streak = bid_streak + 1 if bid_gap_ok else 0
            memory["_gap_bid_streak"] = bid_streak
            if bid_streak >= gap_confirm and bid_gap_ok and sell_cap > 0 and bid_z_ok:
                qty = min(bid1_vol, sell_cap, int(ask_size))
                if qty > 0:
                    orders.append(Order(self.product, bid1, -qty))
                    sell_cap -= qty
                    memory["_gap_sell_px"].append(bid1)
                    if qty >= bid1_vol:
                        gap_swept_bids.add(bid1)
            ask_gap_ok = False
            ask1 = ask2 = ask1_vol = None
            if len(remaining_asks) >= 2:
                ask1, ask2 = remaining_asks[0], remaining_asks[1]
                ask1_vol = -order_depth.sell_orders[ask1]
                ask_gap_ok = (ask2 - ask1) >= gap_min and ask1_vol <= gap_max_vol
            ask_streak = memory.get("_gap_ask_streak", 0)
            ask_streak = ask_streak + 1 if ask_gap_ok else 0
            memory["_gap_ask_streak"] = ask_streak
            if ask_streak >= gap_confirm and ask_gap_ok and buy_cap > 0 and ask_z_ok:
                qty = min(ask1_vol, buy_cap, int(bid_size))
                if qty > 0:
                    orders.append(Order(self.product, ask1, qty))
                    buy_cap -= qty
                    memory["_gap_buy_px"].append(ask1)
                    if qty >= ask1_vol:
                        gap_swept_asks.add(ask1)
        final_remaining_bids = [p for p in remaining_bids if p not in gap_swept_bids]
        final_remaining_asks = [p for p in remaining_asks if p not in gap_swept_asks]
        fullcap_ask_posted = False
        fullcap_bid_posted = False
        if final_remaining_asks:
            ask_price = final_remaining_asks[0] - 1
        elif last_best_ask is not None:
            ask_price = last_best_ask + int(shift)   # LIVE alpha: far above
            if self.params.get("full_capacity_on_empty", False) and sell_cap > 0:
                orders.append(Order(self.product, ask_price, -sell_cap))
                memory["_gap_sell_px"].append(ask_price)
                fullcap_ask_posted = True
        if final_remaining_bids:
            bid_price = final_remaining_bids[0] + 1
        elif last_best_bid is not None:
            bid_price = last_best_bid - int(shift)   # LIVE alpha: far below
            if self.params.get("full_capacity_on_empty", False) and buy_cap > 0:
                orders.append(Order(self.product, bid_price, buy_cap))
                memory["_gap_buy_px"].append(bid_price)
                fullcap_bid_posted = True
        if fullcap_ask_posted:
            sell_cap = 0
        if fullcap_bid_posted:
            buy_cap = 0
        return orders, buy_cap, sell_cap, bid_price, ask_price
    def _apply_toxic_flow(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        buy_size: float,
        sell_size: float,
    ) -> Tuple[float, float]:
        toxic_threshold = float(self.params.get("toxic_threshold", 0.0))
        if toxic_threshold <= 0:
            return buy_size, sell_size
        toxic_window = int(self.params.get("toxic_window", 6))
        toxic_size_frac = float(self.params.get("toxic_size_frac", 0.75))
        flow_history = memory.setdefault("_flow_history", [])
        prev_best_bid = memory.get("_prev_best_bid")
        prev_best_ask = memory.get("_prev_best_ask")
        trades = state.market_trades.get(self.product, [])
        if toxic_window > 0 and prev_best_bid is not None and prev_best_ask is not None:
            for trade in trades:
                if trade.price >= prev_best_ask:
                    flow_history.append(trade.quantity)
                elif trade.price <= prev_best_bid:
                    flow_history.append(-trade.quantity)
            if len(flow_history) > toxic_window:
                del flow_history[:-toxic_window]
        flow_score = 0.0
        if flow_history:
            signed = sum(flow_history)
            total = sum(abs(x) for x in flow_history)
            if total > 0:
                flow_score = signed / total
        memory["_flow_score"] = flow_score
        if flow_score > toxic_threshold and sell_size > 0:
            sell_size = max(1.0, sell_size * toxic_size_frac)
        elif flow_score < -toxic_threshold and buy_size > 0:
            buy_size = max(1.0, buy_size * toxic_size_frac)
        return buy_size, sell_size
    def _apply_jump_filter(
        self,
        book: BookSnapshot,
        memory: Dict[str, Any],
        buy_size: float,
        sell_size: float,
    ) -> Tuple[float, float]:
        threshold = float(self.params.get("trend_jump_threshold", 0.0))
        if threshold <= 0:
            return buy_size, sell_size
        jump_size_frac = float(self.params.get("jump_size_frac", 0.5))
        prev_best_bid = memory.get("_prev_best_bid")
        prev_best_ask = memory.get("_prev_best_ask")
        bid_jumped = prev_best_bid is not None and book.best_bid == prev_best_bid + 1
        ask_jumped = prev_best_ask is not None and book.best_ask == prev_best_ask - 1
        if bid_jumped and sell_size > 0:
            sell_size = max(1.0, sell_size * jump_size_frac)
        if ask_jumped and buy_size > 0:
            buy_size = max(1.0, buy_size * jump_size_frac)
        return buy_size, sell_size
    def _compute_base_mid(
        self,
        raw_mid: float,
        book: BookSnapshot,
    ) -> float:
        vol_filter = int(self.params.get("mid_vol_filter", 0))
        if vol_filter <= 0:
            return raw_mid
        wall_bid = None
        for (p, v) in book.bid_levels:
            if v >= vol_filter:
                wall_bid = p
                break
        wall_ask = None
        for (p, v) in book.ask_levels:
            if v >= vol_filter:
                wall_ask = p
                break
        if wall_bid is None or wall_ask is None:
            return raw_mid
        return (wall_bid + wall_ask) / 2.0
    def _taker_cooldown_active(
        self,
        state: TradingState,
        memory: Dict[str, Any],
    ) -> Tuple[bool, bool]:
        cooldown = int(self.params.get("taker_cooldown_ticks", 0))
        if cooldown <= 0:
            return False, False
        now = int(state.timestamp)
        ts_increment = int(self.params.get("ts_increment", 100))
        last_buy = memory.get("_last_taker_buy_ts")
        last_sell = memory.get("_last_taker_sell_ts")
        buy_blocked = last_buy is not None and (now - last_buy) < cooldown * ts_increment
        sell_blocked = last_sell is not None and (now - last_sell) < cooldown * ts_increment
        return buy_blocked, sell_blocked
    def _update_taker_cooldown(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        taker_buy_px: Set[int],
        taker_sell_px: Set[int],
    ) -> None:
        now = int(state.timestamp)
        if taker_buy_px:
            memory["_last_taker_buy_ts"] = now
        if taker_sell_px:
            memory["_last_taker_sell_ts"] = now
    def _apply_inventory_bias(
        self,
        fair_value: float,
        position: int,
        memory: Dict[str, Any],
    ) -> float:
        gamma = float(self.params.get("inventory_aversion_gamma", 0.0))
        if gamma <= 0 or position == 0:
            return fair_value
        sigma = memory.get("sigma_smoothed", 1.0)
        return fair_value - gamma * position * (sigma ** 2)
    def _microprice_size_tilt(
        self,
        book: BookSnapshot,
        raw_mid: float,
        bid_size: float,
        ask_size: float,
    ) -> Tuple[float, float]:
        gain = float(self.params.get("microprice_size_gain", 0.0))
        if gain <= 0:
            return bid_size, ask_size
        threshold = float(self.params.get("microprice_size_threshold", 0.2))
        micro = self._microprice(book)
        delta = micro - raw_mid
        if abs(delta) < threshold:
            return bid_size, ask_size
        scale = 1.0 + gain * (abs(delta) - threshold)
        if delta > 0:  # bid-heavy -> expect up -> sell more
            return bid_size / scale, ask_size * scale
        else:  # ask-heavy -> expect down -> buy more
            return bid_size * scale, ask_size / scale
    def _apply_spread_widening(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> Tuple[Optional[int], Optional[int]]:
        threshold = float(self.params.get("spread_widen_vol_threshold", 0.0))
        if threshold <= 0 or bid_price is None or ask_price is None:
            return bid_price, ask_price
        if book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price
        sigma = memory.get("sigma_smoothed", 0.0)
        if sigma < threshold:
            return bid_price, ask_price
        extra = int(self.params.get("spread_widen_extra_ticks", 1))
        new_bid = max(1, bid_price - extra)
        new_ask = ask_price + extra
        if book.best_ask is not None:
            new_bid = min(new_bid, book.best_ask - 1)
        if book.best_bid is not None:
            new_ask = max(new_ask, book.best_bid + 1)
        return new_bid, new_ask
    def _effective_position(self, position: int) -> int:
        target = int(self.params.get("inventory_target", 0))
        return position - target
    def _apply_fill_rate_toxicity(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        bid_size: float,
        ask_size: float,
    ) -> Tuple[float, float]:
        window = int(self.params.get("fill_toxicity_window", 0))
        if window <= 0:
            return bid_size, ask_size
        history = memory.setdefault("_fill_history", [])
        for trade in state.own_trades.get(self.product, []):
            qty = float(trade.quantity)
            if trade.buyer == "SUBMISSION":
                history.append(qty)
            elif trade.seller == "SUBMISSION":
                history.append(-qty)
        if len(history) > window:
            del history[:-window]
        if not history:
            return bid_size, ask_size
        signed = sum(history)
        total = sum(abs(x) for x in history)
        if total <= 0:
            return bid_size, ask_size
        imbalance = signed / total
        threshold = float(self.params.get("fill_toxicity_threshold", 0.7))
        frac = float(self.params.get("fill_toxicity_frac", 0.5))
        if imbalance > threshold and bid_size > 0:
            bid_size = max(1.0, bid_size * frac)
        elif imbalance < -threshold and ask_size > 0:
            ask_size = max(1.0, ask_size * frac)
        return bid_size, ask_size
    def _apply_spread_zscore_skew(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        book: BookSnapshot,
        memory: Dict[str, Any],
    ) -> Tuple[Optional[int], Optional[int]]:
        window = int(self.params.get("spread_zscore_window", 0))
        if window <= 0 or bid_price is None or ask_price is None:
            return bid_price, ask_price
        if book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price
        spread = book.best_ask - book.best_bid
        buf: List[float] = memory.setdefault("_spread_buf", [])
        buf.append(spread)
        if len(buf) > window:
            del buf[:-window]
        if len(buf) < max(10, window // 4):
            return bid_price, ask_price
        mean = sum(buf) / len(buf)
        var = sum((x - mean) ** 2 for x in buf) / max(len(buf) - 1, 1)
        std = var ** 0.5
        if std < 1e-9:
            return bid_price, ask_price
        z = (spread - mean) / std
        threshold = float(self.params.get("spread_zscore_threshold", 1.5))
        if z < threshold:
            return bid_price, ask_price
        shift = int(self.params.get("spread_zscore_shift", 1))
        new_bid = min(book.best_ask - 1, bid_price + shift)
        new_ask = max(book.best_bid + 1, ask_price - shift)
        if new_bid >= new_ask:
            new_ask = new_bid + 1
        return new_bid, new_ask
    def _probe_tick0(
        self,
        book: BookSnapshot,
        state: TradingState,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        distances = self.params.get("probe_t0_distances")
        if not distances or book.best_bid is None or book.best_ask is None:
            return [], buy_cap, sell_cap
        max_ts = int(self.params.get("probe_t0_max_ts", 500))
        now = int(state.timestamp)
        if now > max_ts:
            return [], buy_cap, sell_cap
        if memory.get("_probe_t0_fired", False):
            return [], buy_cap, sell_cap
        qty = int(self.params.get("probe_t0_qty", 1))
        orders: List[Order] = []
        for dist in distances:
            d = int(dist)
            if d <= 0:
                continue
            b_qty = min(qty, buy_cap)
            a_qty = min(qty, sell_cap)
            if b_qty > 0:
                orders.append(Order(self.product, book.best_bid - d, b_qty))
                buy_cap -= b_qty
            if a_qty > 0:
                orders.append(Order(self.product, book.best_ask + d, -a_qty))
                sell_cap -= a_qty
        if orders:
            memory["_probe_t0_fired"] = True
        return orders, buy_cap, sell_cap
    def _apply_momentum_follower(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        memory: Dict[str, Any],
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        window = int(self.params.get("momentum_window", 0))
        if window <= 0:
            return [], buy_cap, sell_cap
        history = memory.setdefault("_momentum_history", [])
        prev_bid = memory.get("_prev_best_bid")
        prev_ask = memory.get("_prev_best_ask")
        for trade in state.market_trades.get(self.product, []):
            qty = float(trade.quantity)
            if prev_ask is not None and trade.price >= prev_ask:
                history.append(qty)
            elif prev_bid is not None and trade.price <= prev_bid:
                history.append(-qty)
        if len(history) > window:
            del history[:-window]
        if not history:
            return [], buy_cap, sell_cap
        signed = sum(history)
        total = sum(abs(x) for x in history)
        if total <= 0:
            return [], buy_cap, sell_cap
        flow = signed / total
        threshold = float(self.params.get("momentum_threshold", 0.8))
        qty = int(self.params.get("momentum_qty", 3))
        orders: List[Order] = []
        if flow > threshold and buy_cap > 0:
            asks = sorted(order_depth.sell_orders.keys())
            if asks:
                ask_p = asks[0]
                available = -order_depth.sell_orders[ask_p]
                q = min(qty, buy_cap, available)
                if q > 0:
                    orders.append(Order(self.product, ask_p, q))
                    buy_cap -= q
        elif flow < -threshold and sell_cap > 0:
            bids = sorted(order_depth.buy_orders.keys(), reverse=True)
            if bids:
                bid_p = bids[0]
                volume = order_depth.buy_orders[bid_p]
                q = min(qty, sell_cap, volume)
                if q > 0:
                    orders.append(Order(self.product, bid_p, -q))
                    sell_cap -= q
        return orders, buy_cap, sell_cap
    def _probe_quotes(
        self,
        book: BookSnapshot,
        state: TradingState,
        memory: Dict[str, Any],
        position: int,
        buy_cap: int,
        sell_cap: int,
    ) -> Tuple[List[Order], int, int]:
        probe_dist = int(self.params.get("probe_distance", 0))
        if probe_dist <= 0 or book.best_bid is None or book.best_ask is None:
            return [], buy_cap, sell_cap
        probe_qty = int(self.params.get("probe_qty", 1))
        probe_interval = int(self.params.get("probe_interval_ticks", 100))
        ts_increment = int(self.params.get("ts_increment", 100))
        now = int(state.timestamp)
        last_probe = memory.get("_last_probe_ts", -10**9)
        if (now - last_probe) < probe_interval * ts_increment:
            return [], buy_cap, sell_cap
        orders: List[Order] = []
        actual_bid_qty = min(probe_qty, buy_cap)
        actual_ask_qty = min(probe_qty, sell_cap)
        if actual_bid_qty > 0:
            probe_bid = book.best_bid - probe_dist
            orders.append(Order(self.product, probe_bid, actual_bid_qty))
            buy_cap -= actual_bid_qty
        if actual_ask_qty > 0:
            probe_ask = book.best_ask + probe_dist
            orders.append(Order(self.product, probe_ask, -actual_ask_qty))
            sell_cap -= actual_ask_qty
        if orders:
            memory["_last_probe_ts"] = now
        return orders, buy_cap, sell_cap
    def _asym_passive_skew(
        self,
        bid_price: Optional[int],
        ask_price: Optional[int],
        position: int,
        book: BookSnapshot,
    ) -> Tuple[Optional[int], Optional[int]]:
        skew_max = int(self.params.get("passive_unwind_skew_ticks", 0))
        if skew_max <= 0 or bid_price is None or ask_price is None:
            return bid_price, ask_price
        if book.best_bid is None or book.best_ask is None:
            return bid_price, ask_price  # preserve far-quote when one side empty
        trigger = float(self.params.get("passive_unwind_trigger", 0.3))
        limit = self.position_limit()
        pressure = abs(position) / max(1.0, float(limit))
        if pressure < trigger:
            return bid_price, ask_price
        scaled = (pressure - trigger) / max(1e-9, 1.0 - trigger)
        skew = int(round(skew_max * scaled))
        if skew <= 0:
            return bid_price, ask_price
        if position > 0:
            ask_price = max(book.best_bid + 1, ask_price - skew)
        elif position < 0:
            bid_price = min(book.best_ask - 1, bid_price + skew)
        return bid_price, ask_price
    def _apply_eod_flatten(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        position: int,
    ) -> Optional[List[Order]]:
        eod_ts = int(self.params.get("eod_flatten_ts", 0))
        if eod_ts <= 0 or state.timestamp < eod_ts or position == 0:
            return None
        orders: List[Order] = []
        if position > 0:
            for bid_price in sorted(order_depth.buy_orders, reverse=True):
                vol = order_depth.buy_orders[bid_price]
                qty = min(vol, position)
                if qty <= 0:
                    break
                orders.append(Order(self.product, bid_price, -qty))
                position -= qty
                if position == 0:
                    break
        else:
            need = -position
            for ask_price in sorted(order_depth.sell_orders):
                vol = -order_depth.sell_orders[ask_price]
                qty = min(vol, need)
                if qty <= 0:
                    break
                orders.append(Order(self.product, ask_price, qty))
                need -= qty
                if need == 0:
                    break
        return orders
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
    ) -> Tuple[List[Order], int, int]:
        quote_buy = min(buy_cap, int(bid_size))
        quote_sell = min(sell_cap, int(ask_size))
        inv_abs = abs(position) / float(limit) if limit else 0.0
        hard_stop_thr = 1.0 - float(self.params.get("pct_kept_for_takers", 0.2))
        if inv_abs >= hard_stop_thr:
            if position > 0:
                quote_buy = 0
            elif position < 0:
                quote_sell = 0
        orders: List[Order] = []
        if quote_buy > 0 and bid_price is not None:
            orders.append(Order(self.product, bid_price, quote_buy))
        if quote_sell > 0 and ask_price is not None:
            orders.append(Order(self.product, ask_price, -quote_sell))
        return orders, buy_cap - quote_buy, sell_cap - quote_sell
    def _log_taker_fills(
        self,
        state: TradingState,
        memory: Dict[str, Any],
        this_taker_buy_px: Set[int],
        this_taker_sell_px: Set[int],
    ) -> None:
        prev_taker_buy_px = set(memory.get("_taker_buy_px", []))
        prev_taker_sell_px = set(memory.get("_taker_sell_px", []))
        prev_gap_buy_px = set(memory.get("_gap_buy_px_prev", []))
        prev_gap_sell_px = set(memory.get("_gap_sell_px_prev", []))
        memory["_taker_buy_px"] = list(this_taker_buy_px)
        memory["_taker_sell_px"] = list(this_taker_sell_px)
        memory["_gap_buy_px_prev"] = list(memory.get("_gap_buy_px", []))
        memory["_gap_sell_px_prev"] = list(memory.get("_gap_sell_px", []))
        for trade in state.own_trades.get(self.product, []):
            if trade.buyer == "SUBMISSION":
                side, is_taker = "BUY", trade.price in prev_taker_buy_px
            else:
                side, is_taker = "SELL", trade.price in prev_taker_sell_px
            if is_taker:
                is_gap = (
                    (side == "BUY" and trade.price in prev_gap_buy_px)
                    or (side == "SELL" and trade.price in prev_gap_sell_px)
                )
                self.log_taker_fill(
                    state=state, memory=memory,
                    side=side, price=trade.price, quantity=trade.quantity,
                    gap_exploit=is_gap,
                )
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if order_depth.buy_orders and order_depth.sell_orders:
            eod_orders = self._apply_eod_flatten(state, order_depth, position)
            if eod_orders is not None:
                return eod_orders, 0
        if book.best_bid is None and book.best_ask is None:
            if memory.get("_last_mid") is None:
                return [], 0
        raw_mid = book.mid_price
        if raw_mid is None and book.best_bid is not None:
            raw_mid = float(book.best_bid)
        if raw_mid is None and book.best_ask is not None:
            raw_mid = float(book.best_ask)
        mid = raw_mid if raw_mid is not None else memory["_last_mid"]
        if raw_mid is not None:
            memory["_last_mid"] = raw_mid
        if self.params.get("use_microprice_as_fair", False):
            micro = self._microprice(book)
            base_mid = micro if micro else mid
        else:
            base_mid = self._compute_base_mid(mid, book)
        mid_smooth = self._smooth_mid(base_mid, memory)
        self._compute_zscore(base_mid, memory)
        sigma = self._update_volatility(base_mid, memory)
        fair_value = self._compute_anchor_signal(base_mid, book, mid_smooth, memory)
        eff_position = self._effective_position(position)
        fair_value = self._apply_inventory_bias(fair_value, eff_position, memory)
        limit = self.position_limit()
        inventory_ratio = position / float(limit) if limit else 0.0
        bid_price, ask_price, _ = self._compute_quote_prices(book, inventory_ratio, fair_value)
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        bid_size, ask_size = self._compute_sizes(position, limit)
        bid_factor, ask_factor = self._zscore_size_factors(memory)
        bid_size = max(0.0, bid_size * bid_factor)
        ask_size = max(0.0, ask_size * ask_factor)
        bid_size, ask_size = self._microprice_size_tilt(book, mid, bid_size, ask_size)
        base_edge = self._dynamic_take_edge(memory)
        buy_edge, sell_edge = self._compute_asym_take_edges(base_edge, eff_position, memory)
        buy_blocked, sell_blocked = self._taker_cooldown_active(state, memory)
        if buy_blocked:
            buy_edge = 1_000_000.0   # effectively block buy takers this tick
        if sell_blocked:
            sell_edge = 1_000_000.0
        taker_orders, buy_cap, sell_cap, taker_buy_px, taker_sell_px = self._fire_takers(
            order_depth, fair_value, bid_size, ask_size, buy_cap, sell_cap,
            buy_edge=buy_edge, sell_edge=sell_edge,
        )
        self._update_taker_cooldown(state, memory, taker_buy_px, taker_sell_px)
        gap_orders, buy_cap, sell_cap, bid_price, ask_price = self._gap_exploit(
            order_depth, memory, limit, bid_size, ask_size,
            bid_price, ask_price, buy_cap, sell_cap,
            taker_buy_px, taker_sell_px,
        )
        bid_price, ask_price = self._asym_passive_skew(bid_price, ask_price, eff_position, book)
        bid_price, ask_price = self._apply_spread_widening(bid_price, ask_price, book, memory)
        bid_price, ask_price = self._apply_spread_zscore_skew(bid_price, ask_price, book, memory)
        bid_size, ask_size = self._apply_toxic_flow(state, memory, bid_size, ask_size)
        bid_size, ask_size = self._apply_jump_filter(book, memory, bid_size, ask_size)
        bid_size, ask_size = self._apply_fill_rate_toxicity(state, memory, bid_size, ask_size)
        passive_orders, buy_cap, sell_cap = self._passive_quotes(
            bid_price, ask_price, bid_size, ask_size, buy_cap, sell_cap, position, limit
        )
        probe_orders, buy_cap, sell_cap = self._probe_quotes(
            book, state, memory, position, buy_cap, sell_cap,
        )
        passive_orders.extend(probe_orders)
        probe_t0_orders, buy_cap, sell_cap = self._probe_tick0(
            book, state, memory, buy_cap, sell_cap,
        )
        passive_orders.extend(probe_t0_orders)
        momentum_orders, buy_cap, sell_cap = self._apply_momentum_follower(
            state, order_depth, memory, buy_cap, sell_cap,
        )
        taker_orders.extend(momentum_orders)
        if book.best_bid is not None:
            memory["_prev_best_bid"] = book.best_bid
        if book.best_ask is not None:
            memory["_prev_best_ask"] = book.best_ask
        self._log_taker_fills(state, memory, taker_buy_px, taker_sell_px)
        z = memory.get("zscore")
        self.log_quote_snapshot(
            state=state, memory=memory,
            bid_price=bid_price, ask_price=ask_price,
            extras={
                "position": position,
                "fair": round(fair_value, 2),
                "buy_edge": round(buy_edge, 2),
                "sell_edge": round(sell_edge, 2),
                "bid_size": int(bid_size),
                "ask_size": int(ask_size),
                "zscore": round(z, 4) if z is not None else None,
                "sigma": round(sigma, 4),
                "flow_score": round(memory.get("_flow_score", 0.0), 3),
            },
        )
        sdq = int(self.params.get("osm_standing_deep_qty", 0))
        if sdq > 0:
            sh = int(self.params.get("OB_cleared_shift", 10))
            lbb = memory.get("_last_best_bid")
            lba = memory.get("_last_best_ask")
            ao = taker_orders + gap_orders + passive_orders
            ebp = {o.price for o in ao if o.quantity > 0}
            eap = {o.price for o in ao if o.quantity < 0}
            if lbb is not None and buy_cap > 0:
                db = int(lbb) - sh
                if db > 0 and db not in ebp:
                    q = min(sdq, buy_cap)
                    if q > 0:
                        passive_orders.append(Order(self.product, db, q))
            if lba is not None and sell_cap > 0:
                da = int(lba) + sh
                if da not in eap:
                    q = min(sdq, sell_cap)
                    if q > 0:
                        passive_orders.append(Order(self.product, da, -q))
        return taker_orders + gap_orders + passive_orders, 0
    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (m := memory.get("mid_smoothed")) is not None:
            out["MidSmooth"] = m
        if (a := memory.get("_anchor_ema")) is not None:
            out["AnchorEMA"] = a
        z = memory.get("zscore")
        if z is not None:
            out["Z"] = float(z)
        return out
DEFAULT_TIMESTAMP_UNITS_PER_DAY = 1_000_000.0
DEFAULT_TS_INCREMENT = 100.0
MIN_TTE_DAYS = 0.01
def timestamp_units_per_day_from_params(params: Mapping[str, Any]) -> float:
    explicit = params.get("timestamp_units_per_day")
    if explicit is not None:
        return max(float(explicit), 1.0)
    ticks_per_day = float(params.get("ticks_per_day", DEFAULT_TIMESTAMP_UNITS_PER_DAY / DEFAULT_TS_INCREMENT))
    ts_increment = float(params.get("ts_increment", DEFAULT_TS_INCREMENT))
    return max(ticks_per_day * ts_increment, 1.0)
def time_to_expiry_days(
    timestamp: int | float,
    initial_tte_days: int | float,
    *,
    timestamp_units_per_day: int | float = DEFAULT_TIMESTAMP_UNITS_PER_DAY,
    min_tte_days: int | float = MIN_TTE_DAYS,
) -> float:
    elapsed_days = max(float(timestamp), 0.0) / max(float(timestamp_units_per_day), 1.0)
    return max(float(min_tte_days), float(initial_tte_days) - elapsed_days)
def resolve_initial_tte_days(
    trader_data: str,
    default_tte_days: int | float,
    historical_tte_by_day: Mapping[Any, Any] | None = None,
) -> float:
    if not historical_tte_by_day or not trader_data:
        return float(default_tte_days)
    try:
        loaded = json.loads(trader_data)
    except Exception:
        return float(default_tte_days)
    if not isinstance(loaded, dict):
        return float(default_tte_days)
    meta = loaded.get("_backtest")
    if not isinstance(meta, dict) or "day" not in meta:
        return float(default_tte_days)
    day = meta.get("day")
    candidate_keys = [day, str(day)]
    try:
        candidate_keys.append(int(day))
    except (TypeError, ValueError):
        pass
    for key in candidate_keys:
        if key in historical_tte_by_day:
            try:
                return float(historical_tte_by_day[key])
            except (TypeError, ValueError):
                return float(default_tte_days)
    return float(default_tte_days)
_SQRT_2PI = math.sqrt(2.0 * math.pi)
def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
def _d1_d2(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0):
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        return None, None
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return d1, d2
def call_price(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    if T <= 0.0 or sigma <= 0.0:
        return max(0.0, S - K)
    d1, d2 = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return max(0.0, S - K)
    return S * math.exp(-q * T) * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
def call_delta(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    if T <= 0.0 or sigma <= 0.0:
        return 1.0 if S > K else (0.0 if S < K else 0.5)
    d1, _ = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return 0.5
    return math.exp(-q * T) * _norm_cdf(d1)
def call_gamma(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return 0.0
    return math.exp(-q * T) * _norm_pdf(d1) / (S * sigma * math.sqrt(T))
def call_vega(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    if T <= 0.0 or sigma <= 0.0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return 0.0
    return S * math.exp(-q * T) * _norm_pdf(d1) * math.sqrt(T)
def call_theta(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    if T <= 0.0 or sigma <= 0.0:
        return 0.0
    d1, d2 = _d1_d2(S, K, T, sigma, r, q)
    if d1 is None:
        return 0.0
    term1 = -S * _norm_pdf(d1) * sigma * math.exp(-q * T) / (2.0 * math.sqrt(T))
    term2 = -r * K * math.exp(-r * T) * _norm_cdf(d2)
    term3 = q * S * math.exp(-q * T) * _norm_cdf(d1)
    return term1 + term2 + term3
def put_price(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    c = call_price(S, K, T, sigma, r, q)
    return c - S * math.exp(-q * T) + K * math.exp(-r * T)
def put_delta(S: float, K: float, T: float, sigma: float, r: float = 0.0, q: float = 0.0) -> float:
    return call_delta(S, K, T, sigma, r, q) - math.exp(-q * T)
def call_implied_vol(
    target_price: float,
    S: float,
    K: float,
    T: float,
    r: float = 0.0,
    q: float = 0.0,
    *,
    sigma_init: float = 0.02,
    tol: float = 1e-5,
    max_iter: int = 30,
    sigma_min: float = 1e-5,
    sigma_max: float = 5.0,
) -> float | None:
    import math
    if T <= 0.0 or S <= 0.0 or K <= 0.0:
        return None
    lower_bound = max(S * math.exp(-q * T) - K * math.exp(-r * T), 0.0)
    upper_bound = S * math.exp(-q * T)
    if target_price < lower_bound - 1e-6 or target_price > upper_bound + 1e-6:
        return None
    sigma = sigma_init
    for _ in range(max_iter):
        price = call_price(S, K, T, sigma, r, q)
        diff = price - target_price
        if abs(diff) < tol:
            return sigma
        vega = call_vega(S, K, T, sigma, r, q)
        if vega < 1e-10:
            break  # switch to bisection
        sigma -= diff / vega
        if sigma < sigma_min or sigma > sigma_max:
            break  # switch to bisection
    lo, hi = sigma_min, sigma_max
    p_lo = call_price(S, K, T, lo, r, q)
    p_hi = call_price(S, K, T, hi, r, q)
    if p_lo > target_price or p_hi < target_price:
        return None
    for _ in range(max_iter * 2):
        mid = 0.5 * (lo + hi)
        p_mid = call_price(S, K, T, mid, r, q)
        if abs(p_mid - target_price) < tol:
            return mid
        if p_mid < target_price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
def put_implied_vol(
    target_price: float,
    S: float,
    K: float,
    T: float,
    r: float = 0.0,
    q: float = 0.0,
    **kwargs,
) -> float | None:
    import math
    call_target = target_price + S * math.exp(-q * T) - K * math.exp(-r * T)
    return call_implied_vol(call_target, S, K, T, r, q, **kwargs)
def _solve_normal_eqs(X_cols: List[List[float]], y: List[float]) -> Optional[List[float]]:
    n = len(y)
    d = len(X_cols)
    if n < d:
        return None
    XtX = [[0.0] * d for _ in range(d)]
    Xty = [0.0] * d
    for i in range(d):
        for j in range(d):
            s = 0.0
            for k in range(n):
                s += X_cols[i][k] * X_cols[j][k]
            XtX[i][j] = s
        s = 0.0
        for k in range(n):
            s += X_cols[i][k] * y[k]
        Xty[i] = s
    M = [row[:] + [Xty[i]] for i, row in enumerate(XtX)]  # augmented
    for i in range(d):
        max_row = i
        for r in range(i + 1, d):
            if abs(M[r][i]) > abs(M[max_row][i]):
                max_row = r
        M[i], M[max_row] = M[max_row], M[i]
        if abs(M[i][i]) < 1e-12:
            return None
        pivot = M[i][i]
        for c in range(d + 1):
            M[i][c] /= pivot
        for r in range(d):
            if r != i:
                factor = M[r][i]
                for c in range(d + 1):
                    M[r][c] -= factor * M[i][c]
    return [M[i][d] for i in range(d)]
def fit_smile_poly(
    strikes: Sequence[float],
    vols: Sequence[float],
    S: float,
    T: float,
    r: float = 0.0,
    q: float = 0.0,
    *,
    degree: int = 2,
    min_points: int = 3,
) -> Optional[List[float]]:
    F = S * math.exp((r - q) * T)
    ms: List[float] = []
    sigs: List[float] = []
    for K, v in zip(strikes, vols):
        if v is None or v <= 0.0 or K <= 0.0:
            continue
        ms.append(math.log(K / F))
        sigs.append(float(v))
    if len(ms) < max(min_points, degree + 1):
        return None
    cols: List[List[float]] = []
    for d in range(degree + 1):
        cols.append([m ** d for m in ms])
    return _solve_normal_eqs(cols, sigs)
def smile_predict(
    K: float,
    coeffs: Sequence[float],
    S: float,
    T: float,
    r: float = 0.0,
    q: float = 0.0,
) -> float:
    F = S * math.exp((r - q) * T)
    m = math.log(K / F)
    sig = 0.0
    for i, a in enumerate(coeffs):
        sig += a * (m ** i)
    return max(1e-5, sig)
def average_vol(vols: Sequence[Optional[float]]) -> Optional[float]:
    valid = [v for v in vols if v is not None and v > 0.0]
    if not valid:
        return None
    return sum(valid) / len(valid)
_STATE: Dict[str, Any] = {
    "ts": None,          # int — timestamp of current tick
    "smile": None,       # List[float] or None — last computed smile coeffs
    "spot": {},          # dict: underlying_symbol -> float mid
    "positions": {},     # dict: product -> int position (published by strategies)
}
def _ensure_current_tick(ts: int) -> None:
    if _STATE["ts"] != ts:
        _STATE["ts"] = ts
        _STATE["smile"] = None
        _STATE["spot"] = {}
        _STATE["positions"] = {}
def get_spot(state: TradingState, *, underlying: str) -> Optional[float]:
    ts = int(state.timestamp)
    _ensure_current_tick(ts)
    cached = _STATE["spot"].get(underlying)
    if cached is not None:
        return cached
    od = state.order_depths.get(underlying)
    if not od or not od.buy_orders or not od.sell_orders:
        return None
    bb = max(od.buy_orders.keys())
    ba = min(od.sell_orders.keys())
    spot = 0.5 * (bb + ba)
    _STATE["spot"][underlying] = spot
    return spot
def get_smile(
    state: TradingState,
    *,
    strikes: List[int],
    strike_prefix: str,
    S: float,
    T: float,
    sigma_floor: float,
    sigma_cap: float,
    prior_vol: float,
    degree: int = 2,
) -> Optional[List[float]]:
    ts = int(state.timestamp)
    _ensure_current_tick(ts)
    if _STATE["smile"] is not None:
        return _STATE["smile"]
    valid_strikes: List[float] = []
    valid_vols: List[float] = []
    for K in strikes:
        sym = f"{strike_prefix}{K}"
        od = state.order_depths.get(sym)
        if not od or not od.buy_orders or not od.sell_orders:
            continue
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        mid = 0.5 * (bb + ba)
        iv = call_implied_vol(mid, S, float(K), T, sigma_init=prior_vol)
        if iv is not None and sigma_floor <= iv <= sigma_cap:
            valid_strikes.append(float(K))
            valid_vols.append(iv)
    coeffs: Optional[List[float]] = None
    if len(valid_strikes) >= 3:
        coeffs = fit_smile_poly(valid_strikes, valid_vols, S, T, degree=degree)
    _STATE["smile"] = coeffs
    return coeffs
def publish_position(ts: int, product: str, position: int) -> None:
    _ensure_current_tick(ts)
    _STATE["positions"][product] = int(position)
def get_positions(ts: int) -> Dict[str, int]:
    _ensure_current_tick(ts)
    return dict(_STATE["positions"])
def snapshot() -> Dict[str, Any]:
    return {
        "ts": _STATE["ts"],
        "smile_present": _STATE["smile"] is not None,
        "spot_keys": list(_STATE["spot"].keys()),
        "positions": dict(_STATE["positions"]),
    }
def reset() -> None:
    _STATE["ts"] = None
    _STATE["smile"] = None
    _STATE["spot"] = {}
    _STATE["positions"] = {}
_DEFAULT_VEV_STRIKES: List[int] = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
class OptionMMBSStrategy(BaseStrategy):
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
        p = self._read_params(state)
        ts = int(state.timestamp)
        publish_position(ts, self.product, position)
        S = self._resolve_spot(state, memory, ts)
        if S is None:
            return [], 0
        own_mid = 0.5 * (book.best_bid + book.best_ask)
        sigma = self._resolve_sigma(
            state=state, memory=memory, own_mid=own_mid,
            S=S, K=p["K"], T=p["T"], ts=ts, params=p,
        )
        fair = call_price(S, p["K"], p["T"], sigma)
        self._record_diagnostics(memory, fair=fair, sigma=sigma, T=p["T"], S=S, tte0=p["tte0"])
        if fair < p["min_quote_price"]:
            memory["_skipped"] = 1
            return [], 0
        fair_skewed = fair - p["inv_bias_per_unit"] * position
        bid_px, ask_px = self._compute_quotes(book, fair_skewed, p)
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        orders: List[Order] = []
        if p["enable_takers"]:
            taker_orders, buy_cap, sell_cap = self._fire_takers(
                fair_skewed, book, order_depth, buy_cap, sell_cap, p,
            )
            orders.extend(taker_orders)
        orders.extend(self._post_passive(bid_px, ask_px, buy_cap, sell_cap, p["maker_size"]))
        return orders, 0
    def _read_params(self, state: TradingState) -> Dict[str, Any]:
        params = self.params
        tte0 = resolve_initial_tte_days(
            state.traderData,
            float(params.get("tte_days_initial", 5.0)),
            params.get("historical_tte_by_day"),
        )
        ts = int(state.timestamp)
        ts_per_day = timestamp_units_per_day_from_params(params)
        T = time_to_expiry_days(ts, tte0, timestamp_units_per_day=ts_per_day)
        return {
            "K": float(params["strike"]),
            "tte0": tte0,
            "T": max(0.01, T),
            "prior_vol": float(params.get("prior_vol", 0.02)),
            "maker_edge": int(params.get("maker_edge", 2)),
            "maker_size": int(params.get("maker_size", 20)),
            "take_edge": float(params.get("take_edge", 3.0)),
            "take_size": int(params.get("take_size", 40)),
            "use_smile": bool(params.get("use_smile", True)),
            "iv_ewma_alpha": float(params.get("iv_ewma_alpha", 0.3)),
            "sigma_floor": float(params.get("sigma_floor", 0.005)),
            "sigma_cap": float(params.get("sigma_cap", 0.10)),
            "enable_takers": bool(params.get("enable_takers", True)),
            "penny_improve_around_mkt": bool(params.get("penny_improve_around_mkt", False)),
            "min_quote_price": float(params.get("min_quote_price", 2.0)),
            "inv_bias_per_unit": float(params.get("inv_bias_per_unit", 0.02)),
            "underlying_symbol": params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"),
        }
    def _resolve_spot(
        self, state: TradingState, memory: Dict[str, Any], ts: int,
    ) -> Optional[float]:
        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
        return get_spot(state, underlying=underlying)
    def _resolve_sigma(
        self,
        *,
        state: TradingState,
        memory: Dict[str, Any],
        own_mid: float,
        S: float,
        K: float,
        T: float,
        ts: int,
        params: Dict[str, Any],
    ) -> float:
        iv_smooth = self._update_iv_ewma(own_mid, S, K, T, memory, params)
        shared = self._shared(memory)
        shared.setdefault("vev_iv", {})[K] = iv_smooth
        if not params["use_smile"]:
            return iv_smooth
        smile = self._get_or_fit_smile(state, shared, S, T, ts, params)
        if smile is None:
            return iv_smooth
        sigma = smile_predict(K, smile, S, T)
        return max(params["sigma_floor"], min(params["sigma_cap"], sigma))
    def _update_iv_ewma(
        self,
        own_mid: float,
        S: float,
        K: float,
        T: float,
        memory: Dict[str, Any],
        params: Dict[str, Any],
    ) -> float:
        iv = call_implied_vol(own_mid, S, K, T, sigma_init=params["prior_vol"])
        prev = memory.get("_iv_ewma")
        valid = iv is not None and params["sigma_floor"] <= iv <= params["sigma_cap"]
        if not valid:
            return prev if prev is not None else params["prior_vol"]
        if prev is None:
            memory["_iv_ewma"] = iv
            return iv
        alpha = params["iv_ewma_alpha"]
        iv_new = alpha * iv + (1.0 - alpha) * prev
        memory["_iv_ewma"] = iv_new
        return iv_new
    def _get_or_fit_smile(
        self,
        state: TradingState,
        shared: Dict[str, Any],
        S: float,
        T: float,
        ts: int,
        params: Dict[str, Any],
    ) -> Optional[List[float]]:
        strikes = params.get("smile_strikes") or _DEFAULT_VEV_STRIKES
        strike_prefix = str(params.get("strike_prefix", "VEV_"))
        return get_smile(
            state,
            strikes=list(strikes),
            strike_prefix=strike_prefix,
            S=S,
            T=T,
            sigma_floor=params["sigma_floor"],
            sigma_cap=params["sigma_cap"],
            prior_vol=params["prior_vol"],
        )
    def _compute_quotes(
        self,
        book: BookSnapshot,
        fair_skewed: float,
        params: Dict[str, Any],
    ) -> Tuple[int, int]:
        if params["penny_improve_around_mkt"]:
            bid_px = book.best_bid + 1
            ask_px = book.best_ask - 1
        else:
            bid_px = int(round(fair_skewed - params["maker_edge"]))
            ask_px = int(round(fair_skewed + params["maker_edge"]))
        if bid_px >= book.best_ask:
            bid_px = book.best_ask - 1
        if ask_px <= book.best_bid:
            ask_px = book.best_bid + 1
        bid_px = max(1, bid_px)       # floor (call options can't price below 1)
        ask_px = max(bid_px + 1, ask_px)
        if bid_px > book.best_ask:
            bid_px = -1
        if ask_px < book.best_bid:
            ask_px = -1
        return bid_px, ask_px
    def _fire_takers(
        self,
        fair_skewed: float,
        book: BookSnapshot,
        order_depth: OrderDepth,
        buy_cap: int,
        sell_cap: int,
        params: Dict[str, Any],
    ) -> Tuple[List[Order], int, int]:
        orders: List[Order] = []
        take_edge = params["take_edge"]
        take_size = params["take_size"]
        if book.best_ask is not None and buy_cap > 0:
            if (fair_skewed - book.best_ask) >= take_edge:
                qty = -order_depth.sell_orders[book.best_ask]
                take_qty = min(qty, buy_cap, take_size)
                if take_qty > 0:
                    orders.append(Order(self.product, book.best_ask, take_qty))
                    buy_cap -= take_qty
        if book.best_bid is not None and sell_cap > 0:
            if (book.best_bid - fair_skewed) >= take_edge:
                qty = order_depth.buy_orders[book.best_bid]
                take_qty = min(qty, sell_cap, take_size)
                if take_qty > 0:
                    orders.append(Order(self.product, book.best_bid, -take_qty))
                    sell_cap -= take_qty
        return orders, buy_cap, sell_cap
    def _post_passive(
        self,
        bid_px: int,
        ask_px: int,
        buy_cap: int,
        sell_cap: int,
        maker_size: int,
    ) -> List[Order]:
        orders: List[Order] = []
        if bid_px > 0 and buy_cap > 0:
            orders.append(Order(self.product, bid_px, min(maker_size, buy_cap)))
        if ask_px > 0 and sell_cap > 0:
            orders.append(Order(self.product, ask_px, -min(maker_size, sell_cap)))
        return orders
    def _shared(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        shared = memory.get("_shared")
        if not isinstance(shared, dict):
            shared = {}
            memory["_shared"] = shared
        return shared
    def _record_diagnostics(
        self,
        memory: Dict[str, Any],
        *,
        fair: float,
        sigma: float,
        T: float,
        S: float,
        tte0: float,
    ) -> None:
        memory["_bs_fair"] = fair
        memory["_sigma_use"] = sigma
        memory["_tte_days"] = T
        memory["_tte_initial_days"] = tte0
        memory["_spot"] = S
    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (f := memory.get("_bs_fair")) is not None:
            out["BS_fair"] = f
        if (s := memory.get("_sigma_use")) is not None:
            out["sigma_pct"] = s * 100
        if (T := memory.get("_tte_days")) is not None:
            out["TTE_days"] = T
        return out
PRODUCTS = {'VELVETFRUIT_EXTRACT': {'anchor_alpha': 0.02,
                         'anchor_drift_bound': 2.0,
                         'anchor_price': 5250.0,
                         'ar_gain': 0.3,
                         'ar_shift_source': 'mid_smooth',
                         'full_capacity_on_empty': True,
                         'inventory_aversion_gamma': 0.0015,
                         'last_ts_value': 999900,
                         'log_flush_ts': 1000,
                         'maker_size': 30,
                         'pct_kept_for_takers': 0.05,
                         'position_limit': 200,
                         'strategy': 'mm_first_v4_combo',
                         'take_edge_hi': 0.8,
                         'take_edge_lo': 0.3,
                         'tighten_ticks': 1,
                         'ts_increment': 100,
                         'unwind_take_edge': 3.0},
 'VEV_4000': {'enable_takers': False,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 40,
              'min_quote_price': 2.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 4000,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': True},
 'VEV_4500': {'boost_when_cheap': False,
              'edge_ticks': 0.0,
              'enable_takers': False,
              'entry_size': 30,
              'entry_size_boost': 1.5,
              'implied_vol_prior': 0.0125,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'passive_bid_size': 24,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'skip_when_expensive': True,
              'strategy': 'gamma_scalp_zgated',
              'strike': 4500,
              'take_edge': 3.0,
              'take_size': 40,
              'target_qty': 300,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'unwind_tte_threshold': 1.5,
              'use_smile': True,
              'zscore_boost_threshold': 1.0,
              'zscore_skip_threshold': 0.5,
              'zscore_window': 500},
 'VEV_5000': {'boost_when_cheap': False,
              'edge_ticks': 0.0,
              'enable_takers': False,
              'entry_size': 30,
              'entry_size_boost': 1.5,
              'implied_vol_prior': 0.0125,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'passive_bid_size': 24,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'skip_when_expensive': True,
              'strategy': 'gamma_scalp_zgated',
              'strike': 5000,
              'take_edge': 3.0,
              'take_size': 40,
              'target_qty': 300,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'unwind_tte_threshold': 1.5,
              'use_smile': True,
              'zscore_boost_threshold': 1.0,
              'zscore_skip_threshold': 0.5,
              'zscore_window': 500},
 'VEV_5100': {'boost_when_cheap': False,
              'edge_ticks': 0.0,
              'enable_takers': False,
              'entry_size': 30,
              'entry_size_boost': 1.5,
              'implied_vol_prior': 0.0125,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'passive_bid_size': 24,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'skip_when_expensive': True,
              'strategy': 'gamma_scalp_zgated',
              'strike': 5100,
              'take_edge': 3.0,
              'take_size': 40,
              'target_qty': 300,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'unwind_tte_threshold': 1.5,
              'use_smile': True,
              'zscore_boost_threshold': 1.0,
              'zscore_skip_threshold': 0.5,
              'zscore_window': 500},
 'VEV_5200': {'boost_when_cheap': False,
              'edge_ticks': 0.0,
              'enable_takers': False,
              'entry_size': 30,
              'entry_size_boost': 1.5,
              'implied_vol_prior': 0.0125,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'passive_bid_size': 24,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'skip_when_expensive': True,
              'strategy': 'gamma_scalp_zgated',
              'strike': 5200,
              'take_edge': 3.0,
              'take_size': 40,
              'target_qty': 300,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'unwind_tte_threshold': 1.5,
              'use_smile': True,
              'zscore_boost_threshold': 1.0,
              'zscore_skip_threshold': 0.5,
              'zscore_window': 500},
 'VEV_5300': {'boost_when_cheap': False,
              'edge_ticks': 0.0,
              'enable_takers': False,
              'entry_size': 30,
              'entry_size_boost': 1.5,
              'implied_vol_prior': 0.0125,
              'inv_bias_per_unit': 0.02,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 2,
              'maker_size': 20,
              'min_quote_price': 2.0,
              'passive_bid_size': 24,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'skip_when_expensive': True,
              'strategy': 'gamma_scalp_zgated',
              'strike': 5300,
              'take_edge': 3.0,
              'take_size': 40,
              'target_qty': 300,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'unwind_tte_threshold': 1.5,
              'use_smile': True,
              'zscore_boost_threshold': 1.0,
              'zscore_skip_threshold': 0.5,
              'zscore_window': 500},
 'VEV_5400': {'enable_takers': False,
              'inv_bias_per_unit': 0.04,
              'iv_ewma_alpha': 0.3,
              'last_ts_value': 999900,
              'log_flush_ts': 1000,
              'maker_edge': 1,
              'maker_size': 10,
              'min_quote_price': 1.0,
              'penny_improve_around_mkt': True,
              'position_limit': 300,
              'prior_vol': 0.0125,
              'sigma_cap': 0.1,
              'sigma_floor': 0.005,
              'strategy': 'option_mm_bs',
              'strike': 5400,
              'take_edge': 3.0,
              'take_size': 40,
              'timestamp_units_per_day': 1000000,
              'ts_increment': 100,
              'tte_days_initial': 5.0,
              'underlying_symbol': 'VELVETFRUIT_EXTRACT',
              'use_smile': False}}
STRATEGY_CLASSES = {"gamma_scalp_zgated": GammaScalpZGatedStrategy, "mm_first_v4_combo": MMFirstV4ComboStrategy, "option_mm_bs": OptionMMBSStrategy}
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
