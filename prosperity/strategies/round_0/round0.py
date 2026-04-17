from typing import Dict, List

from datamodel import Order, TradingState

from prosperity.config import ProductProfile, build_round_0_profiles
from prosperity.execution import quote_market, take_opportunities
from prosperity.features import estimate_fair_value
from prosperity.market import snapshot_from_order_depth
from prosperity.persistence import dump_state, load_state
from prosperity.risk import buy_capacity, sell_capacity


class BaseRound0Trader:
    profile_name = "champion"

    def __init__(self, profiles: Dict[str, ProductProfile] | None = None):
        self.profiles = profiles or build_round_0_profiles(self.profile_name)

    def bid(self) -> int:
        return 15

    def run(self, state: TradingState):
        saved_state = load_state(state.traderData)
        product_state = saved_state.setdefault("products", {})
        result: Dict[str, List[Order]] = {}

        for product, profile in self.profiles.items():
            order_depth = state.order_depths.get(product)
            if order_depth is None:
                continue

            snapshot = snapshot_from_order_depth(product, order_depth)
            current_position = state.position.get(product, 0)

            memory = product_state.setdefault(product, {})
            fair_value, _ = estimate_fair_value(snapshot, profile, memory)

            buy_limit = buy_capacity(current_position, profile.position_limit)
            sell_limit = sell_capacity(current_position, profile.position_limit)

            taking_orders, buy_limit, sell_limit, _ = take_opportunities(
                product,
                order_depth,
                fair_value,
                profile,
                buy_limit,
                sell_limit,
            )

            quoting_orders, _ = quote_market(
                product,
                snapshot,
                fair_value,
                current_position,
                profile,
                buy_limit,
                sell_limit,
            )

            result[product] = taking_orders + quoting_orders
            memory["last_position"] = current_position

        saved_state["last_timestamp"] = state.timestamp
        return result, 0, dump_state(saved_state)


class ChampionTrader(BaseRound0Trader):
    profile_name = "champion"


class LeoTrader(BaseRound0Trader):
    profile_name = "leo"


class TheoTrader(BaseRound0Trader):
    profile_name = "theo"


class PietroTrader(BaseRound0Trader):
    profile_name = "pietro"


class Trader(ChampionTrader):
    pass

