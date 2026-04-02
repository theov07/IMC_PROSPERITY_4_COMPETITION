from math import ceil, floor
from typing import Dict, List, Tuple

from datamodel import Order, OrderDepth

from prosperity.config import ProductProfile
from prosperity.market import BookSnapshot
from prosperity.risk import inventory_bias_ticks, quote_size


def take_opportunities(
    product: str,
    order_depth: OrderDepth,
    fair_value: float,
    profile: ProductProfile,
    buy_limit: int,
    sell_limit: int,
) -> Tuple[List[Order], int, int, Dict[str, int | float]]:
    orders: List[Order] = []
    bought = 0
    sold = 0

    remaining_buy = buy_limit
    remaining_sell = sell_limit

    for ask_price, ask_volume in sorted(order_depth.sell_orders.items(), key=lambda item: item[0]):
        available = -ask_volume
        if ask_price > fair_value - profile.take_edge or remaining_buy <= 0:
            break
        quantity = min(available, remaining_buy)
        if quantity > 0:
            orders.append(Order(product, ask_price, quantity))
            remaining_buy -= quantity
            bought += quantity

    for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), key=lambda item: item[0], reverse=True):
        if bid_price < fair_value + profile.take_edge or remaining_sell <= 0:
            break
        quantity = min(bid_volume, remaining_sell)
        if quantity > 0:
            orders.append(Order(product, bid_price, -quantity))
            remaining_sell -= quantity
            sold += quantity

    diagnostics: Dict[str, int | float] = {
        "taker_bought": bought,
        "taker_sold": sold,
        "remaining_buy": remaining_buy,
        "remaining_sell": remaining_sell,
    }
    return orders, remaining_buy, remaining_sell, diagnostics


def quote_market(
    product: str,
    snapshot: BookSnapshot,
    fair_value: float,
    position: int,
    profile: ProductProfile,
    buy_limit: int,
    sell_limit: int,
) -> Tuple[List[Order], Dict[str, int | float | None]]:
    orders: List[Order] = []

    bias_ticks = inventory_bias_ticks(position, profile.position_limit, profile)
    adjusted_fair = fair_value - bias_ticks

    target_bid = floor(adjusted_fair - profile.quote_half_spread)
    target_ask = ceil(adjusted_fair + profile.quote_half_spread)

    if profile.join_best and snapshot.best_bid is not None and snapshot.best_ask is not None:
        inside_bid = min(snapshot.best_bid + profile.improve_ticks, snapshot.best_ask - 1)
        inside_ask = max(snapshot.best_ask - profile.improve_ticks, snapshot.best_bid + 1)
        target_bid = max(target_bid, inside_bid)
        target_ask = min(target_ask, inside_ask)

    if snapshot.best_ask is not None:
        target_bid = min(target_bid, snapshot.best_ask - 1)
    if snapshot.best_bid is not None:
        target_ask = max(target_ask, snapshot.best_bid + 1)

    if target_ask <= target_bid:
        target_ask = target_bid + 1

    quote_buy = quote_size(
        buy_limit,
        position,
        profile.position_limit,
        profile,
        lean_to_unwind=position < 0,
    )
    quote_sell = quote_size(
        sell_limit,
        position,
        profile.position_limit,
        profile,
        lean_to_unwind=position > 0,
    )

    inventory_pressure = abs(position) / float(profile.position_limit) if profile.position_limit else 0.0
    if inventory_pressure >= 0.75:
        if position > 0:
            quote_buy = 0
        elif position < 0:
            quote_sell = 0

    if quote_buy > 0:
        orders.append(Order(product, target_bid, quote_buy))
    if quote_sell > 0:
        orders.append(Order(product, target_ask, -quote_sell))

    diagnostics: Dict[str, int | float | None] = {
        "adjusted_fair": adjusted_fair,
        "inventory_bias_ticks": bias_ticks,
        "target_bid": target_bid,
        "target_ask": target_ask,
        "quote_buy": quote_buy,
        "quote_sell": quote_sell,
    }
    return orders, diagnostics

