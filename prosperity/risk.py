"""Risk management — position capacity, inventory bias, quote sizing."""

from __future__ import annotations

from typing import Any


def buy_capacity(position: int, position_limit: int) -> int:
    return max(0, position_limit - position)


def sell_capacity(position: int, position_limit: int) -> int:
    return max(0, position_limit + position)


def inventory_bias_ticks(position: int, position_limit: int, config: Any) -> int:
    """Compute inventory-aware price bias in ticks.

    Accepts either a ProductProfile (legacy) or ProductConfig with params dict.
    """
    if position_limit <= 0:
        return 0

    # Support both old ProductProfile attrs and new ProductConfig.params dict
    if hasattr(config, "params") and isinstance(config.params, dict):
        aversion = config.params.get("inventory_aversion", 1.0)
        max_ticks = config.params.get("max_inventory_bias_ticks", 3)
    else:
        aversion = getattr(config, "inventory_aversion", 1.0)
        max_ticks = getattr(config, "max_inventory_bias_ticks", 3)

    normalized = position / float(position_limit)
    raw_bias = normalized * aversion * max_ticks
    raw_bias = max(-max_ticks, min(max_ticks, raw_bias))
    return int(round(raw_bias))


def quote_size(capacity: int, position: int, position_limit: int, config: Any, lean_to_unwind: bool) -> int:
    if capacity <= 0:
        return 0

    if hasattr(config, "params") and isinstance(config.params, dict):
        maker_size = config.params.get("maker_size", 12)
    else:
        maker_size = getattr(config, "maker_size", 12)

    size = min(capacity, maker_size)
    inventory_ratio = abs(position) / float(position_limit) if position_limit else 0.0

    if inventory_ratio >= 0.85:
        size = max(1, size // 2)

    if lean_to_unwind:
        size = min(capacity, max(size, min(maker_size * 2, abs(position) // 4 + 1)))

    return max(0, size)
