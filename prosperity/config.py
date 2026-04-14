"""Product configuration and round-level strategy registry.

Each product maps to a strategy name + params dict.  The Trader dispatcher
uses this to instantiate the right BaseStrategy subclass per product.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict


@dataclass(frozen=True)
class ProductConfig:
    """Everything needed to instantiate and configure a strategy for one product."""
    symbol: str
    strategy: str                          # key into STRATEGY_REGISTRY
    position_limit: int = 20
    params: Dict[str, Any] = field(default_factory=dict)


# ── Round 0 ──────────────────────────────────────────────────────────
ROUND_0: Dict[str, ProductConfig] = {
    "EMERALDS": ProductConfig(
        symbol="EMERALDS",
        strategy="market_maker",
        position_limit=80,
        params=dict(
            anchor_price=10000.0,
            fair_mode="anchored_microprice",
            anchor_weight=0.92,
            ema_alpha=0.08,
            take_edge=1.0,
            quote_half_spread=2,
            inventory_aversion=1.2,
            max_inventory_bias_ticks=4,
            maker_size=16,
            join_best=True,
            improve_ticks=1,
        ),
    ),
    "TOMATOES": ProductConfig(
        symbol="TOMATOES",
        strategy="market_maker",
        position_limit=80,
        params=dict(
            anchor_price=None,
            fair_mode="microprice_ema",
            anchor_weight=0.0,
            ema_alpha=0.18,
            take_edge=1.0,
            quote_half_spread=2,
            inventory_aversion=1.5,
            max_inventory_bias_ticks=5,
            maker_size=14,
            join_best=True,
            improve_ticks=1,
        ),
    ),
}

# ── Round templates (filled in when products are revealed) ───────────
# These are EXAMPLES showing how future rounds will be configured.
# Update them as soon as the round opens and products are disclosed.

ROUND_1: Dict[str, ProductConfig] = {
    "ASH_COATED_OSMIUM": ProductConfig(
        symbol="ASH_COATED_OSMIUM",
        strategy="naive_tight_mm",
        position_limit=80,
        params=dict(
            maker_size=20,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
    ),
    "INTARIAN_PEPPER_ROOT": ProductConfig(
        symbol="INTARIAN_PEPPER_ROOT",
        strategy="naive_tight_mm",
        position_limit=80,
        params=dict(
            maker_size=20,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
    ),
}

ROUND_2: Dict[str, ProductConfig] = {}
ROUND_3: Dict[str, ProductConfig] = {}
ROUND_4: Dict[str, ProductConfig] = {}
ROUND_5: Dict[str, ProductConfig] = {}


ROUNDS: Dict[int, Dict[str, ProductConfig]] = {
    0: ROUND_0,
    1: ROUND_1,
    2: ROUND_2,
    3: ROUND_3,
    4: ROUND_4,
    5: ROUND_5,
}


# ── Per-member overrides (for experimentation) ──────────────────────

def _override(base: ProductConfig, **kwargs) -> ProductConfig:
    """Return a copy of base with params updated."""
    new_params = {**base.params, **kwargs}
    return ProductConfig(
        symbol=base.symbol,
        strategy=kwargs.pop("strategy", base.strategy) if "strategy" in kwargs else base.strategy,
        position_limit=kwargs.pop("position_limit", base.position_limit) if "position_limit" in kwargs else base.position_limit,
        params=new_params,
    )


MEMBER_OVERRIDES: Dict[str, Dict[int, Dict[str, ProductConfig]]] = {
    "champion": {},   # uses base configs as-is
    "leo": {
        0: {
            "EMERALDS": _override(ROUND_0["EMERALDS"], quote_half_spread=2, maker_size=18, inventory_aversion=1.0),
            "TOMATOES": _override(ROUND_0["TOMATOES"], ema_alpha=0.14, take_edge=0.75, maker_size=12, inventory_aversion=1.2),
        },
    },
    "tibo_AvSt": {
        0: {
            "EMERALDS": _override(
                ROUND_0["EMERALDS"],
                strategy="avellaneda_stoikov",
                gamma=0.05,
                kappa=1.0,
                maker_size_base_pct=0.5, # in pct of position limit, scales down as inventory increases
                take_edge=5,
                pct_kept_for_takers=0.25, # capacity kept for aggressive takers
                
                min_half_spread=1.0,
                mid_smooth_window=50, # mid_smooth_window=0 => disabled
                mid_smooth_half_life=25,
                sigma_window=200,
                sigma_default=1.0,
                sigma_floor=0.5,
                sigma_half_life=60,

                ts_increment=100,
                last_ts_value=199900,       # IMC live: last timestamp of the day
                bt_last_ts_value=999900,    # internal backtest data: last timestamp of the day
                log_flush_ts=1000, # fires at 900, 1900, 2900 ... every 1000 timestamp units
            ),
            "TOMATOES": _override(
                ROUND_0["TOMATOES"],
                strategy="avellaneda_stoikov",
                gamma=0.1,
                kappa=1.0,
                maker_size_base_pct=0.35, # in pct of position limit, scales down as inventory increases
                take_edge=5,
                pct_kept_for_takers=0.25, # capacity kept for aggressive takers
                
                min_half_spread=1.0,
                mid_smooth_window=50, # mid_smooth_window=0 => disabled
                mid_smooth_half_life=25,
                sigma_window=200,
                sigma_default=1.0,
                sigma_floor=0.5,
                sigma_half_life=60,

                ts_increment=100,
                last_ts_value=199900,
                bt_last_ts_value=199900,
                log_flush_ts=1000, # fires at 900, 1900, 2900 ... every 1000 timestamp units
            ),
        },
    },
    "leo_naive": {
        0: {
            "EMERALDS": _override(
                ROUND_0["EMERALDS"],
                strategy="naive_tight_mm",
                maker_size=18,
                tighten_ticks=1,
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=199900,
            ),
            "TOMATOES": _override(
                ROUND_0["TOMATOES"],
                strategy="naive_tight_mm",
                maker_size=10,
                tighten_ticks=1,
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=199900,
            ),
        },
    },
    "leo_naive_v1_max": {
        0: {
            "EMERALDS": _override(
                ROUND_0["EMERALDS"],
                strategy="naive_tight_mm",
                maker_size=999,
                tighten_ticks=1,
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=199900,
            ),
            "TOMATOES": _override(
                ROUND_0["TOMATOES"],
                strategy="naive_tight_mm",
                maker_size=999,
                tighten_ticks=1,
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=199900,
            ),
        },
    },
    "leo_naive_v2": {
        0: {
            "EMERALDS": _override(
                ROUND_0["EMERALDS"],
                strategy="naive_tight_mm_v2",
                maker_size=18,
                tighten_ticks=1,
                max_tighten_ticks=4,
                decay_interval=3,
                inv_skew_ticks=0,
                log_flush_ts=1000,
                total_ticks=200000,
            ),
            "TOMATOES": _override(
                ROUND_0["TOMATOES"],
                strategy="naive_tight_mm_v2",
                maker_size=10,
                tighten_ticks=1,
                max_tighten_ticks=4,
                decay_interval=3,
                inv_skew_ticks=0,
                log_flush_ts=1000,
                total_ticks=200000,
            ),
        },
    },
    "leo_naive_v3": {
        0: {
            "EMERALDS": _override(
                ROUND_0["EMERALDS"],
                strategy="naive_tight_mm_v3",
                front_size=5,
                tighten_ticks=1,
                log_flush_ts=1000,
                total_ticks=200000,
            ),
            "TOMATOES": _override(
                ROUND_0["TOMATOES"],
                strategy="naive_tight_mm_v3",
                front_size=5,
                tighten_ticks=1,
                log_flush_ts=1000,
                total_ticks=200000,
            ),
        },
    },
    "leo_naive_v4": {
        0: {
            "EMERALDS": _override(
                ROUND_0["EMERALDS"],
                strategy="naive_tight_mm_v4",
                tighten_ticks=1,
                inv_skew_ticks=0,
                log_flush_ts=1000,
                total_ticks=200000,
            ),
            "TOMATOES": _override(
                ROUND_0["TOMATOES"],
                strategy="naive_tight_mm_v4",
                tighten_ticks=1,
                inv_skew_ticks=4,
                log_flush_ts=1000,
                total_ticks=200000,
            ),
        },
    },
    "leo_naive_v5": {
        0: {
            "EMERALDS": _override(
                ROUND_0["EMERALDS"],
                strategy="naive_tight_mm_v5",
                tighten_ticks=1,
                inv_skew_ticks=0,
                spread_extra_threshold=0,
                size_reduce_ratio=1.0,
                imb_threshold=0.2,
                log_flush_ts=1000,
                total_ticks=200000,
            ),
            "TOMATOES": _override(
                ROUND_0["TOMATOES"],
                strategy="naive_tight_mm_v5",
                tighten_ticks=1,
                inv_skew_ticks=4,
                spread_extra_threshold=0,
                size_reduce_ratio=1.0,
                imb_threshold=0.0,
                log_flush_ts=1000,
                total_ticks=200000,
            ),
        },
    },
    "leo_naive_v6": {
        0: {
            "EMERALDS": _override(
                ROUND_0["EMERALDS"],
                strategy="naive_tight_mm_v6",
                tighten_ticks=1,
                take_edge=1.0,
                log_flush_ts=1000,
                total_ticks=200000,
            ),
            "TOMATOES": _override(
                ROUND_0["TOMATOES"],
                strategy="naive_tight_mm_v6",
                tighten_ticks=1,
                take_edge=1.0,
                log_flush_ts=1000,
                total_ticks=200000,
            ),
        },
    },
    "leo_naive_v7": {
        0: {
            "EMERALDS": _override(
                ROUND_0["EMERALDS"],
                strategy="naive_tight_mm_v7",
                tighten_ticks=1,
                take_edge=1.0,
                asym_strength=0.0,
                spread_min_frac=1.0,
                flow_window=0,
                cooldown_ticks=0,
                pj_detect=0,
                pj_size_frac=1.0,
                pj_qty_threshold=0,
                qty_join_threshold=5,
                log_flush_ts=1000,
                total_ticks=200000,
            ),
            "TOMATOES": _override(
                ROUND_0["TOMATOES"],
                strategy="naive_tight_mm_v7",
                tighten_ticks=1,
                take_edge=1.0,
                asym_strength=0.0,
                spread_min_frac=1.0,
                flow_window=0,
                cooldown_ticks=0,
                pj_detect=0,
                pj_size_frac=1.0,
                pj_qty_threshold=0,
                qty_join_threshold=0,
                log_flush_ts=1000,
                total_ticks=200000,
            ),
        },
    },
    "leo_naive_v8": {
        0: {
            "EMERALDS": _override(
                ROUND_0["EMERALDS"],
                strategy="naive_tight_mm_v8",
                maker_size=80,
                tighten_ticks=1,
                take_edge=1.0,
                unwind_take_edge=0.5,
                inventory_soft_ratio=0.60,
                aggravate_min_frac=0.20,
                unwind_boost_frac=0.30,
                toxic_window=6,
                toxic_threshold=0.60,
                toxic_size_frac=0.75,
                jump_size_frac=0.50,
                log_flush_ts=0,
                total_ticks=10000000,
            ),
            "TOMATOES": _override(
                ROUND_0["TOMATOES"],
                strategy="naive_tight_mm_v8",
                maker_size=80,
                tighten_ticks=1,
                take_edge=1.0,
                unwind_take_edge=0.5,
                inventory_soft_ratio=0.55,
                aggravate_min_frac=0.20,
                unwind_boost_frac=0.30,
                toxic_window=6,
                toxic_threshold=0.60,
                toxic_size_frac=0.75,
                jump_size_frac=0.50,
                log_flush_ts=0,
                total_ticks=10000000,
            ),
        },
    },
    "leo_round1_naive": {
        1: {
            "ASH_COATED_OSMIUM": _override(
                ROUND_1["ASH_COATED_OSMIUM"],
                strategy="naive_tight_mm",
                maker_size=80,
                tighten_ticks=1,
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=999900,
            ),
            "INTARIAN_PEPPER_ROOT": _override(
                ROUND_1["INTARIAN_PEPPER_ROOT"],
                strategy="naive_tight_mm",
                maker_size=80,
                tighten_ticks=1,
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=999900,
            ),
        },
    },
    "theo": {
        0: {
            "EMERALDS": _override(ROUND_0["EMERALDS"], take_edge=0.5, quote_half_spread=1, maker_size=14, inventory_aversion=1.6),
            "TOMATOES": _override(ROUND_0["TOMATOES"], ema_alpha=0.22, take_edge=0.5, quote_half_spread=1, maker_size=16, inventory_aversion=1.8, max_inventory_bias_ticks=6),
        },
    },
    "pietro": {
        0: {
            "EMERALDS": _override(ROUND_0["EMERALDS"], quote_half_spread=3, maker_size=12),
            "TOMATOES": _override(ROUND_0["TOMATOES"], ema_alpha=0.10, take_edge=1.5, quote_half_spread=3, maker_size=10, inventory_aversion=1.0),
        },
    },
}


def get_round_config(round_num: int, member: str = "champion") -> Dict[str, ProductConfig]:
    """Build the product config for a given round + member."""
    base = dict(ROUNDS.get(round_num, {}))
    overrides = MEMBER_OVERRIDES.get(member, {}).get(round_num, {})
    base.update(overrides)
    return base
