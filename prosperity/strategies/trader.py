"""Main Trader class — dispatches each product to its configured strategy."""

from __future__ import annotations

from typing import Any, Dict, List

from datamodel import Order, TradingState

from prosperity.config import ProductConfig, get_round_config
from prosperity.persistence import dump_state, load_state
from prosperity.strategies import build_strategy
from prosperity.strategies.base import BaseStrategy


# ── Change these two constants before each round submission ──────────
CURRENT_ROUND = 0
CURRENT_MEMBER = "champion"


class Trader:
    """Universal dispatcher.  Reads CURRENT_ROUND / CURRENT_MEMBER to decide
    which strategy to run per product."""

    def __init__(self):
        config = get_round_config(CURRENT_ROUND, CURRENT_MEMBER)
        self.strategies: Dict[str, BaseStrategy] = {}
        for symbol, pc in config.items():
            merged_params = {"position_limit": pc.position_limit, **pc.params}
            self.strategies[symbol] = build_strategy(pc.strategy, symbol, merged_params)

    def bid(self) -> int:
        return 15

    def run(self, state: TradingState):
        saved = load_state(state.traderData)
        product_memories = saved.setdefault("products", {})
        result: Dict[str, List[Order]] = {}
        total_conversions = 0

        for product, strategy in self.strategies.items():
            if product not in state.order_depths:
                continue
            memory = product_memories.setdefault(product, {})
            orders, conversions = strategy.on_tick(state, memory)
            result[product] = orders
            total_conversions += conversions

        saved["last_timestamp"] = state.timestamp
        return result, total_conversions, dump_state(saved)
