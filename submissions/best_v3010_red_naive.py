"""best_v3010_red_naive — v1610 + pca_residual_mr on OXYGEN_SHAKE_EVENING_BREATH/CHOCOLATE.

Needs SharedR5Context injected for pca_residual_mr to read group z-scores.
"""

from prosperity.config import get_round_config
from prosperity.persistence import dump_state, load_state
from prosperity.strategies import build_strategy
from prosperity.strategies.base import BaseStrategy
from prosperity.baskets import get_or_create_context

from datamodel import Order, TradingState
from typing import Dict, List


class Trader:
    def __init__(self):
        config = get_round_config(5, "best_v3010_red_naive")
        self.strategies: Dict[str, BaseStrategy] = {}
        for symbol, pc in config.items():
            merged = {"position_limit": pc.position_limit, **pc.params}
            self.strategies[symbol] = build_strategy(pc.strategy, symbol, merged)

    def bid(self) -> int:
        return 15

    def run(self, state: TradingState):
        saved = load_state(state.traderData)
        mems = saved.setdefault("products", {})
        ctx_root = saved.setdefault("_r5_ctx", {})
        ctx = get_or_create_context(ctx_root)
        ctx.update(state)

        result: Dict[str, List[Order]] = {}
        features: Dict[str, Dict[str, float]] = {}
        convs = 0
        for product, strat in self.strategies.items():
            if product not in state.order_depths:
                continue
            mem = mems.setdefault(product, {})
            mem["_ctx"] = ctx
            orders, c = strat.on_tick(state, mem)
            mem.pop("_ctx", None)
            result[product] = orders
            convs += c
            fp = strat.feature_prices(mem)
            if fp:
                features[product] = fp
        saved["last_timestamp"] = state.timestamp
        return result, convs, dump_state(saved), features
