"""Backtester entrypoint — ad hoc round 4 member/product experiments."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Dict, List

from datamodel import Order, TradingState

from prosperity.config import get_round_config
from prosperity.persistence import dump_state, load_state
from prosperity.strategies import build_strategy
from prosperity.strategies.base import BaseStrategy


def _parse_scalar(raw: str):
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "none":
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _apply_param_overrides(config):
    raw = os.environ.get("PROSPERITY_PARAM_OVERRIDES")
    if not raw:
        return config

    patched = dict(config)
    for block in raw.split(";"):
        block = block.strip()
        if not block or ":" not in block:
            continue
        symbol, payload = block.split(":", 1)
        symbol = symbol.strip()
        current = patched.get(symbol)
        if current is None:
            continue
        params = dict(current.params)
        for item in payload.split(","):
            item = item.strip()
            if not item or "=" not in item:
                continue
            key, value = item.split("=", 1)
            params[key.strip()] = _parse_scalar(value.strip())
        patched[symbol] = replace(current, params=params)
    return patched


def _load_config():
    member = os.environ.get("PROSPERITY_MEMBER", "champion")
    config = get_round_config(4, member)
    only_products = os.environ.get("PROSPERITY_ONLY_PRODUCTS")
    if only_products:
        keep = {symbol.strip() for symbol in only_products.split(",") if symbol.strip()}
        config = {symbol: pc for symbol, pc in config.items() if symbol in keep}
    return _apply_param_overrides(config)


class Trader:
    def __init__(self):
        config = _load_config()
        self.strategies: Dict[str, BaseStrategy] = {}
        for symbol, pc in config.items():
            merged = {"position_limit": pc.position_limit, **pc.params}
            self.strategies[symbol] = build_strategy(pc.strategy, symbol, merged)

    def bid(self) -> int:
        return 15

    def run(self, state: TradingState):
        saved = load_state(state.traderData)
        mems = saved.setdefault("products", {})
        result: Dict[str, List[Order]] = {}
        features: Dict[str, Dict[str, float]] = {}
        convs = 0
        for product, strat in self.strategies.items():
            if product not in state.order_depths:
                continue
            mem = mems.setdefault(product, {})
            orders, c = strat.on_tick(state, mem)
            result[product] = orders
            convs += c
            fp = strat.feature_prices(mem)
            if fp:
                features[product] = fp
        saved["last_timestamp"] = state.timestamp
        return result, convs, dump_state(saved), features
