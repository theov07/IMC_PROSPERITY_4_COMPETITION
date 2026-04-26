"""Backtester entrypoint — r3_combined_hybrid_options."""

from prosperity.config import get_round_config
from prosperity.persistence import dump_state, load_state
from prosperity.strategies import build_strategy
from prosperity.strategies.base import BaseStrategy

from datamodel import Order, TradingState
from typing import Dict, List


class Trader:
    def __init__(self):
        config = get_round_config(3, "r3_combined_hybrid_options")
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
