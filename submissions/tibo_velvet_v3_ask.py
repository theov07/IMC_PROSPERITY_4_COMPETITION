"""Backtester entrypoint — tibo_velvet_v3_ask.

Products traded:
  VELVETFRUIT_EXTRACT  → VelvetMMV2   (passive MM + implicit delta hedge)
  VEV_4000             → VEVOptionMMV2 (symmetric MM, spread capture)
  VEV_5200             → VEVOptionMMV2 (bid-heavy, accumulate long calls)
  VEV_5300             → VEVOptionMMV2 (bid-heavy, accumulate long calls)
  VEV_5400             → VEVOptionMMV2 (bid-heavy, accumulate long calls)

Excluded: HYDROGEL_PACK, VEV_4500/5000/5100/5500/6000/6500 (set to None in config).

Execution order matters: VEV options run BEFORE VELVETFRUIT so that
vev_total_delta is fully accumulated before VelvetMMV2 reads it.
The submission wrapper resets vev_total_delta=0 at the start of each tick.
"""

from prosperity.config import get_round_config
from prosperity.persistence import dump_state, load_state
from prosperity.strategies import build_strategy
from prosperity.strategies.base import BaseStrategy

from datamodel import Order, TradingState
from typing import Any, Dict, List


class Trader:
    def __init__(self):
        config = get_round_config(3, "tibo_velvet_v3_ask")
        self.strategies: Dict[str, BaseStrategy] = {}
        for symbol, pc in config.items():
            merged = {"position_limit": pc.position_limit, **pc.params}
            self.strategies[symbol] = build_strategy(pc.strategy, symbol, merged)

    def run(self, state: TradingState):
        saved = load_state(state.traderData)
        mems  = saved.setdefault("products", {})
        # Reset vev_total_delta=0 each tick so VEV strategies accumulate cleanly.
        # VEV strategies run first (dict order) and add their position*delta here.
        # VelvetMMV2 runs last and reads the accumulated total for delta hedging.
        shared: Dict[str, Any] = {"timestamp": state.timestamp, "vev_total_delta": 0.0}
        result:   Dict[str, List[Order]] = {}
        features: Dict[str, Dict[str, float]] = {}
        convs = 0

        for product, strat in self.strategies.items():
            if product not in state.order_depths:
                continue
            mem = mems.setdefault(product, {})
            mem["_shared"] = shared
            orders, c = strat.on_tick(state, mem)
            result[product] = orders
            convs += c
            fp = strat.feature_prices(mem)
            if fp:
                features[product] = fp

        for mem in mems.values():
            if isinstance(mem, dict):
                mem.pop("_shared", None)

        saved["last_timestamp"] = state.timestamp
        return result, convs, dump_state(saved), features
