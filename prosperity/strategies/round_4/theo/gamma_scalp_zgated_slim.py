import json
import math

from datamodel import Order

from prosperity.strategies.base.base import BaseStrategy


_SQRT2 = math.sqrt(2.0)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def _call_price(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        return max(0.0, S - K)
    sqrt_t = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def _resolve_initial_tte_days(trader_data: str, default_tte_days: float) -> float:
    if trader_data:
        try:
            loaded = json.loads(trader_data)
            meta = loaded.get("_backtest", {}) if isinstance(loaded, dict) else {}
            day = meta.get("day")
            lookup = {1: 4.0, 2: 3.0, 3: 2.0}
            for key in (day, str(day), int(day) if day is not None else None):
                if key in lookup:
                    return float(lookup[key])
        except Exception:
            pass
    return default_tte_days


class R4GammaScalpZGatedSlimStrategy(BaseStrategy):
    def compute_orders(self, state, book, order_depth, position, memory):
        bb = book.best_bid
        ba = book.best_ask
        if bb is None or ba is None:
            return [], 0

        vod = state.order_depths.get(str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT")))
        if not vod or not vod.buy_orders or not vod.sell_orders:
            return [], 0
        spot = 0.5 * (max(vod.buy_orders) + min(vod.sell_orders))

        window = int(self.params.get("zscore_window", 500))
        buf = memory.setdefault("_zbuf", [])
        buf.append(spot)
        if len(buf) > window:
            del buf[:-window]
        z = None
        if len(buf) >= max(3, window // 4):
            mean = sum(buf) / len(buf)
            var = sum((x - mean) ** 2 for x in buf) / max(len(buf) - 1, 1)
            std = math.sqrt(var)
            if std >= 1e-9:
                z = (spot - mean) / std

        tte0 = _resolve_initial_tte_days(state.traderData, float(self.params.get("tte_days_initial", 4.0)))
        tte = max(0.01, tte0 - max(float(state.timestamp), 0.0) / float(self.params.get("timestamp_units_per_day", 1_000_000)))
        fair = _call_price(
            spot,
            float(self.params["strike"]),
            tte,
            float(self.params.get("implied_vol_prior", self.params.get("prior_vol", 0.0125))),
        )
        if fair < float(self.params.get("min_quote_price", 2.0)):
            return [], 0

        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)
        target_qty = int(self.params.get("target_qty", 300))
        passive_bid_size = int(self.params.get("passive_bid_size", 24))
        orders = []

        if tte < float(self.params.get("unwind_tte_threshold", 1.5)) or position >= target_qty:
            if sell_cap > 0 and position > 0:
                ask_px = int(ba) - 1
                if ask_px <= int(bb):
                    ask_px = int(bb) + 1
                qty = min(passive_bid_size, sell_cap, position)
                if qty > 0:
                    orders.append(Order(self.product, ask_px, -qty))
            return orders, 0

        if bool(self.params.get("skip_when_expensive", True)) and z is not None and z > float(self.params.get("zscore_skip_threshold", 1.0)):
            return [], 0

        if buy_cap > 0 and position < target_qty:
            ask_qty = -order_depth.sell_orders.get(int(ba), 0)
            if int(ba) <= fair + float(self.params.get("edge_ticks", 0.0)):
                qty = min(ask_qty, buy_cap, int(self.params.get("entry_size", 30)), target_qty - position)
                if qty > 0:
                    orders.append(Order(self.product, int(ba), qty))
                    buy_cap -= qty
                    position += qty

        if buy_cap > 0 and position < target_qty:
            bid_px = int(bb) + 1
            if bid_px < int(ba):
                qty = min(passive_bid_size, buy_cap, target_qty - position)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))

        return orders, 0
