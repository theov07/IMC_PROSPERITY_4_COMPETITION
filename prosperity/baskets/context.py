"""Shared per-tick R5 context: group indices + cross-product features.

Pattern: a SINGLE SharedR5Context lives in the trader's `traderData`. Each
strategy queries it via `get_or_create_context(memory_root)`. The context
ensures group indices and inter-group features are computed exactly once
per tick (cached by timestamp).

Usage in a Trader.run():

    saved = load_state(state.traderData)
    ctx = get_or_create_context(saved.setdefault('_r5_ctx', {}))
    ctx.update(state)  # populates mids, group indices

    for product, strat in self.strategies.items():
        mem = saved['products'].setdefault(product, {})
        mem['_ctx'] = ctx       # inject for the strategy's compute_orders
        ...

Strategies can then read from `memory["_ctx"]` to access:
    ctx.mid(product)            -> last mid
    ctx.group_index(group)      -> z-scored equal-weight index of the group
    ctx.group_zscore(group, w)  -> rolling z of group index
    ctx.partner_mid(p)          -> first product in a hand-picked pair list
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from datamodel import TradingState

from prosperity.baskets.groups import GROUPS, group_of


class SharedR5Context:
    """Per-tick computed snapshot of the R5 market.

    Persists rolling state in a single `memory_root` dict so traderData
    stays compact (one shared dict instead of replicated per-product state).
    """

    def __init__(self, memory_root: Dict[str, Any]):
        self.memory = memory_root
        self.timestamp: Optional[int] = None
        self.mids: Dict[str, float] = {}
        self._group_idx_cache: Dict[str, float] = {}
        # rolling buffers persisted across ticks
        self.memory.setdefault("_mid_means", {})  # product -> running mean
        self.memory.setdefault("_mid_stds", {})   # product -> running std (welford-ish)
        self.memory.setdefault("_mid_count", {})  # product -> count for online stats
        self.memory.setdefault("_group_buf", {})  # group -> last N indices for z

    def update(self, state: TradingState) -> None:
        """Compute mids + group indices for the current tick. Idempotent per ts."""
        if self.timestamp == state.timestamp:
            return
        self.timestamp = state.timestamp

        self.mids.clear()
        for sym, od in state.order_depths.items():
            if od.buy_orders and od.sell_orders:
                bb = max(od.buy_orders.keys())
                ba = min(od.sell_orders.keys())
                self.mids[sym] = (bb + ba) / 2.0

        # Update online z-stats per product (Welford lite)
        means = self.memory["_mid_means"]
        m2s = self.memory["_mid_stds"]
        cnts = self.memory["_mid_count"]
        for sym, m in self.mids.items():
            n = cnts.get(sym, 0) + 1
            mu_old = means.get(sym, 0.0)
            mu = mu_old + (m - mu_old) / n
            m2 = m2s.get(sym, 0.0) + (m - mu_old) * (m - mu)
            cnts[sym] = n
            means[sym] = mu
            m2s[sym] = m2

        self._group_idx_cache.clear()

    def mid(self, product: str) -> Optional[float]:
        return self.mids.get(product)

    def product_z(self, product: str) -> float:
        cnts = self.memory["_mid_count"]
        n = cnts.get(product, 0)
        if n < 30:
            return 0.0
        m = self.mids.get(product)
        if m is None:
            return 0.0
        mu = self.memory["_mid_means"][product]
        m2 = self.memory["_mid_stds"][product]
        var = m2 / max(n - 1, 1)
        std = math.sqrt(var)
        if std < 1e-9:
            return 0.0
        return (m - mu) / std

    def group_index(self, group: str) -> Optional[float]:
        """z-scored equal-weight average of the group's product z-scores."""
        if group in self._group_idx_cache:
            return self._group_idx_cache[group]
        members = GROUPS.get(group, [])
        zs = [self.product_z(p) for p in members if p in self.mids]
        if not zs:
            return None
        avg = sum(zs) / len(zs)
        self._group_idx_cache[group] = avg
        # also update group rolling buffer for group-level z
        buf = self.memory["_group_buf"].setdefault(group, [])
        buf.append(avg)
        if len(buf) > 500:
            buf[:] = buf[-500:]
        return avg

    def group_zscore(self, group: str, window: int = 200) -> float:
        """Rolling z of the group index over the last `window` ticks."""
        buf = self.memory["_group_buf"].get(group, [])
        if len(buf) < 30:
            return 0.0
        sub = buf[-window:]
        n = len(sub)
        mu = sum(sub) / n
        var = sum((x - mu) ** 2 for x in sub) / max(n - 1, 1)
        std = var ** 0.5
        if std < 1e-9:
            return 0.0
        cur = self.group_index(group)
        if cur is None:
            return 0.0
        return (cur - mu) / std

    # --- Pair helpers ---
    PAIRS: Dict[str, str] = {
        # SNACKPACKs : strongest neg-corr pair from R5 analysis
        "SNACKPACK_CHOCOLATE": "SNACKPACK_VANILLA",       # -0.974 levels, -0.915 returns
        "SNACKPACK_VANILLA": "SNACKPACK_CHOCOLATE",
        "SNACKPACK_RASPBERRY": "SNACKPACK_STRAWBERRY",     # -0.752 levels, -0.923 returns
        "SNACKPACK_STRAWBERRY": "SNACKPACK_RASPBERRY",
        "SNACKPACK_PISTACHIO": "SNACKPACK_RASPBERRY",     # -0.434 levels, -0.831 returns
        # PEBBLES : XL anti-correlated with each other
        "PEBBLES_XL": "PEBBLES_S",
        "PEBBLES_XS": "PEBBLES_XL",
        "PEBBLES_S": "PEBBLES_XL",
        "PEBBLES_M": "PEBBLES_XL",
        "PEBBLES_L": "PEBBLES_XL",
    }

    def partner_mid(self, product: str) -> Optional[float]:
        partner = self.PAIRS.get(product)
        if partner:
            return self.mids.get(partner)
        return None


def get_or_create_context(memory_root: Dict[str, Any]) -> SharedR5Context:
    """Return the shared context bound to a memory root dict."""
    return SharedR5Context(memory_root)
