"""Backtester entrypoint — r3_anchor_adaptive_champion (Codex design)."""
from prosperity.config import get_round_config
from prosperity.persistence import dump_state, load_state
from prosperity.strategies import build_strategy
from prosperity.strategies.base import BaseStrategy
from datamodel import Order, TradingState
from typing import Dict, List

class Trader:
    def __init__(self):
        config = get_round_config(3, "r3_anchor_adaptive_champion")
        self.strategies: Dict[str, BaseStrategy] = {}
        for symbol, pc in config.items():
            merged = {"position_limit": pc.position_limit, **pc.params}
            self.strategies[symbol] = build_strategy(pc.strategy, symbol, merged)
    def bid(self) -> int:
        return 800
    def run(self, state: TradingState):
        saved = load_state(state.traderData)
        mems = saved.setdefault("products", {})
        result: Dict[str, List[Order]] = {}
        features: Dict[str, Dict[str, float]] = {}
        convs = 0
        order_of_products = sorted(
            self.strategies.keys(),
            key=lambda p: (0 if p.startswith("VEV_") else 1, p),
        )
        for product in order_of_products:
            if product not in state.order_depths:
                continue
            strat = self.strategies[product]
            mem = mems.setdefault(product, {})
            orders, c = strat.on_tick(state, mem)
            result[product] = orders
            convs += c
            fp = strat.feature_prices(mem)
            if fp:
                features[product] = fp
        saved["last_timestamp"] = state.timestamp
        return result, convs, dump_state(saved), features
