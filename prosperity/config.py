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

ROUND_2: Dict[str, ProductConfig] = {
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
ROUND_3: Dict[str, ProductConfig] = {
    "HYDROGEL_PACK": ProductConfig(
        symbol="HYDROGEL_PACK",
        strategy="naive_tight_mm",
        position_limit=200,
        params=dict(
            maker_size=30,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
    ),
    "VELVETFRUIT_EXTRACT": ProductConfig(
        symbol="VELVETFRUIT_EXTRACT",
        strategy="naive_tight_mm",
        position_limit=200,
        params=dict(
            maker_size=30,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
    ),
    # 10 VELVETFRUIT_EXTRACT_VOUCHER options
    **{
        f"VEV_{k}": ProductConfig(
            symbol=f"VEV_{k}",
            strategy="option_mm_bs",
            position_limit=300,
            params=dict(
                strike=k,
                tte_days_initial=5.0,
                ticks_per_day=10000,
                timestamp_units_per_day=1000000,
                historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
                prior_vol=0.0125,   # ATM IV observed ~1.25% daily
                maker_edge=2,
                maker_size=20,
                take_edge=3.0,
                take_size=40,
                use_smile=True,
                iv_ewma_alpha=0.3,
                sigma_floor=0.005,
                sigma_cap=0.10,
                min_quote_price=2.0,    # skip quoting when BS fair < 2 (deep OTM)
                inv_bias_per_unit=0.02,
                enable_takers=False,    # naive: no aggressive takes (too risky on options)
                penny_improve_around_mkt=True,  # naive: penny-improve around book (stable MM)
                underlying_symbol="VELVETFRUIT_EXTRACT",
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=999900,
            ),
        )
        for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
    },
}
ROUND_4: Dict[str, ProductConfig] = {
    "HYDROGEL_PACK": ProductConfig(
        symbol="HYDROGEL_PACK",
        strategy="naive_tight_mm",
        position_limit=200,
        params=dict(
            maker_size=30,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
    ),
    "VELVETFRUIT_EXTRACT": ProductConfig(
        symbol="VELVETFRUIT_EXTRACT",
        strategy="naive_tight_mm",
        position_limit=200,
        params=dict(
            maker_size=30,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
    ),
    # 10 VELVETFRUIT_EXTRACT_VOUCHER options
    # R4 TTE: live = 4 days (vs 5 in R3), historical days 1/2/3 = 7/6/5
    **{
        f"VEV_{k}": ProductConfig(
            symbol=f"VEV_{k}",
            strategy="option_mm_bs",
            position_limit=300,
            params=dict(
                strike=k,
                tte_days_initial=4.0,  # R4 LIVE TTE
                ticks_per_day=10000,
                timestamp_units_per_day=1000000,
                historical_tte_by_day={1: 7.0, 2: 6.0, 3: 5.0},  # R4 backtest days
                prior_vol=0.0125,
                maker_edge=2,
                maker_size=20,
                take_edge=3.0,
                take_size=40,
                use_smile=True,
                iv_ewma_alpha=0.3,
                sigma_floor=0.005,
                sigma_cap=0.10,
                min_quote_price=2.0,
                inv_bias_per_unit=0.02,
                enable_takers=False,
                penny_improve_around_mkt=True,
                underlying_symbol="VELVETFRUIT_EXTRACT",
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=999900,
            ),
        )
        for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
    },
}
_R5_SIMPLE_MM = dict(
    maker_size=3,
    tighten_ticks=1,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)
_R5_PEBBLES_MM = _R5_SIMPLE_MM  # alias used by tibo_r5_v5/v6/best_v7 configs

ROUND_5: Dict[str, ProductConfig] = {
    **{
        sym: ProductConfig(symbol=sym, strategy="naive_tight_mm", position_limit=10, params=_R5_SIMPLE_MM)
        for sym in [
            "GALAXY_SOUNDS_BLACK_HOLES", "GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_PLANETARY_RINGS",
            "GALAXY_SOUNDS_SOLAR_FLAMES", "GALAXY_SOUNDS_SOLAR_WINDS",
            "SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER", "SLEEP_POD_NYLON", "SLEEP_POD_COTTON",
            "MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE", "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE",
            "PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL",
            "ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES", "ROBOT_LAUNDRY", "ROBOT_IRONING",
            "UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE", "UV_VISOR_RED", "UV_VISOR_MAGENTA",
            "TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_ECLIPSE_CHARCOAL",
            "TRANSLATOR_GRAPHITE_MIST", "TRANSLATOR_VOID_BLUE",
            "PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4",
            "OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH", "OXYGEN_SHAKE_MINT",
            "OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_GARLIC",
            "SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
            "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY",
        ]
    },
}


ROUNDS: Dict[int, Dict[str, ProductConfig]] = {
    0: ROUND_0,
    1: ROUND_1,
    2: ROUND_2,
    3: ROUND_3,
    4: ROUND_4,
    5: ROUND_5,
}

_R5_PRODUCTS = list(ROUND_5.keys())


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


MEMBER_OVERRIDES: Dict[str, Dict[int, Dict[str, ProductConfig | None]]] = {
    "champion": {},   # uses base configs as-is
    "tibo_mm_first": {
        1: {
            "ASH_COATED_OSMIUM": _override(
                ROUND_1["ASH_COATED_OSMIUM"],
                strategy="mm_first",
                inv_step_threshold=0.9,   # step to L2 (join) when |pos| >= 80% of limit
                take_edge=0.5,            # take if ask <= mid_smooth - 1 (or bid >= mid_smooth + 1)
                maker_size_base_pct=0.75,  # base passive size as % of position limit

                pct_kept_for_takers=0.1,  # capacity reserved for taker orders
                mid_smooth_window=50,
                mid_smooth_half_life=10,
                taker_buy_threshold = 9990,  # classify taker buys at >= this price
                taker_sell_threshold= 10025,

                gap_trigger_min=10,           # min tick gap L1→L2 to fire gap exploit
                gap_trigger_max_vol_pct=0.2, # L1 "thin" threshold: 10% of limit (=8 units)
                gap_trigger_confirm_ticks=1,  # require 2 consecutive ticks to filter transient gaps

                ts_increment=100,
                last_ts_value=99900,
                log_flush_ts=1000,
            ),
            "INTARIAN_PEPPER_ROOT": _override(
                ROUND_1["INTARIAN_PEPPER_ROOT"],
                strategy="mm_first",
                inv_step_threshold=0.8,
                take_edge=1.0,
                maker_size_base_pct=0.5,
                pct_kept_for_takers=0.2,
                mid_smooth_window=20,
                mid_smooth_half_life=10,

                gap_trigger_min=10,
                gap_trigger_max_vol_pct=0.10,
                gap_trigger_confirm_ticks=2,

                ts_increment=100,
                last_ts_value=99900,
                log_flush_ts=1000,
            ),
        },
    },
    "tibo_mm_first_v2": {
        1: {
            "ASH_COATED_OSMIUM": _override(
                ROUND_1["ASH_COATED_OSMIUM"],
                strategy="mm_first_v2",
                take_edge=1,
                take_edge_lo=0.7,       # edge when sigma <= 2
                take_edge_hi=1,       # edge when sigma >= 5
                take_edge_vol_lo=2.0,   # sigma lower bound
                take_edge_vol_hi=5.0,   # sigma upper bound

                maker_size_base_pct=0.5,
                pct_kept_for_takers=0.1,
                mid_smooth_window=50,
                mid_smooth_half_life=10,
                taker_buy_threshold=9990,
                taker_sell_threshold=10025,

                zscore_window=50,
                zscore_threshold=1,
                zscore_size_scale=0.5,
                zscore_max_scale=5.0,

                gap_trigger_min=10,
                OB_cleared_shift=89,
                gap_trigger_max_vol_pct=0.1,
                gap_trigger_confirm_ticks=1,
                zscore_gap_gate=1.5,

                zscore_skew_threshold=1.5,
                zscore_skew_ticks=1,
                zscore_skew_vol_cap=3,

                quote_trace_enabled=True,
                ts_increment=100,
                last_ts_value=99900,
                log_flush_ts=1000,
            ),
            "INTARIAN_PEPPER_ROOT": _override(
                ROUND_1["INTARIAN_PEPPER_ROOT"],
                strategy="mm_first_v2",
                inv_step_threshold=0.8,
                take_edge=1.0,
                maker_size_base_pct=0.5,
                pct_kept_for_takers=0.2,
                mid_smooth_window=20,
                mid_smooth_half_life=10,
                gap_trigger_min=10,
                gap_trigger_max_vol_pct=0.10,
                gap_trigger_confirm_ticks=2,
                zscore_window=1000,
                zscore_threshold=1.0,
                zscore_size_scale=0.5,
                zscore_max_scale=3.0,
                zscore_gap_gate=1.0,
                quote_trace_enabled=True,
                ts_increment=100,
                last_ts_value=99900,
                log_flush_ts=1000,
            ),
        },
    },
    "tibo_mm_first_v3": {
        2: {
            "ASH_COATED_OSMIUM": _override(
                ROUND_2["ASH_COATED_OSMIUM"],
                strategy="mm_first_v3",
                take_edge=1,
                maker_size_base_pct=0.3,
                pct_kept_for_takers=0.1,
                mid_smooth_window=60,
                mid_smooth_half_life=10,
                taker_buy_threshold=9990,
                taker_sell_threshold=10025,
                gap_trigger_min=10,
                gap_trigger_max_vol_pct=0.1,
                gap_trigger_confirm_ticks=1,
                quote_trace_enabled=True,
                ts_increment=100,
                last_ts_value=999900,
                log_flush_ts=1000,
            ),
            "INTARIAN_PEPPER_ROOT": _override(
                ROUND_2["INTARIAN_PEPPER_ROOT"],
                strategy="mm_first_v3",
                inv_step_threshold=0.8,
                take_edge=1.0,
                maker_size_base_pct=0.5,
                pct_kept_for_takers=0.2,
                mid_smooth_window=20,
                mid_smooth_half_life=10,
                gap_trigger_min=10,
                gap_trigger_max_vol_pct=0.10,
                gap_trigger_confirm_ticks=2,
                quote_trace_enabled=True,
                ts_increment=100,
                last_ts_value=999900,
                log_flush_ts=1000,
            ),
        },
    },

    "buy_and_hold": {
        1: {
            "ASH_COATED_OSMIUM": _override(
                ROUND_1["ASH_COATED_OSMIUM"],
                strategy="buy_and_hold",
            ),
            "INTARIAN_PEPPER_ROOT": _override(
                ROUND_1["INTARIAN_PEPPER_ROOT"],
                strategy="buy_and_hold",
            ),
        },
    },
    
    # V40: same logic as V38/V39 but ultra-conservative startup to eliminate
    # the early mark-to-market PnL dip.  We minimise taker activity during
    # the first ~20k ticks so inventory is built mostly via maker fills
    # (no spread cost), which flattens the initial drawdown curve.

    # ── Round 1 Leo fusion candidates (IPR only, ASH disabled) ──────────
    "leo_fusion_b": {
        1: {
            "ASH_COATED_OSMIUM": None,
            "INTARIAN_PEPPER_ROOT": _override(
                ROUND_1["INTARIAN_PEPPER_ROOT"],
                strategy="leo_fusion_b",
                maker_size=80,
                tighten_ticks=1,
                seed_slope=0.1015,
                block_size=100,
                min_completed_blocks=5,
                reg_horizon=25,
                reg_r2_floor=0.85,
                reg_r2_cap=0.98,
                reg_rmse_floor=1.0,
                reg_residual_reversion=0.25,
                bootstrap_confidence=0.55,
                # V5 inventory target params
                trend_inv_per_tick=26.0,
                resid_inv_per_z=7.0,
                trend_inventory_cap=74,
                startup_target=40,
                startup_end_ts=30000,
                target_gap_scale=26.0,
                trend_buy_boost_per_tick=0.24,
                trend_sell_boost_per_tick=0.20,
                cheap_buy_boost_per_z=0.18,
                rich_sell_boost_per_z=0.14,
                aggravate_cut=0.04,
                one_sided_target_gap=24,
                strong_trend_ticks=1.1,
                very_strong_trend_ticks=2.0,
                cheap_residual_z=0.9,
                rich_residual_z=1.0,
                max_bid_extra_ticks=2,
                max_ask_relax_ticks=2,
                # V18 quoting + take
                bull_threshold=1.0,
                bid_spread_bull=1.0,
                ask_spread_bull=9.0,
                neut_spread_bid=2.0,
                neut_spread_ask=5.0,
                take_buy_edge_bull=-8.0,
                take_sell_edge_bull=6.0,
                take_buy_edge_neut=2.0,
                take_sell_edge_neut=2.0,
                unwind_take_edge=10.0,
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=999900,
            ),
        },
    },
    "theo_round1_v24": {
        1: {
            "ASH_COATED_OSMIUM": _override(
                ROUND_1["ASH_COATED_OSMIUM"],
                strategy="naive_tight_mm_v10",
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
                signal_mode="mean_rev",
                anchor_price=10000.0,
                trend_sensitivity=0.4,
                trend_max_shift=5.0,
                trend_inv_target_per_tick=6.0,
                trend_take_boost=0.2,
                trend_jump_threshold=1.0,
                log_flush_ts=10000,
                total_ticks=10000000,
            ),
            "INTARIAN_PEPPER_ROOT": _override(
                ROUND_1["INTARIAN_PEPPER_ROOT"],
                strategy="naive_tight_mm_v24",
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
                signal_mode="trend",
                trend_alpha=0.005,
                trend_sensitivity=1.0,
                trend_max_shift=6.0,
                trend_inv_target_per_tick=6.0,
                trend_take_boost=0.4,
                trend_jump_threshold=1.5,
                trend_hold_threshold=4.0,
                trend_hold_min_position_frac=0.90,
                trend_hold_sell_size_frac=0.0,
                fast_alpha=0.22,
                dip_window=30,
                dip_trend_threshold=2.0,
                dip_min_pullback=4.0,
                dip_take_boost=0.35,
                dip_buy_size_boost=0.15,
                chase_max_extension=1.5,
                chase_take_edge_penalty=0.75,
                chase_take_size_frac=0.50,
                max_take_buy_size=6,
                core_position_frac=0.80,
                rebuy_block_buy_size_frac=0.15,
                rebuy_block_take_cap_frac=0.0,
                rebuy_block_extension_threshold=0.5,
                rebuy_block_position_floor=80,
                trim_trend_threshold=4.0,
                trim_extension_threshold=1.0,
                trim_sell_size=4,
                trim_ask_improve_ticks=1,
                trim_floor_position=75,
                trim_signal_edge=1.0,
                trim_cooldown_ticks=8,
                accum_band_trend_threshold=4.0,
                accum_mid_start_position=60,
                accum_top_start_position=75,
                accum_mid_take_boost=0.25,
                accum_mid_buy_size_boost=0.25,
                accum_mid_take_cap=8,
                accum_top_take_boost=0.10,
                accum_top_buy_size_boost=0.10,
                accum_top_take_cap=8,
                log_flush_ts=10000,
                total_ticks=10000000,
            ),
        },
    },
}


# ── V2 variants (block_size=200, R^2 ~0.99; rebalanced trend/residual weights
#    so residual_z can drive sells on spikes instead of being dominated by trend).
for _base in ("leo_fusion_b",):
    MEMBER_OVERRIDES[f"{_base}_v2"] = {
        1: {
            "ASH_COATED_OSMIUM": None,
            "INTARIAN_PEPPER_ROOT": _override(
                MEMBER_OVERRIDES[_base][1]["INTARIAN_PEPPER_ROOT"],
                block_size=200,
                trend_inv_per_tick=14.0,
                resid_inv_per_z=18.0,
            ),
        },
    }












MEMBER_OVERRIDES["leo_fusion_b_v9"] = {
    1: {
        "ASH_COATED_OSMIUM": None,
        "INTARIAN_PEPPER_ROOT": _override(
            MEMBER_OVERRIDES["leo_fusion_b_v2"][1]["INTARIAN_PEPPER_ROOT"],
            strategy="leo_fusion_b_v8",
            startup_target=80,
            trend_inventory_cap=80,
            trend_inv_per_tick=16.0,
            resid_inv_per_z=14.0,
            strong_trend_ticks=0.9,
            very_strong_trend_ticks=1.6,
            max_bid_extra_ticks=2,
            take_buy_edge_bull=-8.0,
            fastfill_target=80,
            fastfill_end_ts=12000,
            fastfill_buy_edge_boost=0.0,
            fastfill_min_passive_buy=10,
        ),
    },
}


MEMBER_OVERRIDES["leo_fusion_b_v10"] = {
    1: {
        "ASH_COATED_OSMIUM": None,
        "INTARIAN_PEPPER_ROOT": _override(
            MEMBER_OVERRIDES["leo_fusion_b_v9"][1]["INTARIAN_PEPPER_ROOT"],
            strategy="leo_fusion_b_v10",
            fastfill_deep_take_guard_end_ts=1000,
            fastfill_deep_take_max_gap_ticks=1,
        ),
    },
}


MEMBER_OVERRIDES["leo_osmium_only"] = {
    1: {
        "ASH_COATED_OSMIUM": _override(
            MEMBER_OVERRIDES["theo_round1_v24"][1]["ASH_COATED_OSMIUM"],
            strategy="osmium_mr",
            take_edge=1.75,
            tighten_ticks=1,
            unwind_take_edge=1.0,
            trend_sensitivity=0.6,
            trend_max_shift=5.0,
            trend_take_boost=0.2,
            trend_inv_target_per_tick=12.0,
            ar_gain=0.6,
            anchor_alpha=0.0,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}


MEMBER_OVERRIDES["champion_theo_all"] = {
    1: {
        "ASH_COATED_OSMIUM": _override(
            MEMBER_OVERRIDES["leo_osmium_only"][1]["ASH_COATED_OSMIUM"],
            strategy="osmium_mr_artifact",
        ),
        "INTARIAN_PEPPER_ROOT": MEMBER_OVERRIDES["leo_fusion_b_v10"][1]["INTARIAN_PEPPER_ROOT"],
    },
}


MEMBER_OVERRIDES["leo_osmium_v1"] = {
    1: {
        "ASH_COATED_OSMIUM": _override(
            MEMBER_OVERRIDES["theo_round1_v24"][1]["ASH_COATED_OSMIUM"],
            strategy="osmium_mr",
            take_edge=1.75,
            tighten_ticks=1,
            unwind_take_edge=1.0,
            trend_sensitivity=0.6,
            trend_max_shift=5.0,
            trend_take_boost=0.2,
            trend_inv_target_per_tick=12.0,
            ar_gain=0.6,
            anchor_alpha=0.0,
        ),
        "INTARIAN_PEPPER_ROOT": MEMBER_OVERRIDES["leo_fusion_b_v2"][1]["INTARIAN_PEPPER_ROOT"],
    },
}

# Round 2 port of leo_osmium_v1 — same strategies, same params.
# Lets grid_search target round 2 data while patching round 2 overrides.
MEMBER_OVERRIDES["leo_round2_v1"] = {
    2: {
        "ASH_COATED_OSMIUM": MEMBER_OVERRIDES["leo_osmium_v1"][1]["ASH_COATED_OSMIUM"],
        "INTARIAN_PEPPER_ROOT": MEMBER_OVERRIDES["leo_osmium_v1"][1]["INTARIAN_PEPPER_ROOT"],
    },
}

# Round 2 port of tibo_mm_first_v2 — for product-by-product comparison.
MEMBER_OVERRIDES["tibo_round2_v1"] = {
    2: {
        "ASH_COATED_OSMIUM": MEMBER_OVERRIDES["tibo_mm_first_v2"][1]["ASH_COATED_OSMIUM"],
        "INTARIAN_PEPPER_ROOT": MEMBER_OVERRIDES["tibo_mm_first_v2"][1]["INTARIAN_PEPPER_ROOT"],
    },
}

# First Round 2 champion candidate — Leo strategies + Tibo-style hole-in-OB sweep on both products.
# OSMIUM: osmium_mr_v2 (osmium_mr + gap exploit) with tuned take_edge/ar_gain/inv_soft from gs1..gs5.
# IPR:    leo_fusion_b_gap (leo_fusion_b + gap exploit) baseline params.
MEMBER_OVERRIDES["first_sb_leo_round2"] = {
    2: {
        "ASH_COATED_OSMIUM": _override(
            MEMBER_OVERRIDES["leo_osmium_v1"][1]["ASH_COATED_OSMIUM"],
            strategy="osmium_modulaire",
            take_edge=1.5,
            ar_gain=0.3,
            inventory_soft_ratio=0.9,
            aggravate_min_frac=0.2,
            unwind_boost_frac=0.3,
            gap_trigger_min=20,
            gap_trigger_max_vol_pct=0.15,
            gap_trigger_confirm_ticks=2,
        ),
        "INTARIAN_PEPPER_ROOT": _override(
            MEMBER_OVERRIDES["leo_osmium_v1"][1]["INTARIAN_PEPPER_ROOT"],
            strategy="pepper_modulaire",
            gap_trigger_min=8,
            gap_trigger_max_vol_pct=0.15,
            gap_trigger_confirm_ticks=1,
            empty_side_shift=5,
            gap_scout_floor_position=78,
            gap_scout_min_gap=3,
            gap_scout_size_limit=7,
            gap_scout_recent_ask_window=6,
            gap_scout_early_start_ts=0,
            gap_scout_early_end_ts=999900,
            gap_scout_mid_start_ts=0,
            gap_scout_mid_end_ts=0,
            gap_scout_late_start_ts=0,
            gap_scout_late_end_ts=0,
            gap_rebuy_window=2500,
            gap_rebuy_min_discount=20.0,
            gap_rebuy_buy_edge=-10.0,
            gap_rebuy_take_cap=8,
            hold_sell_size=1,
            hold_sell_offset=0,
        ),
    },
}


MEMBER_OVERRIDES["osmium_sb_leo_round2"] = {
    2: {
        "ASH_COATED_OSMIUM": MEMBER_OVERRIDES["first_sb_leo_round2"][2]["ASH_COATED_OSMIUM"],
        "INTARIAN_PEPPER_ROOT": None,
    },
}


MEMBER_OVERRIDES["pepper_sb_leo_round2"] = {
    2: {
        "ASH_COATED_OSMIUM": None,
        "INTARIAN_PEPPER_ROOT": MEMBER_OVERRIDES["first_sb_leo_round2"][2]["INTARIAN_PEPPER_ROOT"],
    },
}


# Theo's ask-exploit strategy ported to flat-modular style (Round 2).
# Params mirror test_theo submission (theo_ask_exploit_gap_generalised2).
MEMBER_OVERRIDES["theo_sb_round2"] = {
    2: {
        "ASH_COATED_OSMIUM": None,
        "INTARIAN_PEPPER_ROOT": ProductConfig(
            symbol="INTARIAN_PEPPER_ROOT",
            strategy="ask_exploit_modulaire",
            position_limit=80,
            params=dict(
                aggravate_cut=0.04,
                ask_spread_bull=9.0,
                bid_spread_bull=1.0,
                block_size=200,
                bootstrap_confidence=0.55,
                bull_threshold=1.0,
                cheap_buy_boost_per_z=0.18,
                cheap_residual_z=0.9,
                fastfill_buy_edge_boost=0.0,
                fastfill_deep_take_guard_end_ts=1000,
                fastfill_deep_take_max_gap_ticks=1,
                fastfill_end_ts=12000,
                fastfill_min_passive_buy=10,
                fastfill_target=80,
                dip_threshold=1.0,
                chase_threshold=1.25,
                last_ts_value=999900,
                log_flush_ts=1000,
                maker_size=80,
                max_bid_extra_ticks=2,
                min_completed_blocks=5,
                neut_spread_ask=5.0,
                neut_spread_bid=2.0,
                one_sided_target_gap=24,
                position_limit=80,
                reg_horizon=25,
                reg_r2_cap=0.98,
                reg_r2_floor=0.85,
                reg_residual_reversion=0.25,
                reg_rmse_floor=1.0,
                resid_inv_per_z=14.0,
                rich_residual_z=1.0,
                rich_sell_boost_per_z=0.14,
                seed_slope=0.1015,
                startup_anchor_bid_spread=1.0,
                startup_anchor_gap_ticks=1,
                startup_anchor_size=4,
                startup_chase_passive_buy=1,
                startup_chase_take_cap=1,
                startup_chase_take_edge=4.0,
                startup_cold_join_ticks=0,
                startup_cold_passive_buy=3,
                startup_cold_take_cap=4,
                startup_cold_take_edge=3.0,
                startup_delayed_finish_ts=3000,
                startup_dip_take_edge_boost=1.0,
                startup_end_ts=30000,
                startup_fast_passive_buy=8,
                startup_fast_take_cap=12,
                startup_fast_target=32,
                startup_post_pullback_target=64,
                startup_pre_pullback_target=48,
                startup_pullback_ticks=2.0,
                startup_release_take_cap=8,
                startup_release_stretch=1.0,
                startup_target=80,
                strong_trend_ticks=0.9,
                take_buy_edge_bull=-8.0,
                take_buy_edge_neut=2.0,
                take_sell_edge_neut=2.0,
                target_gap_scale=26.0,
                trend_buy_boost_per_tick=0.24,
                trend_inv_per_tick=16.0,
                trend_inventory_cap=80,
                trend_sell_boost_per_tick=0.2,
                ts_increment=100,
                unwind_take_edge=10.0,
                very_strong_trend_ticks=1.6,
                fv_alpha=0.05,
                short_alpha=0.22,
                slope_window=20,
                trim_reference_slope_weight=0.15,
                trim_start_position=79,
                trim_floor_position=78,
                trim_extension_threshold=0.75,
                trim_signal_edge=1.0,
                trim_sell_size=1,
                trim_cooldown_ticks=20,
                trim_take_position=80,
                trim_take_edge=2.0,
                trim_take_stretch=999.0,
                trim_take_sell_size=1,
                trim_ask_local_edge=0.0,
                rebuy_block_ticks=25,
                ask_gap_quote_size=8,
                ask_gap_sell_enable_position=80,
                gap_fill_min_premium=35,
                hold_sell_size=0,
                hold_sell_offset=0,
                gap_rebuy_buy_edge=-10.0,
                gap_rebuy_min_discount=20.0,
                gap_rebuy_passive_buy=6,
                gap_rebuy_take_cap=8,
                gap_rebuy_window=2500,
                gap_trap_arm_streak=2,
                gap_trap_base_size=4,
                gap_trap_clear_after=4,
                gap_trap_floor_position=80,
                gap_trap_fragile_ask_window=6,
                gap_trap_min_gap=3,
                gap_trap_min_imbalance=-0.05,
                gap_trap_min_trend=0.0,
                gap_trap_premium_extra=2,
                gap_trap_premium_size=3,
                gap_trap_premium_streak=2,
                gap_trap_recent_ask_window=12,
                gap_trap_top_ask_max=12,
                empty_side_shift=85,
            ),
        ),
    },
}




MEMBER_OVERRIDES["theo_best_generalized"] = {
    1: {
        "ASH_COATED_OSMIUM": None,
        "INTARIAN_PEPPER_ROOT": _override(
            ROUND_1["INTARIAN_PEPPER_ROOT"],
            strategy="theo_best_generalized",
            # Block OLS signal
            block_size=200,
            min_completed_blocks=5,
            seed_slope=0.1015,
            reg_horizon=25,
            reg_r2_floor=0.85,
            reg_r2_cap=0.98,
            reg_rmse_floor=1.0,
            reg_residual_reversion=0.25,
            bootstrap_confidence=0.55,
            # Inventory model
            trend_inv_per_tick=16.0,
            resid_inv_per_z=14.0,
            trend_inventory_cap=80,
            target_gap_scale=26.0,
            trend_buy_boost_per_tick=0.24,
            trend_sell_boost_per_tick=0.20,
            cheap_buy_boost_per_z=0.18,
            rich_sell_boost_per_z=0.14,
            aggravate_cut=0.04,
            one_sided_target_gap=24,
            startup_target=80,
            startup_end_ts=30000,
            # Regime thresholds
            bull_threshold=1.0,
            bear_threshold=-1.0,
            strong_trend_ticks=0.9,
            very_strong_trend_ticks=1.6,
            cheap_residual_z=0.9,
            rich_residual_z=1.0,
            max_bid_extra_ticks=2,
            max_ask_relax_ticks=2,
            # Quote spreads
            bid_spread_bull=1.0,
            ask_spread_bull=9.0,
            neut_spread_bid=2.0,
            neut_spread_ask=5.0,
            # Build phase
            fastfill_target=80,
            fastfill_end_ts=12000,
            fastfill_min_passive_buy=10,
            fastfill_buy_edge_boost=0.0,
            fastfill_deep_take_guard_end_ts=1000,
            fastfill_deep_take_max_gap_ticks=1,
            build_bid_offset=1,
            build_block_counter_edge=1_000_000.0,
            # Taker edges
            take_buy_edge_bull=-8.0,
            take_sell_edge_bull=6.0,
            take_buy_edge_neut=2.0,
            take_sell_edge_neut=2.0,
            unwind_take_edge=10.0,
            # Trim system
            short_alpha=0.15,
            trim_start_position=80,
            trim_floor_position=79,
            trim_stretch_threshold=1.5,
            trim_sell_size=1,
            trim_cooldown_ticks=20,
            trim_ask_mid_offset=5.0,
            trim_take_enabled=False,
            trim_take_stretch=999.0,
            trim_take_sell_size=1,
            rebuy_block_ticks=3,
            # Sizing
            maker_size=80,
            # Logging
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
            quote_trace_enabled=True,
        ),
    },
}


MEMBER_OVERRIDES["theo_root_ask_gap_generalised"] = {
    2: {
        "ASH_COATED_OSMIUM": None,
        "INTARIAN_PEPPER_ROOT": _override(
            ROUND_2["INTARIAN_PEPPER_ROOT"],
            strategy="theo_root_ask_gap_generalised",
            aggravate_cut=0.04,
            ask_spread_bull=9.0,
            bid_spread_bull=1.0,
            block_size=200,
            bootstrap_confidence=0.55,
            bull_threshold=1.0,
            cheap_buy_boost_per_z=0.18,
            cheap_residual_z=0.9,
            fastfill_buy_edge_boost=0.0,
            fastfill_deep_take_guard_end_ts=1000,
            fastfill_deep_take_max_gap_ticks=1,
            fastfill_end_ts=12000,
            fastfill_min_passive_buy=10,
            fastfill_target=80,
            dip_threshold=1.0,
            chase_threshold=1.25,
            last_ts_value=999900,
            log_flush_ts=1000,
            maker_size=80,
            max_bid_extra_ticks=2,
            min_completed_blocks=5,
            neut_spread_ask=5.0,
            neut_spread_bid=2.0,
            one_sided_target_gap=24,
            position_limit=80,
            reg_horizon=25,
            reg_r2_cap=0.98,
            reg_r2_floor=0.85,
            reg_residual_reversion=0.25,
            reg_rmse_floor=1.0,
            resid_inv_per_z=14.0,
            rich_residual_z=1.0,
            rich_sell_boost_per_z=0.14,
            seed_slope=0.1015,
            startup_anchor_bid_spread=1.0,
            startup_anchor_gap_ticks=1,
            startup_anchor_size=4,
            startup_chase_passive_buy=1,
            startup_chase_take_cap=1,
            startup_chase_take_edge=4.0,
            startup_cold_join_ticks=0,
            startup_cold_passive_buy=3,
            startup_cold_take_cap=4,
            startup_cold_take_edge=3.0,
            startup_delayed_finish_ts=3000,
            startup_dip_take_edge_boost=1.0,
            startup_end_ts=30000,
            startup_fast_passive_buy=8,
            startup_fast_take_cap=12,
            startup_fast_target=32,
            startup_post_pullback_target=64,
            startup_pre_pullback_target=48,
            startup_pullback_ticks=2.0,
            startup_release_take_cap=8,
            startup_release_stretch=1.0,
            startup_target=80,
            strong_trend_ticks=0.9,
            take_buy_edge_bull=-8.0,
            take_buy_edge_neut=2.0,
            take_sell_edge_neut=2.0,
            target_gap_scale=26.0,
            trend_buy_boost_per_tick=0.24,
            trend_inv_per_tick=16.0,
            trend_inventory_cap=80,
            trend_sell_boost_per_tick=0.2,
            ts_increment=100,
            unwind_take_edge=10.0,
            very_strong_trend_ticks=1.6,
            fv_alpha=0.05,
            short_alpha=0.22,
            slope_window=20,
            trim_reference_slope_weight=0.15,
            trim_start_position=79,
            trim_floor_position=78,
            trim_extension_threshold=0.75,
            trim_signal_edge=1.0,
            trim_sell_size=1,
            trim_cooldown_ticks=20,
            trim_take_position=80,
            trim_take_edge=2.0,
            trim_take_stretch=999.0,
            trim_take_sell_size=1,
            trim_ask_local_edge=0.0,
            rebuy_block_ticks=25,
            ask_gap_quote_size=8,
            ask_gap_sell_enable_position=80,
            gap_fill_min_premium=35,
            hold_sell_size=0,
            hold_sell_offset=0,
            gap_rebuy_buy_edge=-10.0,
            gap_rebuy_min_discount=20.0,
            gap_rebuy_passive_buy=6,
            gap_rebuy_take_cap=8,
            gap_rebuy_window=2500,
            gap_trap_arm_streak=2,
            gap_trap_base_size=4,
            gap_trap_clear_after=4,
            gap_trap_floor_position=80,
            gap_trap_fragile_ask_window=6,
            gap_trap_min_gap=3,
            gap_trap_min_imbalance=-0.05,
            gap_trap_min_trend=0.0,
            gap_trap_premium_extra=2,
            gap_trap_premium_size=3,
            gap_trap_premium_streak=2,
            gap_trap_recent_ask_window=12,
            gap_trap_top_ask_max=12,
            empty_side_shift=85,
        ),
    },
}


MEMBER_OVERRIDES["champion_generalized"] = {
    1: {
        # Tibo's mm_first_v2 for ASH_COATED_OSMIUM
        "ASH_COATED_OSMIUM": _override(
            ROUND_1["ASH_COATED_OSMIUM"],
            strategy="mm_first_v2",
            take_edge=1,
            take_edge_lo=0.7,
            take_edge_hi=1,
            take_edge_vol_lo=2.0,
            take_edge_vol_hi=5.0,

            maker_size_base_pct=0.5,
            pct_kept_for_takers=0.1,
            mid_smooth_window=50,
            mid_smooth_half_life=10,
            taker_buy_threshold=9990,
            taker_sell_threshold=10025,

            zscore_window=50,
            zscore_threshold=1,
            zscore_size_scale=0.5,
            zscore_max_scale=5.0,

            gap_trigger_min=10,
            OB_cleared_shift=89,
            gap_trigger_max_vol_pct=0.1,
            gap_trigger_confirm_ticks=1,
            zscore_gap_gate=1.5,

            zscore_skew_threshold=1.5,
            zscore_skew_ticks=1,
            zscore_skew_vol_cap=3,

            quote_trace_enabled=True,
            ts_increment=100,
            last_ts_value=99900,
            log_flush_ts=1000,
        ),
        # Theo's best generalized for INTARIAN_PEPPER_ROOT
        "INTARIAN_PEPPER_ROOT": _override(
            ROUND_1["INTARIAN_PEPPER_ROOT"],
            strategy="theo_best_generalized",
            block_size=200,
            min_completed_blocks=5,
            seed_slope=0.1015,
            reg_horizon=25,
            reg_r2_floor=0.85,
            reg_r2_cap=0.98,
            reg_rmse_floor=1.0,
            reg_residual_reversion=0.25,
            bootstrap_confidence=0.55,
            trend_inv_per_tick=16.0,
            resid_inv_per_z=14.0,
            trend_inventory_cap=80,
            target_gap_scale=26.0,
            trend_buy_boost_per_tick=0.24,
            trend_sell_boost_per_tick=0.20,
            cheap_buy_boost_per_z=0.18,
            rich_sell_boost_per_z=0.14,
            aggravate_cut=0.04,
            one_sided_target_gap=24,
            startup_target=80,
            startup_end_ts=30000,
            bull_threshold=1.0,
            bear_threshold=-1.0,
            strong_trend_ticks=0.9,
            very_strong_trend_ticks=1.6,
            cheap_residual_z=0.9,
            rich_residual_z=1.0,
            max_bid_extra_ticks=2,
            max_ask_relax_ticks=2,
            bid_spread_bull=1.0,
            ask_spread_bull=9.0,
            neut_spread_bid=2.0,
            neut_spread_ask=5.0,
            fastfill_target=80,
            fastfill_end_ts=12000,
            fastfill_min_passive_buy=10,
            fastfill_buy_edge_boost=0.0,
            fastfill_deep_take_guard_end_ts=1000,
            fastfill_deep_take_max_gap_ticks=1,
            build_bid_offset=1,
            build_block_counter_edge=1_000_000.0,
            take_buy_edge_bull=-8.0,
            take_sell_edge_bull=6.0,
            take_buy_edge_neut=2.0,
            take_sell_edge_neut=2.0,
            unwind_take_edge=10.0,
            short_alpha=0.15,
            trim_start_position=80,
            trim_floor_position=79,
            trim_stretch_threshold=1.5,
            trim_sell_size=1,
            trim_cooldown_ticks=20,
            trim_ask_mid_offset=5.0,
            trim_take_enabled=False,
            trim_take_stretch=999.0,
            trim_take_sell_size=1,
            rebuy_block_ticks=3,
            maker_size=80,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
            quote_trace_enabled=True,
        ),
    },
}


# Leo's OSMIUM + Theo's broken-book gap-quote idea (empty_side_shift / gap_size).
# Base = osmium_sb_leo_round2's OSMIUM config, with broken-book handler enabled.
MEMBER_OVERRIDES["leo_osmium_jump_v1"] = {
    2: {
        "ASH_COATED_OSMIUM": _override(
            MEMBER_OVERRIDES["first_sb_leo_round2"][2]["ASH_COATED_OSMIUM"],
            empty_side_shift=85,
            gap_size=30,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}


# Theo's ASH_COATED_OSMIUM penny-improve MM isolated from submission 283574
# (flat-modular port as `aco_mm_modulaire`). OSMIUM-only, IPR disabled.
MEMBER_OVERRIDES["leo_osmium_only_exploration"] = {
    2: {
        "ASH_COATED_OSMIUM": ProductConfig(
            symbol="ASH_COATED_OSMIUM",
            strategy="aco_mm_modulaire",
            position_limit=80,
            params=dict(
                last_ts_value=999900,
                ts_increment=100,
                base_size=10,
                improve_ticks=1,
                inv_skew_threshold=15,
                inv_reduce_factor=0.4,
                max_pos_to_buy=30,
                min_pos_to_sell=-30,
                min_spread_to_quote=4,
                empty_side_shift=85,
                gap_size=30,
            ),
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}


# ── mm_first_v4_combo A/B test configs (Leo x Tibo best-of-both) ────────────
# Base params shared by all variants — match Tibo's mm_first_v3 defaults for OSM
_V4_OSM_BASE = dict(
    strategy="mm_first_v4_combo",
    # Tibo baseline params
    take_edge=1,
    take_edge_lo=0.7,
    take_edge_hi=1,
    take_edge_vol_lo=2.0,
    take_edge_vol_hi=5.0,
    maker_size_base_pct=0.5,
    pct_kept_for_takers=0.1,
    mid_smooth_window=50,
    mid_smooth_half_life=10,
    taker_buy_threshold=9990,
    taker_sell_threshold=10025,
    zscore_window=50,
    zscore_threshold=1,
    zscore_size_scale=0.5,
    zscore_max_scale=5.0,
    # Gap exploit (live alpha — PRESERVED)
    gap_trigger_min=10,
    OB_cleared_shift=89,
    gap_trigger_max_vol_pct=0.1,
    gap_trigger_confirm_ticks=1,
    zscore_gap_gate=1.5,
    # Logging
    quote_trace_enabled=True,
    ts_increment=100,
    last_ts_value=999900,
    log_flush_ts=1000,
)


def _osm_v4(**extra):
    """Build ASH_COATED_OSMIUM override with V4 base + extra opt-in params."""
    return _override(ROUND_2["ASH_COATED_OSMIUM"], **{**_V4_OSM_BASE, **extra})


# Variant A — baseline: all new features OFF  (= mm_first_v3 equivalent)
MEMBER_OVERRIDES["v4_A_baseline"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# Variant B — anchor fixe 10000 (Leo's #1)  + AR(1) on mid_smooth (cleaner signal)
MEMBER_OVERRIDES["v4_B_anchor"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            anchor_price=10000.0,
            anchor_alpha=0.0,       # pure fixed
            ar_gain=0.3,
            ar_shift_source="mid_smooth",
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# Variant B' — anchor hybrid (EWMA bounded to ±10 of 10000)
MEMBER_OVERRIDES["v4_B2_anchor_hybrid"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            anchor_price=10000.0,
            anchor_alpha=0.02,      # slow EMA
            anchor_drift_bound=10.0,
            ar_gain=0.3,
            ar_shift_source="mid_smooth",
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# Variant C — asymmetric takers only (Leo's #3)
MEMBER_OVERRIDES["v4_C_asym"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            unwind_take_edge=1.0,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# Variant D — toxic flow filter only (Leo's #4)
MEMBER_OVERRIDES["v4_D_toxic"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            toxic_threshold=0.6,
            toxic_window=6,
            toxic_size_frac=0.75,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# Variant E — jump filter only (Leo's #5)
MEMBER_OVERRIDES["v4_E_jump"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            trend_jump_threshold=1.0,
            jump_size_frac=0.5,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# Variant F — anchor hybrid + asymmetric (the two highest-impact features)
MEMBER_OVERRIDES["v4_F_anchor_asym"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            anchor_price=10000.0,
            anchor_alpha=0.02,
            anchor_drift_bound=10.0,
            ar_gain=0.3,
            ar_shift_source="mid_smooth",
            unwind_take_edge=1.0,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# Variant F2 — v4_F with tuned unwind params (2D grid winner)
#   Grid searched unwind_take_edge ∈ {0..5} x pct_kept_for_takers ∈ {0.05..0.3}
#   Best: unwind_take_edge=3.0, pct_kept_for_takers=0.05
#   vs v4_F (unwind=1.0, kept=0.1): +658 PnL (+1.1%), inv_ratio 0.232 -> 0.209 (-10%)
#   vs v4_A baseline: +2,391 PnL (+4.1%), inv_ratio 0.282 -> 0.209 (-26%)
MEMBER_OVERRIDES["v4_F2_tuned_unwind"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            anchor_price=10000.0,
            anchor_alpha=0.02,
            anchor_drift_bound=10.0,
            ar_gain=0.3,
            ar_shift_source="mid_smooth",
            unwind_take_edge=3.0,           # tuned up from 1.0
            pct_kept_for_takers=0.05,       # tuned down from 0.1 (less strict hard-stop)
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}


# Variant F3 — v4_F2 + maker-aggressive passive unwind skew
MEMBER_OVERRIDES["v4_F3_maker_unwind"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            anchor_price=10000.0,
            anchor_alpha=0.02,
            anchor_drift_bound=10.0,
            ar_gain=0.3,
            ar_shift_source="mid_smooth",
            unwind_take_edge=3.0,
            pct_kept_for_takers=0.05,
            # New: maker-aggressive unwind via passive skew (live probe)
            # Backtest can't validate this (no queue model) — live test only.
            # Start minimal (1 tick) to limit backtest-visible downside.
            passive_unwind_skew_ticks=1,   # max 1 tick shift toward mid
            passive_unwind_trigger=0.3,    # activate above 30% position
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}


# Variant F4 — v4_F2 + 4 grid search winners cumulated
#   Grid 1: take_edge_lo=0.3, take_edge_hi=0.8 (vs 0.7/1.0) → +117 PnL
#   Grid 2: taker_buy/sell thresholds unchanged (baseline optimal)
#   Grid 3: maker_size_base_pct unchanged (marginal gain, inventory cost too high)
#   Grid 4: anchor_drift_bound=2 (vs 10) → +2,907 PnL (biggest win)
#          + fine grid confirmed drift=2 better than 5
MEMBER_OVERRIDES["v4_F4_champion"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            # From v4_F2 (kept)
            anchor_price=10000.0,
            anchor_alpha=0.02,
            ar_gain=0.3,
            ar_shift_source="mid_smooth",
            unwind_take_edge=3.0,
            pct_kept_for_takers=0.05,
            # Grid 1 winner
            take_edge_lo=0.3,
            take_edge_hi=0.8,
            # Grid 4 winner
            anchor_drift_bound=2.0,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}


# ── v4_F5 feature probes: v4_F4 + 1 new feature each ───────────────────
# Base = v4_F4 champion params + add ONE new feature per variant to isolate effect.

_V4_F4_BASE_PARAMS = dict(
    anchor_price=10000.0,
    anchor_alpha=0.02,
    anchor_drift_bound=2.0,       # from grid 4
    ar_gain=0.3,
    ar_shift_source="mid_smooth",
    unwind_take_edge=3.0,
    pct_kept_for_takers=0.05,
    take_edge_lo=0.3,             # from grid 1
    take_edge_hi=0.8,
)

# v4_F5_wall — volume-filtered mid (wall_mid)
MEMBER_OVERRIDES["v4_F5_wall"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F4_BASE_PARAMS,
            mid_vol_filter=10,   # filter out book levels with vol < 10
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# v4_F5_cooldown — taker cooldown
MEMBER_OVERRIDES["v4_F5_cooldown"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F4_BASE_PARAMS,
            taker_cooldown_ticks=5,   # block takers 5 ticks (500ms) after firing
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# v4_F5_invbias — inventory-aversion fair value bias (AS-lite)
MEMBER_OVERRIDES["v4_F5_invbias"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F4_BASE_PARAMS,
            inventory_aversion_gamma=0.03,   # moderate bias
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# v4_F5_micro — microprice size tilt (predictive)
MEMBER_OVERRIDES["v4_F5_micro"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F4_BASE_PARAMS,
            microprice_size_gain=0.5,
            microprice_size_threshold=0.2,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}


# v4_F5 champion — v4_F4 + inventory_aversion_gamma (AS-lite tuned)
#   Grid searched gamma ∈ {0.0005..0.03} → optimal 0.0015
#   +248 PnL vs v4_F4, inv ratio 0.214 -> 0.181 (-15%)
#   Other 3 features tested (wall_mid, taker_cooldown, microprice_size_tilt)
#   all degraded the backtest, abandoned.
_V4_F5_PARAMS = {**_V4_F4_BASE_PARAMS, "inventory_aversion_gamma": 0.0015}

# v4_F6_spreadwiden
MEMBER_OVERRIDES["v4_F6_spreadwiden"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F5_PARAMS,
            spread_widen_vol_threshold=2.0,
            spread_widen_extra_ticks=1,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# v4_F6_postarget
MEMBER_OVERRIDES["v4_F6_postarget"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F5_PARAMS,
            inventory_target=5,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# v4_F6_filltox
MEMBER_OVERRIDES["v4_F6_filltox"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F5_PARAMS,
            fill_toxicity_window=10,
            fill_toxicity_threshold=0.7,
            fill_toxicity_frac=0.5,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# v4_F6_spreadz
MEMBER_OVERRIDES["v4_F6_spreadz"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F5_PARAMS,
            spread_zscore_window=100,
            spread_zscore_threshold=1.5,
            spread_zscore_shift=1,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}


MEMBER_OVERRIDES["v4_F6_microfair"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F5_PARAMS,
            use_microprice_as_fair=True,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}


# ── Live-probe variants (test on IMC, backtest-invisible) ───────────────

# Multi-shift probes: test OB_cleared_shift at different depths
# to find other potential hole levels where aggressors cross.
MEMBER_OVERRIDES["v4_F5_shift5"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(**_V4_F5_PARAMS, OB_cleared_shift=5),
        "INTARIAN_PEPPER_ROOT": None,
    },
}
MEMBER_OVERRIDES["v4_F5_shift30"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(**_V4_F5_PARAMS, OB_cleared_shift=30),
        "INTARIAN_PEPPER_ROOT": None,
    },
}
MEMBER_OVERRIDES["v4_F5_shift60"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(**_V4_F5_PARAMS, OB_cleared_shift=60),
        "INTARIAN_PEPPER_ROOT": None,
    },
}
MEMBER_OVERRIDES["v4_F5_shift120"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(**_V4_F5_PARAMS, OB_cleared_shift=120),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# Empty-book probe: ALWAYS post far quotes (not just when book empty)
# to detect aggressors that cross at extreme depths under normal conditions.
MEMBER_OVERRIDES["v4_F5_probe"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F5_PARAMS,
            probe_distance=80,          # 80 ticks from best
            probe_qty=1,                # minimal size to limit risk
            probe_interval_ticks=200,   # every 20s (200 ticks)
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}


# tick-0 extreme probe: post at ±200 ticks at session start, see if aggressors fill
MEMBER_OVERRIDES["v4_F5_probe_t0"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F5_PARAMS,
            # Multi-distance probe at session start: tests 4 depths in 1 submission.
            # If any distance fills, we know aggressors cross at that level.
            probe_t0_distances=[30, 60, 100, 150],
            probe_t0_qty=1,
            probe_t0_max_ts=500,   # fire within first 5 ticks
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}

# momentum follower: take aggressively in direction of recent market-trade flow
MEMBER_OVERRIDES["v4_F5_follower"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F5_PARAMS,
            momentum_window=15,
            momentum_threshold=0.7,
            momentum_qty=3,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}


# ── Champion combined 19-04-2026 AM ─────────────────────────────────────
# Variant with empty_side_shift=89 on IPR (matching OSM shift)
# Same as champion_19april_am but with 89 instead of 85 for IPR's far-quote.
MEMBER_OVERRIDES["champion_19april_am_s89"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(**_V4_F5_PARAMS),
        "INTARIAN_PEPPER_ROOT": _override(
            ROUND_2["INTARIAN_PEPPER_ROOT"],
            strategy="theo_best_clean_generalized_v4",
            aggravate_cut=0.04,
            ask_gap_quote_size=8,
            ask_gap_sell_enable_position=75,
            ask_spread_bull=9.0,
            bid_spread_bull=1.0,
            block_size=200,
            bootstrap_confidence=0.55,
            bull_threshold=1.0,
            chase_threshold=1.25,
            cheap_buy_boost_per_z=0.18,
            cheap_residual_z=0.9,
            dip_threshold=1.0,
            dump_reserve_inventory=1,
            dump_reserve_release_min_position=75,
            dump_reserve_release_threshold=3.0,
            empty_side_shift=89,   # ← CHANGED from 85 to 89
            fastfill_buy_edge_boost=0.0,
            fastfill_deep_take_guard_end_ts=1000,
            fastfill_deep_take_max_gap_ticks=1,
            fastfill_end_ts=12000,
            fastfill_min_passive_buy=10,
            fastfill_target=80,
            fv_alpha=0.05,
            gap_fill_min_premium=35,
            gap_rebuy_buy_edge=-10.0,
            gap_rebuy_min_discount=20.0,
            gap_rebuy_passive_buy=6,
            gap_rebuy_take_cap=8,
            gap_rebuy_window=2500,
            gap_trap_arm_streak=2,
            gap_trap_base_size=4,
            gap_trap_clear_after=4,
            gap_trap_floor_position=73,
            gap_trap_fragile_ask_window=6,
            gap_trap_min_gap=3,
            gap_trap_min_imbalance=-0.05,
            gap_trap_min_trend=0.0,
            gap_trap_premium_extra=2,
            gap_trap_premium_size=3,
            gap_trap_premium_streak=2,
            gap_trap_recent_ask_window=12,
            gap_trap_top_ask_max=12,
            hold_sell_offset=0,
            hold_sell_size=0,
            log_flush_ts=1000,
            maker_size=80,
            max_bid_extra_ticks=2,
            max_inventory_sell_guard_position=80,
            max_inventory_sell_guard_threshold=0.0,
            min_completed_blocks=5,
            neut_spread_ask=5.0,
            neut_spread_bid=2.0,
            one_sided_target_gap=24,
            rebuy_block_ticks=25,
            reg_horizon=25,
            reg_r2_cap=0.98,
            reg_r2_floor=0.85,
            reg_residual_reversion=0.25,
            reg_rmse_floor=1.0,
            resid_inv_per_z=14.0,
            rich_residual_z=1.0,
            rich_sell_boost_per_z=0.14,
            seed_slope=0.1015,
            short_alpha=0.22,
            slope_window=20,
            startup_anchor_bid_spread=1.0,
            startup_anchor_gap_ticks=1,
            startup_anchor_size=4,
            startup_chase_passive_buy=1,
            startup_chase_take_cap=1,
            startup_chase_take_edge=4.0,
            startup_cold_join_ticks=0,
            startup_cold_passive_buy=3,
            startup_cold_take_cap=4,
            startup_cold_take_edge=3.0,
            startup_delayed_finish_ts=3000,
            startup_dip_take_edge_boost=1.0,
            startup_end_ts=30000,
            startup_fast_passive_buy=8,
            startup_fast_take_cap=12,
            startup_fast_target=64,
            startup_post_pullback_target=72,
            startup_pre_pullback_target=48,
            startup_pullback_ticks=2.0,
            startup_release_stretch=1.0,
            startup_release_take_cap=8,
            startup_target=80,
            strong_trend_ticks=0.9,
            take_buy_edge_bull=-8.0,
            take_buy_edge_neut=2.0,
            take_sell_edge_neut=2.0,
            target_gap_scale=26.0,
            tighten_ticks=1,
            trend_buy_boost_per_tick=0.24,
            trend_inv_per_tick=16.0,
            trend_inventory_cap=80,
            trend_sell_boost_per_tick=0.2,
            trim_ask_local_edge=0.0,
            trim_cooldown_ticks=20,
            trim_extension_threshold=0.75,
            trim_floor_position=78,
            trim_reference_slope_weight=0.15,
            trim_sell_size=1,
            trim_signal_edge=1.0,
            trim_start_position=79,
            trim_take_edge=2.0,
            trim_take_position=80,
            trim_take_sell_size=1,
            trim_take_stretch=999.0,
            ts_increment=100,
            last_ts_value=999900,
            unwind_take_edge=10.0,
            very_strong_trend_ticks=1.6,
        ),
    },
}


# OSM: v4_F5 (anchor_drift=2, unwind=3, invbias=0.0015 — all grid-tuned)
# IPR: theo_best_clean_generalized_v4 (Theo's live-winning strategy, sub 307401)
MEMBER_OVERRIDES["champion_19april_am"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(**_V4_F5_PARAMS),
        "INTARIAN_PEPPER_ROOT": _override(
            ROUND_2["INTARIAN_PEPPER_ROOT"],
            strategy="theo_best_clean_generalized_v4",
            # Params lifted from Theo's best live IPR submission (307401)
            aggravate_cut=0.04,
            ask_gap_quote_size=8,
            ask_gap_sell_enable_position=75,
            ask_spread_bull=9.0,
            bid_spread_bull=1.0,
            block_size=200,
            bootstrap_confidence=0.55,
            bull_threshold=1.0,
            chase_threshold=1.25,
            cheap_buy_boost_per_z=0.18,
            cheap_residual_z=0.9,
            dip_threshold=1.0,
            dump_reserve_inventory=1,
            dump_reserve_release_min_position=75,
            dump_reserve_release_threshold=3.0,
            empty_side_shift=85,
            fastfill_buy_edge_boost=0.0,
            fastfill_deep_take_guard_end_ts=1000,
            fastfill_deep_take_max_gap_ticks=1,
            fastfill_end_ts=12000,
            fastfill_min_passive_buy=10,
            fastfill_target=80,
            fv_alpha=0.05,
            gap_fill_min_premium=35,
            gap_rebuy_buy_edge=-10.0,
            gap_rebuy_min_discount=20.0,
            gap_rebuy_passive_buy=6,
            gap_rebuy_take_cap=8,
            gap_rebuy_window=2500,
            gap_trap_arm_streak=2,
            gap_trap_base_size=4,
            gap_trap_clear_after=4,
            gap_trap_floor_position=73,
            gap_trap_fragile_ask_window=6,
            gap_trap_min_gap=3,
            gap_trap_min_imbalance=-0.05,
            gap_trap_min_trend=0.0,
            gap_trap_premium_extra=2,
            gap_trap_premium_size=3,
            gap_trap_premium_streak=2,
            gap_trap_recent_ask_window=12,
            gap_trap_top_ask_max=12,
            hold_sell_offset=0,
            hold_sell_size=0,
            log_flush_ts=1000,
            maker_size=80,
            max_bid_extra_ticks=2,
            max_inventory_sell_guard_position=80,
            max_inventory_sell_guard_threshold=0.0,
            min_completed_blocks=5,
            neut_spread_ask=5.0,
            neut_spread_bid=2.0,
            one_sided_target_gap=24,
            rebuy_block_ticks=25,
            reg_horizon=25,
            reg_r2_cap=0.98,
            reg_r2_floor=0.85,
            reg_residual_reversion=0.25,
            reg_rmse_floor=1.0,
            resid_inv_per_z=14.0,
            rich_residual_z=1.0,
            rich_sell_boost_per_z=0.14,
            seed_slope=0.1015,
            short_alpha=0.22,
            slope_window=20,
            startup_anchor_bid_spread=1.0,
            startup_anchor_gap_ticks=1,
            startup_anchor_size=4,
            startup_chase_passive_buy=1,
            startup_chase_take_cap=1,
            startup_chase_take_edge=4.0,
            startup_cold_join_ticks=0,
            startup_cold_passive_buy=3,
            startup_cold_take_cap=4,
            startup_cold_take_edge=3.0,
            startup_delayed_finish_ts=3000,
            startup_dip_take_edge_boost=1.0,
            startup_end_ts=30000,
            startup_fast_passive_buy=8,
            startup_fast_take_cap=12,
            startup_fast_target=64,
            startup_post_pullback_target=72,
            startup_pre_pullback_target=48,
            startup_pullback_ticks=2.0,
            startup_release_stretch=1.0,
            startup_release_take_cap=8,
            startup_target=80,
            strong_trend_ticks=0.9,
            take_buy_edge_bull=-8.0,
            take_buy_edge_neut=2.0,
            take_sell_edge_neut=2.0,
            target_gap_scale=26.0,
            tighten_ticks=1,
            trend_buy_boost_per_tick=0.24,
            trend_inv_per_tick=16.0,
            trend_inventory_cap=80,
            trend_sell_boost_per_tick=0.2,
            trim_ask_local_edge=0.0,
            trim_cooldown_ticks=20,
            trim_extension_threshold=0.75,
            trim_floor_position=78,
            trim_reference_slope_weight=0.15,
            trim_sell_size=1,
            trim_signal_edge=1.0,
            trim_start_position=79,
            trim_take_edge=2.0,
            trim_take_position=80,
            trim_take_sell_size=1,
            trim_take_stretch=999.0,
            ts_increment=100,
            last_ts_value=999900,
            unwind_take_edge=10.0,
            very_strong_trend_ticks=1.6,
        ),
    },
}


# IPR-only variant: Theo v4 with empty_side_shift=89 (matching OSM value)
# Used to test if OSM's shift value transposes to IPR.
MEMBER_OVERRIDES["ipr_theo_v4_shift89"] = {
    2: {
        "ASH_COATED_OSMIUM": None,   # OSM disabled
        "INTARIAN_PEPPER_ROOT": _override(
            ROUND_2["INTARIAN_PEPPER_ROOT"],
            strategy="theo_best_clean_generalized_v4",
            # Same as champion_19april_am IPR params except empty_side_shift=89
            aggravate_cut=0.04,
            ask_gap_quote_size=8,
            ask_gap_sell_enable_position=75,
            ask_spread_bull=9.0,
            bid_spread_bull=1.0,
            block_size=200,
            bootstrap_confidence=0.55,
            bull_threshold=1.0,
            chase_threshold=1.25,
            cheap_buy_boost_per_z=0.18,
            cheap_residual_z=0.9,
            dip_threshold=1.0,
            dump_reserve_inventory=1,
            dump_reserve_release_min_position=75,
            dump_reserve_release_threshold=3.0,
            empty_side_shift=89,   # ← CHANGED from 85 to 89 (match OSM)
            fastfill_buy_edge_boost=0.0,
            fastfill_deep_take_guard_end_ts=1000,
            fastfill_deep_take_max_gap_ticks=1,
            fastfill_end_ts=12000,
            fastfill_min_passive_buy=10,
            fastfill_target=80,
            fv_alpha=0.05,
            gap_fill_min_premium=35,
            gap_rebuy_buy_edge=-10.0,
            gap_rebuy_min_discount=20.0,
            gap_rebuy_passive_buy=6,
            gap_rebuy_take_cap=8,
            gap_rebuy_window=2500,
            gap_trap_arm_streak=2,
            gap_trap_base_size=4,
            gap_trap_clear_after=4,
            gap_trap_floor_position=73,
            gap_trap_fragile_ask_window=6,
            gap_trap_min_gap=3,
            gap_trap_min_imbalance=-0.05,
            gap_trap_min_trend=0.0,
            gap_trap_premium_extra=2,
            gap_trap_premium_size=3,
            gap_trap_premium_streak=2,
            gap_trap_recent_ask_window=12,
            gap_trap_top_ask_max=12,
            hold_sell_offset=0,
            hold_sell_size=0,
            log_flush_ts=1000,
            maker_size=80,
            max_bid_extra_ticks=2,
            max_inventory_sell_guard_position=80,
            max_inventory_sell_guard_threshold=0.0,
            min_completed_blocks=5,
            neut_spread_ask=5.0,
            neut_spread_bid=2.0,
            one_sided_target_gap=24,
            rebuy_block_ticks=25,
            reg_horizon=25,
            reg_r2_cap=0.98,
            reg_r2_floor=0.85,
            reg_residual_reversion=0.25,
            reg_rmse_floor=1.0,
            resid_inv_per_z=14.0,
            rich_residual_z=1.0,
            rich_sell_boost_per_z=0.14,
            seed_slope=0.1015,
            short_alpha=0.22,
            slope_window=20,
            startup_anchor_bid_spread=1.0,
            startup_anchor_gap_ticks=1,
            startup_anchor_size=4,
            startup_chase_passive_buy=1,
            startup_chase_take_cap=1,
            startup_chase_take_edge=4.0,
            startup_cold_join_ticks=0,
            startup_cold_passive_buy=3,
            startup_cold_take_cap=4,
            startup_cold_take_edge=3.0,
            startup_delayed_finish_ts=3000,
            startup_dip_take_edge_boost=1.0,
            startup_end_ts=30000,
            startup_fast_passive_buy=8,
            startup_fast_take_cap=12,
            startup_fast_target=64,
            startup_post_pullback_target=72,
            startup_pre_pullback_target=48,
            startup_pullback_ticks=2.0,
            startup_release_stretch=1.0,
            startup_release_take_cap=8,
            startup_target=80,
            strong_trend_ticks=0.9,
            take_buy_edge_bull=-8.0,
            take_buy_edge_neut=2.0,
            take_sell_edge_neut=2.0,
            target_gap_scale=26.0,
            tighten_ticks=1,
            trend_buy_boost_per_tick=0.24,
            trend_inv_per_tick=16.0,
            trend_inventory_cap=80,
            trend_sell_boost_per_tick=0.2,
            trim_ask_local_edge=0.0,
            trim_cooldown_ticks=20,
            trim_extension_threshold=0.75,
            trim_floor_position=78,
            trim_reference_slope_weight=0.15,
            trim_sell_size=1,
            trim_signal_edge=1.0,
            trim_start_position=79,
            trim_take_edge=2.0,
            trim_take_position=80,
            trim_take_sell_size=1,
            trim_take_stretch=999.0,
            ts_increment=100,
            last_ts_value=999900,
            unwind_take_edge=10.0,
            very_strong_trend_ticks=1.6,
        ),
    },
}


MEMBER_OVERRIDES["v4_F5_champion"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F4_BASE_PARAMS,
            inventory_aversion_gamma=0.0015,   # new winner
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}


# Variant G — all Leo mechanisms combined
MEMBER_OVERRIDES["v4_G_all"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            anchor_price=10000.0,
            anchor_alpha=0.02,
            anchor_drift_bound=10.0,
            ar_gain=0.3,
            ar_shift_source="mid_smooth",
            unwind_take_edge=1.0,
            toxic_threshold=0.6,
            toxic_window=6,
            toxic_size_frac=0.75,
            trend_jump_threshold=1.0,
            jump_size_frac=0.5,
        ),
        "INTARIAN_PEPPER_ROOT": None,
    },
}


# ══════════════════════════════════════════════════════════════════════════════
#  ROUND 3 — Naive champion : MM on HYDROGEL/VELVETFRUIT + BS option MM on VEV
# ══════════════════════════════════════════════════════════════════════════════

# HYDROGEL_PACK : reuse v4_F5 params (anchor=10000, mid range 9928-10071)
_R3_HYDROGEL_PARAMS = {
    **_V4_F5_PARAMS,
    "anchor_price": 10000.0,
    "anchor_drift_bound": 1.5,    # GRID-TUNED 2026-04-25: +2,833 vs default 2.0
    "ar_gain": 0.2,                # GRID-TUNED 2026-04-25: +2,833 vs default 0.3
    "full_capacity_on_empty": True,
}
_R3_HYDROGEL_V4_F5 = _override(
    ROUND_3["HYDROGEL_PACK"],
    strategy="mm_first_v4_combo",
    position_limit=200,
    **_R3_HYDROGEL_PARAMS,
)

# VELVETFRUIT_EXTRACT : same v4_F5 template but anchor at 5250
_R3_VELVETFRUIT_PARAMS = {
    **_V4_F5_PARAMS,
    "anchor_price": 5250.0,
    "full_capacity_on_empty": True,
}
_R3_VELVETFRUIT_V4_F5 = _override(
    ROUND_3["VELVETFRUIT_EXTRACT"],
    strategy="mm_first_v4_combo",
    position_limit=200,
    **_R3_VELVETFRUIT_PARAMS,
)

MEMBER_OVERRIDES["r3_naive_champion"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDROGEL_V4_F5,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        # Vouchers: use default ROUND_3[f"VEV_{k}"] config (option_mm_bs)
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 NAIVE CHAMPION v2 — FIXED after 1st-submit live showed v4_F5 loses money
#
# Live findings (2026-04-24 — see agent_handoff.md, commit):
#   v4_F5 anchor-based MM LOSES -3,077 PnL live. Its anchor=10000 with
#   drift_bound=2.0 is too rigid: when live market drifts away from 10000 the
#   strategy builds max inventory at a stale fair. Position HYDROGEL_PACK
#   ended at +190 (near limit), VELVETFRUIT_EXTRACT at -183.
#
# Fix: use plain book-following MM (naive_tight_mm posting best_bid+1 /
# best_ask-1) for delta-1 products. This matched +1,562 PnL live with the
# naive_base_round_3 submission. Options keep option_mm_bs (neutral ~+270).
# ──────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["r3_naive_champion_v2"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
        ),
        # Vouchers: use ROUND_3 default (option_mm_bs with penny-improve, no takers)
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 v4 TRACKING CHAMPION — v4_F5 code WITHOUT fixed anchor (let mid_smooth float)
#
# Root cause of r3_naive_champion (v4_F5) live failure analysed in hedge_log:
#   HYDROGEL_PACK live mid drifted 10011 → 9960 (-51 ticks) over the session.
#   v4_F5 had anchor_price=10000 + drift_bound=2, clamping our fair value to
#   [9998, 10002]. We kept buying at 9995 thinking below fair; market kept
#   dropping below 9950 → position +190 long @ avg 9995, mid 9949 → -4,096.
#
# Fix: drop the fixed anchor. Without anchor_price, v4_F5 falls back to
# mid_smooth as fair value → tracks the market, no directional forcing.
# Keep the other v4_F5 features (AR drift, inventory aversion, gap exploit).
# ──────────────────────────────────────────────────────────────────────────────
_R3_V4_TRACKING_PARAMS = {k: v for k, v in _V4_F5_PARAMS.items()
                           if k not in ("anchor_price", "anchor_alpha", "anchor_drift_bound")}
# Keep anchor_alpha small so AR(1) shift still uses mid_smooth cleanly.
_R3_V4_TRACKING_PARAMS["anchor_alpha"] = 0.0  # no anchor EMA → fair = mid_smooth

MEMBER_OVERRIDES["r3_v4_tracking_champion"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="mm_first_v4_combo",
            position_limit=200,
            **_R3_V4_TRACKING_PARAMS,
            full_capacity_on_empty=True,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="mm_first_v4_combo",
            position_limit=200,
            **_R3_V4_TRACKING_PARAMS,
            full_capacity_on_empty=True,
        ),
        # Vouchers: default ROUND_3 option_mm_bs
    },
}

# R3 MS: regime-switching overlay from HYDROGEL/VELVET cross-asset states.
# It keeps HYDROGEL close to the naive baseline, skews VELVET by regime, and
# scales passive VEV option quotes instead of forcing a direct pair trade.
_R3_MS_REGIME_PARAMS = dict(
    ms_window=120,
    ms_min_samples=60,
    ms_node_threshold=0.10,
    ms_pos_corr_threshold=0.55,
    ms_neg_corr_threshold=-0.55,
    ms_decorr_threshold=0.15,
    ms_soft_position_ratio=0.70,
    ms_inventory_cut_mult=0.25,
    ms_inventory_exit_mult=1.0,
)
_R3_MS_OPTION_PARAMS = dict(
    ms_option_fav_bid_mult=1.60,
    ms_option_fav_ask_mult=0.30,
    ms_option_bad_bid_mult=0.25,
    ms_option_bad_ask_mult=1.25,
    ms_option_node_mult=0.35,
    ms_option_decoupled_mult=0.70,
    ms_option_warmup_mult=1.0,
    ms_option_outer_mult=1.00,
    ms_option_focus_low=5000,
    ms_option_focus_high=5500,
)
MEMBER_OVERRIDES["r3_ms"] = {
    3: {
        "HYDROGEL_PACK": ProductConfig(
            symbol="HYDROGEL_PACK",
            strategy="ms_regime_delta",
            position_limit=200,
            params={
                **ROUND_3["HYDROGEL_PACK"].params,
                **_R3_MS_REGIME_PARAMS,
                "maker_size": 30,
                "tighten_ticks": 1,
                "ms_role": "hydrogel",
                "ms_history_owner": True,
                "ms_use_shared_only": False,
            },
        ),
        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT",
            strategy="ms_regime_delta",
            position_limit=200,
            params=dict(
                {**ROUND_3["VELVETFRUIT_EXTRACT"].params, **_R3_MS_REGIME_PARAMS},
                maker_size=30,
                tighten_ticks=1,
                ms_role="velvet",
                ms_use_shared_only=True,
                ms_velvet_fav_bid_mult=1.45,
                ms_velvet_fav_ask_mult=0.35,
                ms_velvet_bad_bid_mult=0.35,
                ms_velvet_bad_ask_mult=1.30,
                ms_velvet_node_mult=0.45,
                ms_velvet_decoupled_mult=0.75,
            ),
        ),
        **{
            f"VEV_{k}": ProductConfig(
                symbol=f"VEV_{k}",
                strategy="ms_regime_option",
                position_limit=300,
                params=dict(
                    **ROUND_3[f"VEV_{k}"].params,
                    **_R3_MS_REGIME_PARAMS,
                    **_R3_MS_OPTION_PARAMS,
                    ms_use_shared_only=True,
                ),
            )
            for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
        },
    },
}


# Pure penny-improve baseline across all 12 Round 3 products (no signal, no takers).
MEMBER_OVERRIDES["naive_base_round_3"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="naive_tight_mm",
            maker_size=30,
            tighten_ticks=1,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            maker_size=30,
            tighten_ticks=1,
        ),
        **{
            f"VEV_{k}": ProductConfig(
                symbol=f"VEV_{k}",
                strategy="naive_tight_mm",
                position_limit=300,
                params=dict(
                    maker_size=30,
                    tighten_ticks=1,
                    log_flush_ts=1000,
                    ts_increment=100,
                    last_ts_value=999900,
                ),
            )
            for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
        },
    },
}


_R3_VELVET_IVSCALP_UNDERLYING = _override(
    ROUND_3["VELVETFRUIT_EXTRACT"],
    strategy="mm_first_v4_combo",
    position_limit=200,
    anchor_price=5250.0,
    anchor_alpha=0.02,
    anchor_drift_bound=2.0,
    ar_gain=0.3,
    ar_shift_source="mid_smooth",
    full_capacity_on_empty=True,
    inventory_aversion_gamma=0.0015,
    maker_size=30,
    pct_kept_for_takers=0.05,
    take_edge_lo=0.3,
    take_edge_hi=0.8,
    unwind_take_edge=3.0,
    tighten_ticks=1,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)


def _r3_v24_gamma_option(strike: int) -> ProductConfig:
    return _override(
        ROUND_3[f"VEV_{strike}"],
        strategy="r3_gamma_scalp_zgated",
        position_limit=300,
        strike=strike,
        tte_days_initial=5.0,
        historical_tte_by_day=None,
        timestamp_units_per_day=1000000,
        implied_vol_prior=0.0125,
        prior_vol=0.0125,
        sigma_floor=0.005,
        sigma_cap=0.10,
        min_quote_price=2.0,
        edge_ticks=0.0,
        target_qty=300,
        entry_size=30,
        passive_bid_size=24,
        unwind_tte_threshold=1.5,
        zscore_window=500,
        zscore_skip_threshold=0.5,
        zscore_boost_threshold=1.0,
        skip_when_expensive=True,
        boost_when_cheap=False,
        entry_size_boost=1.5,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        log_flush_ts=1000,
        ts_increment=100,
        last_ts_value=999900,
    )


def _r3_v24_gamma_option_zskip(strike: int, zscore_skip_threshold: float) -> ProductConfig:
    return _override(
        _r3_v24_gamma_option(strike),
        zscore_skip_threshold=zscore_skip_threshold,
    )


def _r3_v24_passive_option(strike: int, *, maker_size: int, maker_edge: int, min_quote_price: float, use_smile: bool) -> ProductConfig:
    return _override(
        ROUND_3[f"VEV_{strike}"],
        strategy="option_mm_bs",
        position_limit=300,
        strike=strike,
        tte_days_initial=5.0,
        historical_tte_by_day=None,
        timestamp_units_per_day=1000000,
        prior_vol=0.0125,
        sigma_floor=0.005,
        sigma_cap=0.10,
        maker_edge=maker_edge,
        maker_size=maker_size,
        take_edge=3.0,
        take_size=40,
        enable_takers=False,
        penny_improve_around_mkt=True,
        min_quote_price=min_quote_price,
        inv_bias_per_unit=0.02,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        use_smile=use_smile,
        log_flush_ts=1000,
        ts_increment=100,
        last_ts_value=999900,
    )


def _r3_smile_iv_scalper_option(strike: int) -> ProductConfig:
    return _override(
        ROUND_3[f"VEV_{strike}"],
        strategy="r3_smile_iv_scalper",
        position_limit=300,
        strike=strike,
        tte_days_initial=5.0,
        historical_tte_by_day=None,
        timestamp_units_per_day=1000000,
        prior_vol=0.0125,
        sigma_floor=0.005,
        sigma_cap=0.10,
        smile_degree=2,
        smile_min_points=4,
        active_reference_spot=5250.0,
        active_base_count=5,
        active_expand_every=120.0,
        active_max_extra_count=2,
        resid_ewma_alpha=0.03,
        resid_std_init=0.0015,
        resid_std_floor=0.0005,
        resid_warmup_ticks=60,
        take_price_edge=3.0,
        reduce_price_edge=1.0,
        take_zscore=1.4,
        reduce_zscore=0.4,
        cheap_reset_z=0.25,
        take_size=4,
        maker_size=0,
        maker_edge=1.5,
        maker_join_best=True,
        soft_position_limit=24,
        entry_position_cap=0,
        take_cooldown_ts=3000,
        inventory_skew=4.0,
        inactive_unwind_bias=1,
        min_quote_price=1.0,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        log_flush_ts=1000,
        ts_increment=100,
        last_ts_value=999900,
    )


MEMBER_OVERRIDES["r3_velvet_options_ivscalp_v1"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVET_IVSCALP_UNDERLYING,
        "VEV_4000": _r3_v24_passive_option(4000, maker_size=40, maker_edge=2, min_quote_price=2.0, use_smile=True),
        "VEV_4500": _r3_v24_gamma_option(4500),
        "VEV_5000": _r3_v24_gamma_option(5000),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option(5200),
        "VEV_5300": _r3_v24_gamma_option(5300),
        "VEV_5400": _r3_v24_passive_option(5400, maker_size=10, maker_edge=1, min_quote_price=1.0, use_smile=False),
        "VEV_5500": _r3_smile_iv_scalper_option(5500),
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


_R3_HYDRO_ALPHA_V4 = _override(
    ROUND_3["HYDROGEL_PACK"],
    strategy="r3_hydro_reversion_mm",
    position_limit=200,
    ema_alpha=0.008,
    fast_ema_alpha=0.03,
    trend_guard=8.0,
    signal_pos_gate=12,
    tighten_ticks=1,
    maker_size=24,
    min_maker_size=3,
    quote_threshold=6.0,
    max_signal_size_boost=12,
    inventory_reduce_per_unit=0.40,
    inventory_unwind_per_unit=0.30,
    max_unwind_boost=20,
    take_threshold=12.0,
    take_cooldown_ts=2000,
    take_size=1,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)


MEMBER_OVERRIDES["r3_velvet_options_v2_hydro_v4"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDRO_ALPHA_V4,
        "VELVETFRUIT_EXTRACT": _R3_VELVET_IVSCALP_UNDERLYING,
        "VEV_4000": _r3_v24_passive_option(4000, maker_size=40, maker_edge=2, min_quote_price=2.0, use_smile=True),
        "VEV_4500": _r3_v24_gamma_option(4500),
        "VEV_5000": _r3_v24_gamma_option(5000),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option(5200),
        "VEV_5300": _r3_v24_gamma_option(5300),
        "VEV_5400": _r3_v24_passive_option(5400, maker_size=10, maker_edge=1, min_quote_price=1.0, use_smile=False),
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r3_velvet_options_v3_hydro_optionblend"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDRO_ALPHA_V4,
        "VELVETFRUIT_EXTRACT": _R3_VELVET_IVSCALP_UNDERLYING,
        "VEV_4000": _r3_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r3_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r3_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r3_v24_gamma_option_zskip(5300, 2.0),
        "VEV_5400": _r3_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}

_R3_VELVET_IVSCALP_UNDERLYING = _override(
    ROUND_3["VELVETFRUIT_EXTRACT"],
    strategy="mm_first_v4_combo",
    position_limit=200,
    anchor_price=5250.0,
    anchor_alpha=0.02,
    anchor_drift_bound=2.0,
    ar_gain=0.3,
    ar_shift_source="mid_smooth",
    full_capacity_on_empty=True,
    inventory_aversion_gamma=0.0015,
    maker_size=30,
    pct_kept_for_takers=0.05,
    take_edge_lo=0.3,
    take_edge_hi=0.8,
    unwind_take_edge=3.0,
    tighten_ticks=1,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)


def _r3_v24_gamma_option(strike: int) -> ProductConfig:
    return _override(
        ROUND_3[f"VEV_{strike}"],
        strategy="r3_gamma_scalp_zgated",
        position_limit=300,
        strike=strike,
        tte_days_initial=5.0,
        historical_tte_by_day=None,
        timestamp_units_per_day=1000000,
        implied_vol_prior=0.0125,
        prior_vol=0.0125,
        sigma_floor=0.005,
        sigma_cap=0.10,
        min_quote_price=2.0,
        edge_ticks=0.0,
        target_qty=300,
        entry_size=30,
        passive_bid_size=24,
        unwind_tte_threshold=1.5,
        zscore_window=500,
        zscore_skip_threshold=0.5,
        zscore_boost_threshold=1.0,
        skip_when_expensive=True,
        boost_when_cheap=False,
        entry_size_boost=1.5,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        log_flush_ts=1000,
        ts_increment=100,
        last_ts_value=999900,
    )


def _r3_v24_gamma_option_zskip(strike: int, zscore_skip_threshold: float) -> ProductConfig:
    return _override(
        _r3_v24_gamma_option(strike),
        zscore_skip_threshold=zscore_skip_threshold,
    )


def _r3_v24_passive_option(strike: int, *, maker_size: int, maker_edge: int, min_quote_price: float, use_smile: bool) -> ProductConfig:
    return _override(
        ROUND_3[f"VEV_{strike}"],
        strategy="option_mm_bs",
        position_limit=300,
        strike=strike,
        tte_days_initial=5.0,
        historical_tte_by_day=None,
        timestamp_units_per_day=1000000,
        prior_vol=0.0125,
        sigma_floor=0.005,
        sigma_cap=0.10,
        maker_edge=maker_edge,
        maker_size=maker_size,
        take_edge=3.0,
        take_size=40,
        enable_takers=False,
        penny_improve_around_mkt=True,
        min_quote_price=min_quote_price,
        inv_bias_per_unit=0.02,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        use_smile=use_smile,
        log_flush_ts=1000,
        ts_increment=100,
        last_ts_value=999900,
    )


def _r3_smile_iv_scalper_option(strike: int) -> ProductConfig:
    return _override(
        ROUND_3[f"VEV_{strike}"],
        strategy="r3_smile_iv_scalper",
        position_limit=300,
        strike=strike,
        tte_days_initial=5.0,
        historical_tte_by_day=None,
        timestamp_units_per_day=1000000,
        prior_vol=0.0125,
        sigma_floor=0.005,
        sigma_cap=0.10,
        smile_degree=2,
        smile_min_points=4,
        active_reference_spot=5250.0,
        active_base_count=5,
        active_expand_every=120.0,
        active_max_extra_count=2,
        resid_ewma_alpha=0.03,
        resid_std_init=0.0015,
        resid_std_floor=0.0005,
        resid_warmup_ticks=60,
        take_price_edge=3.0,
        reduce_price_edge=1.0,
        take_zscore=1.4,
        reduce_zscore=0.4,
        cheap_reset_z=0.25,
        take_size=4,
        maker_size=0,
        maker_edge=1.5,
        maker_join_best=True,
        soft_position_limit=24,
        entry_position_cap=0,
        take_cooldown_ts=3000,
        inventory_skew=4.0,
        inactive_unwind_bias=1,
        min_quote_price=1.0,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        log_flush_ts=1000,
        ts_increment=100,
        last_ts_value=999900,
    )


MEMBER_OVERRIDES["r3_velvet_options_ivscalp_v1"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVET_IVSCALP_UNDERLYING,
        "VEV_4000": _r3_v24_passive_option(4000, maker_size=40, maker_edge=2, min_quote_price=2.0, use_smile=True),
        "VEV_4500": _r3_v24_gamma_option(4500),
        "VEV_5000": _r3_v24_gamma_option(5000),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option(5200),
        "VEV_5300": _r3_v24_gamma_option(5300),
        "VEV_5400": _r3_v24_passive_option(5400, maker_size=10, maker_edge=1, min_quote_price=1.0, use_smile=False),
        "VEV_5500": _r3_smile_iv_scalper_option(5500),
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


_R3_HYDRO_ALPHA_V4 = _override(
    ROUND_3["HYDROGEL_PACK"],
    strategy="r3_hydro_reversion_mm",
    position_limit=200,
    ema_alpha=0.008,
    fast_ema_alpha=0.03,
    trend_guard=8.0,
    signal_pos_gate=12,
    tighten_ticks=1,
    maker_size=24,
    min_maker_size=3,
    quote_threshold=6.0,
    max_signal_size_boost=12,
    inventory_reduce_per_unit=0.40,
    inventory_unwind_per_unit=0.30,
    max_unwind_boost=20,
    take_threshold=12.0,
    take_cooldown_ts=2000,
    take_size=1,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)


MEMBER_OVERRIDES["r3_velvet_options_v2_hydro_v4"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDRO_ALPHA_V4,
        "VELVETFRUIT_EXTRACT": _R3_VELVET_IVSCALP_UNDERLYING,
        "VEV_4000": _r3_v24_passive_option(4000, maker_size=40, maker_edge=2, min_quote_price=2.0, use_smile=True),
        "VEV_4500": _r3_v24_gamma_option(4500),
        "VEV_5000": _r3_v24_gamma_option(5000),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option(5200),
        "VEV_5300": _r3_v24_gamma_option(5300),
        "VEV_5400": _r3_v24_passive_option(5400, maker_size=10, maker_edge=1, min_quote_price=1.0, use_smile=False),
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r3_velvet_options_v3_hydro_optionblend"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDRO_ALPHA_V4,
        "VELVETFRUIT_EXTRACT": _R3_VELVET_IVSCALP_UNDERLYING,
        "VEV_4000": _r3_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r3_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r3_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r3_v24_gamma_option_zskip(5300, 2.0),
        "VEV_5400": _r3_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


# ── CHAMPION FINAL v7 : OSM full_capacity + IPR v7_continuous ──
MEMBER_OVERRIDES["champion_final_v7"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F5_PARAMS,
            full_capacity_on_empty=True,  # post full sell_cap / buy_cap when OB empty
        ),
        "INTARIAN_PEPPER_ROOT": _override(
            ROUND_2["INTARIAN_PEPPER_ROOT"],
            strategy="theo_best_clean_generalized_v7",
            # Base Theo params (from champion_19april_am live winner)
            aggravate_cut=0.04,
            ask_gap_quote_size=160,
            ask_gap_sell_enable_position=75,
            ask_spread_bull=9.0,
            bid_spread_bull=1.0,
            block_size=200,
            bootstrap_confidence=0.55,
            bull_threshold=1.0,
            chase_threshold=1.25,
            cheap_buy_boost_per_z=0.18,
            cheap_residual_z=0.9,
            dip_threshold=1.0,
            dump_reserve_inventory=6,
            dump_reserve_release_min_position=74,
            dump_reserve_release_threshold=3.0,
            # Option B trim: reserve permanente de 5 unités maintenue post-fill
            reserve_target_position=75,
            reserve_trim_per_tick=3,
            empty_side_shift=85,
            empty_side_shift_buy=85,
            empty_side_shift_sell=89,
            standing_deep_qty=15,
            startup_recent_low_crash_drop_ticks=3.0,
            startup_recent_low_start_position=48,
            startup_recent_low_window=12,
            startup_recent_low_gap_threshold=2.0,
            startup_recent_low_release_gap=0.5,
            startup_recent_low_hot_stretch=0.4,
            startup_recent_low_take_cap=2,
            startup_recent_low_passive_buy_cap=3,
            startup_recent_low_anchor_extra_spread=1.0,
            startup_recent_low_buy_edge_floor=1.0,
            startup_recent_low_holdback=6,
            startup_recent_low_end_ts=3000,
            fastfill_buy_edge_boost=0.0,
            fastfill_deep_take_guard_end_ts=1000,
            fastfill_deep_take_max_gap_ticks=1,
            fastfill_end_ts=12000,
            fastfill_min_passive_buy=10,
            fastfill_target=80,
            fv_alpha=0.05,
            gap_fill_min_premium=35,
            gap_rebuy_buy_edge=-10.0,
            gap_rebuy_min_discount=20.0,
            gap_rebuy_passive_buy=6,
            gap_rebuy_take_cap=8,
            gap_rebuy_window=2500,
            gap_trap_arm_streak=2,
            gap_trap_base_size=4,
            gap_trap_clear_after=4,
            gap_trap_floor_position=73,
            gap_trap_fragile_ask_window=6,
            gap_trap_min_gap=3,
            gap_trap_min_imbalance=-0.05,
            gap_trap_min_trend=0.0,
            gap_trap_premium_extra=2,
            gap_trap_premium_size=3,
            gap_trap_premium_streak=2,
            gap_trap_recent_ask_window=12,
            gap_trap_top_ask_max=12,
            hold_sell_offset=0,
            hold_sell_size=0,
            log_flush_ts=1000,
            maker_size=80,
            max_bid_extra_ticks=2,
            max_inventory_sell_guard_position=80,
            max_inventory_sell_guard_threshold=0.0,
            min_completed_blocks=5,
            neut_spread_ask=5.0,
            neut_spread_bid=2.0,
            one_sided_target_gap=24,
            rebuy_block_ticks=25,
            reg_horizon=25,
            reg_r2_cap=0.98,
            reg_r2_floor=0.85,
            reg_residual_reversion=0.25,
            reg_rmse_floor=1.0,
            resid_inv_per_z=14.0,
            rich_residual_z=1.0,
            rich_sell_boost_per_z=0.14,
            seed_slope=0.1015,
            short_alpha=0.22,
            slope_window=20,
            startup_anchor_bid_spread=1.0,
            startup_anchor_gap_ticks=1,
            startup_anchor_size=4,
            startup_chase_passive_buy=1,
            startup_chase_take_cap=1,
            startup_chase_take_edge=4.0,
            startup_cold_join_ticks=0,
            startup_cold_passive_buy=3,
            startup_cold_take_cap=4,
            startup_cold_take_edge=3.0,
            startup_delayed_finish_ts=3000,
            startup_dip_take_edge_boost=1.0,
            startup_end_ts=30000,
            startup_fast_passive_buy=8,
            startup_fast_take_cap=12,
            startup_fast_target=64,
            startup_post_pullback_target=72,
            startup_pre_pullback_target=48,
            startup_pullback_ticks=2.0,
            startup_release_stretch=1.0,
            startup_release_take_cap=8,
            startup_target=80,
            strong_trend_ticks=0.9,
            take_buy_edge_bull=-8.0,
            take_buy_edge_neut=2.0,
            take_sell_edge_neut=2.0,
            target_gap_scale=26.0,
            tighten_ticks=1,
            trend_buy_boost_per_tick=0.24,
            trend_inv_per_tick=16.0,
            trend_inventory_cap=80,
            trend_sell_boost_per_tick=0.2,
            trim_ask_local_edge=0.0,
            trim_cooldown_ticks=20,
            trim_extension_threshold=0.75,
            trim_floor_position=78,
            trim_reference_slope_weight=0.15,
            trim_sell_size=1,
            trim_signal_edge=1.0,
            trim_start_position=79,
            trim_take_edge=2.0,
            trim_take_position=80,
            trim_take_sell_size=1,
            trim_take_stretch=999.0,
            ts_increment=100,
            last_ts_value=999900,
            unwind_take_edge=10.0,
            very_strong_trend_ticks=1.6,
        ),
    },
}

# ── CHAMPION FINAL v7 WITH OSM STANDING DEEPS ──
# Identical to champion_final_v7 except OSM posts preemptive deep quotes
# at last_best_bid - 89 and last_best_ask + 89 every tick (qty=15).
import copy as _copy_cfv7
MEMBER_OVERRIDES["champion_final_v7_osm_deeps"] = _copy_cfv7.deepcopy(
    MEMBER_OVERRIDES["champion_final_v7"]
)
# OSM: preemptive standing deeps at last ± 89 every tick
MEMBER_OVERRIDES["champion_final_v7_osm_deeps"][2]["ASH_COATED_OSMIUM"].params[
    "osm_standing_deep_qty"
] = 15
# IPR: cap normal MM at 75, gap exploit baisse can push to 80, trim back to 75
_ipr_dp = MEMBER_OVERRIDES["champion_final_v7_osm_deeps"][2]["INTARIAN_PEPPER_ROOT"].params
_ipr_dp["fastfill_target"] = 75
_ipr_dp["dump_reserve_inventory"] = 5  # reserve_normal_cap = 80 - 5 = 75
# HARD CAP: normal MM buys cap position at 75. Only standing_deep (gap exploit
# baisse at last_bid-85) can push past 75, up to 80. Option B trim then pulls
# back to 75, recycling the reserve for future gap exploit fills.
_ipr_dp["normal_mm_buy_cap"] = 75

# ── CHAMPION FINAL v8 : v7 + 5 corrections pour matcher exactement best_root ──
# Corrects 5 param drifts vs champion_root standalone (the real best ROOT):
#   - buy_gap_trap_floor_position: 77 (not default 74)
#   - buy_gap_trap_premium_size: 1 (not default 4)
#   - startup_price_improve_start_position: 56 (not default 53)
#   - ask_gap_sell_enable_position: 0 (always active, not 75)
#   - gap_trap_floor_position: 75 (not 73)
MEMBER_OVERRIDES["champion_final_v8"] = _copy_cfv7.deepcopy(
    MEMBER_OVERRIDES["champion_final_v7"]
)
_ipr_v8 = MEMBER_OVERRIDES["champion_final_v8"][2]["INTARIAN_PEPPER_ROOT"].params
_ipr_v8["buy_gap_trap_floor_position"] = 77
_ipr_v8["buy_gap_trap_premium_size"] = 1
_ipr_v8["startup_price_improve_start_position"] = 56
_ipr_v8["ask_gap_sell_enable_position"] = 0
_ipr_v8["gap_trap_floor_position"] = 75

# V8 with OSM standing deeps variant
MEMBER_OVERRIDES["champion_final_v8_osm_deeps"] = _copy_cfv7.deepcopy(
    MEMBER_OVERRIDES["champion_final_v8"]
)
MEMBER_OVERRIDES["champion_final_v8_osm_deeps"][2]["ASH_COATED_OSMIUM"].params[
    "osm_standing_deep_qty"
] = 15
_ipr_v8dp = MEMBER_OVERRIDES["champion_final_v8_osm_deeps"][2]["INTARIAN_PEPPER_ROOT"].params
_ipr_v8dp["fastfill_target"] = 75
_ipr_v8dp["dump_reserve_inventory"] = 5
_ipr_v8dp["normal_mm_buy_cap"] = 75

# TEST ISOLATION: revert dump_reserve_inventory 5→6 from V2, keep everything else
MEMBER_OVERRIDES["_test_v2_dump6"] = _copy_cfv7.deepcopy(MEMBER_OVERRIDES["champion_final_v7_osm_deeps"])
MEMBER_OVERRIDES["_test_v2_dump6"][2]["INTARIAN_PEPPER_ROOT"].params["dump_reserve_inventory"] = 6

# TEST ISOLATION: revert hard cap (normal_mm_buy_cap 75→80)
MEMBER_OVERRIDES["_test_v2_nocap"] = _copy_cfv7.deepcopy(MEMBER_OVERRIDES["champion_final_v7_osm_deeps"])
MEMBER_OVERRIDES["_test_v2_nocap"][2]["INTARIAN_PEPPER_ROOT"].params["normal_mm_buy_cap"] = 80

# TEST ISOLATION: revert fastfill_target 75→80
MEMBER_OVERRIDES["_test_v2_ff80"] = _copy_cfv7.deepcopy(MEMBER_OVERRIDES["champion_final_v7_osm_deeps"])
MEMBER_OVERRIDES["_test_v2_ff80"][2]["INTARIAN_PEPPER_ROOT"].params["fastfill_target"] = 80

# TEST ISOLATION: remove Option B trim (keep everything else in V2)
MEMBER_OVERRIDES["_test_v2_notrim"] = _copy_cfv7.deepcopy(MEMBER_OVERRIDES["champion_final_v7_osm_deeps"])
del MEMBER_OVERRIDES["_test_v2_notrim"][2]["INTARIAN_PEPPER_ROOT"].params["reserve_target_position"]
del MEMBER_OVERRIDES["_test_v2_notrim"][2]["INTARIAN_PEPPER_ROOT"].params["reserve_trim_per_tick"]

# TEST variant A: disable standing_deep, keep trend_inventory_cap=80
MEMBER_OVERRIDES["_test_nodeep"] = _copy_cfv7.deepcopy(MEMBER_OVERRIDES["champion_final_v7_osm_deeps"])
MEMBER_OVERRIDES["_test_nodeep"][2]["INTARIAN_PEPPER_ROOT"].params["standing_deep_qty"] = 0

# TEST variant B: keep standing_deep=15, cap trend at 74
MEMBER_OVERRIDES["_test_capcut"] = _copy_cfv7.deepcopy(MEMBER_OVERRIDES["champion_final_v7_osm_deeps"])
MEMBER_OVERRIDES["_test_capcut"][2]["INTARIAN_PEPPER_ROOT"].params["trend_inventory_cap"] = 74
MEMBER_OVERRIDES["_test_capcut"][2]["INTARIAN_PEPPER_ROOT"].params["maker_size"] = 75

# TEST variant C: both (full cap 75)
MEMBER_OVERRIDES["_test_both"] = _copy_cfv7.deepcopy(MEMBER_OVERRIDES["champion_final_v7_osm_deeps"])
MEMBER_OVERRIDES["_test_both"][2]["INTARIAN_PEPPER_ROOT"].params["standing_deep_qty"] = 0
MEMBER_OVERRIDES["_test_both"][2]["INTARIAN_PEPPER_ROOT"].params["trend_inventory_cap"] = 74
MEMBER_OVERRIDES["_test_both"][2]["INTARIAN_PEPPER_ROOT"].params["maker_size"] = 75

MEMBER_OVERRIDES["champion_osm_v4only"] = {
    2: {
        "ASH_COATED_OSMIUM": _osm_v4(
            **_V4_F5_PARAMS,
            full_capacity_on_empty=False,  # BASELINE  # post full sell_cap / buy_cap when OB empty
        ),
        "INTARIAN_PEPPER_ROOT": _override(
            ROUND_2["INTARIAN_PEPPER_ROOT"],
            strategy="theo_best_clean_generalized_v4",
            # Base Theo params (from champion_19april_am live winner)
            aggravate_cut=0.04,
            ask_gap_quote_size=8,
            ask_gap_sell_enable_position=75,
            ask_spread_bull=9.0,
            bid_spread_bull=1.0,
            block_size=200,
            bootstrap_confidence=0.55,
            bull_threshold=1.0,
            chase_threshold=1.25,
            cheap_buy_boost_per_z=0.18,
            cheap_residual_z=0.9,
            dip_threshold=1.0,
            dump_reserve_inventory=1,
            dump_reserve_release_min_position=75,
            dump_reserve_release_threshold=3.0,
            empty_side_shift=85,
            fastfill_buy_edge_boost=0.0,
            fastfill_deep_take_guard_end_ts=1000,
            fastfill_deep_take_max_gap_ticks=1,
            fastfill_end_ts=12000,
            fastfill_min_passive_buy=10,
            fastfill_target=80,
            fv_alpha=0.05,
            gap_fill_min_premium=35,
            gap_rebuy_buy_edge=-10.0,
            gap_rebuy_min_discount=20.0,
            gap_rebuy_passive_buy=6,
            gap_rebuy_take_cap=8,
            gap_rebuy_window=2500,
            gap_trap_arm_streak=2,
            gap_trap_base_size=4,
            gap_trap_clear_after=4,
            gap_trap_floor_position=73,
            gap_trap_fragile_ask_window=6,
            gap_trap_min_gap=3,
            gap_trap_min_imbalance=-0.05,
            gap_trap_min_trend=0.0,
            gap_trap_premium_extra=2,
            gap_trap_premium_size=3,
            gap_trap_premium_streak=2,
            gap_trap_recent_ask_window=12,
            gap_trap_top_ask_max=12,
            hold_sell_offset=0,
            hold_sell_size=0,
            log_flush_ts=1000,
            maker_size=80,
            max_bid_extra_ticks=2,
            max_inventory_sell_guard_position=80,
            max_inventory_sell_guard_threshold=0.0,
            min_completed_blocks=5,
            neut_spread_ask=5.0,
            neut_spread_bid=2.0,
            one_sided_target_gap=24,
            rebuy_block_ticks=25,
            reg_horizon=25,
            reg_r2_cap=0.98,
            reg_r2_floor=0.85,
            reg_residual_reversion=0.25,
            reg_rmse_floor=1.0,
            resid_inv_per_z=14.0,
            rich_residual_z=1.0,
            rich_sell_boost_per_z=0.14,
            seed_slope=0.1015,
            short_alpha=0.22,
            slope_window=20,
            startup_anchor_bid_spread=1.0,
            startup_anchor_gap_ticks=1,
            startup_anchor_size=4,
            startup_chase_passive_buy=1,
            startup_chase_take_cap=1,
            startup_chase_take_edge=4.0,
            startup_cold_join_ticks=0,
            startup_cold_passive_buy=3,
            startup_cold_take_cap=4,
            startup_cold_take_edge=3.0,
            startup_delayed_finish_ts=3000,
            startup_dip_take_edge_boost=1.0,
            startup_end_ts=30000,
            startup_fast_passive_buy=8,
            startup_fast_take_cap=12,
            startup_fast_target=64,
            startup_post_pullback_target=72,
            startup_pre_pullback_target=48,
            startup_pullback_ticks=2.0,
            startup_release_stretch=1.0,
            startup_release_take_cap=8,
            startup_target=80,
            strong_trend_ticks=0.9,
            take_buy_edge_bull=-8.0,
            take_buy_edge_neut=2.0,
            take_sell_edge_neut=2.0,
            target_gap_scale=26.0,
            tighten_ticks=1,
            trend_buy_boost_per_tick=0.24,
            trend_inv_per_tick=16.0,
            trend_inventory_cap=80,
            trend_sell_boost_per_tick=0.2,
            trim_ask_local_edge=0.0,
            trim_cooldown_ticks=20,
            trim_extension_threshold=0.75,
            trim_floor_position=78,
            trim_reference_slope_weight=0.15,
            trim_sell_size=1,
            trim_signal_edge=1.0,
            trim_start_position=79,
            trim_take_edge=2.0,
            trim_take_position=80,
            trim_take_sell_size=1,
            trim_take_stretch=999.0,
            ts_increment=100,
            last_ts_value=999900,
            unwind_take_edge=10.0,
            very_strong_trend_ticks=1.6,
        ),
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 HEDGED CHAMPION — naive_tight_mm on HYDROGEL + velvet_delta_hedger on
# VELVETFRUIT (reads option positions from coordinator to offset delta) +
# option_mm_bs on vouchers (default ROUND_3 config).
# ──────────────────────────────────────────────────────────────────────────────
_THEO_R3_ACTIVE_OPTION_STRIKES = (5400, 5500)

_THEO_R3_UNDERLYING = _override(
    ROUND_3["VELVETFRUIT_EXTRACT"],
    strategy="theo_r3_vol_arb_v1",
    position_limit=200,
    role="underlying",
    underlying_symbol="VELVETFRUIT_EXTRACT",
    tte_days_initial=5.0,
    ticks_per_day=10000,
    timestamp_units_per_day=1000000,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    prior_vol=0.0125,
    sigma_floor=0.005,
    sigma_cap=0.10,
    realized_vol_default=0.0215,
    realized_var_alpha=0.06,
    realized_vol_floor=0.0100,
    realized_vol_cap=0.0500,
    realized_anchor_weight=0.18,
    hedge_ratio=1.0,
    hedge_abs_position_limit=140,
    hedge_aggressive_band=18,
    hedge_passive_band=6,
    hedge_clip_size=24,
    neutral_mm_size=12,
    neutral_mm_position_cap=20,
)


def _theo_r3_option_override(strike: int) -> ProductConfig:
    return _override(
        ROUND_3[f"VEV_{strike}"],
        strategy="theo_r3_vol_arb_v1",
        position_limit=300,
        role="option",
        strike=strike,
        trade_enabled=True,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        tte_days_initial=5.0,
        ticks_per_day=10000,
        timestamp_units_per_day=1000000,
        historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
        prior_vol=0.0125,
        sigma_floor=0.005,
        sigma_cap=0.10,
        realized_vol_default=0.0215,
        realized_var_alpha=0.06,
        realized_vol_floor=0.0100,
        realized_vol_cap=0.0500,
        realized_anchor_weight=0.18,
        take_edge=12.0,
        reduce_edge=1.5,
        take_size=3,
        maker_size=3,
        maker_edge=2.0,
        enable_takers=False,
        soft_position_limit=16,
        hedge_abs_position_limit=140,
        inventory_skew=6.0,
        min_quote_price=5.0,
    )


MEMBER_OVERRIDES["theo_r3_vol_arb_v1"] = {

    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
        ),
        "VELVETFRUIT_EXTRACT": _THEO_R3_UNDERLYING,
        **{f"VEV_{strike}": _theo_r3_option_override(strike) for strike in _THEO_R3_ACTIVE_OPTION_STRIKES},
    },
}


_R3_LIVE_DEFENSIVE_PARAMS = dict(
    maker_size=30,
    min_maker_size=4,
    tighten_ticks=1,
    trend_alpha=0.05,
    trend_threshold=2.0,
    hard_trend_threshold=7.0,
    inventory_reduce_ratio=0.35,
    inventory_stop_ratio=0.62,
    unwind_boost=1.45,
)


_R3_LIVE_DEFENSIVE_PARAMS = dict(
    maker_size=30,
    min_maker_size=4,
    tighten_ticks=1,
    trend_alpha=0.05,
    trend_threshold=2.0,
    hard_trend_threshold=7.0,
    inventory_reduce_ratio=0.35,
    inventory_stop_ratio=0.62,
    unwind_boost=1.45,
)

MEMBER_OVERRIDES["r3_hedged_champion"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="velvet_delta_hedger",
            position_limit=200,
            underlying_symbol="VELVETFRUIT_EXTRACT",
            hedge_strikes=[4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500],
            strike_prefix="VEV_",
            tte_days_initial=5.0,
            timestamp_units_per_day=1000000,
            historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
            target_delta=0.0,
            hedge_taker_edge=15.0,
            max_hedge_size=30,
            passive_base_size=30,
            passive_skew_per_delta=0.3,
            quote_inside_book=True,
            sigma_floor=0.005,
            sigma_cap=0.10,
            prior_vol=0.0125,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        # Vouchers: use ROUND_3 default (option_mm_bs)
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 VOL HARVEST CHAMPION — long-vol pivot based on realized 2.15% vs implied 1.25%.
# HYDROGEL = naive_tight_mm. VELVET = velvet_delta_hedger with higher threshold.
# ATM vouchers (VEV_5000..5500) = vol_harvest (buy when market < BS@realized_vol).
# ITM (4000/4500) and deep OTM (6000/6500) keep option_mm_bs default.
# ──────────────────────────────────────────────────────────────────────────────
_R3_VOL_HARVEST_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]

# ──────────────────────────────────────────────────────────────────────────────
# R3 ANCHOR ADAPTIVE CHAMPION (Codex design)
# r3_naive_champion (v4_F5 anchor=fixed) makes +124k backtest but loses -3k live.
# Fix: fair = w * anchor_fixed + (1-w) * mid_smooth, where w = confidence in anchor
# based on rolling drift EWMA.
#   - |drift_ewma| < 0.5 → w=1 (anchor regime → full v4_F5 alpha)
#   - |drift_ewma| > 5.0 → w=0 (trend regime → falls back to mid_smooth tracking)
#   - linearly interpolated in between.
# Keeps the +124k backtest alpha on mean-revert days, shields from trend drift.
# ──────────────────────────────────────────────────────────────────────────────
_R3_ANCHOR_ADAPTIVE_BASE = {
    **_V4_F5_PARAMS,
    "confidence_drift_alpha": 0.01,       # slow EWMA so noise doesn't flip regime
    "confidence_drift_mean_rev": 0.5,     # |drift| below → full confidence
    "confidence_drift_trend": 5.0,        # |drift| above → zero confidence
    "confidence_min": 0.0,
    "confidence_max": 1.0,
    "full_capacity_on_empty": True,
}
_R3_ANCHOR_ADAPTIVE_HYDROGEL = {**_R3_ANCHOR_ADAPTIVE_BASE, "anchor_price": 10000.0}
_R3_ANCHOR_ADAPTIVE_VELVET = {**_R3_ANCHOR_ADAPTIVE_BASE, "anchor_price": 5250.0}

MEMBER_OVERRIDES["r3_anchor_adaptive_champion"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="anchor_adaptive",
            position_limit=200,
            **_R3_ANCHOR_ADAPTIVE_HYDROGEL,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="anchor_adaptive",
            position_limit=200,
            **_R3_ANCHOR_ADAPTIVE_VELVET,
        ),
        # Vouchers: default ROUND_3 option_mm_bs
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 GAMMA SCALP CHAMPION — long gamma via ATM options + velvet_delta_hedger
#
# Thesis: realized vol ~1.8%/day vs implied ~1.22%/day → 45% gap.
# Captured by holding long gamma (ATM calls) and hedging delta continuously
# via VELVETFRUIT. When market moves, we rebalance delta; 0.5 gamma ΔS^2 per
# move accumulates > theta decay IF realized > implied.
#
# Delta-1 products use naive_tight_mm + delta_hedger. Options ATM strikes
# (5000..5300) use gamma_scalp. Others (ITM 4000/4500, deep OTM 6000/6500)
# stay on passive option_mm_bs default.
# ──────────────────────────────────────────────────────────────────────────────
_R3_GAMMA_SCALP_STRIKES = [5000, 5100, 5200, 5300]  # ATM-ish, highest gamma

MEMBER_OVERRIDES["r3_gamma_scalp_champion"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="velvet_delta_hedger",
            position_limit=200,
            underlying_symbol="VELVETFRUIT_EXTRACT",
            hedge_strikes=[4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500],
            strike_prefix="VEV_",
            tte_days_initial=5.0,
            timestamp_units_per_day=1000000,
            historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
            target_delta=0.0,
            hedge_taker_edge=5.0,     # tight — re-hedge often for gamma P&L capture
            max_hedge_size=50,
            passive_base_size=30,
            passive_skew_per_delta=0.5,
            quote_inside_book=True,
            sigma_floor=0.005,
            sigma_cap=0.10,
            prior_vol=0.018,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **{
            f"VEV_{k}": ProductConfig(
                symbol=f"VEV_{k}",
                strategy="gamma_scalp",
                position_limit=300,
                params=dict(
                    strike=k,
                    tte_days_initial=5.0,
                    ticks_per_day=10000,
                    timestamp_units_per_day=1000000,
                    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
                    implied_vol_prior=0.0125,   # conservative: priced at market IV
                    edge_ticks=0.0,              # buy when market = fair
                    target_qty=100,
                    entry_size=10,
                    passive_bid_size=10,
                    unwind_tte_threshold=1.5,
                    min_quote_price=2.0,
                    underlying_symbol="VELVETFRUIT_EXTRACT",
                    log_flush_ts=1000,
                    ts_increment=100,
                    last_ts_value=999900,
                ),
            )
            for k in _R3_GAMMA_SCALP_STRIKES
        },
        # Other vouchers (4000/4500/5400/5500/6000/6500) keep option_mm_bs default.
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 HYDROGEL-ONLY CHAMPION — dédié single-asset, pas de options ni VELVETFRUIT
#
# Discovery: HYDROGEL spread = ~15 ticks (énorme), L1 vol = 12 units, mean-rev
# mild (autocorr -0.12). Notre meilleur live = naive_tight_mm = +610 avec seulement
# 20 fills. Le bottleneck c'est le VOLUME, pas l'edge par trade (~6.5 ticks).
#
# Strategy: ladder 3 quotes inside the spread (l1 penny, l2 inside, l3 near-mid)
# to accumulate more fills. Inventory-aversion pour pas saturer. Pas de takers.
# ──────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["r3_hydrogel_only"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_mm",
            position_limit=200,
            l1_size=150,                # scaled up from naive's 30
            level2_inside=3,
            l2_size=0,                 # DISABLE level 2 (hurts in backtest)
            level3_inside=6,
            l3_size=0,                 # DISABLE level 3 (hurts in backtest)
            inventory_aversion=0.5,
            min_spread_for_l2=999,     # effectively off
            min_spread_for_l3=999,     # effectively off
            max_position=200,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        # Disable all other products — this bot ONLY trades HYDROGEL.
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_hydrogel_passive_regime"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_passive_regime_mm",
            position_limit=200,
            maker_size=60,
            improve_ticks=1,
            min_spread=3,
            max_position=200,
            regime_window=120,
            regime_min_samples=60,
            node_threshold=0.10,
            pos_corr_threshold=0.55,
            neg_corr_threshold=-0.55,
            decorr_threshold=0.15,
            cap_warmup=0.35,
            cap_node=0.30,
            cap_neg=0.25,
            cap_pos=0.40,
            cap_decoupled=0.55,
            cap_mixed=0.45,
            size_warmup=0.75,
            size_node=0.55,
            size_neg=0.35,
            size_pos=0.70,
            size_decoupled=1.15,
            size_mixed=0.85,
            inventory_power=2.0,
            inventory_exit_boost=1.4,
            soft_inventory_ratio=0.55,
            soft_worsen_mult=0.15,
            min_worsen_mult=0.0,
            fast_alpha=0.25,
            slow_alpha=0.03,
            momentum_lookback=40,
            kill_position=120,
            kill_dist_ticks=8.0,
            kill_momentum_ticks=12.0,
            kill_exit_mult=2.0,
            kill_exit_improve_ticks=3,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


_R3_ORACLE_DAY2_PRODUCTS = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300,
    "VEV_4500": 300,
    "VEV_5000": 300,
    "VEV_5100": 300,
    "VEV_5200": 300,
    "VEV_5300": 300,
    "VEV_5400": 300,
    "VEV_5500": 300,
}

MEMBER_OVERRIDES["r3_oracle_day2"] = {
    3: {
        **{
            symbol: ProductConfig(
                symbol=symbol,
                strategy="oracle_day2_replay",
                position_limit=limit,
                params={},
            )
            for symbol, limit in _R3_ORACLE_DAY2_PRODUCTS.items()
        },
        "VEV_6000": None,
        "VEV_6500": None,
    },
}

MEMBER_OVERRIDES["r3_oracle_day2_l1"] = {
    3: {
        **{
            symbol: ProductConfig(
                symbol=symbol,
                strategy="oracle_day2_l1_replay",
                position_limit=limit,
                params={},
            )
            for symbol, limit in _R3_ORACLE_DAY2_PRODUCTS.items()
        },
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 HYDROGEL MEAN-REV TAKER — based on ACF/PACF analysis
# Tick returns: AR(1) φ=-0.13 (bid-ask noise, no edge).
# 500-tick agg: ACF(1)=-0.20 (strong mean-rev), std=28 ticks.
# At |z|>=2 → sell/buy taker, edge = 2σ × 0.4 = 11 ticks minus 7 spread = 4 net.
# Passive MM overlay stays on always (+23k baseline).
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# R3 HYDROGEL ORACLE-INSPIRED — rules distilled from Codex day-2 oracle
# Reverse-engineered pattern:
#   BUY  when z<-1.6 AND trend_100<-20 (oracle q75/avg)
#   SELL when z>+0.5 AND trend_100>+10
# Forward move median +33 ticks EOD, spread 15 ticks -> ~18 ticks net per trade.
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# R3 HYDROGEL ASYM MM — Theo's one-sided quoting + our ACF z-score window=500
# Combines the safest live strategy (Theo +587, drawdown -246, 0.42x ratio)
# with our ACF-tuned signal (window=500, the true mean-rev horizon).
# ──────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["r3_hydrogel_asym_mm"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_asym_mm",
            position_limit=200,
            window=500,
            quote_threshold_z=0.8,
            maker_size=24,
            min_maker_size=3,
            signal_boost_max=8,                 # was 12, reduce aggressive scaling
            signal_boost_per_z=4,               # was 6, smoother boost
            inventory_reduce_per_unit=0.60,     # was 0.40, faster reduce wrong side
            inventory_unwind_per_unit=0.50,     # was 0.30, faster unwind
            unwind_boost_max=30,                # was 20, bigger push to unwind
            tighten_ticks=1,
            enable_taker=True,
            take_z=2.5,
            take_size=1,
            take_cooldown_ts=2000,
            soft_position_limit=15,             # was 60, tight taker cap
            hard_pos_cap=15,                    # NEW: hard block passive @ ±15
            min_samples=100,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 HYDROGEL FOLLOW MM — trend-follow one-side + aggressive mean-revert unwind
# Rationale: v2 asym_mm live log (384749) showed mean-rev logic fought the day's
# downtrend. HYDRO drifted 10011 → 9960, strategy shorted early (good) but bought
# back -17→-11 mid-trend (bad). Follow version holds + adds through pullbacks
# and only unwinds on z-score exhaustion (take-profit) or trend flip (stop).
# ──────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["r3_hydrogel_follow_mm"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_follow_mm",
            position_limit=200,
            ema_fast=500,                       # ACF-optimal (tick horizon)
            ema_slow=2000,                      # day-scale trend
            trend_threshold=1.2,                # |trend| > 1.2 std → trend regime
            flat_z_threshold=1.5,               # unused now (flat = symmetric)
            maker_size=20,
            min_maker_size=2,
            follow_boost_max=10,                # size boost cap in trend
            follow_boost_per_trend=4,           # per unit |trend|
            flat_boost_max=0,                   # flat = symmetric MM (no asym)
            flat_boost_per_z=0,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            unwind_boost_max=20,
            tighten_ticks=1,
            enable_taker=True,
            flip_threshold=1.2,                 # was 0.8 — need STRONG flip to stop
            tp_z=2.0,                           # was 1.2 — only extreme z=2σ for TP
            stop_z=3.5,                         # was 2.5 — very wide stop
            unwind_take_size=3,                 # was 4 — smaller bites
            take_cooldown_ts=2500,              # was 500 — match asym_mm cadence
            hard_pos_cap=30,                    # was 35 — a bit tighter
            min_pos_for_take=8,                 # takers only fire when |pos|>=8
            min_samples=200,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_hydrogel_oracle_inspired"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_follow_mm",
            position_limit=200,
            ema_fast=500,                       # ACF-optimal (tick horizon)
            ema_slow=2000,                      # day-scale trend
            trend_threshold=1.2,                # |trend| > 1.2 std → trend regime
            flat_z_threshold=1.5,               # unused now (flat = symmetric)
            maker_size=20,
            min_maker_size=2,
            follow_boost_max=10,                # size boost cap in trend
            follow_boost_per_trend=4,           # per unit |trend|
            flat_boost_max=0,                   # flat = symmetric MM (no asym)
            flat_boost_per_z=0,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            unwind_boost_max=20,
            tighten_ticks=1,
            enable_taker=True,
            flip_threshold=1.2,                 # was 0.8 — need STRONG flip to stop
            tp_z=2.0,                           # was 1.2 — only extreme z=2σ for TP
            stop_z=3.5,                         # was 2.5 — very wide stop
            unwind_take_size=3,                 # was 4 — smaller bites
            take_cooldown_ts=2500,              # was 500 — match asym_mm cadence
            hard_pos_cap=30,                    # was 35 — a bit tighter
            min_pos_for_take=8,                 # takers only fire when |pos|>=8
            min_samples=200,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_hydrogel_oracle_inspired"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_follow_mm",
            position_limit=200,
            ema_fast=500,                       # ACF-optimal (tick horizon)
            ema_slow=2000,                      # day-scale trend
            trend_threshold=1.2,                # |trend| > 1.2 std → trend regime
            flat_z_threshold=1.5,               # unused now (flat = symmetric)
            maker_size=20,
            min_maker_size=2,
            follow_boost_max=10,                # size boost cap in trend
            follow_boost_per_trend=4,           # per unit |trend|
            flat_boost_max=0,                   # flat = symmetric MM (no asym)
            flat_boost_per_z=0,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            unwind_boost_max=20,
            tighten_ticks=1,
            enable_taker=True,
            flip_threshold=1.2,                 # was 0.8 — need STRONG flip to stop
            tp_z=2.0,                           # was 1.2 — only extreme z=2σ for TP
            stop_z=3.5,                         # was 2.5 — very wide stop
            unwind_take_size=3,                 # was 4 — smaller bites
            take_cooldown_ts=2500,              # was 500 — match asym_mm cadence
            hard_pos_cap=30,                    # was 35 — a bit tighter
            min_pos_for_take=8,                 # takers only fire when |pos|>=8
            min_samples=200,
            log_flush_ts=1000,
            quote_trace_enabled=True,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 HYDROGEL LADDER MM — multi-level passive ladder inside spread
# Goal: maximize fill volume by quoting at MULTIPLE price levels improving on
# best. Single-level captures 1 price point; 4 levels capture 4 price points.
# Spread ~15 ticks → up to 7 levels per side available.
# Backtest target: more fills than asym_mm (24 live), edge per fill stays positive.
# ──────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["r3_hydrogel_ladder_mm"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_ladder_mm",
            position_limit=200,
            num_levels=4,                       # 4 price levels per side
            level_step=1,                       # adjacent ticks: best+1, +2, +3, +4
            total_size_per_side=40,             # 40 / 4 = 10 per level (pyramid)
            size_mode="pyramid",                # bigger size at innermost level
            min_spread_for_ladder=4,            # need at least 4-tick spread to ladder
            fallback_size=8,                    # single-level fallback when narrow
            inventory_reduce_per_unit=0.50,     # 0.5 ticks shrunk per unit pos
            inventory_unwind_per_unit=0.30,
            unwind_boost_max=30,
            hard_pos_cap=60,                    # wider cap (more total exposure)
            window=500,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 HYDROGEL LADDER V2 — ladder + trend-aware regime switching
# v1 lost on day 2 (-486) because pure ladder fights the trend.
# v2: in trending regime, ladder ONE-SIDE (follow), single level on counter-trend.
# In flat regime, full ladder for max volume capture.
# ──────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["r3_hydrogel_ladder_v2"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_ladder_v2",
            position_limit=200,
            ema_fast=500,                       # ACF-tuned tick horizon
            ema_slow=2000,                      # day-scale trend
            trend_threshold=1.0,                # |trend| > 1σ → trend regime
            min_samples=200,
            # Ladder geometry per regime
            num_levels_flat=3,                  # flat: 3 levels each side
            num_levels_trend_follow=3,          # trend-follow side: 3 levels
            num_levels_trend_against=1,         # counter-trend side: 1 level
            level_step=1,
            min_spread_for_ladder=4,
            # Sizes
            total_size_flat=30,                 # 30 / 3 = 10 per level (flat)
            total_size_trend_follow=30,         # same total when trending follow
            total_size_trend_against=5,         # tiny single counter-trend quote
            fallback_size=8,
            # Inventory + cap
            inventory_reduce_per_unit=0.50,
            inventory_unwind_per_unit=0.30,
            unwind_boost_max=30,
            hard_pos_cap=30,                    # tighter than v1 (was 60)
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 THEO INSPIRED — multi-product clone of Theo's live winner (log 386998)
# Theo's live: total +1,867 (HYDRO +920, VELVET +677, VEV options +275)
# Strategy stack:
#   - HYDROGEL: hydrogel_reversion_mm (clone of R3HydroReversionMM with trend_guard)
#   - VELVETFRUIT: naive_tight_mm (passive ladder, maker_size=30)
#   - VEV options: option_mm_bs (BS-fair MM with smile, no takers, min_quote=2.0)
# ──────────────────────────────────────────────────────────────────────────────
_THEO_VEV_OPTION_PARAMS = dict(
    enable_takers=False,
    inv_bias_per_unit=0.02,
    iv_ewma_alpha=0.3,
    log_flush_ts=1000,
    maker_edge=2,
    maker_size=20,
    min_quote_price=2.0,
    penny_improve_around_mkt=True,
    prior_vol=0.0125,
    sigma_cap=0.1,
    sigma_floor=0.005,
    take_edge=3.0,
    take_size=40,
    timestamp_units_per_day=1000000,
    ts_increment=100,
    last_ts_value=999900,
    tte_days_initial=5.0,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    use_smile=True,
)


MEMBER_OVERRIDES["r3_theo_inspired"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,                # slow EMA (half-life ~86 ticks)
            fast_ema_alpha=0.03,            # fast EMA (half-life ~23 ticks)
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,            # mid > ema+6 → mean-rev signal fires
            max_signal_size_boost=12,
            trend_guard=6.0,                # CRITICAL: skip signal if |fast-slow|>=6
            signal_pos_gate=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            tighten_ticks=1,
            take_threshold=12.0,
            take_size=1,
            take_cooldown_ts=2000,
            session_drift_bias=0,           # OFF (matches Theo's exact params)
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        # Trade only ITM-ish strikes (4000-5300) — same as Theo's strategy.
        # Skipped: 5400, 5500, 6000, 6500 (too far OTM, min_quote_price gate).
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                strategy="option_mm_bs",
                position_limit=300,
                strike=strike,
                **_THEO_VEV_OPTION_PARAMS,
            )
            for strike in [4000, 4500, 5000, 5100, 5200, 5300]
        },
        # Disable far OTM strikes (too risky / illiquid)
        **{f"VEV_{k}": None for k in [5400, 5500, 6000, 6500]},
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 THEO INSPIRED + LÉO'S DAILY-TREND BIAS
# Same as r3_theo_inspired but with session_drift_bias=4 (lean short in
# first 100k ts of session). Backtest on day 0/1/2 shows -37 ticks avg drift
# in first 1000 ticks, so short bias is statistically favorable.
# ──────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["r3_theo_drift"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            trend_guard=6.0,
            signal_pos_gate=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            tighten_ticks=1,
            take_threshold=12.0,
            take_size=1,
            take_cooldown_ts=2000,
            # Léo's daily-trend bias
            session_drift_bias=4,                       # +4 to ask, -4 to bid in early session
            session_bias_strong_until_ts=100_000,       # 1000 ticks (live window length)
            session_bias_fade_until_ts=300_000,         # fade out by ts 300k
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                strategy="option_mm_bs",
                position_limit=300,
                strike=strike,
                **_THEO_VEV_OPTION_PARAMS,
            )
            for strike in [4000, 4500, 5000, 5100, 5200, 5300]
        },
        **{f"VEV_{k}": None for k in [5400, 5500, 6000, 6500]},
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 HYDROGEL COMBO MM — HYDRO-only with 3 signals + level quoting
# Combines Léo's three insights:
#   1. Level quoting (multi-level passive ladder for volume amplification)
#   2. EWM cross frequency (last N ticks count of bid>EWM vs ask<EWM)
#   3. Daily-trend phase (early bearish, mid neutral, late slightly bullish)
# Aggregate score → regime → ladder geometry per side.
# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# R3 HYDROGEL THEO ONLY — Theo's HYDRO strategy isolated (no VELVET/VEV)
# Useful baseline to measure: how much of Theo's edge comes from HYDRO alone?
# ──────────────────────────────────────────────────────────────────────────────
# With Léo's daily-phase bias (lean short in first 100k ts)
# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# R3 HYDROGEL SMART MM — Theo + confirmed-reversal exit (no overfit)
# Robust answer to "make more PnL on day 2 without overfit":
#   theo_drift_only LIVE held -27 short into 9927→9960 rebound, lost 890 mtm.
#   reversion_v2 + bypass covered too early on transient |dev| spikes (-95 live).
#   smart_mm fires AGGRESSIVE COVER only when:
#     1. position adverse (e.g. short while mid below mean)
#     2. |dev| >= extreme threshold (20)
#     3. mid has reversed direction for >= 3 consecutive ticks
#   This catches the V-bottom (where rebound starts) without false positives
#   on transient spikes during the descent.
# ──────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["r3_hydrogel_smart"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_smart_mm",
            position_limit=200,
            # Theo's HYDRO base
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            trend_guard=6.0,
            signal_pos_gate=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            tighten_ticks=1,
            take_threshold=12.0,
            take_size=1,
            take_cooldown_ts=2000,
            # Confirmed-reversal taker (NEW)
            extreme_dev_threshold=22.0,        # |dev| must be >= 20 to consider firing
            reversal_persist_ticks=3,          # mid must reverse for 3 consecutive ticks
            min_pos_for_reversal_take=8,      # position must be >= 10 for cover to matter
            reversal_take_base=3,              # base size when |dev|=20
            reversal_take_max=12,              # cap
            reversal_take_scale_div=4.0,       # +1 size per 4 ticks of excess |dev|
            reversal_cooldown_ts=1000,         # min 1000ts between reversal takers
            # Adaptive pos_gate (v2 — disabled by default)
            adaptive_pos_gate=False,
            adaptive_pos_gate_range_thr=60.0,
            adaptive_pos_gate_max=18,
            # Léo's session drift bias
            session_drift_bias=4,
            session_bias_strong_until_ts=100_000,
            session_bias_fade_until_ts=300_000,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 HYDROGEL ROBUST MM — aggressive mean-rev (default) → defensive on big range
# Resurrects old r3_hydrogel_mean_rev's aggressive z-skew (which had +44k 3-day
# backtest!) but adds CUMULATIVE_RANGE safety net. Once cumulative range from
# session open exceeds 70 ticks, switch (sticky) to Theo's defensive logic.
#
# Range data:
#   Day 0 ts=99k: 84   Day 1 ts=99k: 66   Day 2 ts=99k: 116
#   Threshold 70 catches day 2 (high-range) without false-trigging days 0/1.
#
# Aggressive mode (default — days 0/1 territory):
#   maker=30, signal_boost=24, quote_thr=4 (fires earlier), trend_guard=8
#   take_threshold=8 (more takers when in mean-rev mode)
# Defensive mode (sticky once range>70):
#   Theo's exact: maker=24, signal_boost=12, quote_thr=6, trend_guard=6
# ──────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["r3_hydrogel_robust"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_robust_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            min_maker_size=3,
            tighten_ticks=1,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_size=1,
            take_cooldown_ts=2000,
            # Regime detector
            range_threshold=70.0,          # cumulative range threshold to go defensive
            # Aggressive params (default)
            agg_maker_size=30,
            agg_quote_threshold=4.0,
            agg_max_signal_size_boost=24,
            agg_trend_guard=8.0,
            agg_signal_pos_gate=12,
            agg_take_threshold=8.0,
            # Defensive params (Theo's exact values)
            def_maker_size=24,
            def_quote_threshold=6.0,
            def_max_signal_size_boost=12,
            def_trend_guard=6.0,
            def_signal_pos_gate=12,
            def_take_threshold=12.0,
            # Drift bias (aggressive only)
            session_drift_bias=4,
            session_bias_strong_until_ts=100_000,
            session_bias_fade_until_ts=300_000,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 HYDROGEL REGIME SWITCH MM — Theo + realized-vol regime adaptation
# Léo's idea: detect mean-rev vs trend regime live, adapt aggression.
# - LOW_VOL (vol<1.8):  aggressive mean-rev (+25% size, +50% boost, faster takers)
# - HIGH_VOL (vol>2.6): defensive (-25% size, -25% boost, slower takers)
# - NORMAL: theo_drift defaults
# NO bypass trend_guard (reversion_v2 covered too early in live, -95 vs theo_drift).
# ──────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["r3_hydrogel_regime_switch"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_regime_switch_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            trend_guard=6.0,
            signal_pos_gate=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            tighten_ticks=1,
            take_threshold=12.0,
            take_size=1,
            take_cooldown_ts=2000,
            # Realized-vol regime detector
            vol_window=200,
            min_vol_samples=100,
            vol_baseline=2.15,
            vol_low_thr=1.8,
            vol_high_thr=2.6,
            # Regime multipliers
            low_vol_maker_mult=1.25,
            low_vol_signal_mult=1.5,
            low_vol_take_thr_mult=0.8,
            low_vol_take_size_mult=1.5,
            high_vol_maker_mult=0.75,
            high_vol_signal_mult=0.75,
            high_vol_take_thr_mult=1.5,
            high_vol_take_size_mult=1.0,
            # Léo's session drift bias
            session_drift_bias=4,
            session_bias_strong_until_ts=100_000,
            session_bias_fade_until_ts=300_000,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 HYDROGEL REVERSION V2 — Theo's strategy + dynamic taker (exhaustion-style)
# theo_drift_only LIVE log 403647: +1,077 final / +2,307 peak / -1,230 DD.
# Lost 1,230 mtm because mid rebounded 9927→9960 at close while we held -27 short.
# Theo's tiny taker (size=1) too slow to cover. Dynamic-size taker scales with
# |dev| to lock profit at extremes. base=1, scale=(|dev|-12)/4, max=12.
# NOTE: live test +982 vs theo_drift +1077 = -95. Bypass covers too early in live.
# ──────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["r3_hydrogel_reversion_v2"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_reversion_v2",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            trend_guard=6.0,
            signal_pos_gate=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            tighten_ticks=1,
            # Dynamic taker (NEW)
            take_threshold=12.0,
            take_size_base=1,
            take_size_max=12,
            take_size_scale_div=4.0,
            take_cooldown_ts=2000,
            take_extreme_threshold=30.0,
            take_extreme_cooldown_ts=500,
            bypass_trend_guard_dev=22.0,
            # Léo's session drift bias
            session_drift_bias=4,
            session_bias_strong_until_ts=100_000,
            session_bias_fade_until_ts=300_000,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 HYDROGEL SUPER MM — Theo + informed-flow gate + daily bias
# Adds informed-flow detection: when 2+ aggressive buys in last 1000ts, suppress
# our ASK (don't sell into rally). Stats: BUY streaks ≥2 have +10.35 markout
# at H=1000, 63% wr (informed).
# ──────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["r3_hydrogel_super_mm"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_super_mm",
            position_limit=200,
            # Theo's HYDRO params
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            trend_guard=6.0,
            signal_pos_gate=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            tighten_ticks=1,
            take_threshold=12.0,
            take_size=1,
            take_cooldown_ts=2000,
            # Informed-flow gate
            streak_window_ts=1000,            # detect 2+ same-side trades in 10 ticks
            streak_min_count=2,
            gate_duration_ts=50000,           # gate active for 500 ticks after trigger
            # Léo's session drift bias
            session_drift_bias=4,
            session_bias_strong_until_ts=100_000,
            session_bias_fade_until_ts=300_000,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_hydrogel_theo_drift_only"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            trend_guard=6.0,
            signal_pos_gate=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            tighten_ticks=1,
            take_threshold=12.0,
            take_size=1,
            take_cooldown_ts=2000,
            session_drift_bias=4,                     # +4 to ask, -4 to bid early session
            session_bias_strong_until_ts=100_000,
            session_bias_fade_until_ts=300_000,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_hydrogel_theo_only"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            trend_guard=6.0,
            signal_pos_gate=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            tighten_ticks=1,
            take_threshold=12.0,
            take_size=1,
            take_cooldown_ts=2000,
            session_drift_bias=0,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# R3 HYDROGEL GUARDED THEO
# HYDRO-only. Sends orders only on HYDROGEL_PACK.
# Base = Theo reversion MM; overlay = tiny L1 exhaustion taker.  The
# VELVET/voucher score is exposed for dashboard analysis and only lightly gates
# exhaustion entries; passive quote gates are disabled by default because they
# did not separate good/bad maker fills on the 3-day backtest.
MEMBER_OVERRIDES["r3_hydro_guarded_theo"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_guarded_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            trend_guard=6.0,
            signal_pos_gate=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            tighten_ticks=1,
            hard_pos_cap=70,
            wrong_side_pos_gate=18,
            wrong_side_unwind_boost=10,
            cross_window=500,
            cross_min_samples=150,
            soft_score=99.0,
            hard_score=999.0,
            soft_reduce_mult=0.35,
            gate_boost_max=12,
            gate_boost_per_score=8,
            w_vertical=0.35,
            w_spread=0.20,
            w_hydro_reversal=0.18,
            w_hydro_fast=0.05,
            w_velvet=0.18,
            hydro_mom_scale=40.0,
            hydro_fast_mom_scale=18.0,
            velvet_mom_scale=18.0,
            enable_theo_taker=True,
            take_threshold=12.0,
            take_size=1,
            take_cooldown_ts=2000,
            take_contra_score=0.75,
            enable_exhaustion_taker=True,
            exhaustion_fast_ticks=42.0,
            exhaustion_slow_ticks=55.0,
            exhaustion_size=3,
            exhaustion_max_position=35,
            exhaustion_cooldown_ts=3000,
            exhaustion_max_recent_against=8.0,
            exhaustion_buy_min_score=-0.10,
            exhaustion_sell_min_score=-0.10,
            quote_trace_enabled=True,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# R3 HYDRO selector suite.
# Three HYDRO-only candidates for the final HYDRO base:
# - anchor_max3d: pure fixed-anchor v4, maximizes known 3-day backtest.
# - day2_oracle_regime: day2 fingerprint -> L1 oracle replay, otherwise guarded Theo.
# - anchor_oracle_hybrid: day2 fingerprint -> L1 oracle replay, otherwise fixed-anchor v4.
_R3_HYDRO_SELECTOR_ANCHOR_PARAMS = {
    **_R3_HYDROGEL_PARAMS,
    "quote_trace_enabled": True,
}
_R3_HYDRO_SELECTOR_GUARDED_PARAMS = {
    **MEMBER_OVERRIDES["r3_hydro_guarded_theo"][3]["HYDROGEL_PACK"].params,
    "quote_trace_enabled": True,
}
_R3_HYDRO_SELECTOR_COMMON = dict(
    strategy="hydrogel_day2_selector_mm",
    position_limit=200,
    anchor_params=_R3_HYDRO_SELECTOR_ANCHOR_PARAMS,
    guarded_params=_R3_HYDRO_SELECTOR_GUARDED_PARAMS,
    day2_start_mid=10011.0,
    day2_start_mid_tolerance=0.25,
    oracle_price_tolerance=2,
    oracle_use_live_l1=True,
    anchor_price=10000.0,
    stationary_ewma_alpha=0.01,
    stationary_max_abs_drift=55.0,
    quote_trace_enabled=True,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)
_R3_HYDRO_DISABLE_REST = {
    "VELVETFRUIT_EXTRACT": None,
    **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
}

MEMBER_OVERRIDES["r3_hydro_anchor_max3d"] = {
    3: {
        "HYDROGEL_PACK": _override(
            _R3_HYDROGEL_V4_F5,
            quote_trace_enabled=True,
        ),
        **_R3_HYDRO_DISABLE_REST,
    },
}


# r3_hydro_anchor_max3d_v7 — same as max3d but with Theo v7 enhancements applied:
# 1) Toxic flow detection (toxic_threshold=0.6, window=8, frac=0.68)
# 2) Passive unwind (skew=1, trigger=0.38)
# 3) inventory_aversion_gamma=0.001 (was 0.0015)
# These are PURE microstructure additions (no regime tuning), should generalize.
MEMBER_OVERRIDES["r3_hydro_anchor_max3d_v7"] = {
    3: {
        "HYDROGEL_PACK": _override(
            _R3_HYDROGEL_V4_F5,
            quote_trace_enabled=True,
            # Toxic flow protection
            toxic_threshold=0.6,
            toxic_window=8,
            toxic_size_frac=0.68,
            # Passive unwind (asymmetric skew toward mid when |pos|>38%)
            passive_unwind_skew_ticks=1,
            passive_unwind_trigger=0.38,
            # Looser fair-value shift (since unwind handles inventory)
            inventory_aversion_gamma=0.001,
            # Match Theo v7 taker reserve
            pct_kept_for_takers=0.005,
        ),
        **_R3_HYDRO_DISABLE_REST,
    },
}


# r3_hydro_v7b_guarded_loose — guarded_v7 with PERMISSIVE guard (threshold 3.0 vs 7.5)
# Guard fires less aggressively → should keep D0 win without losing D2
def _hydro_v7_base():
    return dict(
        toxic_threshold=0.6, toxic_window=8, toxic_size_frac=0.68,
        passive_unwind_skew_ticks=1, passive_unwind_trigger=0.38,
        inventory_aversion_gamma=0.001,
        pct_kept_for_takers=0.005,
    )


def _hydro_guard_params(threshold=7.5, inv_dist=40.0, max_dist=80.0, near_band=0.0):
    return dict(
        guard_trend_alpha=0.45,
        guard_reversion_threshold=threshold,
        guard_inventory_dist=inv_dist,
        guard_min_dist=0.0,
        guard_max_dist=max_dist,
        guard_near_band=near_band,
    )


for label, gparams in [
    ("v7b_guarded_loose",   _hydro_guard_params(threshold=3.0)),       # less restrictive
    ("v7c_guarded_strict",  _hydro_guard_params(threshold=12.0)),      # more restrictive
    ("v7d_guarded_nearband",_hydro_guard_params(threshold=7.5, near_band=20.0)),  # always-on within 20 of anchor
    ("v7e_guarded_widedist", _hydro_guard_params(threshold=7.5, max_dist=120.0)), # extend reverting zone
]:
    MEMBER_OVERRIDES[f"r3_hydro_{label}"] = {
        3: {
            "HYDROGEL_PACK": _override(
                _R3_HYDROGEL_V4_F5,
                strategy="r3_guarded_anchor_mm",
                quote_trace_enabled=True,
                **_hydro_v7_base(),
                **gparams,
            ),
            **_R3_HYDRO_DISABLE_REST,
        },
    }


# v7f: max3d_v7 + ar_gain 0.3 (like VELVET, was 0.2 in HYDRO)
MEMBER_OVERRIDES["r3_hydro_v7f_argain_03"] = {
    3: {
        "HYDROGEL_PACK": _override(
            _R3_HYDROGEL_V4_F5,
            quote_trace_enabled=True,
            **_hydro_v7_base(),
            ar_gain=0.3,
        ),
        **_R3_HYDRO_DISABLE_REST,
    },
}


# v7g: max3d_v7 + stronger passive unwind (skew=2 vs 1)
_v7g_params = _hydro_v7_base()
_v7g_params["passive_unwind_skew_ticks"] = 2
MEMBER_OVERRIDES["r3_hydro_v7g_unwind_skew2"] = {
    3: {
        "HYDROGEL_PACK": _override(
            _R3_HYDROGEL_V4_F5,
            quote_trace_enabled=True,
            **_v7g_params,
        ),
        **_R3_HYDRO_DISABLE_REST,
    },
}


# r3_hydro_guarded_v7 — apply R3GuardedAnchorMM to HYDROGEL (regime-aware anchor)
# Tests if guard logic (skip anchor pull when wrong-way + drifting away) helps HYDRO.
# HYDRO anchor=10000 might benefit from guarding when price drifts >40 ticks away.
MEMBER_OVERRIDES["r3_hydro_guarded_v7"] = {
    3: {
        "HYDROGEL_PACK": _override(
            _R3_HYDROGEL_V4_F5,
            strategy="r3_guarded_anchor_mm",
            quote_trace_enabled=True,
            # Theo v7 layers
            toxic_threshold=0.6,
            toxic_window=8,
            toxic_size_frac=0.68,
            passive_unwind_skew_ticks=1,
            passive_unwind_trigger=0.38,
            inventory_aversion_gamma=0.001,
            pct_kept_for_takers=0.005,
            # Guard params — adapt to HYDRO scale (anchor 10000, range ~9928-10071)
            # range = 143, so dist 40 is reasonable; max_dist 80 ~half range
            guard_trend_alpha=0.45,
            guard_reversion_threshold=7.5,
            guard_inventory_dist=40.0,
            guard_min_dist=0.0,
            guard_max_dist=80.0,
            guard_near_band=0.0,
        ),
        **_R3_HYDRO_DISABLE_REST,
    },
}

def _hydro_anchor_zgate_config(name: str, *, skip: float, taker: bool = False, take: float = 1.5) -> None:
    params = {
        **_R3_HYDROGEL_PARAMS,
        "quote_trace_enabled": True,
        "hzg_zscore_window": 500,
        "hzg_skip_threshold": skip,
        "hzg_enable_taker": taker,
        "hzg_taker_threshold": take,
        "hzg_taker_size": 6,
        "hzg_cooldown_ts": 1000,
    }
    MEMBER_OVERRIDES[name] = {
        3: {
            "HYDROGEL_PACK": _override(
                ROUND_3["HYDROGEL_PACK"],
                strategy="hydro_anchor_zgate_mm",
                position_limit=200,
                **params,
            ),
            **_R3_HYDRO_DISABLE_REST,
        },
    }


_hydro_anchor_zgate_config("r3_hydro_anchor_zgate_05", skip=0.5)
_hydro_anchor_zgate_config("r3_hydro_anchor_zgate_10", skip=1.0)
_hydro_anchor_zgate_config("r3_hydro_anchor_zgate_taker_15", skip=1.0, taker=True, take=1.5)

# Use slim strategies (single-mode) instead of selector_mm (which loads both modes)
# This brings inlined submission size down from 184 KB to <100 KB.
_R3_HYDRO_SELECTOR_COMMON_SLIM = dict(
    position_limit=200,
    anchor_params=_R3_HYDRO_SELECTOR_ANCHOR_PARAMS,
    guarded_params=_R3_HYDRO_SELECTOR_GUARDED_PARAMS,
    day2_start_mid=10011.0,
    day2_start_mid_tolerance=0.25,
    oracle_price_tolerance=2,
    oracle_use_live_l1=True,
    quote_trace_enabled=True,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)

MEMBER_OVERRIDES["r3_hydro_day2_oracle_regime"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_day2_oracle_guarded",       # SLIM: only guarded child
            **_R3_HYDRO_SELECTOR_COMMON_SLIM,
        ),
        **_R3_HYDRO_DISABLE_REST,
    },
}

MEMBER_OVERRIDES["r3_hydro_anchor_oracle_hybrid"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_day2_oracle_anchor",        # SLIM: only anchor child
            **_R3_HYDRO_SELECTOR_COMMON_SLIM,
        ),
        **_R3_HYDRO_DISABLE_REST,
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R3 VELVET + OPTIONS ONLY — alpha bet on options (HYDRO disabled)
# Léo's hypothesis: live IMC alpha is on options, not HYDRO.
# Strategy:
#   - HYDROGEL_PACK: disabled (None — no HYDRO trading)
#   - VELVETFRUIT_EXTRACT: small naive_tight_mm (passive ladder, capped pos)
#   - VEV options: option_mm_bs with smile + takers (more aggressive than theo)
# Theo baseline (day 2 live): VELVET +677, VEV +275 = +952 total
# Goal: capture more option mispricing via smile + tighter takers
# ──────────────────────────────────────────────────────────────────────────────
_R3_VELVET_OPT_OPTION_PARAMS = dict(
    strategy="option_mm_bs",
    enable_takers=False,                 # OFF — enabling takers led to -$662k loss
    inv_bias_per_unit=0.02,
    iv_ewma_alpha=0.3,
    log_flush_ts=1000,
    maker_edge=2,
    maker_size=24,
    min_quote_price=2.0,
    penny_improve_around_mkt=True,
    prior_vol=0.0125,
    sigma_cap=0.1,
    sigma_floor=0.005,
    take_edge=3.0,
    take_size=40,
    timestamp_units_per_day=1000000,
    ts_increment=100,
    last_ts_value=999900,
    tte_days_initial=5.0,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    use_smile=True,
)

# ──────────────────────────────────────────────────────────────────────────────
# R3 COMBINED — HYDRO (anchor+oracle hybrid TUNED) + VELVET + options
# Combines best HYDRO strategy (#3 hybrid +106k 3-day) with best VELVET+options
# (#5 velvet_options_alpha +13k 3-day). Goal: ~+120k 3-day total.
# ──────────────────────────────────────────────────────────────────────────────
# MEDIUM combined variant: anchor_max3d HYDRO (no oracle) + velvet+options
MEMBER_OVERRIDES["r3_combined_anchor_options"] = {
    3: {
        "HYDROGEL_PACK": _override(
            _R3_HYDROGEL_V4_F5,
            quote_trace_enabled=True,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=40,
            maker_size=20,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                position_limit=300,
                strike=strike,
                **_R3_VELVET_OPT_OPTION_PARAMS,
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# SLIM combined variant: smart HYDRO + velvet+options (under 100 KB)
MEMBER_OVERRIDES["r3_combined_smart_options"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_smart_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            trend_guard=6.0,
            signal_pos_gate=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            tighten_ticks=1,
            take_threshold=12.0,
            take_size=1,
            take_cooldown_ts=2000,
            extreme_dev_threshold=22.0,
            reversal_persist_ticks=3,
            min_pos_for_reversal_take=8,
            reversal_take_base=3,
            reversal_take_max=12,
            reversal_take_scale_div=4.0,
            reversal_cooldown_ts=1000,
            session_drift_bias=4,
            session_bias_strong_until_ts=100_000,
            session_bias_fade_until_ts=300_000,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=40,
            maker_size=20,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                position_limit=300,
                strike=strike,
                **_R3_VELVET_OPT_OPTION_PARAMS,
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_combined_hybrid_options"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_day2_oracle_anchor",
            **_R3_HYDRO_SELECTOR_COMMON_SLIM,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=40,
            maker_size=20,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                position_limit=300,
                strike=strike,
                **_R3_VELVET_OPT_OPTION_PARAMS,
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_velvet_options_alpha"] = {
    3: {
        "HYDROGEL_PACK": None,           # NO HYDRO — focus on options alpha
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=40,           # CAP tight (was 80) — markout small, no adverse blow-up
            maker_size=20,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        # VEV_4000: deep ITM gold mine — markout +9.26/fill, 0% adverse, BOOST size
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},  # 1.7x size
        ),
        # VEV_4500, 5000, 5100, 5200: standard size (some fill, some don't, low risk)
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                position_limit=300,
                strike=strike,
                **_R3_VELVET_OPT_OPTION_PARAMS,
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        # VEV_5300+: DISABLE — adverse selected (40-43% adverse, negative markout)
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# r3_velvet_options_alpha_v3 — same as v2 (alpha) but with selective taker on
# VEV_4500 ONLY (alpha analysis: rich_edge ≤ -2.0 → +3.6 markout, 84% win
# over 1000 ticks). All other strikes keep takers OFF (passive only).
# Also bumps inv_bias_per_unit 0.02 → 0.04 to attack the -4k inventory drift.
_R3_VELVET_OPT_OPTION_PARAMS_V3 = {
    **_R3_VELVET_OPT_OPTION_PARAMS,
    "inv_bias_per_unit": 0.04,
}
MEMBER_OVERRIDES["r3_velvet_options_alpha_v3"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=40,
            maker_size=20,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS_V3, "maker_size": 40},
        ),
        # VEV_4500: enable takers (selective alpha — rich_edge_le_-2 has 84% win)
        "VEV_4500": _override(
            ROUND_3["VEV_4500"],
            position_limit=300,
            strike=4500,
            **{
                **_R3_VELVET_OPT_OPTION_PARAMS_V3,
                "enable_takers": True,
                "take_edge": 2.0,         # match alpha-scan threshold
                "take_size": 20,          # cap per-tick taker size
                "maker_size": 28,         # boost passive too
            },
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                position_limit=300,
                strike=strike,
                **_R3_VELVET_OPT_OPTION_PARAMS_V3,
            )
            for strike in [5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_velvet_options_alpha_v4_sizeup"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=40,
            maker_size=20,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS_V3, "maker_size": 64},
        ),
        "VEV_4500": _override(
            ROUND_3["VEV_4500"],
            position_limit=300,
            strike=4500,
            **{
                **_R3_VELVET_OPT_OPTION_PARAMS_V3,
                "enable_takers": True,
                "take_edge": 2.0,
                "take_size": 20,
                "maker_size": 28,
            },
        ),
        "VEV_5200": _override(
            ROUND_3["VEV_5200"],
            position_limit=300,
            strike=5200,
            **{**_R3_VELVET_OPT_OPTION_PARAMS_V3, "maker_size": 48},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                position_limit=300,
                strike=strike,
                **_R3_VELVET_OPT_OPTION_PARAMS_V3,
            )
            for strike in [5000, 5100]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# r3_velvet_options_alpha_v4_high_k — fixes strike selection based on actual
# trade flow: VEV_4500/5000/5100 have ~0 market trades, VEV_5300/5400/5500
# have 37-94 trades/day. Switches to the active set with use_smile=False to
# avoid the smile-overshoot adverse selection that previously disabled them.
_R3_VELVET_OPT_HIGH_K = {
    **_R3_VELVET_OPT_OPTION_PARAMS_V3,
    "use_smile": False,
    "maker_size": 10,
    "maker_edge": 1,
    "min_quote_price": 1.0,
}
MEMBER_OVERRIDES["r3_velvet_options_alpha_v4_high_k"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=40,
            maker_size=20,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS_V3, "maker_size": 40},
        ),
        "VEV_5200": _override(
            ROUND_3["VEV_5200"],
            position_limit=300,
            strike=5200,
            **_R3_VELVET_OPT_OPTION_PARAMS_V3,
        ),
        "VEV_5300": _override(
            ROUND_3["VEV_5300"],
            position_limit=300,
            strike=5300,
            **_R3_VELVET_OPT_HIGH_K,
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"],
            position_limit=300,
            strike=5400,
            **_R3_VELVET_OPT_HIGH_K,
        ),
        "VEV_5500": _override(
            ROUND_3["VEV_5500"],
            position_limit=300,
            strike=5500,
            **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [4500, 5000, 5100, 6000, 6500]},
    },
}


# r3_velvet_options_alpha_v5_boost — same shape as v4_high_k but boosts
# VEV_5300 maker_size 10 → 18 (it produced +2,787 from 116 trades, max_pos
# 150/300 — capacity for more flow). Smaller boost on 5400 (12), keep 5500
# at break-even threshold (8).
MEMBER_OVERRIDES["r3_velvet_options_alpha_v5_boost"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=40,
            maker_size=20,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS_V3, "maker_size": 40},
        ),
        "VEV_5200": _override(
            ROUND_3["VEV_5200"],
            position_limit=300,
            strike=5200,
            **_R3_VELVET_OPT_OPTION_PARAMS_V3,
        ),
        "VEV_5300": _override(
            ROUND_3["VEV_5300"],
            position_limit=300,
            strike=5300,
            **{**_R3_VELVET_OPT_HIGH_K, "maker_size": 18},
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"],
            position_limit=300,
            strike=5400,
            **{**_R3_VELVET_OPT_HIGH_K, "maker_size": 12},
        ),
        "VEV_5500": _override(
            ROUND_3["VEV_5500"],
            position_limit=300,
            strike=5500,
            **{**_R3_VELVET_OPT_HIGH_K, "maker_size": 8},
        ),
        **{f"VEV_{k}": None for k in [4500, 5000, 5100, 6000, 6500]},
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# CLASSIC MM BASELINES (velvet + options only, HYDRO disabled)
# Used to anchor the alpha-comparison: how much does each piece of cleverness
# contribute on top of "what someone would write on day one of round 3"?
# ─────────────────────────────────────────────────────────────────────────────

# Naive MM baseline — naive_tight_mm on every product, no Black-Scholes,
# no smile, no inventory bias, no taker. Just: post penny-improved bid/ask.
MEMBER_OVERRIDES["r3_velvet_options_naive_mm"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=80,
            maker_size=30,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **{
            f"VEV_{k}": ProductConfig(
                symbol=f"VEV_{k}",
                strategy="naive_tight_mm",
                position_limit=300,
                params=dict(
                    maker_size=30,
                    tighten_ticks=1,
                    log_flush_ts=1000,
                    ts_increment=100,
                    last_ts_value=999900,
                ),
            )
            for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
        },
    },
}


# BS baseline — option_mm_bs with EVERYTHING disabled: no smile, no taker,
# no inventory bias. Just: penny-improve around BS-fair-implied EWMA mid.
# All 10 strikes enabled. This is what you'd write after reading the docs
# of option_mm_bs and toggling the "safest" defaults.
_R3_VELVET_OPT_BASELINE_BS = dict(
    strategy="option_mm_bs",
    enable_takers=False,
    inv_bias_per_unit=0.0,            # OFF
    iv_ewma_alpha=0.3,
    log_flush_ts=1000,
    maker_edge=2,
    maker_size=20,
    min_quote_price=2.0,
    penny_improve_around_mkt=True,
    prior_vol=0.0125,
    sigma_cap=0.10,
    sigma_floor=0.005,
    take_edge=3.0,
    take_size=40,
    timestamp_units_per_day=1000000,
    ts_increment=100,
    last_ts_value=999900,
    tte_days_initial=5.0,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    use_smile=False,                  # OFF — no smile
)
MEMBER_OVERRIDES["r3_velvet_options_baseline_bs"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=80,
            maker_size=30,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **{
            f"VEV_{k}": _override(
                ROUND_3[f"VEV_{k}"],
                position_limit=300,
                strike=k,
                **_R3_VELVET_OPT_BASELINE_BS,
            )
            for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
        },
    },
}


# r3_combined_hybrid_v4_high_k — HYDRO oracle+anchor hybrid (best 3d HYDRO)
# combined with v4_high_k velvet/options (active strikes 5300/5400/5500
# instead of dead 4500/5000/5100). Best of both worlds.
MEMBER_OVERRIDES["r3_combined_hybrid_v4_high_k"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_day2_oracle_anchor",
            **_R3_HYDRO_SELECTOR_COMMON_SLIM,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=40,
            maker_size=20,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS_V3, "maker_size": 40},
        ),
        "VEV_5200": _override(
            ROUND_3["VEV_5200"],
            position_limit=300,
            strike=5200,
            **_R3_VELVET_OPT_OPTION_PARAMS_V3,
        ),
        "VEV_5300": _override(
            ROUND_3["VEV_5300"],
            position_limit=300,
            strike=5300,
            **_R3_VELVET_OPT_HIGH_K,
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"],
            position_limit=300,
            strike=5400,
            **_R3_VELVET_OPT_HIGH_K,
        ),
        "VEV_5500": _override(
            ROUND_3["VEV_5500"],
            position_limit=300,
            strike=5500,
            **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [4500, 5000, 5100, 6000, 6500]},
    },
}


# R3 VELVET/options research variants (HYDRO disabled).
# These are intentionally separated so live tests can isolate the source of PnL.
_R3_VELVET_SMALL_MM = dict(
    strategy="naive_tight_mm",
    position_limit=40,
    maker_size=20,
    tighten_ticks=1,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)

_R3_OPTION_SKEW_SIGNAL_BASE = dict(
    strategy="option_skew_signal_mm",
    tte_days_initial=5.0,
    ticks_per_day=10000,
    timestamp_units_per_day=1000000,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    underlying_symbol="VELVETFRUIT_EXTRACT",
    strike_prefix="VEV_",
    smile_strikes=[4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500],
    prior_vol=0.0125,
    sigma_floor=0.005,
    sigma_cap=0.10,
    min_quote_price=2.0,
    maker_size=16,
    neutral_size=0,
    exit_size=10,
    take_size=10,
    enable_takers=False,
    quote_neutral=False,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)

MEMBER_OVERRIDES["r3_velvet_options_skew_signal"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_VELVET_SMALL_MM,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        "VEV_4500": _override(
            ROUND_3["VEV_4500"],
            position_limit=300,
            strike=4500,
            **{
                **_R3_OPTION_SKEW_SIGNAL_BASE,
                "entry_edge": 2.0,
                "maker_size": 24,
                "max_long": 20,
                "max_short": 100,
                "allow_new_shorts": True,
            },
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                position_limit=300,
                strike=strike,
                **{
                    **_R3_OPTION_SKEW_SIGNAL_BASE,
                    "entry_edge": (2.0 if strike in [5000, 5100] else 5.0),
                    "maker_size": 18,
                    "max_long": 80,
                    "max_short": 0,
                    "allow_new_shorts": False,
                },
            )
            for strike in [5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_velvet_options_skew_taker"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_VELVET_SMALL_MM,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        "VEV_4500": _override(
            ROUND_3["VEV_4500"],
            position_limit=300,
            strike=4500,
            **{
                **_R3_OPTION_SKEW_SIGNAL_BASE,
                "entry_edge": 2.0,
                "take_edge": 2.0,
                "maker_size": 8,
                "take_size": 8,
                "max_long": 10,
                "max_short": 80,
                "allow_new_shorts": True,
                "enable_takers": True,
            },
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                position_limit=300,
                strike=strike,
                **{
                    **_R3_OPTION_SKEW_SIGNAL_BASE,
                    "entry_edge": (2.0 if strike in [5000, 5100] else 5.0),
                    "take_edge": (2.0 if strike in [5000, 5100] else 5.0),
                    "maker_size": 8,
                    "take_size": 8,
                    "max_long": 60,
                    "max_short": 0,
                    "allow_new_shorts": False,
                    "enable_takers": True,
                },
            )
            for strike in [5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


_R3_VOL_HARVEST_OPTION_PARAMS = dict(
    strategy="vol_harvest",
    tte_days_initial=5.0,
    ticks_per_day=10000,
    timestamp_units_per_day=1000000,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    realized_vol_prior=0.0215,
    entry_edge=1.0,
    exit_edge=2.0,
    target_position=50,
    entry_size=8,
    exit_size=16,
    passive_bid_size=5,
    post_passive=True,
    min_quote_price=2.0,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)

MEMBER_OVERRIDES["r3_velvet_options_vol_harvest"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="velvet_delta_hedger",
            position_limit=200,
            underlying_symbol="VELVETFRUIT_EXTRACT",
            hedge_strikes=[4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500],
            strike_prefix="VEV_",
            tte_days_initial=5.0,
            timestamp_units_per_day=1000000,
            historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
            target_delta=0.0,
            hedge_taker_edge=25.0,
            max_hedge_size=35,
            passive_base_size=18,
            passive_skew_per_delta=0.25,
            quote_inside_book=True,
            sigma_floor=0.005,
            sigma_cap=0.10,
            prior_vol=0.0215,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                position_limit=300,
                strike=strike,
                **_R3_VOL_HARVEST_OPTION_PARAMS,
            )
            for strike in [5000, 5100, 5200, 5300, 5400, 5500]
        },
        **{f"VEV_{k}": None for k in [4500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_velvet_options_vol_harvest_unhedged"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_VELVET_SMALL_MM,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                position_limit=300,
                strike=strike,
                **_R3_VOL_HARVEST_OPTION_PARAMS,
            )
            for strike in [5000, 5100, 5200, 5300, 5400, 5500]
        },
        **{f"VEV_{k}": None for k in [4500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_velvet_options_gamma_scalp"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="velvet_delta_hedger",
            position_limit=200,
            underlying_symbol="VELVETFRUIT_EXTRACT",
            hedge_strikes=[4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500],
            strike_prefix="VEV_",
            tte_days_initial=5.0,
            timestamp_units_per_day=1000000,
            historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
            target_delta=0.0,
            hedge_taker_edge=10.0,
            max_hedge_size=35,
            passive_base_size=18,
            passive_skew_per_delta=0.30,
            quote_inside_book=True,
            sigma_floor=0.005,
            sigma_cap=0.10,
            prior_vol=0.018,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                strategy="gamma_scalp",
                position_limit=300,
                strike=strike,
                tte_days_initial=5.0,
                ticks_per_day=10000,
                timestamp_units_per_day=1000000,
                historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
                implied_vol_prior=0.0125,
                edge_ticks=0.0,
                target_qty=60,
                entry_size=8,
                passive_bid_size=6,
                unwind_tte_threshold=1.5,
                min_quote_price=2.0,
                underlying_symbol="VELVETFRUIT_EXTRACT",
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=999900,
            )
            for strike in [5000, 5100, 5200, 5300]
        },
        **{f"VEV_{k}": None for k in [4500, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_velvet_options_gamma_unhedged"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_VELVET_SMALL_MM,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                strategy="gamma_scalp",
                position_limit=300,
                strike=strike,
                tte_days_initial=5.0,
                ticks_per_day=10000,
                timestamp_units_per_day=1000000,
                historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
                implied_vol_prior=0.0125,
                edge_ticks=0.0,
                target_qty=60,
                entry_size=8,
                passive_bid_size=6,
                unwind_tte_threshold=1.5,
                min_quote_price=2.0,
                underlying_symbol="VELVETFRUIT_EXTRACT",
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=999900,
            )
            for strike in [5000, 5100, 5200, 5300]
        },
        **{f"VEV_{k}": None for k in [4500, 5400, 5500, 6000, 6500]},
    },
}


# r3_velvet_options_max3d_blend -- product-wise best-of for maximum 3-day
# VELVET/options backtest PnL.  This intentionally combines independent legs:
# VEV_4500 selective option_mm_bs, VEV_5000/5100/5200 unhedged gamma, and
# VEV_5300/5400 high-k passive.  VEV_5500 is disabled because it was slightly
# negative in the high-k baseline.
MEMBER_OVERRIDES["r3_velvet_options_max3d_blend"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_VELVET_SMALL_MM,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=300,
            strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        "VEV_4500": _override(
            ROUND_3["VEV_4500"],
            position_limit=300,
            strike=4500,
            **{
                **_R3_VELVET_OPT_OPTION_PARAMS_V3,
                "enable_takers": True,
                "take_edge": 2.0,
                "take_size": 20,
                "maker_size": 28,
            },
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                strategy="gamma_scalp",
                position_limit=300,
                strike=strike,
                tte_days_initial=5.0,
                ticks_per_day=10000,
                timestamp_units_per_day=1000000,
                historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
                implied_vol_prior=0.0125,
                edge_ticks=0.0,
                target_qty=60,
                entry_size=8,
                passive_bid_size=6,
                unwind_tte_threshold=1.5,
                min_quote_price=2.0,
                underlying_symbol="VELVETFRUIT_EXTRACT",
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=999900,
            )
            for strike in [5000, 5100, 5200]
        },
        "VEV_5300": _override(
            ROUND_3["VEV_5300"],
            position_limit=300,
            strike=5300,
            **_R3_VELVET_OPT_HIGH_K,
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"],
            position_limit=300,
            strike=5400,
            **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# Shared gamma_scalp params (UNHEDGED — hedging burns -21k)
def _gamma_scalp_params(target_qty: int, entry_size: int = 8, passive_bid_size: int = 6,
                        edge_ticks: float = 0.0, min_q: float = 2.0):
    return dict(
        strategy="gamma_scalp",
        tte_days_initial=5.0,
        ticks_per_day=10000,
        timestamp_units_per_day=1000000,
        historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
        implied_vol_prior=0.0125,
        edge_ticks=edge_ticks,
        target_qty=target_qty,
        entry_size=entry_size,
        passive_bid_size=passive_bid_size,
        unwind_tte_threshold=1.5,
        min_quote_price=min_q,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        log_flush_ts=1000,
        ts_increment=100,
        last_ts_value=999900,
    )


# r3_velvet_options_max3d_v2 — extends max3d_blend with:
#   - gamma_scalp on VEV_5400 (was passive +330)
#   - gamma_scalp on VEV_5500 (was disabled, has 81-94 trades/day)
#   - target_qty raised 60→100 on VEV_5000/5100/5200 (capacity-uncapped)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v2"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        "VEV_4500": _override(
            ROUND_3["VEV_4500"], position_limit=300, strike=4500,
            **{
                **_R3_VELVET_OPT_OPTION_PARAMS_V3,
                "enable_takers": True, "take_edge": 2.0, "take_size": 20, "maker_size": 28,
            },
        ),
        # gamma cluster — bigger target
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_scalp_params(target_qty=100, entry_size=10, passive_bid_size=8),
            )
            for strike in [5000, 5100, 5200]
        },
        # NEW — VEV_5300 keep no-smile passive (it beat gamma here +2787 vs +915)
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300, **_R3_VELVET_OPT_HIGH_K,
        ),
        # NEW — VEV_5400 try gamma_scalp (was passive +330)
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400,
            **_gamma_scalp_params(target_qty=80, entry_size=8, passive_bid_size=6, min_q=2.0),
        ),
        # NEW — VEV_5500 try gamma_scalp (was disabled — 81-94 trades/day)
        "VEV_5500": _override(
            ROUND_3["VEV_5500"], position_limit=300, strike=5500,
            **_gamma_scalp_params(target_qty=40, entry_size=5, passive_bid_size=4, min_q=1.0),
        ),
        **{f"VEV_{k}": None for k in [6000, 6500]},
    },
}


# r3_velvet_options_max3d_v3 — adds skew TILT (option_skew_signal_mm with low
# entry_edge + quote_neutral=True) on VEV_5300/5400 instead of no-smile passive.
# This captures the leave-one-out smile residual as a size bias rather than as
# a binary taker signal — the user's "informed-vs-OA" dichotomy.
_R3_SKEW_TILT_BASE = dict(
    strategy="option_skew_signal_mm",
    tte_days_initial=5.0,
    ticks_per_day=10000,
    timestamp_units_per_day=1000000,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    underlying_symbol="VELVETFRUIT_EXTRACT",
    strike_prefix="VEV_",
    smile_strikes=[4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500],
    prior_vol=0.0125,
    sigma_floor=0.005,
    sigma_cap=0.10,
    min_quote_price=1.0,
    entry_edge=1.0,                    # LOWER threshold — fire more often
    enable_takers=False,
    quote_neutral=True,                # <— always quote
    neutral_size=8,                    # smaller in neutral
    maker_size=16,                     # bigger when signal fires
    exit_size=10,
    take_size=10,
    max_long=80,
    max_short=40,
    allow_new_shorts=True,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v3"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        "VEV_4500": _override(
            ROUND_3["VEV_4500"], position_limit=300, strike=4500,
            **{
                **_R3_VELVET_OPT_OPTION_PARAMS_V3,
                "enable_takers": True, "take_edge": 2.0, "take_size": 20, "maker_size": 28,
            },
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_scalp_params(target_qty=60, entry_size=8, passive_bid_size=6),
            )
            for strike in [5000, 5100, 5200]
        },
        # NEW — skew tilt instead of no-smile passive
        "VEV_5300": _override(ROUND_3["VEV_5300"], position_limit=300, strike=5300, **_R3_SKEW_TILT_BASE),
        "VEV_5400": _override(ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_SKEW_TILT_BASE),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# r3_velvet_options_max3d_v5_optimal — best-of after v2/v3/v4 ablation:
#   - target_qty=100 on 5000/5100/5200 (the big +4.5k gain from v2)
#   - keep no-smile passive on 5300/5400 (beats both gamma and skew_tilt)
#   - VEV_5500 stays disabled (gamma loses, passive marginal-negative)
# Expected: ~+28,300 (= v2 minus the gamma-5400 loss minus the gamma-5500 loss)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v5_optimal"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        "VEV_4500": _override(
            ROUND_3["VEV_4500"], position_limit=300, strike=4500,
            **{
                **_R3_VELVET_OPT_OPTION_PARAMS_V3,
                "enable_takers": True, "take_edge": 2.0, "take_size": 20, "maker_size": 28,
            },
        ),
        # gamma cluster — target_qty=100 is the v2 unlock
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_scalp_params(target_qty=100, entry_size=10, passive_bid_size=8),
            )
            for strike in [5000, 5100, 5200]
        },
        # 5300 + 5400 — no-smile passive beats gamma_scalp here
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300, **_R3_VELVET_OPT_HIGH_K,
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# r3_velvet_options_max3d_v7_target200 / v8_target300 — keep pushing target_qty
# until we find the inflection. v6@150 = +36,548 still capped at max_pos=150.
def _v_with_target(target_qty: int):
    return {
        3: {
            "HYDROGEL_PACK": None,
            "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
            "VEV_4000": _override(
                ROUND_3["VEV_4000"], position_limit=300, strike=4000,
                **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
            ),
            "VEV_4500": _override(
                ROUND_3["VEV_4500"], position_limit=300, strike=4500,
                **{
                    **_R3_VELVET_OPT_OPTION_PARAMS_V3,
                    "enable_takers": True, "take_edge": 2.0, "take_size": 20, "maker_size": 28,
                },
            ),
            **{
                f"VEV_{strike}": _override(
                    ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                    **_gamma_scalp_params(
                        target_qty=target_qty,
                        entry_size=max(int(target_qty * 0.10), 10),
                        passive_bid_size=max(int(target_qty * 0.08), 8),
                    ),
                )
                for strike in [5000, 5100, 5200]
            },
            "VEV_5300": _override(ROUND_3["VEV_5300"], position_limit=300, strike=5300, **_R3_VELVET_OPT_HIGH_K),
            "VEV_5400": _override(ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K),
            **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
        },
    }
MEMBER_OVERRIDES["r3_velvet_options_max3d_v7_target200"] = _v_with_target(200)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v8_target300"] = _v_with_target(300)


# r3_velvet_options_max3d_v9_widegamma — extend gamma cluster to VEV_5300 too
# (was no-smile passive +2,787; gamma at target=300 might unlock more)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v9_widegamma"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        "VEV_4500": _override(
            ROUND_3["VEV_4500"], position_limit=300, strike=4500,
            **{
                **_R3_VELVET_OPT_OPTION_PARAMS_V3,
                "enable_takers": True, "take_edge": 2.0, "take_size": 20, "maker_size": 28,
            },
        ),
        # Extend gamma cluster to 5300 too
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_scalp_params(target_qty=300, entry_size=30, passive_bid_size=24),
            )
            for strike in [5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# r3_velvet_options_max3d_v11_optimal — best of all variants:
#   - gamma_scalp@target=300 on VEV_4500/5000/5100/5200/5300 (the +18k VEV_4500 unlock from v10)
#   - VEV_5400 stays no-smile passive (gamma loses there in v10: -296 vs +330 passive)
#   - VEV_4000 stays option_mm_bs default (smile, the +8.8k workhorse)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v11_optimal"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        # gamma cluster — 4500 to 5300 at target=300
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_scalp_params(target_qty=300, entry_size=30, passive_bid_size=24),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        # VEV_5400 stays no-smile passive (gamma fails here)
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Delta hedge variants on top of v11_optimal (the +70,386 leader). The default
# velvet_delta_hedger burns -21k via aggressive taker hedges. These variants
# damp the hedger to passive-only / low-frequency to keep the gamma PnL while
# reducing the -56k max drawdown.
# ─────────────────────────────────────────────────────────────────────────────

# v12_dh_passive — passive size skew only, no taker hedge ever
def _v11_options_only():
    """Returns the option leg of v11 (HYDROGEL=None, all 8 VEV strikes set)."""
    return {
        "HYDROGEL_PACK": None,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_scalp_params(target_qty=300, entry_size=30, passive_bid_size=24),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    }


_R3_VELVET_DH_BASE = dict(
    strategy="velvet_delta_hedger",
    underlying_symbol="VELVETFRUIT_EXTRACT",
    strike_prefix="VEV_",
    hedge_strikes=[4500, 5000, 5100, 5200, 5300, 5400],
    target_delta=0.0,
    passive_base_size=30,
    quote_inside_book=True,
    tte_days_initial=5.0,
    timestamp_units_per_day=1000000,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    sigma_floor=0.005,
    sigma_cap=0.10,
    prior_vol=0.0125,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)


# R3 live-defensive candidate:
# - no fixed anchor on the delta-1 products
# - throttle bids into downtrends / asks into uptrends
# - aggressively favor the side that reduces inventory
# - keep vouchers on the passive BS option MM that has been stable live
MEMBER_OVERRIDES["r3_live_defensive_v1"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_live_defensive_mm",
            position_limit=200,
            **_R3_LIVE_DEFENSIVE_PARAMS,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="r3_live_defensive_mm",
            position_limit=200,
            **_R3_LIVE_DEFENSIVE_PARAMS,
        ),
        # Vouchers: use ROUND_3 default option_mm_bs (penny-improve, no takers).
    },
}


# R3 live-defensive candidate:
# - no fixed anchor on the delta-1 products
# - throttle bids into downtrends / asks into uptrends
# - aggressively favor the side that reduces inventory
# - keep vouchers on the passive BS option MM that has been stable live
MEMBER_OVERRIDES["r3_live_defensive_v1"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_live_defensive_mm",
            position_limit=200,
            **_R3_LIVE_DEFENSIVE_PARAMS,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="r3_live_defensive_mm",
            position_limit=200,
            **_R3_LIVE_DEFENSIVE_PARAMS,
        ),
        # Vouchers: use ROUND_3 default option_mm_bs (penny-improve, no takers).
    },
}

# v12: passive-only hedger (taker_edge huge → never fires), small size skew
MEMBER_OVERRIDES["r3_velvet_options_max3d_v12_dh_passive"] = {
    3: {
        **_v11_options_only(),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            position_limit=40,                 # same as v11 cap
            **{
                **_R3_VELVET_DH_BASE,
                "hedge_taker_edge": 99999,     # NEVER fire taker
                "passive_skew_per_delta": 0.05,  # small bias (per unit option delta)
                "passive_base_size": 20,        # match v11 maker_size
            },
        ),
    },
}


# Hybrid candidate after ablation:
# HYDROGEL historically likes the pure book-following naive MM, while VELVET
# benefits from defensive trend/inventory throttling. Options remain the stable
# passive BS MM.
MEMBER_OVERRIDES["r3_live_hybrid_v1"] = {
    3: {},  # placeholder — original content lost in bad merge
}


# Hybrid candidate after ablation:
# HYDROGEL historically likes the pure book-following naive MM, while VELVET
# benefits from defensive trend/inventory throttling. Options remain the stable
# passive BS MM.
MEMBER_OVERRIDES["r3_live_hybrid_v1"] = {}  # content removed — was incomplete

# v13: low-freq hedger — taker only on huge imbalance + bigger passive bias


MEMBER_OVERRIDES["r3_velvet_options_max3d_v13_dh_lowfreq"] = {
    3: {
        **_v11_options_only(),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            position_limit=40,
            **{
                **_R3_VELVET_DH_BASE,
                "hedge_taker_edge": 250,        # rare — option delta sums easily reach 100s
                "max_hedge_size": 20,           # smaller hedge size when fired
                "passive_skew_per_delta": 0.10,
                "passive_base_size": 20,
            },
        ),
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Tibo-inspired variants: VELVET z-score gating on gamma_scalp entries
# (skip when expensive, optionally boost when cheap)
# ─────────────────────────────────────────────────────────────────────────────
def _gamma_zgated_params(target_qty: int, entry_size: int = 30, passive_size: int = 24,
                          skip_when_expensive: bool = True,
                          boost_when_cheap: bool = False,
                          z_skip_threshold: float = 1.0,
                          z_boost_threshold: float = 1.0,
                          entry_size_boost: float = 1.5,
                          edge_ticks: float = 0.0,
                          min_q: float = 2.0):
    return dict(
        strategy="gamma_scalp_zgated",
        tte_days_initial=5.0,
        ticks_per_day=10000,
        timestamp_units_per_day=1000000,
        historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
        implied_vol_prior=0.0125,
        edge_ticks=edge_ticks,
        target_qty=target_qty,
        entry_size=entry_size,
        passive_bid_size=passive_size,
        unwind_tte_threshold=1.5,
        min_quote_price=min_q,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        # z-gate
        zscore_window=500,
        zscore_skip_threshold=z_skip_threshold,
        zscore_boost_threshold=z_boost_threshold,
        skip_when_expensive=skip_when_expensive,
        boost_when_cheap=boost_when_cheap,
        entry_size_boost=entry_size_boost,
        log_flush_ts=1000,
        ts_increment=100,
        last_ts_value=999900,
    )


# v18_z_skip: v11 + skip entries when VELVET z > +1.0 (Tibo's "expensive" gate)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v18_z_skip"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        # gamma_scalp_zgated on 4500-5300 with skip_when_expensive=True
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, skip_when_expensive=True),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v19_z_skip_loose: same but z_skip_threshold=1.5 (less aggressive gate)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v19_z_skip_loose"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=1.5),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v20_z_skip_strict: aggressive gate z_skip_threshold=0.5 (most reduction in DD)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v20_z_skip_strict"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v21_z_sell: v20 (skip on z>0.5) + profit-take when z>+1.5 (Tibo asymmetric ASK)
def _gamma_zgated_with_sell(z_skip: float = 0.5, z_sell: float = 1.5,
                              sell_pct: float = 0.10,
                              target_qty: int = 300):
    return dict(
        strategy="gamma_scalp_zgated",
        tte_days_initial=5.0,
        ticks_per_day=10000,
        timestamp_units_per_day=1000000,
        historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
        implied_vol_prior=0.0125,
        edge_ticks=0.0,
        target_qty=target_qty,
        entry_size=30,
        passive_bid_size=24,
        unwind_tte_threshold=1.5,
        min_quote_price=2.0,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        zscore_window=500,
        zscore_skip_threshold=z_skip,
        skip_when_expensive=True,
        boost_when_cheap=False,
        # Profit-take asymmetric ask
        sell_when_very_expensive=True,
        zscore_sell_threshold=z_sell,
        sell_size_pct=sell_pct,
        log_flush_ts=1000,
        ts_increment=100,
        last_ts_value=999900,
    )


MEMBER_OVERRIDES["r3_velvet_options_max3d_v21_z_sell"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_sell(z_skip=0.5, z_sell=1.5, sell_pct=0.10),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v22_z_sell_aggro: lower sell threshold (z>1.0) + bigger sell pct (15%)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v22_z_sell_aggro"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_sell(z_skip=0.5, z_sell=1.0, sell_pct=0.15),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v23_vega_pair: vega-neutral pair on K=5100 + K=5300 (similar vegas, opposite IV bias)
# rest of stack = v11 unchanged
_R3_VEGA_PAIR_BASE = dict(
    strategy="vega_neutral_pair_mm",
    underlying_symbol="VELVETFRUIT_EXTRACT",
    prior_vol=0.0125,
    base_size=50,
    maker_size=10,
    exit_size=10,
    iv_gap_threshold=0.0005,    # 5 bps IV (per-day) gap to enter
    exit_threshold=0.0001,      # 1 bp gap to exit
    tte_days_initial=5.0,
    timestamp_units_per_day=1000000,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)
# v32: v24 + IV residual gate on gamma cluster (passive momentum exploitation).
# Skip entries when option residual is "cheap getting cheaper" (avoid catching
# falling option). Boost passive size when "rich getting richer" (load at peak).
def _gamma_zgated_with_iv_gate(z_skip: float = 0.5, target_qty: int = 300,
                                 iv_skip: float = 0.0010,
                                 iv_boost: float = 0.0010,
                                 iv_delta: float = 0.0003,
                                 passive_boost: float = 1.5):
    return dict(
        strategy="gamma_scalp_zgated",
        tte_days_initial=5.0,
        ticks_per_day=10000,
        timestamp_units_per_day=1000000,
        historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
        implied_vol_prior=0.0125,
        edge_ticks=0.0,
        target_qty=target_qty,
        entry_size=30,
        passive_bid_size=24,
        unwind_tte_threshold=1.5,
        min_quote_price=2.0,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        zscore_window=500,
        zscore_skip_threshold=z_skip,
        skip_when_expensive=True,
        boost_when_cheap=False,
        iv_residual_gate=True,
        iv_skip_threshold=iv_skip,
        iv_boost_threshold=iv_boost,
        iv_delta_threshold=iv_delta,
        iv_ewma_fast_alpha=0.10,
        iv_ewma_slow_alpha=0.02,
        iv_passive_boost=passive_boost,
        log_flush_ts=1000,
        ts_increment=100,
        last_ts_value=999900,
    )


MEMBER_OVERRIDES["r3_velvet_options_max3d_v32_iv_gate"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v33: per-strike z-skip thresholds (tuned by greeks)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v33_per_strike_z"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        # K=4500 (delta~1) → tight z (more reactive to VELVET extremes)
        "VEV_4500": _override(
            ROUND_3["VEV_4500"], position_limit=300, strike=4500,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.3),
        ),
        # K=5000-5200 (max vega) → standard
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
            )
            for strike in [5000, 5100, 5200]
        },
        # K=5300 (lower vega) → looser
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.8),
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v35: per-strike z REVERSED hypothesis (4500 looser since high delta = wants more)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v35_per_strike_z_rev"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        # K=4500 LOOSER (more accumulation OK, near-delta-1 + caps already at 300)
        "VEV_4500": _override(
            ROUND_3["VEV_4500"], position_limit=300, strike=4500,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=1.0),
        ),
        # K=5000-5200 STANDARD
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
            )
            for strike in [5000, 5100, 5200]
        },
        # K=5300 standard
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v50: Theo's improvements integrated (velvet+options ONLY, no HYDROGEL)
# Adopt: 1) R3GuardedAnchorMM on VELVET (guard logic — only anchor when reverting)
#        2) gamma_scalp_zgated on VEV_4000 with target=300 (vs option_mm_bs)
# Drop: HYDROGEL (keep velvet+options scope)
# Keep: gamma cluster 4500-5300 (from v34 best mix), drop 5400 + 5500
_R3_THEO_GUARDED_VELVET_PARAMS = dict(
    strategy="r3_guarded_anchor_mm",
    position_limit=200,
    maker_size=30,
    tighten_ticks=1,
    pct_kept_for_takers=0.05,
    anchor_price=5250.0,
    anchor_alpha=0.02,
    anchor_drift_bound=2.0,
    ar_gain=0.3,
    ar_shift_source="mid_smooth",
    full_capacity_on_empty=True,
    inventory_aversion_gamma=0.0015,
    take_edge_lo=0.6,
    take_edge_hi=1.2,
    unwind_take_edge=3.0,
    # Guard params
    guard_trend_alpha=0.45,
    guard_reversion_threshold=7.5,
    guard_inventory_dist=40.0,
    guard_min_dist=0.0,
    guard_max_dist=80.0,
    guard_near_band=0.0,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v50_theo_integrated"] = {
    3: {
        "HYDROGEL_PACK": None,
        # KEY 1: R3GuardedAnchorMM on VELVET (Theo's guard logic)
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_GUARDED_VELVET_PARAMS,
        ),
        # KEY 2: VEV_4000 on gamma_scalp_zgated target=300 (Theo's setup)
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
        ),
        # Gamma cluster 4500-5300 (our v34 mix with IV gate)
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **_gamma_zgated_with_iv_gate(z_skip=0.8),
        ),
        # Drop 5400/5500 (drag per per-asset analysis)
        **{f"VEV_{k}": None for k in [5400, 5500, 6000, 6500]},
    },
}


# v51: same as v50 but add VEV_5400 and VEV_5500 like Theo (full strikes)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v51_theo_full"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_GUARDED_VELVET_PARAMS,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
        ),
        # All 4500-5500 strikes on gamma_scalp_zgated like Theo
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
            )
            for strike in [4500, 5000, 5100, 5200, 5300, 5400, 5500]
        },
        **{f"VEV_{k}": None for k in [6000, 6500]},
    },
}


# v52: v50 + drop 5300 too (max 4 strikes only, ultra-conservative)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v52_theo_minimal"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_GUARDED_VELVET_PARAMS,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# === Theo v6 velvettuned integration ====================================
# Theo's v6 adds toxic flow detection on VELVET (toxic_threshold=0.6,
# toxic_window=8, toxic_size_frac=0.68). When market trades show >60%
# directional imbalance over last 8 trades, shrink the wrong-side quote
# to 68% — protects against informed flow.
# Also: pct_kept_for_takers 0.05 → 0.005 (more aggressive takers),
# adds maker_size_base_pct=0.4. Theo claims +2k PnL vs v5.
_R3_THEO_V6_GUARDED_VELVET_PARAMS = dict(
    _R3_THEO_GUARDED_VELVET_PARAMS,
    # Toxic flow protection (NEW in v6)
    toxic_threshold=0.6,
    toxic_window=8,
    toxic_size_frac=0.68,
    # More aggressive taker reserve
    pct_kept_for_takers=0.005,
    # Explicit base sizing
    maker_size_base_pct=0.4,
)


# v53: v52 + Theo v6 toxic flow on VELVET (4 strikes only — minimal scope)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v53_v6_minimal"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V6_GUARDED_VELVET_PARAMS,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# v54: v53 + Theo v6 per-strike zscore_skip_threshold (his actual tuning)
# Theo's per-strike z thresholds (4000-5500): 1.5, 2.0, 1.0, 0.5, 2.0, 2.0, 1.0, 0.5
# But we drop 5300/5400/5500 like v52
_THEO_V6_Z_SKIP = {
    4000: 1.5,
    4500: 2.0,
    5000: 1.0,
    5100: 0.5,
    5200: 2.0,
    5300: 2.0,
    5400: 1.0,
    5500: 0.5,
}
MEMBER_OVERRIDES["r3_velvet_options_max3d_v54_v6_per_strike_z"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V6_GUARDED_VELVET_PARAMS,
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=_THEO_V6_Z_SKIP[strike]),
            )
            for strike in [4000, 4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# v55: v54 + full strikes 4500-5500 like Theo v6 (max scope)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v55_v6_full"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V6_GUARDED_VELVET_PARAMS,
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=_THEO_V6_Z_SKIP[strike]),
            )
            for strike in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500]
        },
        **{f"VEV_{k}": None for k in [6000, 6500]},
    },
}


# v57: v53 + Theo v7 passive unwind on VELVET (asym skew toward mid when |pos|>38%)
# Theo v7 diff vs v6: only 3 lines in VELVET params
#   inventory_aversion_gamma: 0.0015 → 0.001 (less fair-value shift)
#   passive_unwind_skew_ticks=1
#   passive_unwind_trigger=0.38
# Logic: when |pos|/limit > 0.38, tighten only the UNWIND side passive quote by
# 1 tick (scaled linearly with pressure). More efficient than shifting both sides.
_R3_THEO_V7_GUARDED_VELVET_PARAMS = dict(
    _R3_THEO_V6_GUARDED_VELVET_PARAMS,
    inventory_aversion_gamma=0.001,  # was 0.0015
    passive_unwind_skew_ticks=1,
    passive_unwind_trigger=0.38,
)


MEMBER_OVERRIDES["r3_velvet_options_max3d_v57_v7_passive_unwind"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V7_GUARDED_VELVET_PARAMS,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# v58: v56 + passive unwind (5300 included with iv_gate)
# Sensitivity test: vary passive_unwind_trigger to detect overfit
def _build_unwind_variant(trigger: float) -> Dict[str, Any]:
    return dict(
        _R3_THEO_V6_GUARDED_VELVET_PARAMS,
        inventory_aversion_gamma=0.001,
        passive_unwind_skew_ticks=1,
        passive_unwind_trigger=trigger,
    )

for _suffix, _trigger in [("030", 0.30), ("040", 0.40), ("050", 0.50)]:
    MEMBER_OVERRIDES[f"r3_velvet_options_max3d_v57_unwind_trigger_{_suffix}"] = {
        3: {
            "HYDROGEL_PACK": None,
            "VELVETFRUIT_EXTRACT": _override(
                ROUND_3["VELVETFRUIT_EXTRACT"],
                **_build_unwind_variant(_trigger),
            ),
            "VEV_4000": _override(
                ROUND_3["VEV_4000"], position_limit=300, strike=4000,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
            ),
            **{
                f"VEV_{strike}": _override(
                    ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                    **_gamma_zgated_with_iv_gate(z_skip=0.5),
                )
                for strike in [4500, 5000, 5100, 5200]
            },
            **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
        },
    }


# v61: v57 base (R3GuardedAnchor + toxic + unwind on VELVET, gamma_scalp+IV gate on 4500-5200)
# + Tibo's VEVOptionMMV3 (2-sided passive MM) on VEV_5300/5400 (re-enable far-OTM strikes)
# Tibo proved: 2-sided MM beats gamma_scalp on far-OTM by ~6k because we can flip out
def _tibo_vev_mm(strike: int, prevent_crossing: bool = False, **extra: Any) -> Dict[str, Any]:
    return _override(
        ROUND_3[f"VEV_{strike}"],
        position_limit=300,
        strategy="vev_option_mm_v3",
        strike=float(strike),
        ask_offset_neutral=10,
        ask_offset_sell=1,
        delta_sigma=0.022,
        maker_size_ask=5,
        maker_size_bid=20,
        min_quote_price=2.0,
        prevent_crossing=prevent_crossing,
        zscore_bid_max=4.0,
        zscore_bid_scale=2.0,
        zscore_exec_mode="none",
        zscore_threshold=1.0,
        zscore_window=500,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        log_flush_ts=1000,
        ts_increment=100,
        last_ts_value=999900,
        tte_days_initial=5.0,
        timestamp_units_per_day=1000000,
        historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
        **extra,
    )


# v61: v57 + 2-sided MM on VEV_5300/5400 (re-enable with safe approach)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v61_tibo_far_otm"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V7_GUARDED_VELVET_PARAMS,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        # Tibo's far-OTM MM (re-enable 5300/5400 with 2-sided)
        "VEV_5300": _tibo_vev_mm(5300),
        "VEV_5400": _tibo_vev_mm(5400, prevent_crossing=True),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v62: v61 + replace gamma_scalp on 5200 with Tibo's 2-sided MM (full Tibo far-OTM mode)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v62_tibo_5200_5400"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V7_GUARDED_VELVET_PARAMS,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100]
        },
        # Tibo's far-OTM MM (5200/5300/5400 all 2-sided)
        "VEV_5200": _tibo_vev_mm(5200),
        "VEV_5300": _tibo_vev_mm(5300),
        "VEV_5400": _tibo_vev_mm(5400, prevent_crossing=True),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v59: v55 (max PnL stretch with all 8 strikes per-strike z) + passive unwind on VELVET
# Goal: capture +6.4k VELVET boost from passive unwind on top of v55's max PnL setup
MEMBER_OVERRIDES["r3_velvet_options_max3d_v59_v7_max_pnl_unwind"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V7_GUARDED_VELVET_PARAMS,
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=_THEO_V6_Z_SKIP[strike]),
            )
            for strike in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500]
        },
        **{f"VEV_{k}": None for k in [6000, 6500]},
    },
}


# v60: v54 (per-strike z, no full strikes) + passive unwind
# Goal: capture VELVET boost without 5400/5500 drag
MEMBER_OVERRIDES["r3_velvet_options_max3d_v60_v7_per_strike_z_unwind"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V7_GUARDED_VELVET_PARAMS,
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=_THEO_V6_Z_SKIP[strike]),
            )
            for strike in [4000, 4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_velvet_options_max3d_v58_v7_with_5300"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V7_GUARDED_VELVET_PARAMS,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **_gamma_zgated_with_iv_gate(z_skip=0.8),
        ),
        **{f"VEV_{k}": None for k in [5400, 5500, 6000, 6500]},
    },
}


# v56: v53 + add VEV_5300 with iv_gate (Pareto stretch — like v50 with v6 toxic flow)
# Live evidence core from IMC probes 00A..17.
# Keep only legs with positive live markout and remove toxic live probes:
# HYDRO anchor/passive, VELVET small passive, tiny passive VEV_4000,
# dynamic VEV_4500, small conservative VEV_5000/5100/5200.
_R3_LIVE_CORE_4000_PASSIVE = {
    **_R3_VELVET_OPT_OPTION_PARAMS_V3,
    "maker_size": 10,
    "enable_takers": False,
    "take_size": 0,
}


def _r3_live_core_gamma_params(
    *,
    target_qty: int,
    entry_size: int,
    passive_bid_size: int,
    passive_boost: float,
    z_skip: float = 0.5,
) -> Dict[str, Any]:
    params = _gamma_zgated_with_iv_gate(
        z_skip=z_skip,
        target_qty=target_qty,
        passive_boost=passive_boost,
    )
    params.update(
        entry_size=entry_size,
        passive_bid_size=passive_bid_size,
        take_size=0,
    )
    return params


MEMBER_OVERRIDES["r3_live_alpha_core_v1"] = {
    3: {
        "HYDROGEL_PACK": _override(
            _R3_HYDROGEL_V4_F5,
            quote_trace_enabled=True,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_VELVET_SMALL_MM,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"],
            position_limit=80,
            strike=4000,
            **_R3_LIVE_CORE_4000_PASSIVE,
        ),
        "VEV_4500": _override(
            ROUND_3["VEV_4500"],
            position_limit=180,
            strike=4500,
            **_r3_live_core_gamma_params(
                target_qty=160,
                entry_size=12,
                passive_bid_size=10,
                passive_boost=1.25,
                z_skip=0.5,
            ),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                position_limit=120,
                strike=strike,
                **_r3_live_core_gamma_params(
                    target_qty=60,
                    entry_size=6,
                    passive_bid_size=5,
                    passive_boost=1.15,
                    z_skip=0.5,
                ),
            )
            for strike in [5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_velvet_options_max3d_v56_v6_with_5300"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V6_GUARDED_VELVET_PARAMS,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **_gamma_zgated_with_iv_gate(z_skip=0.8),
        ),
        **{f"VEV_{k}": None for k in [5400, 5500, 6000, 6500]},
    },
}


# v44: v38 + VEV_4000 enable_takers=True (test if smile-aware takers help on best strike)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v44_4000_takers"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{
                **_R3_VELVET_OPT_OPTION_PARAMS,
                "maker_size": 40,
                "enable_takers": True,    # NEW: turn on smile-aware takers
                "take_edge": 3.0,
                "take_size": 20,
            },
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# v45: v38 + VEV_5500 short OTM theta seller (greeks split — passive ASK only)
# Hypothesis: collect spread + theta, exit if delta gets bad
MEMBER_OVERRIDES["r3_velvet_options_max3d_v45_greeks_split"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        # NEW: VEV_5500 as short-only theta seller (small naive_tight_mm)
        "VEV_5500": _override(
            ROUND_3["VEV_5500"],
            strategy="naive_tight_mm",
            position_limit=80,
            maker_size=8,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **{f"VEV_{k}": None for k in [5300, 5400, 6000, 6500]},
    },
}


# v46: v38 architecture + vega-weighted target_qty
# (per per-asset analysis: 5200/5300 vega ~5500, 5000/5100 ~3000-4000, 4500 ~110)
# Target_qty proportional to vega cap=300 max
# Vega rough: 4500=110, 5000=2135, 5100=4071, 5200=5501
# Sum = 11817, weights = 0.93%, 18%, 34%, 47%. Cap at 300 → all hit cap
# Uniform 300 IS already vega-weighted at the top — no improvement expected
MEMBER_OVERRIDES["r3_velvet_options_max3d_v46_vega_weighted"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        # Vega-weighted target_qty (ATM strikes higher target)
        "VEV_4500": _override(
            ROUND_3["VEV_4500"], position_limit=300, strike=4500,
            **_gamma_zgated_params(target_qty=100, z_skip_threshold=0.5),  # low vega → small
        ),
        "VEV_5000": _override(
            ROUND_3["VEV_5000"], position_limit=300, strike=5000,
            **_gamma_zgated_params(target_qty=200, z_skip_threshold=0.5),  # mid vega
        ),
        "VEV_5100": _override(
            ROUND_3["VEV_5100"], position_limit=300, strike=5100,
            **_gamma_zgated_params(target_qty=280, z_skip_threshold=0.5),  # higher
        ),
        "VEV_5200": _override(
            ROUND_3["VEV_5200"], position_limit=300, strike=5200,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),  # max vega → max
        ),
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# v42: OPTIMAL = v38 (drop drag) + IV gate ALL gamma cluster
# Best of both: drop drag strikes (5300/5400) AND apply IV gate selective to all
MEMBER_OVERRIDES["r3_velvet_options_max3d_v42_optimal"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        # gamma cluster 4500-5200 with IV gate (drop 5300 + 5400)
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# v43: SELECTIVE = v38 + IV gate ONLY on VEV_5000 (where it proved best per per-asset)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v43_selective_iv_gate"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        # 4500/5100/5200: standard z-skip, NO IV gate
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
            )
            for strike in [4500, 5100, 5200]
        },
        # 5000: IV gate ON (per-asset analysis: best risk-adj swap here)
        "VEV_5000": _override(
            ROUND_3["VEV_5000"], position_limit=300, strike=5000,
            **_gamma_zgated_with_iv_gate(z_skip=0.5),
        ),
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# v40: v24 base + VEV_4000 BIG size boost (best risk-adj 4.69, underweighted)
# Try maker_size 40 → 80 to see if more flow available
MEMBER_OVERRIDES["r3_velvet_options_max3d_v40_4000_boost"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 80},  # 2x boost
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v41: combo BEST = drop VEV_5400 + VEV_4000 size boost + IV gate + 5300 z>0.8
MEMBER_OVERRIDES["r3_velvet_options_max3d_v41_combo_best"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 80},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **_gamma_zgated_with_iv_gate(z_skip=0.8),
        ),
        **{f"VEV_{k}": None for k in [5400, 5500, 6000, 6500]},  # drop 5400
    },
}


# v38: drop VEV_5300/5400 (per-asset analysis: ratio 0.42/0.30 = drag).
# Keep IV gate + standard z>0.5 on remaining gamma cluster.
MEMBER_OVERRIDES["r3_velvet_options_max3d_v38_drop_bad"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        # Gamma cluster on 4500-5200 (drop 5300!)
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        # DROP 5300 and 5400 (poor risk-adjusted ratios)
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# v39: drop only VEV_5400 (keep 5300 — ratio 0.42 still adds some PnL)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v39_drop_5400_only"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        # Keep 5300 with looser z (0.8) + IV gate
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **_gamma_zgated_with_iv_gate(z_skip=0.8),
        ),
        **{f"VEV_{k}": None for k in [5400, 5500, 6000, 6500]},
    },
}


# v37: BEST OF ALL — IV gate + 5300 z>0.8 (only param tweak that worked) + others stay 0.5
MEMBER_OVERRIDES["r3_velvet_options_max3d_v37_best_combo"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        # All gamma cluster z>0.5 + IV gate (IV gate added to v24)
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        # K=5300 looser (z>0.8) + IV gate
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **_gamma_zgated_with_iv_gate(z_skip=0.8),
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v36: ULTIMATE = v34 + v35's looser 4500 (z>0.7 — middle ground)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v36_ultimate"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        # K=4500 LOOSER (z>0.7 — try to keep the +18k full)
        "VEV_4500": _override(
            ROUND_3["VEV_4500"], position_limit=300, strike=4500,
            **_gamma_zgated_with_iv_gate(z_skip=0.7),
        ),
        # K=5000-5200 standard with IV gate
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [5000, 5100, 5200]
        },
        # K=5300 looser standard
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **_gamma_zgated_with_iv_gate(z_skip=0.8),
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v34: combo — v32 (IV gate) + v33 (per-strike z thresholds)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v34_combined"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        "VEV_4500": _override(
            ROUND_3["VEV_4500"], position_limit=300, strike=4500,
            **_gamma_zgated_with_iv_gate(z_skip=0.3),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [5000, 5100, 5200]
        },
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **_gamma_zgated_with_iv_gate(z_skip=0.8),
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v30: v24 architecture + LOW-FREQUENCY delta hedge (only 1 hedge per 1000 ticks)
# Tests if rare-but-large hedges have better cost/benefit than every-tick.
MEMBER_OVERRIDES["r3_velvet_options_max3d_v30_dh_lowfreq_1000"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            position_limit=200,                # like v12 (R2 wants larger limit)
            **{
                **_R3_VELVET_DH_BASE,
                "hedge_taker_edge": 100,        # fire when |delta| > 100
                "min_ticks_between_hedges": 1000,  # NEW — at most 1 hedge per 1000 ticks
                "max_hedge_size": 30,
                "passive_skew_per_delta": 0.20,
                "passive_base_size": 30,        # match R2-ish size
            },
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v31: same but every 5000 ticks (very rare hedges)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v31_dh_lowfreq_5000"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            position_limit=200,
            **{
                **_R3_VELVET_DH_BASE,
                "hedge_taker_edge": 200,
                "min_ticks_between_hedges": 5000,
                "max_hedge_size": 50,
                "passive_skew_per_delta": 0.15,
                "passive_base_size": 30,
            },
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v28_iv_momentum: v24 base + iv_momentum_mm on VEV_5300/5400 (replaces gamma+passive).
# Tests: ρ_1=+0.14 IV residual momentum → BUY rich + SELL cheap (follow direction).
_R3_IV_MOMENTUM_BASE = dict(
    strategy="iv_momentum_mm",
    underlying_symbol="VELVETFRUIT_EXTRACT",
    strike_prefix="VEV_",
    smile_strikes=[4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500],
    prior_vol=0.0125,
    sigma_floor=0.005,
    sigma_cap=0.10,
    signal_threshold=0.0015,    # 15bp residual to enter
    delta_threshold=0.0003,     # 3bp delta_resid permissive (allow flat momentum)
    ewma_fast_alpha=0.10,
    ewma_slow_alpha=0.02,
    maker_size=20,
    exit_size=15,
    max_long=120,
    max_short=80,
    enable_takers=True,
    take_size=10,
    take_threshold_mult=1.5,
    tte_days_initial=5.0,
    timestamp_units_per_day=1000000,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v28_iv_momentum"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,   # R2 anchor
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        # gamma cluster z-gated on 4500-5200 (kept)
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        # IV momentum on VEV_5300/5400 (replaces gamma/passive)
        "VEV_5300": _override(ROUND_3["VEV_5300"], position_limit=300, strike=5300, **_R3_IV_MOMENTUM_BASE),
        "VEV_5400": _override(ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_IV_MOMENTUM_BASE),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v29_iv_momentum_aggro: lower threshold + bigger sizes, all 5 ATM strikes
MEMBER_OVERRIDES["r3_velvet_options_max3d_v29_iv_momentum_aggro"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        # IV momentum on entire ATM cluster 5000-5400 (REPLACES gamma)
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **{
                    **_R3_IV_MOMENTUM_BASE,
                    "signal_threshold": 0.001,   # 10bp - more aggressive
                    "max_long": 150, "max_short": 100,
                    "maker_size": 25,
                    "take_size": 15,
                },
            )
            for strike in [5000, 5100, 5200, 5300, 5400]
        },
        "VEV_4500": _override(
            ROUND_3["VEV_4500"], position_limit=300, strike=4500,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v24_r2velvet_zskip: v12 (R2 anchor MM on VELVET) + v20's z-skip on gamma cluster
# Goal: keep VELVET +27k drift gain + reduce DD via z-gated gamma entries
# v26: v24 architecture but VELVET = mr_taker_overlay (z-score taker on |z|>2)
# Tests if explicit mean-reversion taker (validated by ρ_1 = -0.16) beats R2 MM
MEMBER_OVERRIDES["r3_velvet_options_max3d_v26_velvet_mr_taker"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="velvet_mr_taker_overlay",
            position_limit=200,
            zscore_window=500,
            zscore_taker_threshold=2.0,
            taker_size=8,
            taker_cooldown_ticks=200,
            maker_size_base_pct=0.30,
            pct_kept_for_takers=0.15,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v27: v24 + VELVET MR taker layered ON TOP of R2 anchor MM (need a different design)
# For now, simpler test: v24 baseline + tighter zscore_taker_threshold to test
# if combination of R2 + extra taker activity adds anything. SKIP for now (would
# need running 2 strategies on same product, not supported).


MEMBER_OVERRIDES["r3_velvet_options_max3d_v24_r2velvet_zskip"] = {
    3: {
        "HYDROGEL_PACK": None,
        # R2 anchor MM on VELVET (proven Tibo strat — +27k historical)
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        # gamma_scalp_zgated on 4500-5300 with skip when z > 0.5 (v20's tuning)
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# v25_r2velvet_zskip_loose: same but z>1.0 (less aggressive gate, keep more PnL)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v25_r2velvet_zskip_loose"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_params(target_qty=300, z_skip_threshold=1.0),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


def _velvet_r2_exhaustion_params(
    *,
    z_threshold: float,
    displacement_threshold: float,
    taker_size: int,
    cooldown_ts: int,
    cascade_threshold: float,
) -> Dict[str, Any]:
    return {
        **_R3_VELVETFRUIT_PARAMS,
        "overlay_z_threshold": z_threshold,
        "overlay_displacement_threshold": displacement_threshold,
        "overlay_taker_size": taker_size,
        "overlay_cooldown_ts": cooldown_ts,
        "overlay_cascade_threshold": cascade_threshold,
        "overlay_zscore_window": 500,
        "overlay_lookback_ts": 10000,
        "overlay_short_lookback_ts": 1000,
    }


def _v24_with_velvet(product_config: ProductConfig) -> Dict[int, Dict[str, ProductConfig | None]]:
    return {
        3: {
            "HYDROGEL_PACK": None,
            "VELVETFRUIT_EXTRACT": product_config,
            "VEV_4000": _override(
                ROUND_3["VEV_4000"], position_limit=300, strike=4000,
                **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
            ),
            **{
                f"VEV_{strike}": _override(
                    ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                    **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
                )
                for strike in [4500, 5000, 5100, 5200, 5300]
            },
            "VEV_5400": _override(
                ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
            ),
            **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
        },
    }


MEMBER_OVERRIDES["r3_velvet_options_max3d_v28_r2exh_mid"] = _v24_with_velvet(
    _override(
        ROUND_3["VELVETFRUIT_EXTRACT"],
        strategy="velvet_r2_exhaustion_mm",
        position_limit=200,
        **_velvet_r2_exhaustion_params(
            z_threshold=2.0,
            displacement_threshold=30.0,
            taker_size=6,
            cooldown_ts=1000,
            cascade_threshold=8.0,
        ),
    )
)


MEMBER_OVERRIDES["r3_velvet_options_max3d_v29_r2exh_conservative"] = _v24_with_velvet(
    _override(
        ROUND_3["VELVETFRUIT_EXTRACT"],
        strategy="velvet_r2_exhaustion_mm",
        position_limit=200,
        **_velvet_r2_exhaustion_params(
            z_threshold=2.5,
            displacement_threshold=40.0,
            taker_size=5,
            cooldown_ts=2000,
            cascade_threshold=10.0,
        ),
    )
)


MEMBER_OVERRIDES["r3_velvet_options_max3d_v30_r2exh_aggressive"] = _v24_with_velvet(
    _override(
        ROUND_3["VELVETFRUIT_EXTRACT"],
        strategy="velvet_r2_exhaustion_mm",
        position_limit=200,
        **_velvet_r2_exhaustion_params(
            z_threshold=1.5,
            displacement_threshold=22.0,
            taker_size=10,
            cooldown_ts=500,
            cascade_threshold=6.0,
        ),
    )
)


MEMBER_OVERRIDES["r3_velvet_options_max3d_v23_vega_pair"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        # gamma cluster on 4500 + 5000 + 5200 (skip 5100/5300 — used by pair below)
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_scalp_params(target_qty=300, entry_size=30, passive_bid_size=24),
            )
            for strike in [4500, 5000, 5200]
        },
        # Vega-neutral pair: K=5100 partners with K=5300
        "VEV_5100": _override(
            ROUND_3["VEV_5100"], position_limit=300, strike=5100,
            **{**_R3_VEGA_PAIR_BASE, "partner_strike": 5300},
        ),
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **{**_R3_VEGA_PAIR_BASE, "partner_strike": 5100},
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# Dynamic skew detector base params
_R3_SKEW_DYNAMIC_BASE = dict(
    strategy="option_skew_dynamic_mm",
    underlying_symbol="VELVETFRUIT_EXTRACT",
    strike_prefix="VEV_",
    smile_strikes=[4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500],
    prior_vol=0.0125,
    sigma_floor=0.005,
    sigma_cap=0.10,
    min_quote_price=1.0,
    signal_threshold=0.001,    # 10 bps IV residual
    delta_threshold=0.0005,    # 5 bps change
    ewma_slow_alpha=0.02,      # half-life ~35
    ewma_fast_alpha=0.10,      # half-life ~7
    maker_size=14,
    neutral_size=6,
    exit_size=10,
    take_size=8,
    max_long=120,
    max_short=80,
    allow_new_shorts=True,
    enable_takers=False,
    tte_days_initial=5.0,
    timestamp_units_per_day=1000000,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)


# v15_skew_dynamic_auto: replace VEV_5300/5400 with dynamic skew detector in
# AUTO mode (informed → follow, OA → fade based on residual change). Compare
# vs v11 (no-smile passive on those strikes).
MEMBER_OVERRIDES["r3_velvet_options_max3d_v15_skew_dyn_auto"] = {
    3: {
        **_v11_options_only(),
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        # Override 5300 / 5400 to dynamic skew (was gamma / passive in v11)
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **{**_R3_SKEW_DYNAMIC_BASE, "mode": "auto"},
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400,
            **{**_R3_SKEW_DYNAMIC_BASE, "mode": "auto"},
        ),
    },
}


# v16: same but FOLLOW mode only (treat all deformation as informed)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v16_skew_dyn_follow"] = {
    3: {
        **_v11_options_only(),
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **{**_R3_SKEW_DYNAMIC_BASE, "mode": "follow"},
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400,
            **{**_R3_SKEW_DYNAMIC_BASE, "mode": "follow"},
        ),
    },
}


# v17: same but FADE mode only (treat all deformation as OA → mean-revert)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v17_skew_dyn_fade"] = {
    3: {
        **_v11_options_only(),
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **{**_R3_SKEW_DYNAMIC_BASE, "mode": "fade"},
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400,
            **{**_R3_SKEW_DYNAMIC_BASE, "mode": "fade"},
        ),
    },
}


# v14: aggressive hedge — full hedger with default-ish params on top of v11
# (sanity check: did the previous -21k drag persist on the v11 stack?)
MEMBER_OVERRIDES["r3_velvet_options_max3d_v14_dh_default"] = {
    3: {
        **_v11_options_only(),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            position_limit=40,
            **{
                **_R3_VELVET_DH_BASE,
                "hedge_taker_edge": 60,
                "max_hedge_size": 20,
                "passive_skew_per_delta": 0.30,
                "passive_base_size": 20,
            },
        ),
    },
}


# r3_velvet_options_max3d_v10_fullgamma — every active strike on gamma_scalp
# at target=300 (4500/5000/5100/5200/5300/5400). Stress test: does the strategy
# work for non-ATM strikes too?
# r3_velvet_options_max3d_v12_r2velvet -- same option stack as v11, but restores
# the round-2/v4 anchor MM on VELVET itself. This is explicitly max-backtest:
# v4 anchor made +27.5k on historical VELVET but was live-fragile.
MEMBER_OVERRIDES["r3_velvet_options_max3d_v12_r2velvet"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _R3_VELVETFRUIT_V4_F5,
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_scalp_params(target_qty=300, entry_size=30, passive_bid_size=24),
            )
            for strike in [4500, 5000, 5100, 5200, 5300]
        },
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_velvet_options_max3d_v10_fullgamma"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_scalp_params(target_qty=300, entry_size=30, passive_bid_size=24),
            )
            for strike in [4500, 5000, 5100, 5200, 5300, 5400]
        },
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# r3_velvet_options_max3d_v6_pushtarget — push target_qty even further (150)
# on the gamma cluster to test if 5000-5200 are still capacity-capped.
MEMBER_OVERRIDES["r3_velvet_options_max3d_v6_pushtarget"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        "VEV_4500": _override(
            ROUND_3["VEV_4500"], position_limit=300, strike=4500,
            **{
                **_R3_VELVET_OPT_OPTION_PARAMS_V3,
                "enable_takers": True, "take_edge": 2.0, "take_size": 20, "maker_size": 28,
            },
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_scalp_params(target_qty=150, entry_size=15, passive_bid_size=12),
            )
            for strike in [5000, 5100, 5200]
        },
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300, **_R3_VELVET_OPT_HIGH_K,
        ),
        "VEV_5400": _override(
            ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_VELVET_OPT_HIGH_K,
        ),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# r3_velvet_options_max3d_v4 — combines v2 (gamma everywhere + bigger target)
# with v3 (skew tilt on 5300). Goal: stack independent alpha sources.
MEMBER_OVERRIDES["r3_velvet_options_max3d_v4"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(ROUND_3["VELVETFRUIT_EXTRACT"], **_R3_VELVET_SMALL_MM),
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **{**_R3_VELVET_OPT_OPTION_PARAMS, "maker_size": 40},
        ),
        "VEV_4500": _override(
            ROUND_3["VEV_4500"], position_limit=300, strike=4500,
            **{
                **_R3_VELVET_OPT_OPTION_PARAMS_V3,
                "enable_takers": True, "take_edge": 2.0, "take_size": 20, "maker_size": 28,
            },
        ),
        # gamma cluster bigger target
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_scalp_params(target_qty=100, entry_size=10, passive_bid_size=8),
            )
            for strike in [5000, 5100, 5200]
        },
        # skew tilt on 5300/5400
        "VEV_5300": _override(ROUND_3["VEV_5300"], position_limit=300, strike=5300, **_R3_SKEW_TILT_BASE),
        "VEV_5400": _override(ROUND_3["VEV_5400"], position_limit=300, strike=5400, **_R3_SKEW_TILT_BASE),
        # gamma on 5500
        "VEV_5500": _override(
            ROUND_3["VEV_5500"], position_limit=300, strike=5500,
            **_gamma_scalp_params(target_qty=40, entry_size=5, passive_bid_size=4, min_q=1.0),
        ),
        **{f"VEV_{k}": None for k in [6000, 6500]},
    },
}


_R3_BS_GUARDED_TAKER_PARAMS = {
    **_R3_VELVET_OPT_OPTION_PARAMS,
    "penny_improve_around_mkt": False,
    "enable_takers": True,
    "maker_edge": 4,
    "maker_size": 12,
    "take_edge": 10.0,
    "take_size": 8,
    "inv_bias_per_unit": 0.04,
}

MEMBER_OVERRIDES["r3_velvet_options_bs_guarded_taker"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_VELVET_SMALL_MM,
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                position_limit=300,
                strike=strike,
                **(
                    _R3_BS_GUARDED_TAKER_PARAMS
                    if strike != 4000
                    else {**_R3_BS_GUARDED_TAKER_PARAMS, "maker_size": 24}
                ),
            )
            for strike in [4000, 4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_hydrogel_combo_mm"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_combo_mm",
            position_limit=200,
            # Signal 1: dual EMA (Theo's params)
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,                # scale factor for trend normalization
            # Signal 2: cross-frequency window (last 200 ticks ~ 20s)
            cross_window=200,
            min_samples=100,                # warmup
            # Signal 3: daily-phase knots (based on -37 ticks avg drift in first 1000 ticks)
            daily_phase_decay_ts=300_000,   # bias decays from -1 to -0.5 by ts 300k
            daily_phase_neutral_ts=500_000, # neutral at ts 500k
            daily_phase_bullish_ts=700_000, # peak bullish bias at ts 700k
            daily_phase_bullish_val=0.5,    # max late-session bullish strength
            # Aggregate weights (sum to 1.0)
            w_trend=0.5,
            w_cross=0.3,
            w_daily=0.2,
            regime_threshold=0.30,          # |score| > 0.30 → trend regime
            # Ladder geometry
            num_levels_flat=3,              # 3 levels each side when flat
            num_levels_follow=4,            # 4 levels on trend side (more volume)
            num_levels_against=1,           # 1 level counter-trend (tiny)
            level_step=1,
            min_spread_for_ladder=4,
            # Sizes per side (split across levels by pyramid)
            total_size_flat=30,
            total_size_follow=40,
            total_size_against=5,
            fallback_size=8,
            # Inventory + cap
            inventory_reduce_per_unit=0.50,
            inventory_unwind_per_unit=0.30,
            unwind_boost_max=30,
            hard_pos_cap=30,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# R3 HYDRO/VELVET SPREAD SKEW
# Uses the dashboard-style spread HYDRO_norm - VELVET_norm as a toxicity and
# one-sided quoting overlay.  This is intentionally a MM skew, not an aggressive
# pair-trade: HYDRO keeps the Theo trend guard, VELVET/VEV keep the proven Theo
# stack in the default variant.
_R3_HV_SPREAD_HYDRO_PARAMS = dict(
    strategy="hydro_velvet_spread_skew_mm",
    position_limit=200,
    ema_alpha=0.008,
    fast_ema_alpha=0.03,
    quote_threshold=6.0,
    trend_guard=6.0,
    trend_follow_threshold=6.0,
    trend_extreme_block=10.0,
    enable_trend_follow=True,
    maker_size=24,
    min_maker_size=3,
    counter_quote_size=0,
    conflict_quote_size=0,
    max_signal_size_boost=12,
    signal_boost_per_unit=8,
    tighten_ticks=1,
    spread_window=500,
    spread_min_samples=150,
    spread_skew_z=1.5,
    spread_hard_z=2.0,
    spread_extreme_z=2.7,
    inventory_reduce_per_unit=0.40,
    inventory_unwind_per_unit=0.30,
    max_unwind_boost=20,
    hard_pos_cap=20,
    wrong_side_pos_gate=8,
    wrong_side_unwind_boost=12,
    enable_wrong_side_taker=False,
    wrong_side_take_confidence=1.0,
    wrong_side_take_pos_gate=12,
    wrong_side_take_size=1,
    wrong_side_take_cooldown_ts=2000,
    session_drift_bias=0,
    quote_trace_enabled=True,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)


_R3_HV_SPREAD_VELVET_PAIR_PARAMS = dict(
    strategy="hydro_velvet_spread_skew_mm",
    position_limit=200,
    ema_alpha=0.008,
    fast_ema_alpha=0.03,
    quote_threshold=4.0,
    trend_guard=4.0,
    trend_follow_threshold=5.0,
    trend_extreme_block=8.0,
    enable_trend_follow=False,
    maker_size=8,
    min_maker_size=2,
    counter_quote_size=0,
    conflict_quote_size=0,
    max_signal_size_boost=6,
    signal_boost_per_unit=5,
    tighten_ticks=1,
    spread_window=500,
    spread_min_samples=150,
    spread_skew_z=1.5,
    spread_hard_z=2.0,
    spread_extreme_z=2.7,
    inventory_reduce_per_unit=0.45,
    inventory_unwind_per_unit=0.35,
    max_unwind_boost=12,
    hard_pos_cap=20,
    wrong_side_pos_gate=8,
    wrong_side_unwind_boost=8,
    enable_wrong_side_taker=False,
    quote_trace_enabled=True,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)


MEMBER_OVERRIDES["r3_hydro_velvet_spread_skew"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            **_R3_HV_SPREAD_HYDRO_PARAMS,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                strategy="option_mm_bs",
                position_limit=300,
                strike=strike,
                **_THEO_VEV_OPTION_PARAMS,
            )
            for strike in [4000, 4500, 5000, 5100, 5200, 5300]
        },
        **{f"VEV_{k}": None for k in [5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_hydro_velvet_pair_skew"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            **_R3_HV_SPREAD_HYDRO_PARAMS,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_HV_SPREAD_VELVET_PAIR_PARAMS,
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"],
                strategy="option_mm_bs",
                position_limit=300,
                strike=strike,
                **_THEO_VEV_OPTION_PARAMS,
            )
            for strike in [4000, 4500, 5000, 5100, 5200, 5300]
        },
        **{f"VEV_{k}": None for k in [5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_hydrogel_oracle_inspired"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_oracle_inspired",
            position_limit=200,
            window=500,
            trend_lookback=100,
            buy_z_threshold=-2.5,
            buy_trend_threshold=-40.0,
            sell_z_threshold=0.5,
            sell_trend_threshold=20.0,
            taker_size=10,
            max_position=100,
            unwind_z_threshold=0.3,
            unwind_chunk_size=10,
            passive_l1_size=0,
            enable_passive_mm=False,
            min_samples=200,
            cooldown_ticks=1000,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_hydrogel_exhaustion"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_exhaustion_taker",
            position_limit=200,
            fast_lookback_ts=10000,
            slow_lookback_ts=20000,
            entry_fast_ticks=999.0,
            entry_slow_ticks=60.0,
            max_position=60,
            taker_size=15,
            exit_size=15,
            cooldown_ts=1000,
            hold_ts=30000,
            allow_l2=False,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_hydrogel_mean_rev"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="hydrogel_mean_rev_taker",
            position_limit=200,
            window=500,
            entry_z=99.0,      # effectively disable taker entry
            exit_z=0.5,
            taker_size_base=0,
            taker_size_per_z=0,
            max_taker_position=0,
            z_passive_skew_gain=3.0,   # z-skew on passive sizes
            exit_chunk_size=30,
            passive_l1_size=30,
            inventory_aversion=0.5,
            enable_passive_mm=True,
            min_samples=100,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_vol_harvest_champion"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="r3_live_defensive_mm",
            position_limit=200,
            **_R3_LIVE_DEFENSIVE_PARAMS,
        ),
        # VEV options: vol_harvest strategy (orphan velvet_delta_hedger params dropped — bad merge artifact)
        **{
            f"VEV_{k}": ProductConfig(
                symbol=f"VEV_{k}",
                strategy="vol_harvest",
                position_limit=300,
                params=dict(
                    strike=k,
                    tte_days_initial=5.0,
                    ticks_per_day=10000,
                    timestamp_units_per_day=1000000,
                    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
                    realized_vol_prior=0.0215,
                    entry_edge=1.0,
                    exit_edge=2.0,
                    target_position=60,
                    entry_size=10,
                    exit_size=20,
                    passive_bid_size=5,
                    post_passive=True,
                    min_quote_price=2.0,
                    underlying_symbol="VELVETFRUIT_EXTRACT",
                    log_flush_ts=1000,
                    ts_increment=100,
                    last_ts_value=999900,
                ),
            )
            for k in _R3_VOL_HARVEST_STRIKES
        },
    },
}


# Guarded-anchor candidate:
# HYDROGEL stays on the live-stable book-following MM. VELVET keeps the old
# anchor alpha only when short-term flow is reverting toward 5250; otherwise it
# falls back to passive book-following and blocks anchor takers.
_R3_GUARDED_VELVET_PARAMS = {
    **_V4_F5_PARAMS,
    "anchor_price": 5250.0,
    "anchor_alpha": 0.02,
    "anchor_drift_bound": 2.0,
    "full_capacity_on_empty": True,
    "guard_near_band": 0.0,
    "guard_trend_alpha": 0.3,
    "guard_min_dist": 0.0,
    "guard_max_dist": 80.0,
    "guard_reversion_threshold": 0.0,
    "guard_inventory_dist": 40.0,
}

# Guarded-anchor candidate:
# HYDROGEL stays on the live-stable book-following MM. VELVET keeps the old
# anchor alpha only when short-term flow is reverting toward 5250; otherwise it
# falls back to passive book-following and blocks anchor takers.
_R3_GUARDED_VELVET_PARAMS = {
    **_V4_F5_PARAMS,
    "anchor_price": 5250.0,
    "anchor_alpha": 0.02,
    "anchor_drift_bound": 2.0,
    "full_capacity_on_empty": True,
    "guard_near_band": 0.0,
    "guard_trend_alpha": 0.3,
    "guard_min_dist": 0.0,
    "guard_max_dist": 80.0,
    "guard_reversion_threshold": 0.0,
    "guard_inventory_dist": 40.0,
}

# Live-only alpha probes. These intentionally use event/flow/book-state rules,
# not day/timestamp fingerprints. They are meant for IMC live discovery runs.
_R3_LIVE_PROBE_VELVET_BASE = {
    **_R3_VELVETFRUIT_PARAMS,
    "maker_size_base_pct": 0.04,
    "pct_kept_for_takers": 0.8,
    "take_edge": 1_000_000.0,
    "take_edge_lo": 1_000_000.0,
    "take_edge_hi": 1_000_000.0,
    "taker_buy_threshold": -1_000_000,
    "taker_sell_threshold": 1_000_000,
    "full_capacity_on_empty": False,
    "quote_trace_enabled": True,
    "log_flush_ts": 1000,
    "ts_increment": 100,
    "last_ts_value": 999900,
}


def _r3_guarded_velvet_underlying(**extra) -> ProductConfig:
    return _override(
        ROUND_3["VELVETFRUIT_EXTRACT"],
        strategy="r3_guarded_anchor_mm",
        position_limit=200,
        **{**_R3_GUARDED_VELVET_PARAMS, **extra},
    )


def _r4_v24_gamma_option(strike: int) -> ProductConfig:
    return _override(
        ROUND_4[f"VEV_{strike}"],
        strategy="r3_gamma_scalp_zgated",
        position_limit=300,
        strike=strike,
        tte_days_initial=4.0,
        historical_tte_by_day={1: 4.0, 2: 3.0, 3: 2.0},
        timestamp_units_per_day=1000000,
        implied_vol_prior=0.0125,
        prior_vol=0.0125,
        sigma_floor=0.005,
        sigma_cap=0.10,
        min_quote_price=2.0,
        edge_ticks=0.0,
        target_qty=300,
        entry_size=30,
        passive_bid_size=24,
        unwind_tte_threshold=1.5,
        zscore_window=500,
        zscore_skip_threshold=0.5,
        zscore_boost_threshold=1.0,
        skip_when_expensive=True,
        boost_when_cheap=False,
        entry_size_boost=1.5,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        log_flush_ts=1000,
        ts_increment=100,
        last_ts_value=999900,
    )


def _r4_v24_gamma_option_zskip(strike: int, zscore_skip_threshold: float) -> ProductConfig:
    return _override(
        _r4_v24_gamma_option(strike),
        zscore_skip_threshold=zscore_skip_threshold,
    )


def _r4_guarded_velvet_underlying(**extra) -> ProductConfig:
    return _override(
        ROUND_4["VELVETFRUIT_EXTRACT"],
        strategy="r3_guarded_anchor_mm",
        position_limit=200,
        **{**_R3_GUARDED_VELVET_PARAMS, **extra},
    )


_R4_HYDRO_PORT_V9 = _override(
    ROUND_4["HYDROGEL_PACK"],
    strategy="r3_hydro_reversion_mm",
    position_limit=200,
    ema_alpha=0.006,
    fast_ema_alpha=0.025,
    trend_guard=8.0,
    signal_pos_gate=12,
    tighten_ticks=1,
    maker_size=22,
    min_maker_size=3,
    quote_threshold=6.0,
    max_signal_size_boost=12,
    inventory_reduce_per_unit=0.40,
    inventory_unwind_per_unit=0.20,
    max_unwind_boost=20,
    take_threshold=13.0,
    take_cooldown_ts=2000,
    take_size=2,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)


_R4_HYDRO_COUNTERPARTY_V1 = _override(
    _R4_HYDRO_PORT_V9,
    mark_signal_enabled=True,
    mark_signal_alpha=0.35,
    mark_signal_decay=0.70,
    mark_signal_clip=6.0,
    mark_qty_norm=8.0,
    mark_buy_weights={
        "Mark 14": 1.0,
        "Mark 38": -1.0,
    },
    mark_sell_weights={
        "Mark 14": -1.0,
        "Mark 38": 0.5,
    },
    mark_fair_shift_per_unit=0.8,
    mark_max_fair_shift=4.0,
    mark_size_skew=0.45,
    mark_size_clip=2.5,
)


_R4_VELVET_PORT_V9 = _r4_guarded_velvet_underlying(
    guard_reversion_threshold=7.5,
    guard_trend_alpha=0.45,
    take_edge_lo=0.5,
    take_edge_hi=1.2,
    maker_size_base_pct=0.31,
    pct_kept_for_takers=0.003,
    toxic_threshold=0.65,
    toxic_window=8,
    toxic_size_frac=0.6,
    inventory_aversion_gamma=0.0008,
    passive_unwind_skew_ticks=1,
    passive_unwind_trigger=0.38,
)


_R4_VELVET_COUNTERPARTY_V1 = _override(
    _R4_VELVET_PORT_V9,
    mark_signal_enabled=True,
    mark_signal_alpha=0.35,
    mark_signal_decay=0.72,
    mark_signal_clip=6.0,
    mark_qty_norm=10.0,
    mark_buy_weights={
        "Mark 67": 1.2,
        "Mark 55": 0.4,
        "Mark 22": 0.2,
        "Mark 14": -0.6,
        "Mark 01": -0.1,
    },
    mark_sell_weights={
        "Mark 55": -0.4,
        "Mark 01": -0.4,
        "Mark 14": 0.7,
        "Mark 22": 1.0,
        "Mark 49": 1.0,
    },
    mark_anchor_shift_per_unit=1.0,
    mark_anchor_shift_max=6.0,
    mark_inventory_target_per_unit=6.0,
    mark_inventory_target_max=30,
)


MEMBER_OVERRIDES["r4_v0_port_v9"] = {
    4: {
        "HYDROGEL_PACK": _R4_HYDRO_PORT_V9,
        "VELVETFRUIT_EXTRACT": _R4_VELVET_PORT_V9,
        "VEV_4000": _r4_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r4_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r4_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r4_v24_gamma_option(5100),
        "VEV_5200": _r4_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r4_v24_gamma_option_zskip(5300, 2.5),
        "VEV_5400": _r4_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": _r4_v24_gamma_option(5500),
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r4_v1_hydromarks"] = {
    4: {
        **MEMBER_OVERRIDES["r4_v0_port_v9"][4],
        "HYDROGEL_PACK": _R4_HYDRO_COUNTERPARTY_V1,
    },
}


MEMBER_OVERRIDES["r4_v1_velvetmarks"] = {
    4: {
        **MEMBER_OVERRIDES["r4_v0_port_v9"][4],
        "VELVETFRUIT_EXTRACT": _R4_VELVET_COUNTERPARTY_V1,
    },
}


MEMBER_OVERRIDES["r4_velvet_options_v1_counterparty"] = {
    4: {
        "HYDROGEL_PACK": _R4_HYDRO_COUNTERPARTY_V1,
        "VELVETFRUIT_EXTRACT": _R4_VELVET_COUNTERPARTY_V1,
        "VEV_4000": _r4_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r4_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r4_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r4_v24_gamma_option(5100),
        "VEV_5200": _override(
            _r4_v24_gamma_option_zskip(5200, 2.0),
            mark_signal_enabled=True,
            mark_signal_alpha=0.45,
            mark_signal_decay=0.75,
            mark_signal_clip=4.0,
            mark_qty_norm=4.0,
            mark_buy_weights={"Mark 01": 1.0, "Mark 14": 0.35},
            mark_sell_weights={"Mark 22": -0.35},
            mark_fair_shift_per_unit=0.45,
            mark_max_fair_shift=1.2,
            mark_entry_size_boost=0.6,
            mark_target_bonus=40,
            mark_skip_relax=0.6,
            mark_unwind_threshold=1.0,
        ),
        "VEV_5300": _override(
            _r4_v24_gamma_option_zskip(5300, 2.5),
            mark_signal_enabled=True,
            mark_signal_alpha=0.45,
            mark_signal_decay=0.75,
            mark_signal_clip=4.0,
            mark_qty_norm=4.0,
            mark_buy_weights={"Mark 14": 0.45, "Mark 01": 0.15},
            mark_sell_weights={"Mark 22": -0.20},
            mark_fair_shift_per_unit=0.35,
            mark_max_fair_shift=1.0,
            mark_entry_size_boost=0.5,
            mark_target_bonus=30,
            mark_skip_relax=0.4,
            mark_unwind_threshold=1.0,
        ),
        "VEV_5400": _r4_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": _r4_v24_gamma_option(5500),
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r4_velvet_options_v1"] = {
    4: {
        **MEMBER_OVERRIDES["r4_v0_port_v9"][4],
        "VEV_5200": _r4_v24_gamma_option_zskip(5200, 1.5),
        "VEV_5300": _r4_v24_gamma_option_zskip(5300, 3.0),
        "VEV_5400": _r4_v24_gamma_option_zskip(5400, 2.0),
    },
}


def _r4_gamma_option_slim(strike: int, zscore_skip_threshold: float) -> ProductConfig:
    return _override(
        MEMBER_OVERRIDES["r4_velvet_options_v1"][4][f"VEV_{strike}"],
        strategy="r4_gamma_scalp_zgated_slim",
        zscore_skip_threshold=zscore_skip_threshold,
    )


MEMBER_OVERRIDES["r4_velvet_options_v1_under100k"] = {
    4: {
        **MEMBER_OVERRIDES["r4_velvet_options_v1"][4],
        "HYDROGEL_PACK": _override(_R4_HYDRO_PORT_V9, strategy="r4_hydro_reversion_mm_slim"),
        "VEV_4000": _r4_gamma_option_slim(4000, 1.5),
        "VEV_4500": _r4_gamma_option_slim(4500, 2.0),
        "VEV_5000": _r4_gamma_option_slim(5000, 1.0),
        "VEV_5100": _r4_gamma_option_slim(5100, 0.5),
        "VEV_5200": _r4_gamma_option_slim(5200, 1.5),
        "VEV_5300": _r4_gamma_option_slim(5300, 3.0),
        "VEV_5400": _r4_gamma_option_slim(5400, 2.0),
        "VEV_5500": _r4_gamma_option_slim(5500, 0.5),
    },
}


MEMBER_OVERRIDES["r4_hydro_mark14_v1"] = {
    4: {
        "HYDROGEL_PACK": _override(
            ROUND_4["HYDROGEL_PACK"],
            strategy="r4_hydro_mark14_mm",
            position_limit=200,
            ema_alpha=0.02,
            fast_alpha=0.08,
            micro_alpha=0.35,
            improve_ticks=1,
            min_spread_to_improve=15,
            base_size=6,
            min_size=2,
            max_size=12,
            quote_edge=0.8,
            edge_boost=4,
            inventory_gamma=0.03,
            inventory_reduce_per_unit=0.08,
            inventory_unwind_per_unit=0.05,
            signal_alpha=0.45,
            signal_decay=0.82,
            signal_qty_norm=6.0,
            signal_clip=6.0,
            mark14_weight=0.0,
            mark38_weight=0.0,
            signal_fair_shift=0.0,
            signal_size_skew=0.0,
            trend_guard=4.5,
            trend_soft=True,
            trend_position_gate=20,
            relief_position_threshold=60,
            relief_size=2,
            relief_edge_gate=1.0,
            relief_signal_gate=1.0,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None,
        "VEV_4500": None,
        "VEV_5000": None,
        "VEV_5100": None,
        "VEV_5200": None,
        "VEV_5300": None,
        "VEV_5400": None,
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r4_hydro_only_v1_guarded_mark14"] = {
    4: {
        "HYDROGEL_PACK": _override(
            ROUND_4["HYDROGEL_PACK"],
            strategy="r3_guarded_anchor_mm",
            position_limit=200,
            anchor_price=10000.0,
            anchor_alpha=0.02,
            anchor_drift_bound=1.5,
            ar_gain=0.2,
            ar_shift_source="mid_smooth",
            full_capacity_on_empty=True,
            guard_inventory_dist=40.0,
            guard_max_dist=80.0,
            guard_min_dist=0.0,
            guard_near_band=0.0,
            guard_reversion_threshold=6.5,
            guard_trend_alpha=0.45,
            inventory_aversion_gamma=0.0020,
            last_ts_value=999900,
            log_flush_ts=1000,
            maker_size=30,
            maker_size_base_pct=0.16,
            passive_unwind_skew_ticks=1,
            passive_unwind_trigger=0.38,
            pct_kept_for_takers=0.005,
            quote_trace_enabled=False,
            take_edge_lo=0.55,
            take_edge_hi=1.10,
            tighten_ticks=1,
            toxic_size_frac=0.68,
            toxic_threshold=0.6,
            toxic_window=8,
            ts_increment=100,
            unwind_take_edge=3.0,
            mark_signal_enabled=True,
            mark_buy_weights={"Mark 14": 1.0},
            mark_sell_weights={"Mark 14": -1.0},
            mark_signal_alpha=0.45,
            mark_signal_decay=0.78,
            mark_qty_norm=10.0,
            mark_signal_clip=6.0,
            mark_anchor_shift_per_unit=1.0,
            mark_anchor_shift_max=5.0,
            mark_inventory_target_per_unit=0.0,
            mark_inventory_target_max=0,
        ),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None,
        "VEV_4500": None,
        "VEV_5000": None,
        "VEV_5100": None,
        "VEV_5200": None,
        "VEV_5300": None,
        "VEV_5400": None,
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r4_hydro_only_v2_guarded_mark14_skew"] = {
    4: {
        "HYDROGEL_PACK": _override(
            ROUND_4["HYDROGEL_PACK"],
            strategy="r4_hydro_guarded_mark_skew",
            position_limit=200,
            anchor_price=10000.0,
            anchor_alpha=0.02,
            anchor_drift_bound=1.5,
            ar_gain=0.2,
            ar_shift_source="mid_smooth",
            full_capacity_on_empty=True,
            guard_inventory_dist=40.0,
            guard_max_dist=80.0,
            guard_min_dist=0.0,
            guard_near_band=0.0,
            guard_reversion_threshold=6.5,
            guard_trend_alpha=0.45,
            inventory_aversion_gamma=0.0019,
            last_ts_value=999900,
            log_flush_ts=1000,
            maker_size=30,
            maker_size_base_pct=0.16,
            passive_unwind_skew_ticks=1,
            passive_unwind_trigger=0.38,
            pct_kept_for_takers=0.005,
            quote_trace_enabled=False,
            take_edge_lo=0.60,
            take_edge_hi=1.15,
            tighten_ticks=1,
            toxic_size_frac=0.68,
            toxic_threshold=0.6,
            toxic_window=8,
            ts_increment=100,
            unwind_take_edge=3.0,
            mark_signal_enabled=True,
            mark_buy_weights={"Mark 14": 1.0},
            mark_sell_weights={"Mark 14": -1.0},
            mark_signal_alpha=0.45,
            mark_signal_decay=0.78,
            mark_qty_norm=10.0,
            mark_signal_clip=6.0,
            mark_anchor_shift_per_unit=1.0,
            mark_anchor_shift_max=5.0,
            mark_inventory_target_per_unit=0.0,
            mark_inventory_target_max=0,
            mark_size_skew=0.10,
            mark_size_clip=6.0,
        ),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None,
        "VEV_4500": None,
        "VEV_5000": None,
        "VEV_5100": None,
        "VEV_5200": None,
        "VEV_5300": None,
        "VEV_5400": None,
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r4_hydro_mv_v6_invaware"] = {
    4: {
        "HYDROGEL_PACK": _override(
            ROUND_4["HYDROGEL_PACK"],
            strategy="r4_hydro_mv_v6_invaware",
            position_limit=200,
            anchor_alpha=0.02,
            anchor_drift_bound=1.5,
            anchor_price=10000,
            ar_gain=8.0,
            ar_smooth_half_life=5,
            ar_taker_edge=12.0,
            ar_taker_size_pct=0.3,
            dev_smooth_half_life=5,
            informed_trader_name="Mark 14",
            inventory_taker_edge_shift=4.0,
            last_ts_value=999900,
            log_flush_ts=1000,
            maker_size_base_pct=0.25,
            mid_smooth_half_life=20,
            passive_quoting=True,
            pct_kept_for_takers=0.2,
            trader_buy_weights={"Mark 14": 1.0, "Mark 38": -1.0},
            trader_fair_shift_per_unit=0.5,
            trader_qty_norm=10.0,
            trader_sell_weights={"Mark 14": -1.0, "Mark 38": 1.0},
            trader_signal_alpha=0.45,
            trader_signal_clip=6.0,
            trader_signal_decay=0.78,
            use_anchor_guard=False,
            use_ar_quote_bias=False,
            use_ar_taker=True,
            use_gap_exploit=False,
            use_inventory_bias=True,
            use_m14_gate=False,
        ),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None,
        "VEV_4500": None,
        "VEV_5000": None,
        "VEV_5100": None,
        "VEV_5200": None,
        "VEV_5300": None,
        "VEV_5400": None,
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r4_hydro_mv_v7_maker30_fair110"] = {
    4: {
        "HYDROGEL_PACK": _override(
            ROUND_4["HYDROGEL_PACK"],
            strategy="r4_hydro_mv_v6_invaware",
            position_limit=200,
            anchor_alpha=0.02,
            anchor_drift_bound=1.5,
            anchor_price=10000,
            ar_gain=8.0,
            ar_smooth_half_life=5,
            ar_taker_edge=12.0,
            ar_taker_size_pct=0.3,
            dev_smooth_half_life=5,
            informed_trader_name="Mark 14",
            inventory_taker_edge_shift=4.0,
            last_ts_value=999900,
            log_flush_ts=1000,
            maker_size_base_pct=0.30,
            mid_smooth_half_life=20,
            passive_quoting=True,
            pct_kept_for_takers=0.2,
            trader_buy_weights={"Mark 14": 1.0, "Mark 38": -1.0},
            trader_fair_shift_per_unit=1.10,
            trader_qty_norm=10.0,
            trader_sell_weights={"Mark 14": -1.0, "Mark 38": 1.0},
            trader_signal_alpha=0.45,
            trader_signal_clip=6.0,
            trader_signal_decay=0.78,
            use_anchor_guard=False,
            use_ar_quote_bias=False,
            use_ar_taker=True,
            use_gap_exploit=False,
            use_inventory_bias=True,
            use_m14_gate=False,
        ),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None,
        "VEV_4500": None,
        "VEV_5000": None,
        "VEV_5100": None,
        "VEV_5200": None,
        "VEV_5300": None,
        "VEV_5400": None,
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r4_hydro_mv_v7_mmsoft"] = {
    4: {
        "HYDROGEL_PACK": _override(
            ROUND_4["HYDROGEL_PACK"],
            strategy="r4_hydro_mv_v6_invaware",
            position_limit=200,
            anchor_alpha=0.02,
            anchor_drift_bound=1.5,
            anchor_price=10000,
            ar_gain=8.0,
            ar_smooth_half_life=5,
            ar_taker_edge=12.0,
            ar_taker_size_pct=0.3,
            dev_smooth_half_life=5,
            informed_trader_name="Mark 14",
            inventory_opposite_side_boost=1.0,
            inventory_opposite_side_cap_mult=2.0,
            inventory_same_side_power=1.4,
            inventory_taker_edge_shift=4.0,
            last_ts_value=999900,
            log_flush_ts=1000,
            maker_size_base_pct=0.30,
            mid_smooth_half_life=20,
            passive_quoting=True,
            pct_kept_for_takers=0.2,
            trader_buy_weights={"Mark 14": 1.0, "Mark 38": -1.0},
            trader_fair_shift_per_unit=1.10,
            trader_qty_norm=10.0,
            trader_sell_weights={"Mark 14": -1.0, "Mark 38": 1.0},
            trader_signal_alpha=0.45,
            trader_signal_clip=6.0,
            trader_signal_decay=0.93,
            use_anchor_guard=False,
            use_ar_quote_bias=False,
            use_ar_taker=True,
            use_gap_exploit=False,
            use_inventory_bias=True,
            use_m14_gate=False,
            working_position_limit=200,
        ),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None,
        "VEV_4500": None,
        "VEV_5000": None,
        "VEV_5100": None,
        "VEV_5200": None,
        "VEV_5300": None,
        "VEV_5400": None,
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r4_hydro_mv_v9_adaptive_fair"] = {
    4: {
        "HYDROGEL_PACK": _override(
            ROUND_4["HYDROGEL_PACK"],
            strategy="r4_hydro_mv_v9_adaptive_fair",
            position_limit=200,
            anchor_price=10000,
            ar_gain=7.0,
            ar_smooth_half_life=5,
            ar_taker_edge=12.0,
            ar_taker_size_pct=0.3,
            dev_smooth_half_life=5,
            informed_trader_name="Mark 14",
            adaptive_conf_min=0.45,
            adaptive_drift_alpha=0.004,
            adaptive_mean_rev=4.0,
            adaptive_trend=50.0,
            inventory_opposite_side_boost=1.0,
            inventory_opposite_side_cap_mult=2.0,
            inventory_same_side_power=1.5,
            inventory_taker_edge_shift=4.0,
            last_ts_value=999900,
            log_flush_ts=1000,
            maker_size_base_pct=0.30,
            mid_smooth_half_life=18,
            passive_quoting=True,
            pct_kept_for_takers=0.2,
            trader_buy_weights={"Mark 14": 1.0, "Mark 38": -1.0},
            trader_fair_shift_per_unit=1.10,
            trader_qty_norm=10.0,
            trader_sell_weights={"Mark 14": -1.0, "Mark 38": 1.0},
            trader_signal_alpha=0.45,
            trader_signal_clip=6.0,
            trader_signal_decay=0.93,
            use_anchor_guard=False,
            use_ar_quote_bias=False,
            use_ar_taker=True,
            use_gap_exploit=False,
            use_inventory_bias=True,
            use_m14_gate=False,
            working_position_limit=200,
        ),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None,
        "VEV_4500": None,
        "VEV_5000": None,
        "VEV_5100": None,
        "VEV_5200": None,
        "VEV_5300": None,
        "VEV_5400": None,
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r4_hydro_mv_v10_live_defensive"] = {
    4: {
        "HYDROGEL_PACK": _override(
            ROUND_4["HYDROGEL_PACK"],
            strategy="r4_hydro_mv_v10_live_defensive",
            position_limit=200,
            anchor_price=10000,
            ar_gain=7.0,
            ar_smooth_half_life=5,
            ar_taker_edge=12.0,
            ar_taker_size_pct=0.3,
            dev_smooth_half_life=5,
            informed_trader_name="Mark 14",
            adaptive_conf_min=0.45,
            adaptive_drift_alpha=0.004,
            adaptive_mean_rev=4.0,
            adaptive_trend=50.0,
            inventory_fair_activation_ratio=0.60,
            inventory_fair_pull_fraction=0.12,
            inventory_fair_ar_mom_cancel=2.0,
            inventory_long_taker_kill_ratio=0.96,
            inventory_opposite_side_boost=1.0,
            inventory_opposite_side_cap_mult=2.0,
            inventory_same_side_power=1.5,
            inventory_short_taker_kill_ratio=0.96,
            inventory_taker_edge_shift=4.0,
            inventory_taker_kill_dev_threshold=8.0,
            inventory_taker_kill_mom_threshold=0.3,
            last_ts_value=999900,
            log_flush_ts=1000,
            maker_size_base_pct=0.30,
            mid_smooth_half_life=18,
            passive_quoting=True,
            pct_kept_for_takers=0.2,
            trader_buy_weights={"Mark 14": 1.0, "Mark 38": -1.0},
            trader_fair_shift_per_unit=1.10,
            trader_qty_norm=10.0,
            trader_sell_weights={"Mark 14": -1.0, "Mark 38": 1.0},
            trader_signal_alpha=0.45,
            trader_signal_clip=6.0,
            trader_signal_decay=0.93,
            use_anchor_guard=False,
            use_ar_quote_bias=False,
            use_ar_taker=True,
            use_gap_exploit=False,
            use_inventory_bias=True,
            use_m14_gate=False,
            working_position_limit=200,
        ),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None,
        "VEV_4500": None,
        "VEV_5000": None,
        "VEV_5100": None,
        "VEV_5200": None,
        "VEV_5300": None,
        "VEV_5400": None,
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r4_hydro_mv_v9_mark14_tuned"] = {
    4: {
        "HYDROGEL_PACK": _override(
            ROUND_4["HYDROGEL_PACK"],
            strategy="r4_hydro_mv_v9_adaptive_fair",
            position_limit=200,
            anchor_price=10000,
            ar_gain=7.0,
            ar_smooth_half_life=5,
            ar_taker_edge=12.0,
            ar_taker_size_pct=0.3,
            dev_smooth_half_life=5,
            informed_trader_name="Mark 14",
            adaptive_conf_min=0.45,
            adaptive_drift_alpha=0.004,
            adaptive_mean_rev=4.0,
            adaptive_trend=50.0,
            inventory_opposite_side_boost=1.0,
            inventory_opposite_side_cap_mult=2.0,
            inventory_same_side_power=1.5,
            inventory_taker_edge_shift=4.0,
            last_ts_value=999900,
            log_flush_ts=1000,
            maker_size_base_pct=0.30,
            mid_smooth_half_life=18,
            passive_quoting=True,
            # KEY CHANGE 1: Mark 14 signal amplification.
            # When Mark 14 buys (Mark 38 sold = price dip), we shift fair
            # up by 12 × signal, making the AR taker fire much more
            # aggressively on mean-reversion dips. Grid search found shift=12
            # optimal (original v9 was 1.10, a 10× increase).
            trader_fair_shift_per_unit=12.0,
            # KEY CHANGE 2: Remove passive soft-stop to capture 100% of
            # Mark 38's bid+1/ask-1 crosses regardless of inventory level.
            # AR taker handles unwinding.
            pct_kept_for_takers=0.0,
            trader_buy_weights={"Mark 14": 1.0, "Mark 38": -1.0},
            trader_qty_norm=10.0,
            trader_sell_weights={"Mark 14": -1.0, "Mark 38": 1.0},
            trader_signal_alpha=0.45,
            trader_signal_clip=6.0,
            trader_signal_decay=0.93,
            use_anchor_guard=False,
            use_ar_quote_bias=False,
            use_ar_taker=True,
            use_gap_exploit=False,
            use_inventory_bias=True,
            use_m14_gate=False,
            working_position_limit=200,
        ),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None,
        "VEV_4500": None,
        "VEV_5000": None,
        "VEV_5100": None,
        "VEV_5200": None,
        "VEV_5300": None,
        "VEV_5400": None,
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r4_hydro_mv_v11_mark_oracle"] = {
    4: {
        "HYDROGEL_PACK": _override(
            ROUND_4["HYDROGEL_PACK"],
            strategy="r4_hydro_mv_v11_mark_oracle",
            position_limit=200,
            # Oracle anchor: very slow EWMA of mid — same adaptive confidence
            # as v9 but against this drifting reference instead of literal 10000.
            # Half-life in ticks.  20000 ticks ≈ 33 min → barely moves per day,
            # but adapts over weeks of live trading.
            # Grid search: oracle_hl=5000,10000,20000,50000 (50000 ≈ hardcoded).
            oracle_hl=20000.0,
            # AR model (same as v9)
            ar_gain=7.0,
            ar_smooth_half_life=5,
            ar_taker_edge=12.0,
            ar_taker_size_pct=0.3,
            dev_smooth_half_life=5,
            # Trader signal (Mark 14 / Mark 38 flow)
            informed_trader_name="Mark 14",
            trader_buy_weights={"Mark 14": 1.0, "Mark 38": -1.0},
            trader_fair_shift_per_unit=1.10,
            trader_qty_norm=10.0,
            trader_sell_weights={"Mark 14": -1.0, "Mark 38": 1.0},
            trader_signal_alpha=0.45,
            trader_signal_clip=6.0,
            trader_signal_decay=0.93,
            # Inventory management (same as v9)
            inventory_opposite_side_boost=1.0,
            inventory_opposite_side_cap_mult=2.0,
            inventory_same_side_power=1.5,
            inventory_taker_edge_shift=4.0,
            # Quoting / sizing (same as v9)
            last_ts_value=999900,
            log_flush_ts=1000,
            maker_size_base_pct=0.30,
            mid_smooth_half_life=18,
            passive_quoting=True,
            pct_kept_for_takers=0.2,
            use_anchor_guard=False,
            use_ar_quote_bias=False,
            use_ar_taker=True,
            use_gap_exploit=False,
            use_inventory_bias=True,
            use_m14_gate=False,
            working_position_limit=200,
        ),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None,
        "VEV_4500": None,
        "VEV_5000": None,
        "VEV_5100": None,
        "VEV_5200": None,
        "VEV_5300": None,
        "VEV_5400": None,
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r4_hydro_mv_v11_early_kill_fairsoft"] = {
    4: {
        "HYDROGEL_PACK": _override(
            ROUND_4["HYDROGEL_PACK"],
            strategy="r4_hydro_mv_v11_early_kill_fairsoft",
            position_limit=200,
            anchor_price=10000,
            ar_gain=7.0,
            ar_smooth_half_life=5,
            ar_taker_edge=12.0,
            ar_taker_size_pct=0.3,
            dev_smooth_half_life=5,
            informed_trader_name="Mark 14",
            adaptive_conf_min=0.50,
            adaptive_drift_alpha=0.005,
            adaptive_mean_rev=4.0,
            adaptive_trend=50.0,
            inventory_fair_activation_ratio=0.50,
            inventory_fair_pull_fraction=0.18,
            inventory_fair_ar_mom_cancel=3.0,
            inventory_long_taker_kill_ratio=0.90,
            inventory_opposite_side_boost=1.0,
            inventory_opposite_side_cap_mult=2.0,
            inventory_same_side_power=1.5,
            inventory_short_taker_kill_ratio=0.90,
            inventory_taker_edge_shift=4.0,
            inventory_taker_kill_dev_threshold=8.0,
            inventory_taker_kill_mom_threshold=0.10,
            last_ts_value=999900,
            log_flush_ts=1000,
            maker_size_base_pct=0.30,
            mid_smooth_half_life=18,
            passive_quoting=True,
            pct_kept_for_takers=0.2,
            trader_buy_weights={"Mark 14": 1.0, "Mark 38": -1.0},
            trader_fair_shift_per_unit=1.10,
            trader_qty_norm=10.0,
            trader_sell_weights={"Mark 14": -1.0, "Mark 38": 1.0},
            trader_signal_alpha=0.45,
            trader_signal_clip=6.0,
            trader_signal_decay=0.93,
            use_anchor_guard=False,
            use_ar_quote_bias=False,
            use_ar_taker=True,
            use_gap_exploit=False,
            use_inventory_bias=True,
            use_m14_gate=False,
            working_position_limit=200,
        ),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None,
        "VEV_4500": None,
        "VEV_5000": None,
        "VEV_5100": None,
        "VEV_5200": None,
        "VEV_5300": None,
        "VEV_5400": None,
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r4_hydro_mv_v12_vol_tail_kill"] = {
    4: {
        "HYDROGEL_PACK": _override(
            ROUND_4["HYDROGEL_PACK"],
            strategy="r4_hydro_mv_v12_vol_tail_kill",
            position_limit=200,
            anchor_price=10000,
            ar_gain=7.0,
            ar_smooth_half_life=5,
            ar_taker_edge=12.0,
            ar_taker_size_pct=0.3,
            dev_smooth_half_life=5,
            informed_trader_name="Mark 14",
            adaptive_conf_min=0.50,
            adaptive_drift_alpha=0.005,
            adaptive_mean_rev=4.0,
            adaptive_trend=50.0,
            inventory_fair_activation_ratio=0.50,
            inventory_fair_pull_fraction=0.18,
            inventory_fair_ar_mom_cancel=3.0,
            inventory_long_taker_kill_ratio=0.90,
            inventory_opposite_side_boost=1.0,
            inventory_opposite_side_cap_mult=2.0,
            inventory_same_side_power=1.5,
            inventory_short_taker_kill_ratio=0.90,
            inventory_taker_edge_shift=4.0,
            inventory_taker_kill_dev_threshold=8.0,
            inventory_taker_kill_mom_threshold=0.10,
            high_vol_sigma_start=2.44,
            high_vol_sigma_end=2.64,
            high_vol_inventory_fair_pull_add=0.08,
            high_vol_inventory_fair_mom_add=1.25,
            high_vol_short_taker_kill_ratio=0.85,
            high_vol_long_taker_kill_ratio=0.85,
            high_vol_taker_kill_dev_threshold=6.0,
            high_vol_taker_kill_mom_threshold=0.05,
            last_ts_value=999900,
            log_flush_ts=1000,
            maker_size_base_pct=0.30,
            mid_smooth_half_life=18,
            passive_quoting=True,
            pct_kept_for_takers=0.2,
            trader_buy_weights={"Mark 14": 1.0, "Mark 38": -1.0},
            trader_fair_shift_per_unit=1.10,
            trader_qty_norm=10.0,
            trader_sell_weights={"Mark 14": -1.0, "Mark 38": 1.0},
            trader_signal_alpha=0.45,
            trader_signal_clip=6.0,
            trader_signal_decay=0.93,
            use_anchor_guard=False,
            use_ar_quote_bias=False,
            use_ar_taker=True,
            use_gap_exploit=False,
            use_inventory_bias=True,
            use_m14_gate=False,
            working_position_limit=200,
        ),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None,
        "VEV_4500": None,
        "VEV_5000": None,
        "VEV_5100": None,
        "VEV_5200": None,
        "VEV_5300": None,
        "VEV_5400": None,
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r3_guarded_hybrid_v1"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
        ),
        "VELVETFRUIT_EXTRACT": _r3_guarded_velvet_underlying(),
        # Vouchers: use ROUND_3 default option_mm_bs (penny-improve, no takers).
    },
}


MEMBER_OVERRIDES["r3_velvet_options_v4_guardedblend"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDRO_ALPHA_V4,
        "VELVETFRUIT_EXTRACT": _r3_guarded_velvet_underlying(),
        "VEV_4000": _r3_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r3_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r3_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r3_v24_gamma_option_zskip(5300, 2.0),
        "VEV_5400": _r3_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r3_velvet_options_v5_guardedtuned"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDRO_ALPHA_V4,
        "VELVETFRUIT_EXTRACT": _r3_guarded_velvet_underlying(
            guard_reversion_threshold=7.5,
            guard_trend_alpha=0.45,
            take_edge_lo=0.6,
            take_edge_hi=1.2,
        ),
        "VEV_4000": _r3_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r3_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r3_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r3_v24_gamma_option_zskip(5300, 2.0),
        "VEV_5400": _r3_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": _r3_v24_gamma_option(5500),
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r3_velvet_options_v6_velvettuned"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDRO_ALPHA_V4,
        "VELVETFRUIT_EXTRACT": _r3_guarded_velvet_underlying(
            guard_reversion_threshold=7.5,
            guard_trend_alpha=0.45,
            take_edge_lo=0.6,
            take_edge_hi=1.2,
            maker_size_base_pct=0.4,
            pct_kept_for_takers=0.005,
            toxic_threshold=0.6,
            toxic_window=8,
            toxic_size_frac=0.68,
        ),
        "VEV_4000": _r3_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r3_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r3_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r3_v24_gamma_option_zskip(5300, 2.0),
        "VEV_5400": _r3_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": _r3_v24_gamma_option(5500),
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r3_velvet_options_v7_passiveunwind"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDRO_ALPHA_V4,
        "VELVETFRUIT_EXTRACT": _r3_guarded_velvet_underlying(
            guard_reversion_threshold=7.5,
            guard_trend_alpha=0.45,
            take_edge_lo=0.6,
            take_edge_hi=1.2,
            maker_size_base_pct=0.4,
            pct_kept_for_takers=0.005,
            toxic_threshold=0.6,
            toxic_window=8,
            toxic_size_frac=0.68,
            inventory_aversion_gamma=0.0010,
            passive_unwind_skew_ticks=1,
            passive_unwind_trigger=0.38,
        ),
        "VEV_4000": _r3_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r3_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r3_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r3_v24_gamma_option_zskip(5300, 2.0),
        "VEV_5400": _r3_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": _r3_v24_gamma_option(5500),
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r3_velvet_options_v8_lightermaker"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDRO_ALPHA_V4,
        "VELVETFRUIT_EXTRACT": _r3_guarded_velvet_underlying(
            guard_reversion_threshold=7.5,
            guard_trend_alpha=0.45,
            take_edge_lo=0.6,
            take_edge_hi=1.2,
            maker_size_base_pct=0.31,
            pct_kept_for_takers=0.005,
            toxic_threshold=0.6,
            toxic_window=8,
            toxic_size_frac=0.68,
            inventory_aversion_gamma=0.0010,
            passive_unwind_skew_ticks=1,
            passive_unwind_trigger=0.38,
        ),
        "VEV_4000": _r3_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r3_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r3_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r3_v24_gamma_option_zskip(5300, 2.0),
        "VEV_5400": _r3_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": _r3_v24_gamma_option(5500),
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r3_velvet_options_v9_globalretuned"] = {
    3: {
        "HYDROGEL_PACK": _override(
            _R3_HYDRO_ALPHA_V4,
            ema_alpha=0.006,
            fast_ema_alpha=0.025,
            maker_size=22,
            inventory_unwind_per_unit=0.20,
            take_threshold=13.0,
            take_size=2,
        ),
        "VELVETFRUIT_EXTRACT": _r3_guarded_velvet_underlying(
            guard_reversion_threshold=7.5,
            guard_trend_alpha=0.45,
            take_edge_lo=0.5,
            take_edge_hi=1.2,
            maker_size_base_pct=0.31,
            pct_kept_for_takers=0.003,
            toxic_threshold=0.65,
            toxic_window=8,
            toxic_size_frac=0.6,
            inventory_aversion_gamma=0.0008,
            passive_unwind_skew_ticks=1,
            passive_unwind_trigger=0.38,
        ),
        "VEV_4000": _r3_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r3_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r3_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r3_v24_gamma_option_zskip(5300, 2.5),
        "VEV_5400": _r3_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": _r3_v24_gamma_option(5500),
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


# Same signal stack as v1, but caps VELVET exposure lower. The new live log
# showed v1 can finish near the 200 limit; this version gives up some full
# backtest PnL for a much cleaner inventory profile.
MEMBER_OVERRIDES["r3_guarded_hybrid_v2"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="r3_guarded_anchor_mm",
            position_limit=150,
            **_R3_GUARDED_VELVET_PARAMS,
        ),
        # Vouchers: use ROUND_3 default option_mm_bs (penny-improve, no takers).
    },
}


_R3_HYDRO_PASSIVE_PRODUCTS_OFF = {
    "VELVETFRUIT_EXTRACT": None,
    **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
}


MEMBER_OVERRIDES["r3_hydro_passive_v1"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_live_defensive_mm",
            position_limit=200,
            maker_size=30,
            min_maker_size=4,
            tighten_ticks=1,
            trend_alpha=0.05,
            trend_threshold=99.0,
            hard_trend_threshold=999.0,
            inventory_reduce_ratio=0.60,
            inventory_stop_ratio=0.80,
            unwind_boost=0.80,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_passive_v2"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_live_defensive_mm",
            position_limit=200,
            maker_size=30,
            min_maker_size=4,
            tighten_ticks=1,
            trend_alpha=0.05,
            trend_threshold=99.0,
            hard_trend_threshold=999.0,
            inventory_reduce_ratio=0.60,
            inventory_stop_ratio=0.70,
            unwind_boost=0.80,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_only_v6"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=28,
            tighten_ticks=1,
            maker_size=20,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=8.0,
            take_cooldown_ts=3000,
            take_size=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_only_v7"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=28,
            tighten_ticks=1,
            maker_size=20,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=8.0,
            take_cooldown_ts=3000,
            take_size=1,
            eod_start_ts=85000,
            eod_end_ts=99900,
            eod_start_pos_limit=28,
            eod_end_pos_limit=0,
            eod_unwind_size_bonus=12,
            eod_take_size=1,
            eod_take_cooldown_ts=500,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_only_v8"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=28,
            tighten_ticks=1,
            maker_size=20,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=8.0,
            take_cooldown_ts=3000,
            take_size=1,
            eod_start_ts=85000,
            eod_end_ts=99900,
            eod_start_pos_limit=28,
            eod_end_pos_limit=0,
            eod_unwind_size_bonus=12,
            eod_take_size=1,
            eod_take_cooldown_ts=500,
            risk_abs_position_threshold=18,
            risk_target_position=10,
            risk_realized_progress_threshold=8.0,
            risk_realized_stall_ts=4000,
            risk_unrealized_peak_min=150.0,
            risk_unrealized_giveback_threshold=180.0,
            risk_giveback_window_ts=15000,
            risk_adverse_trend_threshold=2.0,
            risk_trend_turn_threshold=1.2,
            risk_force_giveback_threshold=300.0,
            risk_hold_ts=6000,
            risk_unwind_size_bonus=14,
            risk_take_size=2,
            risk_take_cooldown_ts=800,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_only_v9"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=28,
            tighten_ticks=1,
            maker_size=20,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=8.0,
            take_cooldown_ts=3000,
            take_size=1,
            eod_start_ts=85000,
            eod_end_ts=99900,
            eod_start_pos_limit=28,
            eod_end_pos_limit=0,
            eod_unwind_size_bonus=12,
            eod_take_size=1,
            eod_take_cooldown_ts=500,
            risk_abs_position_threshold=20,
            risk_target_position=14,
            risk_realized_progress_threshold=10.0,
            risk_realized_stall_ts=5000,
            risk_unrealized_peak_min=180.0,
            risk_unrealized_giveback_threshold=220.0,
            risk_giveback_window_ts=18000,
            risk_adverse_trend_threshold=3.0,
            risk_trend_turn_threshold=1.6,
            risk_force_giveback_threshold=420.0,
            risk_hold_ts=4000,
            risk_unwind_size_bonus=8,
            risk_unwind_tighten_ticks=4,
            risk_unwind_leave_gap_ticks=1,
            risk_take_size=0,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_only_v10"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=28,
            tighten_ticks=1,
            maker_size=20,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=8.0,
            take_cooldown_ts=3000,
            take_size=1,
            eod_start_ts=85000,
            eod_end_ts=99900,
            eod_start_pos_limit=28,
            eod_end_pos_limit=0,
            eod_unwind_size_bonus=12,
            eod_take_size=1,
            eod_take_cooldown_ts=500,
            midcap_activation_position=18,
            midcap_base_position_cap=28,
            midcap_min_position_cap=12,
            midcap_capture_ticks_threshold=20.0,
            midcap_rebound_start_ticks=10.0,
            midcap_rebound_full_ticks=24.0,
            midcap_rebound_window_ts=16000,
            midcap_realized_floor=100.0,
            midcap_unrealized_floor=120.0,
            midcap_unwind_size_bonus=8,
            midcap_unwind_tighten_ticks=3,
            midcap_unwind_leave_gap_ticks=1,
            midcap_same_side_size_cap=2,
            midcap_take_size=1,
            midcap_take_cooldown_ts=1200,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_only_v11"] = MEMBER_OVERRIDES["r3_hydro_only_v10"]


MEMBER_OVERRIDES["r3_hydro_only_v12"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            use_target_inventory_model=True,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            target_max_short=32,
            target_trend_entry=2.5,
            target_trend_full=10.0,
            target_regime_reset_trend=1.0,
            target_oversold_start=8.0,
            target_oversold_full=22.0,
            target_rebound_start=18.0,
            target_rebound_full=35.0,
            target_turn_start=0.7,
            target_turn_full=2.4,
            target_oversold_relief_weight=0.70,
            target_rebound_relief_weight=0.40,
            target_turn_relief_weight=0.85,
            target_min_active_position=4,
            target_hold_band=2,
            target_neutral_maker_size=4,
            target_same_side_size=0,
            target_max_quote_size=18,
            target_size_gain_per_unit=0.75,
            target_base_tighten_ticks=2,
            target_gap_per_tighten_step=6,
            target_max_tighten_ticks=5,
            target_leave_gap_ticks=1,
            target_cover_take_size=1,
            target_cover_take_gap_threshold=10,
            target_cover_take_rebound_threshold=20.0,
            target_cover_take_cooldown_ts=900,
            target_entry_take_size=2,
            target_entry_take_gap_threshold=8,
            target_entry_take_trend_threshold=6.0,
            target_entry_take_short_signal_threshold=0.72,
            target_entry_take_relief_cap=0.35,
            target_entry_take_cooldown_ts=1600,
            eod_start_ts=85000,
            eod_end_ts=99900,
            eod_start_pos_limit=28,
            eod_end_pos_limit=0,
            eod_take_size=1,
            eod_take_cooldown_ts=500,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_only_v13"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=28,
            tighten_ticks=1,
            maker_size=20,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=8.0,
            take_cooldown_ts=3000,
            take_size=1,
            trailcap_activation_position=22,
            trailcap_base_position_cap=28,
            trailcap_min_position_cap=8,
            trailcap_capture_start=20.0,
            trailcap_rebound_start=10.0,
            trailcap_rebound_full=22.0,
            trailcap_stale_start_ts=3000,
            trailcap_stale_full_ts=12000,
            trailcap_turn_start=0.8,
            trailcap_turn_full=2.0,
            trailcap_stale_weight=0.7,
            trailcap_turn_weight=0.8,
            trailcap_unwind_size_bonus=10,
            trailcap_unwind_tighten_ticks=3,
            trailcap_unwind_leave_gap_ticks=1,
            trailcap_same_side_size_cap=0,
            trailcap_take_size=1,
            trailcap_take_cooldown_ts=1200,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["theo_r3_hydro_v4"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=8.0,
            signal_pos_gate=12,
            tighten_ticks=1,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=12.0,
            take_cooldown_ts=2000,
            take_size=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": _THEO_R3_UNDERLYING,
        **{f"VEV_{strike}": _theo_r3_option_override(strike) for strike in _THEO_R3_ACTIVE_OPTION_STRIKES},
    },
}


# v5: symmetric trend guard (|trend| < tg suppresses signal in both directions).
# Fixes V-shape recovery drawdown seen in log 382946: during bounce, fast EMA trends
# toward 0 but passes through the tg boundary, re-activating sell signal on a still-short
# position. Tighter tg=6 prevents that. pos_gate=12 caps directional inventory from signal.
MEMBER_OVERRIDES["theo_r3_hydro_v5"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=12,
            tighten_ticks=1,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=12.0,
            take_cooldown_ts=2000,
            take_size=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": _THEO_R3_UNDERLYING,
        **{f"VEV_{strike}": _theo_r3_option_override(strike) for strike in _THEO_R3_ACTIVE_OPTION_STRIKES},
    },
}


MEMBER_OVERRIDES["theo_r3_hydro_v3"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            tighten_ticks=1,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=12.0,
            take_cooldown_ts=2000,
            take_size=1,
            soft_position_limit=60,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": _THEO_R3_UNDERLYING,
        **{f"VEV_{strike}": _theo_r3_option_override(strike) for strike in _THEO_R3_ACTIVE_OPTION_STRIKES},
    },
}


# Vol-arb v2: active strikes moved to (5200, 5300) where vega is maximal and fills exist;
# takers enabled; realized vol anchor raised to actually express the long-vol thesis.
_THEO_R3_ACTIVE_OPTION_STRIKES_V2 = (5200, 5300)


def _theo_r3_option_override_v2(strike: int) -> ProductConfig:
    return _override(
        ROUND_3[f"VEV_{strike}"],
        strategy="theo_r3_vol_arb_v1",
        position_limit=300,
        role="option",
        strike=strike,
        trade_enabled=True,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        tte_days_initial=5.0,
        ticks_per_day=10000,
        timestamp_units_per_day=1000000,
        historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
        prior_vol=0.0125,
        sigma_floor=0.005,
        sigma_cap=0.10,
        realized_vol_default=0.0215,
        realized_var_alpha=0.06,
        realized_vol_floor=0.0100,
        realized_vol_cap=0.0500,
        realized_anchor_weight=0.55,   # was 0.18 — express vol edge properly
        take_edge=10.0,                # was 12.0 — fire when edge >= 10 ticks
        reduce_edge=3.0,               # keep position unless bid significantly > fair
        take_size=6,                   # was 3 — accumulate faster
        maker_size=4,
        maker_edge=2.0,
        enable_takers=True,            # was False — core change: actually buy underpriced options
        soft_position_limit=40,        # was 16 — allow meaningful vol position
        hedge_abs_position_limit=140,
        inventory_skew=0,              # don't skew quotes by position — hold the vol
        min_quote_price=5.0,
    )


MEMBER_OVERRIDES["theo_r3_vol_arb_v2"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=12,
            tighten_ticks=1,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=12.0,
            take_cooldown_ts=2000,
            take_size=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        # naive_tight_mm for VELVETFRUIT: drops the delta-hedge overhead that was
        # bleeding -870 PnL over 3 days. Just follow the book and capture spread.
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
        ),
        # Options: no override → inherits ROUND_3 default option_mm_bs on all 10 strikes.
        # VEV_5400/5500 vol_arb layer dropped (was getting 0 fills in live + backtest).
    },
}


def _r3_guarded_velvet_underlying(**extra) -> ProductConfig:
    return _override(
        ROUND_3["VELVETFRUIT_EXTRACT"],
        strategy="r3_guarded_anchor_mm",
        position_limit=200,
        **{**_R3_GUARDED_VELVET_PARAMS, **extra},
    )


MEMBER_OVERRIDES["r3_guarded_hybrid_v1"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
        ),
        "VELVETFRUIT_EXTRACT": _r3_guarded_velvet_underlying(),
        # Vouchers: use ROUND_3 default option_mm_bs (penny-improve, no takers).
    },
}


MEMBER_OVERRIDES["r3_velvet_options_v4_guardedblend"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDRO_ALPHA_V4,
        "VELVETFRUIT_EXTRACT": _r3_guarded_velvet_underlying(),
        "VEV_4000": _r3_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r3_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r3_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r3_v24_gamma_option_zskip(5300, 2.0),
        "VEV_5400": _r3_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": None,
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r3_velvet_options_v5_guardedtuned"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDRO_ALPHA_V4,
        "VELVETFRUIT_EXTRACT": _r3_guarded_velvet_underlying(
            guard_reversion_threshold=7.5,
            guard_trend_alpha=0.45,
            take_edge_lo=0.6,
            take_edge_hi=1.2,
        ),
        "VEV_4000": _r3_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r3_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r3_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r3_v24_gamma_option_zskip(5300, 2.0),
        "VEV_5400": _r3_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": _r3_v24_gamma_option(5500),
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r3_velvet_options_v6_velvettuned"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDRO_ALPHA_V4,
        "VELVETFRUIT_EXTRACT": _r3_guarded_velvet_underlying(
            guard_reversion_threshold=7.5,
            guard_trend_alpha=0.45,
            take_edge_lo=0.6,
            take_edge_hi=1.2,
            maker_size_base_pct=0.4,
            pct_kept_for_takers=0.005,
            toxic_threshold=0.6,
            toxic_window=8,
            toxic_size_frac=0.68,
        ),
        "VEV_4000": _r3_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r3_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r3_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r3_v24_gamma_option_zskip(5300, 2.0),
        "VEV_5400": _r3_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": _r3_v24_gamma_option(5500),
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r3_velvet_options_v7_passiveunwind"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDRO_ALPHA_V4,
        "VELVETFRUIT_EXTRACT": _r3_guarded_velvet_underlying(
            guard_reversion_threshold=7.5,
            guard_trend_alpha=0.45,
            take_edge_lo=0.6,
            take_edge_hi=1.2,
            maker_size_base_pct=0.4,
            pct_kept_for_takers=0.005,
            toxic_threshold=0.6,
            toxic_window=8,
            toxic_size_frac=0.68,
            inventory_aversion_gamma=0.0010,
            passive_unwind_skew_ticks=1,
            passive_unwind_trigger=0.38,
        ),
        "VEV_4000": _r3_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r3_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r3_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r3_v24_gamma_option_zskip(5300, 2.0),
        "VEV_5400": _r3_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": _r3_v24_gamma_option(5500),
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r3_velvet_options_v8_lightermaker"] = {
    3: {
        "HYDROGEL_PACK": _R3_HYDRO_ALPHA_V4,
        "VELVETFRUIT_EXTRACT": _r3_guarded_velvet_underlying(
            guard_reversion_threshold=7.5,
            guard_trend_alpha=0.45,
            take_edge_lo=0.6,
            take_edge_hi=1.2,
            maker_size_base_pct=0.31,
            pct_kept_for_takers=0.005,
            toxic_threshold=0.6,
            toxic_window=8,
            toxic_size_frac=0.68,
            inventory_aversion_gamma=0.0010,
            passive_unwind_skew_ticks=1,
            passive_unwind_trigger=0.38,
        ),
        "VEV_4000": _r3_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r3_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r3_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r3_v24_gamma_option_zskip(5300, 2.0),
        "VEV_5400": _r3_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": _r3_v24_gamma_option(5500),
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


MEMBER_OVERRIDES["r3_velvet_options_v9_globalretuned"] = {
    3: {
        "HYDROGEL_PACK": _override(
            _R3_HYDRO_ALPHA_V4,
            ema_alpha=0.006,
            fast_ema_alpha=0.025,
            maker_size=22,
            inventory_unwind_per_unit=0.20,
            take_threshold=13.0,
            take_size=2,
        ),
        "VELVETFRUIT_EXTRACT": _r3_guarded_velvet_underlying(
            guard_reversion_threshold=7.5,
            guard_trend_alpha=0.45,
            take_edge_lo=0.5,
            take_edge_hi=1.2,
            maker_size_base_pct=0.31,
            pct_kept_for_takers=0.003,
            toxic_threshold=0.65,
            toxic_window=8,
            toxic_size_frac=0.6,
            inventory_aversion_gamma=0.0008,
            passive_unwind_skew_ticks=1,
            passive_unwind_trigger=0.38,
        ),
        "VEV_4000": _r3_v24_gamma_option_zskip(4000, 1.5),
        "VEV_4500": _r3_v24_gamma_option_zskip(4500, 2.0),
        "VEV_5000": _r3_v24_gamma_option_zskip(5000, 1.0),
        "VEV_5100": _r3_v24_gamma_option(5100),
        "VEV_5200": _r3_v24_gamma_option_zskip(5200, 2.0),
        "VEV_5300": _r3_v24_gamma_option_zskip(5300, 2.5),
        "VEV_5400": _r3_v24_gamma_option_zskip(5400, 1.0),
        "VEV_5500": _r3_v24_gamma_option(5500),
        "VEV_6000": None,
        "VEV_6500": None,
    },
}


# Same signal stack as v1, but caps VELVET exposure lower. The new live log
# showed v1 can finish near the 200 limit; this version gives up some full
# backtest PnL for a much cleaner inventory profile.
MEMBER_OVERRIDES["r3_guarded_hybrid_v2"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="r3_guarded_anchor_mm",
            position_limit=150,
            **_R3_GUARDED_VELVET_PARAMS,
        ),
        # Vouchers: use ROUND_3 default option_mm_bs (penny-improve, no takers).
    },
}


_R3_HYDRO_PASSIVE_PRODUCTS_OFF = {
    "VELVETFRUIT_EXTRACT": None,
    **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
}


MEMBER_OVERRIDES["r3_hydro_passive_v1"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_live_defensive_mm",
            position_limit=200,
            maker_size=30,
            min_maker_size=4,
            tighten_ticks=1,
            trend_alpha=0.05,
            trend_threshold=99.0,
            hard_trend_threshold=999.0,
            inventory_reduce_ratio=0.60,
            inventory_stop_ratio=0.80,
            unwind_boost=0.80,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_passive_v2"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_live_defensive_mm",
            position_limit=200,
            maker_size=30,
            min_maker_size=4,
            tighten_ticks=1,
            trend_alpha=0.05,
            trend_threshold=99.0,
            hard_trend_threshold=999.0,
            inventory_reduce_ratio=0.60,
            inventory_stop_ratio=0.70,
            unwind_boost=0.80,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_only_v6"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=28,
            tighten_ticks=1,
            maker_size=20,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=8.0,
            take_cooldown_ts=3000,
            take_size=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_only_v7"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=28,
            tighten_ticks=1,
            maker_size=20,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=8.0,
            take_cooldown_ts=3000,
            take_size=1,
            eod_start_ts=85000,
            eod_end_ts=99900,
            eod_start_pos_limit=28,
            eod_end_pos_limit=0,
            eod_unwind_size_bonus=12,
            eod_take_size=1,
            eod_take_cooldown_ts=500,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_only_v8"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=28,
            tighten_ticks=1,
            maker_size=20,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=8.0,
            take_cooldown_ts=3000,
            take_size=1,
            eod_start_ts=85000,
            eod_end_ts=99900,
            eod_start_pos_limit=28,
            eod_end_pos_limit=0,
            eod_unwind_size_bonus=12,
            eod_take_size=1,
            eod_take_cooldown_ts=500,
            risk_abs_position_threshold=18,
            risk_target_position=10,
            risk_realized_progress_threshold=8.0,
            risk_realized_stall_ts=4000,
            risk_unrealized_peak_min=150.0,
            risk_unrealized_giveback_threshold=180.0,
            risk_giveback_window_ts=15000,
            risk_adverse_trend_threshold=2.0,
            risk_trend_turn_threshold=1.2,
            risk_force_giveback_threshold=300.0,
            risk_hold_ts=6000,
            risk_unwind_size_bonus=14,
            risk_take_size=2,
            risk_take_cooldown_ts=800,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_only_v9"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=28,
            tighten_ticks=1,
            maker_size=20,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=8.0,
            take_cooldown_ts=3000,
            take_size=1,
            eod_start_ts=85000,
            eod_end_ts=99900,
            eod_start_pos_limit=28,
            eod_end_pos_limit=0,
            eod_unwind_size_bonus=12,
            eod_take_size=1,
            eod_take_cooldown_ts=500,
            risk_abs_position_threshold=20,
            risk_target_position=14,
            risk_realized_progress_threshold=10.0,
            risk_realized_stall_ts=5000,
            risk_unrealized_peak_min=180.0,
            risk_unrealized_giveback_threshold=220.0,
            risk_giveback_window_ts=18000,
            risk_adverse_trend_threshold=3.0,
            risk_trend_turn_threshold=1.6,
            risk_force_giveback_threshold=420.0,
            risk_hold_ts=4000,
            risk_unwind_size_bonus=8,
            risk_unwind_tighten_ticks=4,
            risk_unwind_leave_gap_ticks=1,
            risk_take_size=0,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_only_v10"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=28,
            tighten_ticks=1,
            maker_size=20,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=8.0,
            take_cooldown_ts=3000,
            take_size=1,
            eod_start_ts=85000,
            eod_end_ts=99900,
            eod_start_pos_limit=28,
            eod_end_pos_limit=0,
            eod_unwind_size_bonus=12,
            eod_take_size=1,
            eod_take_cooldown_ts=500,
            midcap_activation_position=18,
            midcap_base_position_cap=28,
            midcap_min_position_cap=12,
            midcap_capture_ticks_threshold=20.0,
            midcap_rebound_start_ticks=10.0,
            midcap_rebound_full_ticks=24.0,
            midcap_rebound_window_ts=16000,
            midcap_realized_floor=100.0,
            midcap_unrealized_floor=120.0,
            midcap_unwind_size_bonus=8,
            midcap_unwind_tighten_ticks=3,
            midcap_unwind_leave_gap_ticks=1,
            midcap_same_side_size_cap=2,
            midcap_take_size=1,
            midcap_take_cooldown_ts=1200,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_only_v11"] = MEMBER_OVERRIDES["r3_hydro_only_v10"]


MEMBER_OVERRIDES["r3_hydro_only_v12"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            use_target_inventory_model=True,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            target_max_short=32,
            target_trend_entry=2.5,
            target_trend_full=10.0,
            target_regime_reset_trend=1.0,
            target_oversold_start=8.0,
            target_oversold_full=22.0,
            target_rebound_start=18.0,
            target_rebound_full=35.0,
            target_turn_start=0.7,
            target_turn_full=2.4,
            target_oversold_relief_weight=0.70,
            target_rebound_relief_weight=0.40,
            target_turn_relief_weight=0.85,
            target_min_active_position=4,
            target_hold_band=2,
            target_neutral_maker_size=4,
            target_same_side_size=0,
            target_max_quote_size=18,
            target_size_gain_per_unit=0.75,
            target_base_tighten_ticks=2,
            target_gap_per_tighten_step=6,
            target_max_tighten_ticks=5,
            target_leave_gap_ticks=1,
            target_cover_take_size=1,
            target_cover_take_gap_threshold=10,
            target_cover_take_rebound_threshold=20.0,
            target_cover_take_cooldown_ts=900,
            target_entry_take_size=2,
            target_entry_take_gap_threshold=8,
            target_entry_take_trend_threshold=6.0,
            target_entry_take_short_signal_threshold=0.72,
            target_entry_take_relief_cap=0.35,
            target_entry_take_cooldown_ts=1600,
            eod_start_ts=85000,
            eod_end_ts=99900,
            eod_start_pos_limit=28,
            eod_end_pos_limit=0,
            eod_take_size=1,
            eod_take_cooldown_ts=500,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["r3_hydro_only_v13"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=28,
            tighten_ticks=1,
            maker_size=20,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=8.0,
            take_cooldown_ts=3000,
            take_size=1,
            trailcap_activation_position=22,
            trailcap_base_position_cap=28,
            trailcap_min_position_cap=8,
            trailcap_capture_start=20.0,
            trailcap_rebound_start=10.0,
            trailcap_rebound_full=22.0,
            trailcap_stale_start_ts=3000,
            trailcap_stale_full_ts=12000,
            trailcap_turn_start=0.8,
            trailcap_turn_full=2.0,
            trailcap_stale_weight=0.7,
            trailcap_turn_weight=0.8,
            trailcap_unwind_size_bonus=10,
            trailcap_unwind_tighten_ticks=3,
            trailcap_unwind_leave_gap_ticks=1,
            trailcap_same_side_size_cap=0,
            trailcap_take_size=1,
            trailcap_take_cooldown_ts=1200,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **_R3_HYDRO_PASSIVE_PRODUCTS_OFF,
    },
}


MEMBER_OVERRIDES["theo_r3_hydro_v4"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=8.0,
            signal_pos_gate=12,
            tighten_ticks=1,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=12.0,
            take_cooldown_ts=2000,
            take_size=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": _THEO_R3_UNDERLYING,
        **{f"VEV_{strike}": _theo_r3_option_override(strike) for strike in _THEO_R3_ACTIVE_OPTION_STRIKES},
    },
}


# v5: symmetric trend guard (|trend| < tg suppresses signal in both directions).
# Fixes V-shape recovery drawdown seen in log 382946: during bounce, fast EMA trends
# toward 0 but passes through the tg boundary, re-activating sell signal on a still-short
# position. Tighter tg=6 prevents that. pos_gate=12 caps directional inventory from signal.
MEMBER_OVERRIDES["theo_r3_hydro_v5"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=12,
            tighten_ticks=1,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=12.0,
            take_cooldown_ts=2000,
            take_size=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": _THEO_R3_UNDERLYING,
        **{f"VEV_{strike}": _theo_r3_option_override(strike) for strike in _THEO_R3_ACTIVE_OPTION_STRIKES},
    },
}


MEMBER_OVERRIDES["theo_r3_hydro_v3"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            tighten_ticks=1,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=12.0,
            take_cooldown_ts=2000,
            take_size=1,
            soft_position_limit=60,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": _THEO_R3_UNDERLYING,
        **{f"VEV_{strike}": _theo_r3_option_override(strike) for strike in _THEO_R3_ACTIVE_OPTION_STRIKES},
    },
}


# Vol-arb v2: active strikes moved to (5200, 5300) where vega is maximal and fills exist;
# takers enabled; realized vol anchor raised to actually express the long-vol thesis.
_THEO_R3_ACTIVE_OPTION_STRIKES_V2 = (5200, 5300)


def _theo_r3_option_override_v2(strike: int) -> ProductConfig:
    return _override(
        ROUND_3[f"VEV_{strike}"],
        strategy="theo_r3_vol_arb_v1",
        position_limit=300,
        role="option",
        strike=strike,
        trade_enabled=True,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        tte_days_initial=5.0,
        ticks_per_day=10000,
        timestamp_units_per_day=1000000,
        historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
        prior_vol=0.0125,
        sigma_floor=0.005,
        sigma_cap=0.10,
        realized_vol_default=0.0215,
        realized_var_alpha=0.06,
        realized_vol_floor=0.0100,
        realized_vol_cap=0.0500,
        realized_anchor_weight=0.55,   # was 0.18 — express vol edge properly
        take_edge=10.0,                # was 12.0 — fire when edge >= 10 ticks
        reduce_edge=3.0,               # keep position unless bid significantly > fair
        take_size=6,                   # was 3 — accumulate faster
        maker_size=4,
        maker_edge=2.0,
        enable_takers=True,            # was False — core change: actually buy underpriced options
        soft_position_limit=40,        # was 16 — allow meaningful vol position
        hedge_abs_position_limit=140,
        inventory_skew=0,              # don't skew quotes by position — hold the vol
        min_quote_price=5.0,
    )


MEMBER_OVERRIDES["theo_r3_vol_arb_v2"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=6.0,
            signal_pos_gate=12,
            tighten_ticks=1,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=12.0,
            take_cooldown_ts=2000,
            take_size=1,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        # naive_tight_mm for VELVETFRUIT: drops the delta-hedge overhead that was
        # bleeding -870 PnL over 3 days. Just follow the book and capture spread.
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
        ),
        # Options: no override → inherits ROUND_3 default option_mm_bs on all 10 strikes.
        # VEV_5400/5500 vol_arb layer dropped (was getting 0 fills in live + backtest).
    },
}


_R3_LIVE_PROBE_OPTION_BASE = dict(
    strategy="option_live_probe_mm",
    quote_trace_enabled=True,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
)

_R3_LIVE_PROBE_OPTION_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]


def _r3_option_live_probe(strike: int, **extra: Any) -> ProductConfig:
    return _override(
        ROUND_3[f"VEV_{strike}"],
        position_limit=30,
        strike=strike,
        **{**_R3_LIVE_PROBE_OPTION_BASE, **extra},
    )


def _r3_delta_live_probe(symbol: str, *, anchor_price: float, **extra: Any) -> ProductConfig:
    return _override(
        ROUND_3[symbol],
        strategy="mm_first_v4_combo",
        position_limit=60,
        **{
            **_R3_LIVE_PROBE_VELVET_BASE,
            "anchor_price": anchor_price,
            **extra,
        },
    )


MEMBER_OVERRIDES["r3_live_probe_all_far_quotes"] = {
    3: {
        "HYDROGEL_PACK": _r3_delta_live_probe(
            "HYDROGEL_PACK",
            anchor_price=10000.0,
            gap_trigger_min=0,
            probe_distance=80,
            probe_qty=1,
            probe_interval_ticks=150,
            probe_t0_distances=[30, 60, 100, 150],
            probe_t0_qty=1,
            probe_t0_max_ts=1000,
        ),
        "VELVETFRUIT_EXTRACT": _r3_delta_live_probe(
            "VELVETFRUIT_EXTRACT",
            anchor_price=5250.0,
            gap_trigger_min=0,
            probe_distance=80,
            probe_qty=1,
            probe_interval_ticks=150,
            probe_t0_distances=[30, 60, 100, 150],
            probe_t0_qty=1,
            probe_t0_max_ts=1000,
        ),
        **{
            f"VEV_{strike}": _r3_option_live_probe(
                strike,
                far_probe_distances=[25, 50, 100],
                far_probe_qty=1,
                far_probe_interval_ticks=150,
            )
            for strike in _R3_LIVE_PROBE_OPTION_STRIKES
        },
    },
}


MEMBER_OVERRIDES["theo_r3_vol_arb_v3"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=8.0,        # was 6.0 — +1,120 backtest; must pair with take_size=1
            signal_pos_gate=12,
            tighten_ticks=1,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=12.0,
            take_cooldown_ts=2000,
            take_size=1,            # keep at 1 — take_size=3 with tg=8 destroys the edge
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
        ),
    },
}


MEMBER_OVERRIDES["theo_r3_vol_arb_v3"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="r3_hydro_reversion_mm",
            position_limit=200,
            ema_alpha=0.008,
            fast_ema_alpha=0.03,
            trend_guard=8.0,        # was 6.0 — +1,120 backtest; must pair with take_size=1
            signal_pos_gate=12,
            tighten_ticks=1,
            maker_size=24,
            min_maker_size=3,
            quote_threshold=6.0,
            max_signal_size_boost=12,
            inventory_reduce_per_unit=0.40,
            inventory_unwind_per_unit=0.30,
            max_unwind_boost=20,
            take_threshold=12.0,
            take_cooldown_ts=2000,
            take_size=1,            # keep at 1 — take_size=3 with tg=8 destroys the edge
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="naive_tight_mm",
            position_limit=200,
            maker_size=30,
            tighten_ticks=1,
        ),
    },
}

MEMBER_OVERRIDES["r3_live_probe_all_gap_flow_follow"] = {
    3: {
        "HYDROGEL_PACK": _r3_delta_live_probe(
            "HYDROGEL_PACK",
            anchor_price=10000.0,
            gap_trigger_min=10,
            gap_trigger_max_vol_pct=0.05,
            gap_trigger_confirm_ticks=1,
            OB_cleared_shift=60,
            momentum_window=30,
            momentum_threshold=0.75,
            momentum_qty=1,
        ),
        "VELVETFRUIT_EXTRACT": _r3_delta_live_probe(
            "VELVETFRUIT_EXTRACT",
            anchor_price=5250.0,
            gap_trigger_min=10,
            gap_trigger_max_vol_pct=0.05,
            gap_trigger_confirm_ticks=1,
            OB_cleared_shift=60,
            momentum_window=30,
            momentum_threshold=0.75,
            momentum_qty=1,
        ),
        **{
            f"VEV_{strike}": _r3_option_live_probe(
                strike,
                gap_sweep_min=3,
                gap_sweep_max_l1_qty=8,
                gap_sweep_confirm_ticks=1,
                gap_sweep_size=1,
                flow_mode="follow",
                flow_window=30,
                flow_threshold=0.75,
                flow_interval_ticks=20,
                flow_size=1,
            )
            for strike in _R3_LIVE_PROBE_OPTION_STRIKES
        },
    },
}


MEMBER_OVERRIDES["r3_live_probe_options_flow_fade_all_strikes"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": None,
        **{
            f"VEV_{strike}": _r3_option_live_probe(
                strike,
                flow_mode="fade",
                flow_window=30,
                flow_threshold=0.75,
                flow_interval_ticks=20,
                flow_size=1,
            )
            for strike in _R3_LIVE_PROBE_OPTION_STRIKES
        },
    },
}


MEMBER_OVERRIDES["r3_live_probe_velvet_far_quotes"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="mm_first_v4_combo",
            position_limit=60,
            **{
                **_R3_LIVE_PROBE_VELVET_BASE,
                "gap_trigger_min": 0,
                "probe_distance": 80,
                "probe_qty": 1,
                "probe_interval_ticks": 150,
                "probe_t0_distances": [30, 60, 100, 150],
                "probe_t0_qty": 1,
                "probe_t0_max_ts": 1000,
            },
        ),
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_live_probe_velvet_flow_follow"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            strategy="mm_first_v4_combo",
            position_limit=60,
            **{
                **_R3_LIVE_PROBE_VELVET_BASE,
                "gap_trigger_min": 0,
                "momentum_window": 30,
                "momentum_threshold": 0.75,
                "momentum_qty": 2,
            },
        ),
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_live_probe_hydro_far_quotes"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            strategy="mm_first_v4_combo",
            position_limit=60,
            **{
                **_R3_LIVE_PROBE_VELVET_BASE,
                "anchor_price": 10000.0,
                "gap_trigger_min": 0,
                "probe_distance": 80,
                "probe_qty": 1,
                "probe_interval_ticks": 150,
                "probe_t0_distances": [30, 60, 100, 150],
                "probe_t0_qty": 1,
                "probe_t0_max_ts": 1000,
            },
        ),
        "VELVETFRUIT_EXTRACT": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_live_probe_option_far_quotes"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": None,
        **{
            f"VEV_{strike}": _r3_option_live_probe(
                strike,
                far_probe_distances=[25, 50, 100],
                far_probe_qty=1,
                far_probe_interval_ticks=150,
            )
            for strike in [4000, 4500, 5000, 5100, 5200, 5300, 5400]
        },
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_live_probe_option_gap_sweep"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": None,
        **{
            f"VEV_{strike}": _r3_option_live_probe(
                strike,
                gap_sweep_min=3,
                gap_sweep_max_l1_qty=8,
                gap_sweep_confirm_ticks=1,
                gap_sweep_size=1,
            )
            for strike in [4000, 4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_live_probe_option_flow_follow"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": None,
        **{
            f"VEV_{strike}": _r3_option_live_probe(
                strike,
                flow_mode="follow",
                flow_window=30,
                flow_threshold=0.75,
                flow_interval_ticks=20,
                flow_size=1,
            )
            for strike in [4000, 4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


MEMBER_OVERRIDES["r3_live_probe_option_flow_fade"] = {
    3: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": None,
        **{
            f"VEV_{strike}": _r3_option_live_probe(
                strike,
                flow_mode="fade",
                flow_window=30,
                flow_threshold=0.75,
                flow_interval_ticks=20,
                flow_size=1,
            )
            for strike in [4000, 4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# ─── Probe 17: diagnostic (G1 named participants + G5 adverse selection) ───
# Designed after analyzing 00A/00B/00C live logs which revealed:
#  - VEV_4000 has 95-100% adverse-selection rate in BOTH follow and fade modes
#    (different live market structure vs backtest)
#  - HYDROGEL_PACK has consistent +5.78 avg signed_mtm (good)
#  - No named participants appeared in current live data, but probe logs them
#    in case they show up
#
# Trades minimally (1 lot every 200 ticks far from mid) → low PnL but max
# data on adverse selection per product.

_R3_DIAGNOSTIC_PROBE_BASE = dict(
    strategy="diagnostic_probe_mm",
    quote_trace_enabled=True,
    log_flush_ts=1000,
    ts_increment=100,
    last_ts_value=999900,
    far_probe_distances=[25, 50, 100],
    far_probe_interval_ticks=200,
    far_probe_qty=1,
    adverse_horizon_ticks=5,
    adverse_max_window=50,
    participant_log_max=30,
)


def _r3_diagnostic_probe(symbol: str, **extra: Any) -> ProductConfig:
    base = ROUND_3.get(symbol)
    if base is None:
        # Construct minimal ProductConfig for products not in ROUND_3 base
        from copy import deepcopy
        base = deepcopy(ROUND_3.get("VEV_4000"))
    return _override(
        base,
        position_limit=30,
        **{**_R3_DIAGNOSTIC_PROBE_BASE, **extra},
    )


# All 12 products on diagnostic probe — broad coverage in one upload
MEMBER_OVERRIDES["r3_live_probe_diagnostic_all"] = {
    3: {
        "HYDROGEL_PACK": _override(
            ROUND_3["HYDROGEL_PACK"],
            position_limit=30,
            **_R3_DIAGNOSTIC_PROBE_BASE,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            position_limit=30,
            **_R3_DIAGNOSTIC_PROBE_BASE,
        ),
        **{
            f"VEV_{strike}": _r3_diagnostic_probe(f"VEV_{strike}", strike=strike)
            for strike in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
        },
    },
}


# ══════════════════════════════════════════════════════════════════════════════
#  TIBO ROUND 3 — velvet_strat series
# ══════════════════════════════════════════════════════════════════════════════

# v1: pure passive MM on VELVETFRUIT_EXTRACT only
# Grid-tuned: maker_size_base_pct=0.30, pct_kept_for_takers=0.15 (+20,127 over 3 days)
MEMBER_OVERRIDES["tibo_velvet_v1"] = {
    3: {
        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT",
            strategy="velvet_strat",
            position_limit=200,
            params=dict(
                maker_size_base_pct=0.30,       # grid winner: 60 units base per side
                pct_kept_for_takers=0.15,       # hard stop at 85% of limit
                mid_smooth_window=50,
                mid_smooth_half_life=20,
                take_edge=999.0,                # takers off
                gap_trigger_min=0,              # gap exploit off
                gap_trigger_max_vol_pct=0.10,
                gap_trigger_confirm_ticks=2,
                OB_cleared_shift=10,
                ts_increment=100,
                last_ts_value=999900,
                log_flush_ts=1000,
            ),
        ),
    },
}


# ── v3: z-score signal-gated VEV option accumulation ─────────────────────────
# ask_adapt mode: tighten ask when VELVETFRUIT expensive, widen when cheap
# 3-day backtest: +48,922
_VEV_OPT_V3_BASE = dict(
    tte_days_initial=5.0,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    ticks_per_day=10000,
    ts_increment=100,
    timestamp_units_per_day=1_000_000,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    delta_sigma=0.022,
    min_quote_price=2.0,
    log_flush_ts=1000,
    last_ts_value=999900,
    zscore_window=500,
    zscore_threshold=1.0,
    zscore_bid_scale=2.0,
    zscore_bid_max=4.0,
    zscore_exec_mode="ask_adapt",
    ask_offset_neutral=10,
    ask_offset_sell=1,
)

_VELVET_V3_MM_PARAMS = dict(
    maker_size_base_pct=0.30,
    pct_kept_for_takers=0.15,
    mid_smooth_window=50,
    mid_smooth_half_life=20,
    use_delta_hedge=True,
    zscore_window=500,
    ts_increment=100,
    last_ts_value=999900,
    log_flush_ts=1000,
)

MEMBER_OVERRIDES["tibo_velvet_v3"] = {
    3: {
        "HYDROGEL_PACK": None,
        # VEV options run BEFORE VELVETFRUIT so delta is published first
        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="velvet_strat_v3_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 4000.0, "maker_size_bid": 20, "maker_size_ask": 20,
                    "ask_offset_neutral": 1, "ask_offset_sell": 1}),  # deep ITM: always symmetric
        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="velvet_strat_v3_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 5200.0, "maker_size_bid": 20, "maker_size_ask": 5}),
        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="velvet_strat_v3_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 5300.0, "maker_size_bid": 20, "maker_size_ask": 5}),
        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="velvet_strat_v3_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 5400.0, "maker_size_bid": 20, "maker_size_ask": 5,
                    "prevent_crossing": True}),  # 1-tick spread: stay passive
        "VEV_4500": None, "VEV_5000": None, "VEV_5100": None,
        "VEV_5500": None, "VEV_6000": None, "VEV_6500": None,
        # VELVETFRUIT MM runs LAST (reads vev_total_delta from shared)
        "VELVETFRUIT_EXTRACT": ProductConfig(symbol="VELVETFRUIT_EXTRACT", strategy="velvet_strat_v3_mm",
            position_limit=200, params=_VELVET_V3_MM_PARAMS),
    },
}


# ── tibo_velvet_v24: friend's merged strategy ─────────────────────────────────
# VELVETFRUIT: MMFirstV4ComboStrategy (anchor-price MM + AR shift + takers)
# VEV_4000:    OptionMMBSStrategy (symmetric BS-aware MM)
# VEV_4500/5000/5100/5200/5300: GammaScalpZGatedStrategy (z-gated long-call accumulation)
# VEV_5400:    OptionMMBSStrategy (tight passive MM, use_smile=False)
_V24_OPT_BS_BASE = dict(
    tte_days_initial=5.0,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    timestamp_units_per_day=1_000_000,
    ts_increment=100,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    prior_vol=0.0125,
    sigma_floor=0.005,
    sigma_cap=0.1,
    iv_ewma_alpha=0.3,
    min_quote_price=2.0,
    take_edge=3.0,
    take_size=40,
    enable_takers=False,
    penny_improve_around_mkt=True,
    inv_bias_per_unit=0.02,
    log_flush_ts=1000,
    last_ts_value=999900,
)

_V24_GAMMA_BASE = dict(
    tte_days_initial=5.0,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    timestamp_units_per_day=1_000_000,
    ts_increment=100,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    implied_vol_prior=0.0125,
    min_quote_price=2.0,
    entry_size=30,
    passive_bid_size=24,
    target_qty=300,
    unwind_tte_threshold=1.5,
    skip_when_expensive=True,
    zscore_skip_threshold=0.5,
    boost_when_cheap=False,
    zscore_boost_threshold=1.0,
    entry_size_boost=1.5,
    sell_when_very_expensive=False,
    edge_ticks=0.0,
    zscore_window=500,
    log_flush_ts=1000,
    last_ts_value=999900,
)

MEMBER_OVERRIDES["tibo_velvet_v24"] = {
    3: {
        "HYDROGEL_PACK": None,

        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="option_mm_bs", position_limit=300,
            params={**_V24_OPT_BS_BASE, "strike": 4000, "maker_edge": 2, "maker_size": 40,
                    "use_smile": True}),

        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="gamma_scalp_zgated", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 4500}),
        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="gamma_scalp_zgated", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5000}),
        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="gamma_scalp_zgated", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5100}),
        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="gamma_scalp_zgated", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5200}),
        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="gamma_scalp_zgated", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5300}),

        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="option_mm_bs", position_limit=300,
            params={**_V24_OPT_BS_BASE, "strike": 5400, "maker_edge": 1, "maker_size": 10,
                    "min_quote_price": 1.0, "inv_bias_per_unit": 0.04, "use_smile": False}),

        "VEV_5500": None, "VEV_6000": None, "VEV_6500": None,

        "VELVETFRUIT_EXTRACT": ProductConfig(symbol="VELVETFRUIT_EXTRACT",
            strategy="mm_first_v4_combo", position_limit=200,
            params=dict(
                anchor_price=5250.0,
                anchor_alpha=0.02,
                anchor_drift_bound=2.0,
                ar_gain=0.3,
                ar_shift_source="mid_smooth",
                maker_size=30,
                pct_kept_for_takers=0.05,
                take_edge_lo=0.3,
                take_edge_hi=0.8,
                inventory_aversion_gamma=0.0015,
                unwind_take_edge=3.0,
                tighten_ticks=1,
                full_capacity_on_empty=True,
                ts_increment=100,
                last_ts_value=999900,
                log_flush_ts=1000,
            )),
    },
}


# ── tibo_velvet_v25: best-of-both combination ────────────────────────────────
# VELVETFRUIT + VEV_4000/5200/5300/5400: v3 approach (passive MM, never directional)
# VEV_4500/5000/5100:                    v24 approach (GammaScalpZGated, new strikes)
#
# Root causes fixed vs v24:
#   VELVETFRUIT:  mm_first_v4_combo AR signal shorted on D2 when price rose → -6.5k
#                 Fix: revert to VelvetMMV3 (passive, consistent +6-7k/day, no direction bet)
#   VEV_5200/5300: skip_when_expensive+threshold=0.5 silenced accumulation when VELVETFRUIT
#                 trended (z>0.5 majority of D1) → only 27/90 units vs v3's 300
#                 Fix: revert to VEVOptionMMV3 which never skips bids, only adapts ask

MEMBER_OVERRIDES["tibo_velvet_v25"] = {
    3: {
        "HYDROGEL_PACK": None,

        # ── VEV options: run BEFORE VELVETFRUIT so delta is published first ──

        # VEV_4000: symmetric passive MM, deep ITM spread capture
        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="velvet_strat_v25_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 4000.0, "maker_size_bid": 20, "maker_size_ask": 20,
                    "ask_offset_neutral": 1, "ask_offset_sell": 1}),

        # VEV_4500/5000/5100: GammaScalpV25 — active taker + passive bid accumulation
        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="gamma_scalp_v25", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 4500}),
        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="gamma_scalp_v25", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5000}),
        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="gamma_scalp_v25", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5100}),

        # VEV_5200/5300: bid-heavy passive MM, never skips bids, ask adapts to z-score
        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="velvet_strat_v25_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 5200.0, "maker_size_bid": 20, "maker_size_ask": 5}),
        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="velvet_strat_v25_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 5300.0, "maker_size_bid": 20, "maker_size_ask": 5}),

        # VEV_5400: prevent_crossing=True — passive only, 1-tick spread
        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="velvet_strat_v25_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 5400.0, "maker_size_bid": 20, "maker_size_ask": 5,
                    "prevent_crossing": True}),

        "VEV_5500": None, "VEV_6000": None, "VEV_6500": None,

        # VELVETFRUIT: passive penny-improve MM, no directional bets, delta hedge from VEV
        "VELVETFRUIT_EXTRACT": ProductConfig(symbol="VELVETFRUIT_EXTRACT",
            strategy="velvet_strat_v25_mm", position_limit=200, params=_VELVET_V3_MM_PARAMS),
    },
}


# ── tibo_velvet_v26: ablation-driven simplification of v25 ───────────────────
# Ablation findings (3-day, realistic fill mode):
#   zscore_exec_mode removal (VEV_5200/5300/5400): 0 PnL impact → remove
#   use_delta_hedge removal (VELVETFRUIT):          0 PnL impact → remove
#   skip_when_expensive=False on V4500:            +2,326
#   skip_when_expensive=False on V5000:            +2,265
#   skip_when_expensive=True  on V5100 (keep):     saves -2,410 if removed
#   Expected v26 total: ~+96,264 vs v25's +94,083

_VELVET_V26_MM_PARAMS = dict(
    maker_size_base_pct=0.30,
    pct_kept_for_takers=0.15,
    mid_smooth_window=50,
    mid_smooth_half_life=20,
    use_delta_hedge=False,        # ablation: zero impact, removed for simplicity
    zscore_window=500,
    ts_increment=100,
    last_ts_value=999900,
    log_flush_ts=1000,
)

_VEV_OPT_V26_BASE = dict(
    **{k: v for k, v in _VEV_OPT_V3_BASE.items() if k != "zscore_exec_mode"},
    zscore_exec_mode="none",      # ablation: zero impact, z-score ask adapt is dead code
)

MEMBER_OVERRIDES["tibo_velvet_v26"] = {
    3: {
        "HYDROGEL_PACK": None,

        # VEV_4000: symmetric passive MM, deep ITM spread capture
        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="velvet_strat_v26_opt", position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 4000.0, "maker_size_bid": 20, "maker_size_ask": 20,
                    "ask_offset_neutral": 1, "ask_offset_sell": 1}),

        # VEV_4500: skip gate OFF — delta≈1 so accumulating when expensive is fine (+2,326)
        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="gamma_scalp_v26", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 4500, "skip_when_expensive": False}),

        # VEV_5000: skip gate OFF — benefit from extra fills outweighs directional risk (+2,265)
        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="gamma_scalp_v26", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5000, "skip_when_expensive": False}),

        # VEV_5100: skip gate ON — closest to ATM (delta≈0.7), removing would cost -2,410
        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="gamma_scalp_v26", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5100, "skip_when_expensive": True}),

        # VEV_5200/5300: bid-heavy, mode="none" (z-score ask adapt was dead code)
        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="velvet_strat_v26_opt", position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5200.0, "maker_size_bid": 20, "maker_size_ask": 5}),
        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="velvet_strat_v26_opt", position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5300.0, "maker_size_bid": 20, "maker_size_ask": 5}),

        # VEV_5400: passive only, prevent_crossing=True
        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="velvet_strat_v26_opt", position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5400.0, "maker_size_bid": 20, "maker_size_ask": 5,
                    "prevent_crossing": True}),

        "VEV_5500": None, "VEV_6000": None, "VEV_6500": None,

        # VELVETFRUIT: passive MM, delta hedge removed (zero ablation impact)
        "VELVETFRUIT_EXTRACT": ProductConfig(symbol="VELVETFRUIT_EXTRACT",
            strategy="velvet_strat_v26_mm", position_limit=200, params=_VELVET_V26_MM_PARAMS),
    },
}


# ── tibo_velvet_v27: SmileIVScaler for OTM/NTM VEV strikes ──────────────────
# Replaces VEV_5100/5200/5300/5400 with SmileIVScalerV27:
#   - LOO polynomial smile fit → fair IV per strike
#   - EWMA residual baseline + z-score
#   - Aggressively buy when cheap vs smile (resid_z <= -0.9)
#   - Exit when IV mean-reverts (resid_z >= 0.6 or price edge met)
#   - Passive maker around smile reference price
# Unchanged from v26: VELVETFRUIT, VEV_4000, VEV_4500, VEV_5000

_SMILE_SCALPER_V27_BASE = dict(
    tte_days_initial=5.0,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    timestamp_units_per_day=1_000_000,
    ts_increment=100,
    last_ts_value=999900,
    log_flush_ts=1000,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    # IV / smile params
    prior_vol=0.0125,
    implied_vol_prior=0.0125,
    smile_degree=2,
    smile_min_points=4,
    sigma_floor=0.005,
    sigma_cap=0.10,
    # Residual EWMA
    resid_ewma_alpha=0.03,
    resid_std_init=0.0015,
    resid_std_floor=0.0005,
    # Active rank gate
    active_reference_spot=5250.0,
    active_expand_every=120.0,
    active_base_count=6,
    active_max_extra_count=2,
    # Trading params
    soft_position_limit=150,
    entry_position_cap=60,
    take_size=20,
    maker_size=10,
    maker_edge=2.0,
    take_price_edge=2.0,
    reduce_price_edge=1.0,
    take_zscore=0.9,
    reduce_zscore=0.6,
    cheap_reset_z=0.35,
    inventory_skew=3.0,
    min_quote_price=1.0,
    resid_warmup_ticks=60,
    maker_join_best=True,
    inactive_unwind_bias=1,
    take_cooldown_ts=0,
    position_limit=300,
)

MEMBER_OVERRIDES["tibo_velvet_v27"] = {
    3: {
        "HYDROGEL_PACK": None,

        # VEV_4000: deep ITM, symmetric passive MM — unchanged from v26
        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="velvet_strat_v26_opt", position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 4000.0, "maker_size_bid": 20, "maker_size_ask": 20,
                    "ask_offset_neutral": 1, "ask_offset_sell": 1}),

        # VEV_4500/5000: skip gate OFF — ablation confirmed +4,591 — unchanged from v26
        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="gamma_scalp_v26", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 4500, "skip_when_expensive": False}),
        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="gamma_scalp_v26", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5000, "skip_when_expensive": False}),

        # VEV_5100/5200/5300/5400: SmileIVScaler (replaces GammaScalp skip=True + passive MM)
        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="smile_iv_scaler_v27", position_limit=300,
            params={**_SMILE_SCALPER_V27_BASE, "strike": 5100}),
        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="smile_iv_scaler_v27", position_limit=300,
            params={**_SMILE_SCALPER_V27_BASE, "strike": 5200}),
        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="smile_iv_scaler_v27", position_limit=300,
            params={**_SMILE_SCALPER_V27_BASE, "strike": 5300}),
        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="smile_iv_scaler_v27", position_limit=300,
            params={**_SMILE_SCALPER_V27_BASE, "strike": 5400}),

        "VEV_5500": None, "VEV_6000": None, "VEV_6500": None,

        # VELVETFRUIT: unchanged from v26
        "VELVETFRUIT_EXTRACT": ProductConfig(symbol="VELVETFRUIT_EXTRACT",
            strategy="velvet_strat_v26_mm", position_limit=200, params=_VELVET_V26_MM_PARAMS),
    },
}


# ── tibo_theo_v7: Theo's velvettuned_v7 as a member config ───────────────────
# Params copied verbatim from velvettuned_v7.py PRODUCTS dict.
# HYDROGEL excluded. VEV_4000–VEV_5500 all use TheoV7GammaScalp.

_THEO_V7_VEV_BASE = dict(
    boost_when_cheap=False,
    edge_ticks=0.0,
    enable_takers=False,
    entry_size=30,
    entry_size_boost=1.5,
    implied_vol_prior=0.0125,
    inv_bias_per_unit=0.02,
    iv_ewma_alpha=0.3,
    last_ts_value=999900,
    log_flush_ts=1000,
    maker_edge=2,
    maker_size=20,
    min_quote_price=2.0,
    passive_bid_size=24,
    penny_improve_around_mkt=True,
    prior_vol=0.0125,
    sigma_cap=0.1,
    sigma_floor=0.005,
    skip_when_expensive=True,
    take_edge=3.0,
    take_size=40,
    target_qty=300,
    timestamp_units_per_day=1_000_000,
    ts_increment=100,
    tte_days_initial=5.0,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    unwind_tte_threshold=1.5,
    use_smile=True,
    zscore_boost_threshold=1.0,
    zscore_window=500,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
)

_THEO_V7_VELVET_PARAMS = dict(
    anchor_alpha=0.02,
    anchor_drift_bound=2.0,
    anchor_price=5250.0,
    ar_gain=0.3,
    ar_shift_source="mid_smooth",
    full_capacity_on_empty=True,
    guard_inventory_dist=40.0,
    guard_max_dist=80.0,
    guard_min_dist=0.0,
    guard_near_band=0.0,
    guard_reversion_threshold=7.5,
    guard_trend_alpha=0.45,
    inventory_aversion_gamma=0.001,
    last_ts_value=999900,
    log_flush_ts=1000,
    maker_size=30,
    maker_size_base_pct=0.4,
    passive_unwind_skew_ticks=1,
    passive_unwind_trigger=0.38,
    pct_kept_for_takers=0.005,
    take_edge_hi=1.2,
    take_edge_lo=0.6,
    tighten_ticks=1,
    toxic_size_frac=0.68,
    toxic_threshold=0.6,
    toxic_window=8,
    ts_increment=100,
    unwind_take_edge=3.0,
)

MEMBER_OVERRIDES["tibo_theo_v7"] = {
    3: {
        "HYDROGEL_PACK": None,

        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT", strategy="theo_v7_velvet_mm",
            position_limit=200, params=_THEO_V7_VELVET_PARAMS),

        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4000,
                "zscore_skip_threshold": 1.5}),
        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4500,
                "zscore_skip_threshold": 2.0}),
        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5000,
                "zscore_skip_threshold": 1.0}),
        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5100,
                "zscore_skip_threshold": 0.5}),
        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5200,
                "zscore_skip_threshold": 2.0}),
        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5300,
                "zscore_skip_threshold": 2.0}),
        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5400,
                "zscore_skip_threshold": 1.0}),
        "VEV_5500": ProductConfig(symbol="VEV_5500", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5500,
                "zscore_skip_threshold": 0.5}),

        "VEV_6000": None, "VEV_6500": None,
    },
}


# ── tibo_velvet_v28: best-of-both v7 + v26 ablation fixes ────────────────────
# v7 wins: VELVETFRUIT (GuardedAnchor), VEV_4000 (GammaScalp active taker)
# v26 wins: VEV_5200/5300/5400 (passive bid-heavy), VEV_5000 skip=False

MEMBER_OVERRIDES["tibo_velvet_v28"] = {
    3: {
        "HYDROGEL_PACK": None,

        # VELVETFRUIT: v7's GuardedAnchorMM (unchanged from v7)
        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT", strategy="velvet_strat_v28_mm",
            position_limit=200, params=_THEO_V7_VELVET_PARAMS),

        # VEV_4000: v7 GammaScalp, skip=True thresh=1.5 (unchanged)
        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="gamma_scalp_v28",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4000,
                "zscore_skip_threshold": 1.5}),

        # VEV_4500: v7 GammaScalp, skip=True thresh=2.0 (near-equiv to skip=False)
        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="gamma_scalp_v28",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4500,
                "zscore_skip_threshold": 2.0}),

        # VEV_5000: skip=False (v26 ablation: +2,265 vs skip=True thresh=0.5)
        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="gamma_scalp_v28",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5000,
                "skip_when_expensive": False}),

        # VEV_5100: keep skip=True thresh=0.5 (ablation confirmed: removing costs -2,410)
        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="gamma_scalp_v28",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5100,
                "zscore_skip_threshold": 0.5}),

        # VEV_5200/5300/5400: switch to passive bid-heavy (v26 wins: +6.2k total)
        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="velvet_strat_v28_opt",
            position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5200.0,
                    "maker_size_bid": 20, "maker_size_ask": 5}),
        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="velvet_strat_v28_opt",
            position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5300.0,
                    "maker_size_bid": 20, "maker_size_ask": 5}),
        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="velvet_strat_v28_opt",
            position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5400.0,
                    "maker_size_bid": 20, "maker_size_ask": 5,
                    "prevent_crossing": True}),

        # VEV_5500: keep v7 GammaScalp
        "VEV_5500": ProductConfig(symbol="VEV_5500", strategy="gamma_scalp_v28",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5500,
                "zscore_skip_threshold": 0.5}),

        "VEV_6000": None, "VEV_6500": None,
    },
}


# ── tibo_velvet_v28_dyn_*: v28 with dynamic slow-anchor on VELVETFRUIT ───────
# Replace fixed anchor=5250 with a slow EWMA of mid.  Three alpha values:
#   slow   (alpha=0.00005, HL ~14000 ticks = ~1.4 days)
#   medium (alpha=0.0002,  HL ~ 3500 ticks = ~0.35 days)
#   fast   (alpha=0.0008,  HL ~  866 ticks = ~0.09 days)
# All other params identical to v28.  anchor_alpha=0 (no fast-drift on top),
# anchor_drift_bound=0 (dynamic anchor is already smooth enough).

def _v28_dyn_velvet_params(alpha: float) -> dict:
    return dict(
        _THEO_V7_VELVET_PARAMS,
        anchor_price=5250.0,          # seed value only (overridden dynamically)
        anchor_alpha=0.0,             # disable fast anchor drift
        anchor_drift_bound=0.0,       # no drift bound
        anchor_slow_alpha=alpha,
    )

def _make_v28_dyn(alpha: float) -> Dict:
    vf = ProductConfig(
        symbol="VELVETFRUIT_EXTRACT", strategy="dynamic_anchor_mm",
        position_limit=200, params=_v28_dyn_velvet_params(alpha))
    base = dict(MEMBER_OVERRIDES["tibo_velvet_v28"][3])
    base["VELVETFRUIT_EXTRACT"] = vf
    return {3: base}

MEMBER_OVERRIDES["tibo_velvet_v28_dyn_slow"]   = _make_v28_dyn(0.00005)
MEMBER_OVERRIDES["tibo_velvet_v28_dyn_medium"]  = _make_v28_dyn(0.0002)
MEMBER_OVERRIDES["tibo_velvet_v28_dyn_fast"]    = _make_v28_dyn(0.0008)


# ── tibo_velvet_v29: v28 + Leo's IV residual gate on VEV_5300 ──────────────────

_V29_IV_GATE_BASE = dict(
    iv_residual_gate=True,
    iv_skip_threshold=0.0010,
    iv_boost_threshold=0.0010,
    iv_delta_threshold=0.0003,
    iv_ewma_fast_alpha=0.10,
    iv_ewma_slow_alpha=0.02,
    iv_passive_boost=1.5,
)

_tibo_velvet_v29 = dict(MEMBER_OVERRIDES["tibo_velvet_v28"][3])
_tibo_velvet_v29["VEV_5300"] = ProductConfig(
    symbol="VEV_5300",
    strategy="gamma_scalp_v28",
    position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_V29_IV_GATE_BASE, "strike": 5300, "skip_when_expensive": False},
)
MEMBER_OVERRIDES["tibo_velvet_v29"] = {3: _tibo_velvet_v29}


# ── tibo_velvet_v29_*: product-isolated option idea probes ──────────────────
# Keep VELVETFRUIT + all untouched options identical to v29, then swap exactly
# one option so attribution stays clean in compare runs.

_V29_VEV5000_WITH_ASK = {
    **_THEO_V7_VEV_BASE,
    "strike": 5000,
    "skip_when_expensive": False,
    "passive_ask_size": 5,
    "ask_only_above_fair": True,
    "ask_min_position": 20,
}

_tibo_v29_vev5000_with_ask = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v29_vev5000_with_ask["VEV_5000"] = ProductConfig(
    symbol="VEV_5000",
    strategy="gamma_scalp_with_ask_v40",
    position_limit=300,
    params=_V29_VEV5000_WITH_ASK,
)
MEMBER_OVERRIDES["tibo_velvet_v29_vev5000_with_ask"] = {3: _tibo_v29_vev5000_with_ask}

_V29_VEV5000_SMILE_ASK = {
    **_V29_VEV5000_WITH_ASK,
    "target_qty": 280,
    "fair_vol_mode": "smile_iv",
    "fair_vol_scale": 1.0,
}

_tibo_v29_vev5000_smile_ask = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v29_vev5000_smile_ask["VEV_5000"] = ProductConfig(
    symbol="VEV_5000",
    strategy="gamma_scalp_with_ask_v40",
    position_limit=300,
    params=_V29_VEV5000_SMILE_ASK,
)
MEMBER_OVERRIDES["tibo_velvet_v29_vev5000_smile_ask"] = {3: _tibo_v29_vev5000_smile_ask}

_V29_VEV5000_SMILE_MM = dict(
    implied_vol_prior=0.0125,
    fair_vol_mode="smile_iv",
    base_size=15,
    bid_size_mult=1.5,
    inventory_skew_ticks=0,
    min_spread_to_quote=2,
    min_quote_price=2.0,
    taker_buy_edge=0.0,
    taker_sell_edge=0.0,
    max_taker_size=10,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    tte_days_initial=5.0,
    timestamp_units_per_day=1_000_000,
    ts_increment=100,
    last_ts_value=999900,
    log_flush_ts=1000,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    sigma_floor=0.005,
    sigma_cap=0.10,
    prior_vol=0.0125,
    smile_degree=2,
    smile_min_points=4,
    active_base_count=6,
    active_max_extra_count=2,
    active_expand_every=120.0,
    active_reference_spot=5250.0,
    strike=5000,
)

_tibo_v29_vev5000_smile_mm = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v29_vev5000_smile_mm["VEV_5000"] = ProductConfig(
    symbol="VEV_5000",
    strategy="symmetric_option_mm_v40",
    position_limit=300,
    params=_V29_VEV5000_SMILE_MM,
)
MEMBER_OVERRIDES["tibo_velvet_v29_vev5000_smile_mm"] = {3: _tibo_v29_vev5000_smile_mm}

_V29_VEV5400_SMILE_VALUE = {
    **_THEO_V7_VEV_BASE,
    "strike": 5400,
    "skip_when_expensive": False,
    "target_qty": 220,
    "entry_size": 20,
    "passive_bid_size": 18,
    "edge_ticks": -2.0,
    "fair_vol_mode": "smile_iv",
    "sell_when_very_expensive": True,
    "zscore_sell_threshold": 1.2,
    "sell_size_pct": 0.12,
}

_tibo_v29_vev5400_smile_value = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v29_vev5400_smile_value["VEV_5400"] = ProductConfig(
    symbol="VEV_5400",
    strategy="gamma_scalp_v28",
    position_limit=300,
    params=_V29_VEV5400_SMILE_VALUE,
)
MEMBER_OVERRIDES["tibo_velvet_v29_vev5400_smile_value"] = {3: _tibo_v29_vev5400_smile_value}

_V29_VEV4000_SYM_MM = {
    "implied_vol_prior": 0.0125,
    "fair_vol_mode": "fixed",
    "base_size": 18,
    "bid_size_mult": 1.0,
    "inventory_skew_ticks": 1,
    "min_spread_to_quote": 4,
    "min_quote_price": 2.0,
    "taker_buy_edge": 0.0,
    "taker_sell_edge": 0.0,
    "max_taker_size": 10,
    "underlying_symbol": "VELVETFRUIT_EXTRACT",
    "tte_days_initial": 5.0,
    "timestamp_units_per_day": 1_000_000,
    "ts_increment": 100,
    "last_ts_value": 999900,
    "log_flush_ts": 1000,
    "historical_tte_by_day": {0: 8.0, 1: 7.0, 2: 6.0},
    "sigma_floor": 0.005,
    "sigma_cap": 0.10,
    "prior_vol": 0.0125,
    "smile_degree": 2,
    "smile_min_points": 4,
    "active_base_count": 6,
    "active_max_extra_count": 2,
    "active_expand_every": 120.0,
    "active_reference_spot": 5250.0,
    "strike": 4000,
}

_tibo_v29_vev4000_sym_mm = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v29_vev4000_sym_mm["VEV_4000"] = ProductConfig(
    symbol="VEV_4000",
    strategy="symmetric_option_mm_v40",
    position_limit=300,
    params=_V29_VEV4000_SYM_MM,
)
MEMBER_OVERRIDES["tibo_velvet_v29_vev4000_sym_mm"] = {3: _tibo_v29_vev4000_sym_mm}


# ══════════════════════════════════════════════════════════════════════════════
#  v40+: True 2-sided market making experiments
#  Base: tibo_velvet_v28 (VELVETFRUIT unchanged in all v40 variants)
#
#  Spread analysis (3-day historical):
#    VEV_4000: avg 21 ticks  VEV_4500: avg 16  VEV_5000: avg 6
#    VEV_5100: avg 4-5       VEV_5200: avg 3   VEV_5300: avg 2
#    VEV_5400/5500: avg 1    (too tight to MM)
#
#  Experiments:
#    v40  — SymmetricOptionMM (pure 2-sided, fixed sigma=0.0125) for 5000+5100
#    v41  — GammaScalpWithAsk (accumulate bias + passive ask) for 5000+5100
#    v42  — SymmetricOptionMM with smile_iv for 5100 (best fair value)
#    v43  — ask_adapt mode (VEVOptionMMV3 with zscore_exec_mode=ask_adapt) for 5200+5300
#    v44  — Best combo across v40-v43
# ══════════════════════════════════════════════════════════════════════════════

_V40_SYM_MM_BASE = dict(
    implied_vol_prior=0.0125,
    fair_vol_mode="fixed",
    base_size=15,
    bid_size_mult=1.0,       # symmetric (1.0) — can set >1 for long bias
    inventory_skew_ticks=0,
    min_spread_to_quote=2,
    min_quote_price=2.0,
    taker_buy_edge=0.0,      # no taker: too aggressive per live lesson
    taker_sell_edge=0.0,
    max_taker_size=10,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    tte_days_initial=5.0,
    timestamp_units_per_day=1_000_000,
    ts_increment=100,
    last_ts_value=999900,
    log_flush_ts=1000,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    sigma_floor=0.005,
    sigma_cap=0.10,
    prior_vol=0.0125,
    smile_degree=2,
    smile_min_points=4,
    active_base_count=6,
    active_max_extra_count=2,
    active_expand_every=120.0,
    active_reference_spot=5250.0,
)

# v40: SymmetricOptionMM (neutral, fixed sigma) for VEV_5000 and VEV_5100
_tibo_v40 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v40["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="symmetric_option_mm_v40", position_limit=300,
    params={**_V40_SYM_MM_BASE, "strike": 5000, "base_size": 15, "bid_size_mult": 1.0})
_tibo_v40["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="symmetric_option_mm_v40", position_limit=300,
    params={**_V40_SYM_MM_BASE, "strike": 5100, "base_size": 12, "bid_size_mult": 1.0})
MEMBER_OVERRIDES["tibo_velvet_v40"] = {3: _tibo_v40}

# v40b: SymmetricOptionMM long-biased (bid 2x ask) for VEV_5000/5100
_tibo_v40b = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v40b["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="symmetric_option_mm_v40", position_limit=300,
    params={**_V40_SYM_MM_BASE, "strike": 5000, "base_size": 12, "bid_size_mult": 2.0})
_tibo_v40b["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="symmetric_option_mm_v40", position_limit=300,
    params={**_V40_SYM_MM_BASE, "strike": 5100, "base_size": 12, "bid_size_mult": 2.0})
MEMBER_OVERRIDES["tibo_velvet_v40b"] = {3: _tibo_v40b}

# v41: GammaScalpWithAsk for VEV_5000 (accumulate + small passive ask)
_tibo_v41 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v41["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, "strike": 5000, "skip_when_expensive": False,
            "passive_ask_size": 5, "ask_only_above_fair": True, "ask_min_position": 20})
MEMBER_OVERRIDES["tibo_velvet_v41"] = {3: _tibo_v41}

# v41b: GammaScalpWithAsk for VEV_5100 too
_tibo_v41b = dict(MEMBER_OVERRIDES["tibo_velvet_v41"][3])
_tibo_v41b["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, "strike": 5100,
            "zscore_skip_threshold": 0.5,
            "passive_ask_size": 5, "ask_only_above_fair": True, "ask_min_position": 20})
MEMBER_OVERRIDES["tibo_velvet_v41b"] = {3: _tibo_v41b}

# v41c: GammaScalpWithAsk bigger ask size (8) for VEV_5000+5100
_tibo_v41c = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v41c["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, "strike": 5000, "skip_when_expensive": False,
            "passive_ask_size": 8, "ask_only_above_fair": True, "ask_min_position": 20})
_tibo_v41c["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, "strike": 5100,
            "zscore_skip_threshold": 0.5,
            "passive_ask_size": 8, "ask_only_above_fair": True, "ask_min_position": 20})
MEMBER_OVERRIDES["tibo_velvet_v41c"] = {3: _tibo_v41c}

# v42: SymmetricOptionMM with smile_iv for VEV_5100 (LOO smile fair value)
_tibo_v42 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v42["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="symmetric_option_mm_v40", position_limit=300,
    params={**_V40_SYM_MM_BASE, "strike": 5100, "base_size": 12,
            "fair_vol_mode": "smile_iv", "bid_size_mult": 1.5})
MEMBER_OVERRIDES["tibo_velvet_v42"] = {3: _tibo_v42}

# v42b: SymmetricOptionMM smile_iv for VEV_5000 and VEV_5100
_tibo_v42b = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v42b["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="symmetric_option_mm_v40", position_limit=300,
    params={**_V40_SYM_MM_BASE, "strike": 5000, "base_size": 15,
            "fair_vol_mode": "smile_iv", "bid_size_mult": 1.5})
_tibo_v42b["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="symmetric_option_mm_v40", position_limit=300,
    params={**_V40_SYM_MM_BASE, "strike": 5100, "base_size": 12,
            "fair_vol_mode": "smile_iv", "bid_size_mult": 1.5})
MEMBER_OVERRIDES["tibo_velvet_v42b"] = {3: _tibo_v42b}

# v43: VEV_5200/5300 with zscore ask-adapt (sell into VELVETFRUIT strength)
# Uses existing VEVOptionMMV3 with ask_adapt mode enabled
_tibo_v43 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v43["VEV_5200"] = ProductConfig(
    symbol="VEV_5200", strategy="velvet_strat_v28_opt", position_limit=300,
    params={**_VEV_OPT_V26_BASE, "strike": 5200.0,
            "maker_size_bid": 20, "maker_size_ask": 5,
            "zscore_exec_mode": "ask_adapt",   # enable z-score sell on expensive
            "zscore_threshold": 1.0})
_tibo_v43["VEV_5300"] = ProductConfig(
    symbol="VEV_5300", strategy="velvet_strat_v28_opt", position_limit=300,
    params={**_VEV_OPT_V26_BASE, "strike": 5300.0,
            "maker_size_bid": 20, "maker_size_ask": 5,
            "zscore_exec_mode": "ask_adapt",
            "zscore_threshold": 1.0})
MEMBER_OVERRIDES["tibo_velvet_v43"] = {3: _tibo_v43}

# v43b: tighter z threshold (0.5) for ask_adapt on VEV_5200/5300
_tibo_v43b = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v43b["VEV_5200"] = ProductConfig(
    symbol="VEV_5200", strategy="velvet_strat_v28_opt", position_limit=300,
    params={**_VEV_OPT_V26_BASE, "strike": 5200.0,
            "maker_size_bid": 20, "maker_size_ask": 10,
            "zscore_exec_mode": "ask_adapt",
            "zscore_threshold": 0.5})
_tibo_v43b["VEV_5300"] = ProductConfig(
    symbol="VEV_5300", strategy="velvet_strat_v28_opt", position_limit=300,
    params={**_VEV_OPT_V26_BASE, "strike": 5300.0,
            "maker_size_bid": 20, "maker_size_ask": 10,
            "zscore_exec_mode": "ask_adapt",
            "zscore_threshold": 0.5})
MEMBER_OVERRIDES["tibo_velvet_v43b"] = {3: _tibo_v43b}

# v44: GammaScalpWithAsk for VEV_4500 (wider spread = more spread income)
_tibo_v44 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v44["VEV_4500"] = ProductConfig(
    symbol="VEV_4500", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, "strike": 4500,
            "zscore_skip_threshold": 2.0,
            "passive_ask_size": 8, "ask_only_above_fair": True, "ask_min_position": 30})
MEMBER_OVERRIDES["tibo_velvet_v44"] = {3: _tibo_v44}


# ── tibo_velvet_v45+: taker-sell experiments ──────────────────────────────────
# Key insight from v40-v44: passive asks don't fill in realistic backtest.
# Only taker sells (at best_bid) fill reliably. Testing here:
#   v45  — taker sell on VEV_5100 (z>1.5, sell 10%)
#   v45b — z>1.0, sell 15%
#   v46  — taker sell on VEV_5000 (z>1.5)
#   v46b — taker sell on both 5000+5100
#   v47  — taker sell on VEV_4500 (wider spread = better spread ratio)
#   v48  — taker sell on 4500+5000+5100 (full sweep)

_TAKER_SELL_BASE = dict(
    taker_sell_enabled=True,
    taker_sell_zscore=1.5,
    taker_sell_size_pct=0.10,
    taker_sell_max_size=20,
    taker_sell_cooldown_ts=500,
)

_tibo_v45 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v45["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 5100,
            "zscore_skip_threshold": 0.5})
MEMBER_OVERRIDES["tibo_velvet_v45"] = {3: _tibo_v45}

_tibo_v45b = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v45b["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 5100,
            "zscore_skip_threshold": 0.5,
            "taker_sell_zscore": 1.0, "taker_sell_size_pct": 0.15})
MEMBER_OVERRIDES["tibo_velvet_v45b"] = {3: _tibo_v45b}

_tibo_v46 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v46["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 5000,
            "skip_when_expensive": False})
MEMBER_OVERRIDES["tibo_velvet_v46"] = {3: _tibo_v46}

_tibo_v46b = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v46b["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 5000,
            "skip_when_expensive": False})
_tibo_v46b["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 5100,
            "zscore_skip_threshold": 0.5})
MEMBER_OVERRIDES["tibo_velvet_v46b"] = {3: _tibo_v46b}

_tibo_v47 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v47["VEV_4500"] = ProductConfig(
    symbol="VEV_4500", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 4500,
            "zscore_skip_threshold": 2.0,
            "taker_sell_zscore": 2.0, "taker_sell_size_pct": 0.10,
            "taker_sell_max_size": 20})
MEMBER_OVERRIDES["tibo_velvet_v47"] = {3: _tibo_v47}

_tibo_v48 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v48["VEV_4500"] = ProductConfig(
    symbol="VEV_4500", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 4500,
            "zscore_skip_threshold": 2.0, "taker_sell_zscore": 2.0})
_tibo_v48["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 5000,
            "skip_when_expensive": False, "taker_sell_zscore": 1.5})
_tibo_v48["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 5100,
            "zscore_skip_threshold": 0.5, "taker_sell_zscore": 1.5})
MEMBER_OVERRIDES["tibo_velvet_v48"] = {3: _tibo_v48}


# ══════════════════════════════════════════════════════════════════════════════
#  v30: four targeted ideas not tested in v29/v40-v48
#  Base: tibo_velvet_v29. Each config swaps exactly ONE option vs v29.
# ══════════════════════════════════════════════════════════════════════════════

# Shared smile params (added to _THEO_V7_VEV_BASE for smile_iv mode)
_V30_SMILE_EXTRA = dict(
    smile_degree=2,
    smile_min_points=4,
    active_base_count=6,
    active_max_extra_count=2,
    active_expand_every=120.0,
    active_reference_spot=5250.0,
)

# ── Idea 1: VEV_4500 — smile-calibrated GammaScalp ────────────────────────
# Previous: GammaScalp skip=True, thresh=2.0, fixed sigma=0.0125 → 18,802
# Change: fair_vol_mode="smile_iv". For K=4500 (slightly ITM), smile typically
# predicts higher IV than 0.0125 → fair price higher → taker buys more active.
_tibo_v30_4500_smile = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v30_4500_smile["VEV_4500"] = ProductConfig(
    symbol="VEV_4500",
    strategy="gamma_scalp_smile_v30_vev4500",
    position_limit=300,
    params={
        **_THEO_V7_VEV_BASE,
        **_V30_SMILE_EXTRA,
        "strike": 4500,
        "zscore_skip_threshold": 2.0,
        "fair_vol_mode": "smile_iv",
    },
)
MEMBER_OVERRIDES["tibo_velvet_v30_4500_smile"] = {3: _tibo_v30_4500_smile}

# ── Idea 2: VEV_5100 — gentle gamma + tiny passive ask ────────────────────
# Previous v42 (pure SymmetricOptionMM) lost -12.9k — abandoned accumulation bias.
# This keeps full GammaScalp accumulation and adds a tiny passive ask (size=4)
# only when position >= 80 AND market ask > BS fair.
_tibo_v30_5100_ask = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v30_5100_ask["VEV_5100"] = ProductConfig(
    symbol="VEV_5100",
    strategy="gamma_scalp_with_ask_v30_vev5100",
    position_limit=300,
    params={
        **_THEO_V7_VEV_BASE,
        "strike": 5100,
        "zscore_skip_threshold": 0.5,
        "passive_ask_size": 4,
        "ask_min_position": 80,
        "ask_only_above_fair": True,
        "taker_sell_enabled": False,
    },
)
MEMBER_OVERRIDES["tibo_velvet_v30_5100_ask"] = {3: _tibo_v30_5100_ask}

# ── Idea 3: VEV_5200 — smile-calibrated accumulator ──────────────────────
# Previous: VEVOptionMMV28 (passive bid-heavy, no fair value) → 11,882
# Change: GammaScalp with smile_iv, skip=False, edge_ticks=3 so the taker
# fires when market ask is still below smile-fair + 3 ticks. Passive bid kept.
_tibo_v30_5200_smile = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v30_5200_smile["VEV_5200"] = ProductConfig(
    symbol="VEV_5200",
    strategy="gamma_scalp_smile_v30_vev5200",
    position_limit=300,
    params={
        **_THEO_V7_VEV_BASE,
        **_V30_SMILE_EXTRA,
        "strike": 5200,
        "skip_when_expensive": False,
        "fair_vol_mode": "smile_iv",
        "edge_ticks": 3.0,
        "entry_size": 20,
        "passive_bid_size": 20,
    },
)
MEMBER_OVERRIDES["tibo_velvet_v30_5200_smile"] = {3: _tibo_v30_5200_smile}

# ── Idea 4: VEV_4000 — delta-one MM using VELVETFRUIT microprice ──────────
# Previous v29_vev4000_sym_mm used generic SymmetricOptionMM (2-sided, bad).
# DeltaOneMMV30 uses VELVETFRUIT top-of-book microprice for fair value and
# scales passive bid size by order book imbalance (bid-heavy → bigger bid).
_tibo_v30_4000_delta1 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v30_4000_delta1["VEV_4000"] = ProductConfig(
    symbol="VEV_4000",
    strategy="delta_one_mm_v30",
    position_limit=300,
    params={
        "strike": 4000,
        "implied_vol_prior": 0.0125,
        "target_qty": 300,
        "entry_size": 30,
        "passive_bid_size": 24,
        "edge_ticks": 0.0,
        "unwind_tte_threshold": 1.5,
        "min_quote_price": 2.0,
        "imbalance_bid_boost": 1.8,
        "imbalance_bid_reduce": 0.4,
        "imbalance_tick_threshold": 0.3,
        "underlying_symbol": "VELVETFRUIT_EXTRACT",
        "tte_days_initial": 5.0,
        "historical_tte_by_day": {0: 8.0, 1: 7.0, 2: 6.0},
        "timestamp_units_per_day": 1_000_000,
        "ts_increment": 100,
        "last_ts_value": 999900,
        "log_flush_ts": 1000,
        "sigma_floor": 0.005,
        "sigma_cap": 0.10,
        "prior_vol": 0.0125,
        "smile_degree": 2,
        "smile_min_points": 4,
    },
)
MEMBER_OVERRIDES["tibo_velvet_v30_4000_delta1"] = {3: _tibo_v30_4000_delta1}


# ── Theo's HYDROGEL strategy (r3_hydro_v7b_guarded_loose) ─────────────────────
# Ported from Theo's self-contained submission file.
# Uses R3GuardedAnchorMMStrategy (same class as VELVETFRUIT) with:
#   - anchor_price=10000   (HYDROGEL mean-reverts to 10000)
#   - looser guard (reversion_threshold=3.0 vs 7.5 for VELVET)
#   - tighter take edges (lo=0.3, hi=0.8 vs lo=0.6, hi=1.2 for VELVET)
#   - smaller ar_gain=0.2 (vs 0.3 for VELVET)

_HYDRO_V7B_PARAMS = dict(
    anchor_alpha=0.02,
    anchor_drift_bound=1.5,
    anchor_price=10000.0,
    ar_gain=0.2,
    ar_shift_source="mid_smooth",
    full_capacity_on_empty=True,
    guard_inventory_dist=40.0,
    guard_max_dist=80.0,
    guard_min_dist=0.0,
    guard_near_band=0.0,
    guard_reversion_threshold=3.0,
    guard_trend_alpha=0.45,
    inventory_aversion_gamma=0.001,
    last_ts_value=999900,
    log_flush_ts=1000,
    maker_size=30,
    maker_size_base_pct=0.15,    # 30/200 — matches maker_size intent
    passive_unwind_skew_ticks=1,
    passive_unwind_trigger=0.38,
    pct_kept_for_takers=0.005,
    take_edge_hi=0.8,
    take_edge_lo=0.3,
    tighten_ticks=1,
    toxic_size_frac=0.68,
    toxic_threshold=0.6,
    toxic_window=8,
    ts_increment=100,
    unwind_take_edge=3.0,
)

# Standalone HYDROGEL-only config (useful for single-product backtest)
MEMBER_OVERRIDES["hydro_v7b"] = {
    3: {
        "HYDROGEL_PACK": ProductConfig(
            symbol="HYDROGEL_PACK", strategy="r3_guarded_anchor_mm",
            position_limit=200, params=_HYDRO_V7B_PARAMS),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None, "VEV_4500": None, "VEV_5000": None, "VEV_5100": None,
        "VEV_5200": None, "VEV_5300": None, "VEV_5400": None, "VEV_5500": None,
        "VEV_6000": None, "VEV_6500": None,
    }
}

# Combined: tibo's v29 (VELVETFRUIT + VEV options) + Theo's hydro v7b (HYDROGEL)
_tibo_v29_plus_hydro = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v29_plus_hydro["HYDROGEL_PACK"] = ProductConfig(
    symbol="HYDROGEL_PACK", strategy="r3_guarded_anchor_mm",
    position_limit=200, params=_HYDRO_V7B_PARAMS)
MEMBER_OVERRIDES["tibo_v29_plus_hydro"] = {3: _tibo_v29_plus_hydro}


# ── v100: canonical standalone configs — no intermediate wrapper chain ────────
# Strategy keys map directly onto the canonical implementation classes:
#   velvet_mm_v100      → VelvetMMV100(R3GuardedAnchorMMStrategy)
#   gamma_scalp_v100    → GammaScalpV100(GammaScalpZGatedMixinStrategy)
#   vev_option_mm_v100  → VEVOptionMMV100(VEVOptionMMV3)
#   hydro_mm_v100       → HydroMMV100(R3GuardedAnchorMMStrategy)
# Params are identical to tibo_velvet_v29 / hydro_v7b — pure refactor.

MEMBER_OVERRIDES["tibo_velvet_v100"] = {
    3: {
        "HYDROGEL_PACK": None,

        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT", strategy="velvet_mm_v100",
            position_limit=200, params=_THEO_V7_VELVET_PARAMS),

        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="gamma_scalp_v100",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4000,
                "zscore_skip_threshold": 1.5}),

        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="gamma_scalp_v100",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4500,
                "zscore_skip_threshold": 2.0}),

        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="gamma_scalp_v100",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5000,
                "skip_when_expensive": False}),

        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="gamma_scalp_v100",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5100,
                "zscore_skip_threshold": 0.5}),

        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="vev_option_mm_v100",
            position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5200.0,
                    "maker_size_bid": 20, "maker_size_ask": 5}),

        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="gamma_scalp_v100",
            position_limit=300,
            params={**_THEO_V7_VEV_BASE, **_V29_IV_GATE_BASE, "strike": 5300,
                    "skip_when_expensive": False}),

        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="vev_option_mm_v100",
            position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5400.0,
                    "maker_size_bid": 20, "maker_size_ask": 5,
                    "prevent_crossing": True}),

        "VEV_5500": ProductConfig(symbol="VEV_5500", strategy="gamma_scalp_v100",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5500,
                "zscore_skip_threshold": 0.5}),

        "VEV_6000": None, "VEV_6500": None,
    },
}

MEMBER_OVERRIDES["hydro_v100"] = {
    3: {
        "HYDROGEL_PACK": ProductConfig(
            symbol="HYDROGEL_PACK", strategy="hydro_mm_v100",
            position_limit=200, params=_HYDRO_V7B_PARAMS),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None, "VEV_4500": None, "VEV_5000": None, "VEV_5100": None,
        "VEV_5200": None, "VEV_5300": None, "VEV_5400": None, "VEV_5500": None,
        "VEV_6000": None, "VEV_6500": None,
    }
}

MEMBER_OVERRIDES["hydro_v200"] = {
    3: {
        "HYDROGEL_PACK": ProductConfig(
            symbol="HYDROGEL_PACK", strategy="hydro_mm_v200",
            position_limit=200, params=_HYDRO_V7B_PARAMS),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None, "VEV_4500": None, "VEV_5000": None, "VEV_5100": None,
        "VEV_5200": None, "VEV_5300": None, "VEV_5400": None, "VEV_5500": None,
        "VEV_6000": None, "VEV_6500": None,
    }
}

MEMBER_OVERRIDES["hydro_v200_r4"] = {
    3: {
        "HYDROGEL_PACK": ProductConfig(
            symbol="HYDROGEL_PACK", strategy="hydro_mm_v200_r4",
            position_limit=200, params=_HYDRO_V7B_PARAMS),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None, "VEV_4500": None, "VEV_5000": None, "VEV_5100": None,
        "VEV_5200": None, "VEV_5300": None, "VEV_5400": None, "VEV_5500": None,
        "VEV_6000": None, "VEV_6500": None,
    }
}

# ── Hydro MV strategies (directional mean-reversion + passive MM) ────────────
# v4_best: AR directional MR, 22,060 PnL (beats spread-paying taker baseline)
# v5_best: Passive MM + selective AR taker, 153,117 PnL (34% above v201 MM)

# BEST v4: AR directional MR — 22,060 PnL, DD 3,751 (3-day realistic).
# Signal: deviation of smoothed mid from AR fair value. M14 scale mode amplifies size.
# Only beneficial feature from ablation: dev_size_scale (larger dev → bigger position).
MEMBER_OVERRIDES["hydro_mv_v4_best"] = {
    4: {"HYDROGEL_PACK": ProductConfig(
        symbol="HYDROGEL_PACK", strategy="hydro_mv_v4",
        position_limit=200,
        params={
            "anchor_price":           10000.0,
            "anchor_alpha":           0.02,
            "anchor_drift_bound":     1.5,
            "ar_gain":                8.0,
            "ar_smooth_half_life":    5,
            "mid_smooth_half_life":   20,
            "dev_smooth_half_life":   5,
            "entry_threshold":        20.0,
            "exit_threshold":         2.0,
            "entry_size":             20,
            "informed_trader_name":   "Mark 14",
            "mark14_mode":            "scale",
            "m14_agree_factor":       3.0,
            "m14_lookback_ticks":     20,
            "trend_guard_threshold":  0.0,
            "stop_loss_mult":         0.0,
            "toxic_flow_threshold":   0.0,
            "dev_size_scale":         2.0,
            "dev_size_max_mult":      5.0,
            "vol_thresh_scale":       0.0,
            "last_ts_value":          999900,
            "log_flush_ts":           1000,
            "ts_increment":           100,
        })}
}

# BEST v5: Passive MM + selective AR taker — 153,117 PnL, DD 20,086 (3-day realistic).
# 34% above v201 (114,350 PnL). Core insight: passive quoting earns the spread;
# high ar_taker_edge (12) fires selectively → balanced position → more passive fill room.
MEMBER_OVERRIDES["hydro_mv_v5_best"] = {
    4: {"HYDROGEL_PACK": ProductConfig(
        symbol="HYDROGEL_PACK", strategy="hydro_mv_v5",
        position_limit=200,
        params={
            # AR model
            "anchor_price":             10000,
            "anchor_alpha":             0.02,
            "anchor_drift_bound":       1.5,
            "ar_gain":                  8.0,
            "ar_smooth_half_life":      5,
            "mid_smooth_half_life":     20,
            "dev_smooth_half_life":     5,
            # Passive MM
            "passive_quoting":          True,
            "maker_size_base_pct":      0.25,   # 50 units base per side
            "pct_kept_for_takers":      0.2,
            "use_inventory_bias":       True,
            # AR taker (selective: only fires when deviation > 12 ticks from fair)
            "use_ar_taker":             True,
            "ar_taker_edge":            12.0,
            "ar_taker_size_pct":        0.3,
            # All other features off
            "use_gap_exploit":          False,
            "use_m14_gate":             False,
            "use_ar_quote_bias":        False,
            "use_anchor_guard":         False,
            "informed_trader_name":     "Mark 14",
            "last_ts_value":            999900,
            "log_flush_ts":             1000,
            "diag_enabled":             True,
        })}
}

# ─────────────────────────────────────────────────────────────────────────────
# mv_v6: Dynamic anchor — inv_protected mode
# Anchor only updates when |position| < pos_threshold × limit (flat or light).
# Once we're heavily positioned the anchor freezes, preventing fair_value from
# drifting further in the wrong direction and amplifying the taker signal.
# quote_trace_enabled=True: full per-tick log of FairValue/Anchor/DevSmooth/etc,
# flushed every log_flush_ts ticks so the visualizer sees dense data.
# ─────────────────────────────────────────────────────────────────────────────
_V6_BASE_PARAMS = {
    "anchor_price":          10000,
    "anchor_alpha":          0.02,      # overridden per variant
    "anchor_drift_bound":    1.5,       # only used by "fixed" mode
    "ar_gain":               8.0,
    "ar_smooth_half_life":   5,
    "mid_smooth_half_life":  20,
    "dev_smooth_half_life":  5,
    "passive_quoting":       True,
    "maker_size_base_pct":   0.25,
    "pct_kept_for_takers":   0.2,
    "use_inventory_bias":    True,
    "use_ar_taker":          True,
    "ar_taker_edge":         12.0,
    "ar_taker_size_pct":     0.3,
    "use_gap_exploit":       False,
    "use_m14_gate":          False,
    "use_ar_quote_bias":     False,
    "use_anchor_guard":      False,
    "informed_trader_name":  "Mark 14",
    "last_ts_value":         999900,
    "quote_trace_enabled":   True,   # per-tick buffer, flushed every log_flush_ts
    "log_flush_ts":          1000,   # flush ~100 rows per chunk (10 ticks × 100 chunks)
}

def _v6(anchor_mode: str, **extra) -> ProductConfig:
    return ProductConfig(
        symbol="HYDROGEL_PACK", strategy="hydro_mv_v6", position_limit=200,
        params={**_V6_BASE_PARAMS, "anchor_mode": anchor_mode, **extra},
    )

# v6a: best backtest — pos_threshold=30% (60u), alpha=0.007 → 179,172 PnL, DD=20,136
MEMBER_OVERRIDES["hydro_mv_v6a"] = {
    4: {"HYDROGEL_PACK": _v6("inv_protected", anchor_pos_threshold=0.30, anchor_alpha=0.007)}
}
# v6b: conservative — pos_threshold=20% (40u), alpha=0.005 → 178,785 PnL, DD=20,130
MEMBER_OVERRIDES["hydro_mv_v6b"] = {
    4: {"HYDROGEL_PACK": _v6("inv_protected", anchor_pos_threshold=0.20, anchor_alpha=0.005)}
}

# ─────────────────────────────────────────────────────────────────────────────
# mv_v7 — two-component passive MM
#
# Fix for v6 live failure: AR taker built runaway -200 short when price trended
# up for hours. V7 splits inventory into two components:
#   Anchor (40% = 80u): AR taker fires only when |pos| < 80. Same inv_protected
#     anchor as v6b (alpha=0.005, freeze when |pos| >= 20% × 200).
#   MM (remainder): always posts best_bid+1 / best_ask-1, inventory-adaptive
#     sizing — reducing side gets more size, so position self-limits.
#
# 3-day backtest: 104,602 PnL | 9,067 abs DD | 25.3% | PnL/DD=11.5
# vs v6b:         178,785 PnL | 20,130 abs DD | 88.9% | PnL/DD=8.9
# ─────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["hydro_mv_v7"] = {
    4: {"HYDROGEL_PACK": ProductConfig(
        symbol="HYDROGEL_PACK", strategy="hydro_mv_v7", position_limit=200,
        params=dict(
            anchor_price=10000,
            anchor_alpha=0.005,
            anchor_pos_threshold=0.20,
            ar_gain=8.0,
            ar_smooth_half_life=5,
            mid_smooth_half_life=20,
            dev_smooth_half_life=5,
            ar_taker_edge=15.0,
            ar_taker_size_pct=0.30,
            anchor_reserve_pct=0.40,
            mm_mode="bestquote",
            mm_base_size=20,
            fast_mid_half_life=5,
            mm_spread=1,
            last_ts_value=999900,
            quote_trace_enabled=True,
            log_flush_ts=1000,
        ),
    )}
}

# ─────────────────────────────────────────────────────────────────────────────
# mv_v10 — active MM with hard inventory cap + vol gate (starting from v6b)
#
# Root cause confirmed (v9 live):
#   - m14_cum=-4260 → gate never fired. Position hit -200 by ts=10k.
#   - Passive MM asks filled continuously (ask_size only =0 at position=-200).
#
# Fixes:
#   1. Hard MM cap: stop ALL asks when position <= -mm_cap (25% = 50u).
#   2. Separate AR taker cap: stop AR sells when position <= -ar_cap (40% = 80u).
#   3. Vol gate: when realized vol >= threshold (3.0), stop all adds to position.
#
# 3-day backtest: 117,246 PnL | 16,540 DD | 14.1% | PnL/DD=7.1  (66% of v6b)
# Day 1 alone:    42,908 PnL  (74% of v6b day1) — max short: -129u
# Root causes fixed:
#   1. Unified hysteresis: stop=0.70 (-140u), restart=0.30 (-60u).
#      MM ask + AR taker both stop at -140u. Only restart when pos > -60u.
#      Prevents the MM-bid/AR-taker "fight" (buying at 10027, selling at 10025).
#   2. Inventory skew: bid raised by floor(4 × |pos/limit|) ticks when short.
#      Makes passive bids more competitive during recovery.
#   v9 live (position → -187 in seconds): v10 caps at -140u (hysteresis).
#   Max live loss: 140 × 50 ticks = 7,000 (vs 200 × 50 = 10,000 in v9).
# ─────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["hydro_mv_v10"] = {
    4: {"HYDROGEL_PACK": ProductConfig(
        symbol="HYDROGEL_PACK", strategy="hydro_mv_v10", position_limit=200,
        params=dict(
            anchor_price=10000,
            anchor_alpha=0.005,
            anchor_pos_threshold=0.20,
            ar_gain=8.0,
            ar_smooth_half_life=5,
            mid_smooth_half_life=20,
            dev_smooth_half_life=5,
            ar_taker_edge=12.0,
            ar_taker_size_pct=0.30,
            sell_stop_pct=0.70,         # ALL selling stops at -140u (70% of 200)
            sell_restart_pct=0.30,      # restarts only when position > -60u (80u gap)
            buy_stop_pct=0.70,          # symmetric for long side
            buy_restart_pct=0.30,
            maker_size_base_pct=0.15,
            inv_skew_ticks=4,           # raise bid 4 ticks per |pos/limit| when short
            vol_half_life=20,
            vol_threshold=3.5,
            m14_trader="Mark 14",
            m38_trader="Mark 38",
            m14_bullish_threshold=75,   # M14 gate
            m38_weight=0.0,
            last_ts_value=999900,
            quote_trace_enabled=True,
            log_flush_ts=1000,
        ),
    )}
}

# ─────────────────────────────────────────────────────────────────────────────
# mv_v9 — v6b + hard cap ALL orders + M14 cumulative gate + inv skew
#
# Starting from v6b (178,785 PnL). Two confirmed live failures fixed:
#   1. Hard cap ALL sells (taker + MM ask) when pos <= -sell_cap_pct × limit.
#      v8 bug: hard cap blocked only AR taker; MM asks kept filling as Mark 14
#      lifted them → position went to -105 despite sell_ok=0.
#   2. M14 cumulative gate: track M14 net buys since day start. When M14 has
#      bought > bullish_threshold units net, suppress ALL selling (confirmed
#      uptrend signal). In v8 live, M14 bought +75 units total — early gate
#      fire at +40 would have capped position near -50 vs actual -105.
#
# 3-day backtest: 169,512 PnL | 19,662 abs DD | 11.6% | PnL/DD=8.6 (94.8% of v6b)
# M14 gate fires when m14_cum >= 75 (v8 live: M14 bought 75 exactly → gate fires).
# ─────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["hydro_mv_v13"] = {
    # Dual gate: v9 M14-HYDRO cumulative + v12 VEV_4000 hedge signal
    4: {"HYDROGEL_PACK": ProductConfig(
        symbol="HYDROGEL_PACK", strategy="hydro_mv_v13", position_limit=200,
        params=dict(
            anchor_price=10000, anchor_alpha=0.005, anchor_pos_threshold=0.30,
            ar_gain=8.0, ar_smooth_half_life=5, mid_smooth_half_life=20,
            dev_smooth_half_life=5, ar_taker_edge=12.0, ar_taker_size_pct=0.30,
            sell_cap_pct=1.0, buy_cap_pct=1.0,
            maker_size_base_pct=0.12, inv_skew_ticks=4,
            # Gate 1: M14 HYDROGEL cumulative (v9 gate)
            m14_trader="Mark 14",
            m14_hydro_threshold=75.0,
            # Gate 2: M14 VEV_4000 cross-asset hedge (v12 gate)
            vev_gate_product="VEV_4000",
            vev_gate_trader="Mark 14",
            vev_gate_hl=100.0,
            vev_gate_threshold=5.0,
            last_ts_value=999900, quote_trace_enabled=True, log_flush_ts=1000,
        ),
    )}
}
MEMBER_OVERRIDES["hydro_mv_v9"] = {
    4: {"HYDROGEL_PACK": ProductConfig(
        symbol="HYDROGEL_PACK", strategy="hydro_mv_v9", position_limit=200,
        params=dict(
            anchor_price=10000,
            anchor_alpha=0.005,
            anchor_pos_threshold=0.30,   # grid winner: anchor updates when |pos| < 60u (+14k vs 0.20)
            ar_gain=8.0,
            ar_smooth_half_life=5,
            mid_smooth_half_life=20,
            dev_smooth_half_life=5,
            ar_taker_edge=12.0,
            ar_taker_size_pct=0.30,
            sell_cap_pct=1.0,           # no hard cap — M14 gate is primary protection
            buy_cap_pct=1.0,            # symmetric (rarely needed)
            maker_size_base_pct=0.12,   # grid winner: 12% × 200 = 24u per side
            inv_skew_ticks=4,
            m14_trader="Mark 14",
            m38_trader="Mark 38",
            m14_bullish_threshold=75,   # gate fires when M14 net >= 75u (catches v8 live scenario exactly)
            m14_bearish_threshold=75,
            m38_weight=0.0,             # M14 only; set >0 to add M38 contribution
            last_ts_value=999900,
            quote_trace_enabled=True,
            log_flush_ts=1000,
        ),
    )}
}

# ─────────────────────────────────────────────────────────────────────────────
# mv_v8 — hysteresis + inventory-skewed MM
#
# Root cause of v7 live failure: zero hysteresis on anchor_limit=80.
# MM buys 6u → AR taker immediately re-sells 6u. Position stuck at -80 for 53%
# of session, paying spread both ways. Final pos: -91. PnL: 1,307.
#
# v8 fixes:
#   1. Hysteresis: stop selling when |pos| >= stop_pct×limit (80u=40%),
#      restart only when |pos| < start_pct×limit (76u=38%). 4u gap.
#   2. Cooldown: after any taker fire, blocks re-fire for 20 ticks (2s).
#      Prevents the 1-tick fight: MM buys 6u → taker re-sells 6u next tick.
#   3. Inventory skew: when short, raise bid by floor(4 × |pos/limit|) ticks
#      above best_bid+1. Modest improvement in recovery fill rate.
#
# 3-day backtest: 97,692 PnL | 10,158 abs DD | 10.4% | PnL/DD=9.6
# vs v7:          104,602 PnL |  9,067 abs DD |  8.7% | PnL/DD=11.5  (-6.6%)
# vs v6b:         178,785 PnL | 20,130 abs DD | 88.9% | PnL/DD=8.9
#
# Live (v7b): stuck at pos -80 for 53% of session, profit 1,307.
# Live (v8 expected): 2s breathing room between taker fires + 4u hysteresis
#   gap breaks the MM-vs-taker fight. Position should oscillate less tightly.
# ─────────────────────────────────────────────────────────────────────────────
MEMBER_OVERRIDES["hydro_mv_v8"] = {
    4: {"HYDROGEL_PACK": ProductConfig(
        symbol="HYDROGEL_PACK", strategy="hydro_mv_v8", position_limit=200,
        params=dict(
            anchor_price=10000,
            anchor_alpha=0.005,
            anchor_pos_threshold=0.20,
            ar_gain=8.0,
            ar_smooth_half_life=5,
            mid_smooth_half_life=20,
            dev_smooth_half_life=5,
            ar_taker_edge=15.0,
            ar_taker_size_pct=0.30,
            ar_taker_stop_pct=0.40,     # taker stops selling at -80u
            ar_taker_start_pct=0.38,    # restart only when pos > -76u (4u hysteresis gap)
            taker_cooldown_ticks=20,    # 2s min between consecutive fires
            mm_base_size=20,
            inv_skew_ticks=4,           # modest bid skew: floor(4 × |pos/limit|) ticks
            fast_mid_half_life=5,
            last_ts_value=999900,
            quote_trace_enabled=True,
            log_flush_ts=1000,
        ),
    )}
}

# ── mv_v1: z-score mean-reversion + Mark 14 gate ─────────────────────────────
MEMBER_OVERRIDES["hydro_mv_v1"] = {
    4: {
        "HYDROGEL_PACK": ProductConfig(
            symbol="HYDROGEL_PACK", strategy="hydro_mv_v1",
            position_limit=200,
            params=dict(
                # z-score signal
                zscore_window=50,
                mid_smooth_half_life=10,
                entry_z_threshold=2.0,
                exit_z_threshold=0.5,
                entry_size=20,
                # Mark 14 gate
                informed_trader_name="Mark 14",
                m14_lookback_ticks=10,
                m14_wait_ticks=10,
                # logging (quote_trace emitted to stdout in live; features via feature_prices() in backtest)
                quote_trace_enabled=True,
                last_ts_value=999900,
                log_flush_ts=1000,
                ts_increment=100,
            )),
    },
}

# ── v201: Mark 14 informed-trader gate (3 variants) ───────────────────────────
_HYDRO_V201_BASE_PARAMS = dict(
    **_HYDRO_V7B_PARAMS,
    informed_trader_name="Mark 14",
)

_HYDRO_V201_NONE_PRODS = {
    "VELVETFRUIT_EXTRACT": None,
    "VEV_4000": None, "VEV_4500": None, "VEV_5000": None, "VEV_5100": None,
    "VEV_5200": None, "VEV_5300": None, "VEV_5400": None, "VEV_5500": None,
    "VEV_6000": None, "VEV_6500": None,
}


# Variant 2: Influenced — suppress opposing, scale agreeing sizes ×2
MEMBER_OVERRIDES["hydro_v201_influenced"] = {
    3: {
        "HYDROGEL_PACK": ProductConfig(
            symbol="HYDROGEL_PACK", strategy="hydro_mm_v201_influenced",
            position_limit=200,
            params=dict(**_HYDRO_V201_BASE_PARAMS, mark14_agree_factor=2.0)),
        **_HYDRO_V201_NONE_PRODS,
    },
    4: {
        "HYDROGEL_PACK": ProductConfig(
            symbol="HYDROGEL_PACK", strategy="hydro_mm_v201_influenced",
            position_limit=200,
            params=dict(**_HYDRO_V201_BASE_PARAMS, mark14_agree_factor=2.0)),
    },
}

# Baseline v200 round 4 reference
MEMBER_OVERRIDES["hydro_v200_r4_ref"] = {
    4: {
        "HYDROGEL_PACK": ProductConfig(
            symbol="HYDROGEL_PACK", strategy="hydro_mm_v200_r4",
            position_limit=200, params=_HYDRO_V7B_PARAMS),
    }
}

_tibo_v100_full = dict(MEMBER_OVERRIDES["tibo_velvet_v100"][3])
_tibo_v100_full["HYDROGEL_PACK"] = ProductConfig(
    symbol="HYDROGEL_PACK", strategy="hydro_mm_v100",
    position_limit=200, params=_HYDRO_V7B_PARAMS)
MEMBER_OVERRIDES["tibo_v100_full"] = {3: _tibo_v100_full}

MEMBER_OVERRIDES["tibo_v200_full"] = {
    3: {
        "HYDROGEL_PACK": ProductConfig(
            symbol="HYDROGEL_PACK", strategy="hydro_mm_v200",
            position_limit=200, params=_HYDRO_V7B_PARAMS),

        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT", strategy="velvet_mm_v200",
            position_limit=200, params=_THEO_V7_VELVET_PARAMS),

        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="gamma_scalp_v200",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4000,
                "zscore_skip_threshold": 1.5}),

        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="gamma_scalp_v200",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4500,
                "zscore_skip_threshold": 2.0}),

        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="gamma_scalp_v200",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5000,
                "skip_when_expensive": False}),

        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="gamma_scalp_v200",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5100,
                "zscore_skip_threshold": 0.5}),

        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="gamma_scalp_v200",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5200,
                "zscore_skip_threshold": 2.0}),

        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="gamma_scalp_v200",
            position_limit=300,
            params={**_THEO_V7_VEV_BASE, **_V29_IV_GATE_BASE, "strike": 5300,
                    "skip_when_expensive": False}),

        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="gamma_scalp_v200",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5400,
                "zscore_skip_threshold": 1.0}),

        "VEV_5500": ProductConfig(symbol="VEV_5500", strategy="gamma_scalp_v200",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5500,
                "zscore_skip_threshold": 0.5}),

        "VEV_6000": None, "VEV_6500": None,
    }
}


# ══════════════════════════════════════════════════════════════════════════════
#  TIBO ROUND 3 — velvet_strat series
# ══════════════════════════════════════════════════════════════════════════════

# v1: pure passive MM on VELVETFRUIT_EXTRACT only
# Grid-tuned: maker_size_base_pct=0.30, pct_kept_for_takers=0.15 (+20,127 over 3 days)
MEMBER_OVERRIDES["tibo_velvet_v1"] = {
    3: {
        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT",
            strategy="velvet_strat",
            position_limit=200,
            params=dict(
                maker_size_base_pct=0.30,       # grid winner: 60 units base per side
                pct_kept_for_takers=0.15,       # hard stop at 85% of limit
                mid_smooth_window=50,
                mid_smooth_half_life=20,
                take_edge=999.0,                # takers off
                gap_trigger_min=0,              # gap exploit off
                gap_trigger_max_vol_pct=0.10,
                gap_trigger_confirm_ticks=2,
                OB_cleared_shift=10,
                ts_increment=100,
                last_ts_value=999900,
                log_flush_ts=1000,
            ),
        ),
    },
}


# ── v3: z-score signal-gated VEV option accumulation ─────────────────────────
# ask_adapt mode: tighten ask when VELVETFRUIT expensive, widen when cheap
# 3-day backtest: +48,922
_VEV_OPT_V3_BASE = dict(
    tte_days_initial=5.0,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    ticks_per_day=10000,
    ts_increment=100,
    timestamp_units_per_day=1_000_000,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    delta_sigma=0.022,
    min_quote_price=2.0,
    log_flush_ts=1000,
    last_ts_value=999900,
    zscore_window=500,
    zscore_threshold=1.0,
    zscore_bid_scale=2.0,
    zscore_bid_max=4.0,
    zscore_exec_mode="ask_adapt",
    ask_offset_neutral=10,
    ask_offset_sell=1,
)

_VELVET_V3_MM_PARAMS = dict(
    maker_size_base_pct=0.30,
    pct_kept_for_takers=0.15,
    mid_smooth_window=50,
    mid_smooth_half_life=20,
    use_delta_hedge=True,
    zscore_window=500,
    ts_increment=100,
    last_ts_value=999900,
    log_flush_ts=1000,
)

MEMBER_OVERRIDES["tibo_velvet_v3"] = {
    3: {
        "HYDROGEL_PACK": None,
        # VEV options run BEFORE VELVETFRUIT so delta is published first
        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="velvet_strat_v3_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 4000.0, "maker_size_bid": 20, "maker_size_ask": 20,
                    "ask_offset_neutral": 1, "ask_offset_sell": 1}),  # deep ITM: always symmetric
        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="velvet_strat_v3_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 5200.0, "maker_size_bid": 20, "maker_size_ask": 5}),
        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="velvet_strat_v3_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 5300.0, "maker_size_bid": 20, "maker_size_ask": 5}),
        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="velvet_strat_v3_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 5400.0, "maker_size_bid": 20, "maker_size_ask": 5,
                    "prevent_crossing": True}),  # 1-tick spread: stay passive
        "VEV_4500": None, "VEV_5000": None, "VEV_5100": None,
        "VEV_5500": None, "VEV_6000": None, "VEV_6500": None,
        # VELVETFRUIT MM runs LAST (reads vev_total_delta from shared)
        "VELVETFRUIT_EXTRACT": ProductConfig(symbol="VELVETFRUIT_EXTRACT", strategy="velvet_strat_v3_mm",
            position_limit=200, params=_VELVET_V3_MM_PARAMS),
    },
}


# ── tibo_velvet_v24: friend's merged strategy ─────────────────────────────────
# VELVETFRUIT: MMFirstV4ComboStrategy (anchor-price MM + AR shift + takers)
# VEV_4000:    OptionMMBSStrategy (symmetric BS-aware MM)
# VEV_4500/5000/5100/5200/5300: GammaScalpZGatedStrategy (z-gated long-call accumulation)
# VEV_5400:    OptionMMBSStrategy (tight passive MM, use_smile=False)
_V24_OPT_BS_BASE = dict(
    tte_days_initial=5.0,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    timestamp_units_per_day=1_000_000,
    ts_increment=100,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    prior_vol=0.0125,
    sigma_floor=0.005,
    sigma_cap=0.1,
    iv_ewma_alpha=0.3,
    min_quote_price=2.0,
    take_edge=3.0,
    take_size=40,
    enable_takers=False,
    penny_improve_around_mkt=True,
    inv_bias_per_unit=0.02,
    log_flush_ts=1000,
    last_ts_value=999900,
)

_V24_GAMMA_BASE = dict(
    tte_days_initial=5.0,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    timestamp_units_per_day=1_000_000,
    ts_increment=100,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    implied_vol_prior=0.0125,
    min_quote_price=2.0,
    entry_size=30,
    passive_bid_size=24,
    target_qty=300,
    unwind_tte_threshold=1.5,
    skip_when_expensive=True,
    zscore_skip_threshold=0.5,
    boost_when_cheap=False,
    zscore_boost_threshold=1.0,
    entry_size_boost=1.5,
    sell_when_very_expensive=False,
    edge_ticks=0.0,
    zscore_window=500,
    log_flush_ts=1000,
    last_ts_value=999900,
)

MEMBER_OVERRIDES["tibo_velvet_v24"] = {
    3: {
        "HYDROGEL_PACK": None,

        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="option_mm_bs", position_limit=300,
            params={**_V24_OPT_BS_BASE, "strike": 4000, "maker_edge": 2, "maker_size": 40,
                    "use_smile": True}),

        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="gamma_scalp_zgated", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 4500}),
        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="gamma_scalp_zgated", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5000}),
        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="gamma_scalp_zgated", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5100}),
        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="gamma_scalp_zgated", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5200}),
        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="gamma_scalp_zgated", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5300}),

        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="option_mm_bs", position_limit=300,
            params={**_V24_OPT_BS_BASE, "strike": 5400, "maker_edge": 1, "maker_size": 10,
                    "min_quote_price": 1.0, "inv_bias_per_unit": 0.04, "use_smile": False}),

        "VEV_5500": None, "VEV_6000": None, "VEV_6500": None,

        "VELVETFRUIT_EXTRACT": ProductConfig(symbol="VELVETFRUIT_EXTRACT",
            strategy="mm_first_v4_combo", position_limit=200,
            params=dict(
                anchor_price=5250.0,
                anchor_alpha=0.02,
                anchor_drift_bound=2.0,
                ar_gain=0.3,
                ar_shift_source="mid_smooth",
                maker_size=30,
                pct_kept_for_takers=0.05,
                take_edge_lo=0.3,
                take_edge_hi=0.8,
                inventory_aversion_gamma=0.0015,
                unwind_take_edge=3.0,
                tighten_ticks=1,
                full_capacity_on_empty=True,
                ts_increment=100,
                last_ts_value=999900,
                log_flush_ts=1000,
            )),
    },
}


# ── tibo_velvet_v25: best-of-both combination ────────────────────────────────
# VELVETFRUIT + VEV_4000/5200/5300/5400: v3 approach (passive MM, never directional)
# VEV_4500/5000/5100:                    v24 approach (GammaScalpZGated, new strikes)
#
# Root causes fixed vs v24:
#   VELVETFRUIT:  mm_first_v4_combo AR signal shorted on D2 when price rose → -6.5k
#                 Fix: revert to VelvetMMV3 (passive, consistent +6-7k/day, no direction bet)
#   VEV_5200/5300: skip_when_expensive+threshold=0.5 silenced accumulation when VELVETFRUIT
#                 trended (z>0.5 majority of D1) → only 27/90 units vs v3's 300
#                 Fix: revert to VEVOptionMMV3 which never skips bids, only adapts ask

MEMBER_OVERRIDES["tibo_velvet_v25"] = {
    3: {
        "HYDROGEL_PACK": None,

        # ── VEV options: run BEFORE VELVETFRUIT so delta is published first ──

        # VEV_4000: symmetric passive MM, deep ITM spread capture
        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="velvet_strat_v25_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 4000.0, "maker_size_bid": 20, "maker_size_ask": 20,
                    "ask_offset_neutral": 1, "ask_offset_sell": 1}),

        # VEV_4500/5000/5100: GammaScalpV25 — active taker + passive bid accumulation
        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="gamma_scalp_v25", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 4500}),
        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="gamma_scalp_v25", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5000}),
        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="gamma_scalp_v25", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5100}),

        # VEV_5200/5300: bid-heavy passive MM, never skips bids, ask adapts to z-score
        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="velvet_strat_v25_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 5200.0, "maker_size_bid": 20, "maker_size_ask": 5}),
        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="velvet_strat_v25_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 5300.0, "maker_size_bid": 20, "maker_size_ask": 5}),

        # VEV_5400: prevent_crossing=True — passive only, 1-tick spread
        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="velvet_strat_v25_opt", position_limit=300,
            params={**_VEV_OPT_V3_BASE, "strike": 5400.0, "maker_size_bid": 20, "maker_size_ask": 5,
                    "prevent_crossing": True}),

        "VEV_5500": None, "VEV_6000": None, "VEV_6500": None,

        # VELVETFRUIT: passive penny-improve MM, no directional bets, delta hedge from VEV
        "VELVETFRUIT_EXTRACT": ProductConfig(symbol="VELVETFRUIT_EXTRACT",
            strategy="velvet_strat_v25_mm", position_limit=200, params=_VELVET_V3_MM_PARAMS),
    },
}


# ── tibo_velvet_v26: ablation-driven simplification of v25 ───────────────────
# Ablation findings (3-day, realistic fill mode):
#   zscore_exec_mode removal (VEV_5200/5300/5400): 0 PnL impact → remove
#   use_delta_hedge removal (VELVETFRUIT):          0 PnL impact → remove
#   skip_when_expensive=False on V4500:            +2,326
#   skip_when_expensive=False on V5000:            +2,265
#   skip_when_expensive=True  on V5100 (keep):     saves -2,410 if removed
#   Expected v26 total: ~+96,264 vs v25's +94,083

_VELVET_V26_MM_PARAMS = dict(
    maker_size_base_pct=0.30,
    pct_kept_for_takers=0.15,
    mid_smooth_window=50,
    mid_smooth_half_life=20,
    use_delta_hedge=False,        # ablation: zero impact, removed for simplicity
    zscore_window=500,
    ts_increment=100,
    last_ts_value=999900,
    log_flush_ts=1000,
)

_VEV_OPT_V26_BASE = dict(
    **{k: v for k, v in _VEV_OPT_V3_BASE.items() if k != "zscore_exec_mode"},
    zscore_exec_mode="none",      # ablation: zero impact, z-score ask adapt is dead code
)

MEMBER_OVERRIDES["tibo_velvet_v26"] = {
    3: {
        "HYDROGEL_PACK": None,

        # VEV_4000: symmetric passive MM, deep ITM spread capture
        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="velvet_strat_v26_opt", position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 4000.0, "maker_size_bid": 20, "maker_size_ask": 20,
                    "ask_offset_neutral": 1, "ask_offset_sell": 1}),

        # VEV_4500: skip gate OFF — delta≈1 so accumulating when expensive is fine (+2,326)
        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="gamma_scalp_v26", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 4500, "skip_when_expensive": False}),

        # VEV_5000: skip gate OFF — benefit from extra fills outweighs directional risk (+2,265)
        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="gamma_scalp_v26", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5000, "skip_when_expensive": False}),

        # VEV_5100: skip gate ON — closest to ATM (delta≈0.7), removing would cost -2,410
        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="gamma_scalp_v26", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5100, "skip_when_expensive": True}),

        # VEV_5200/5300: bid-heavy, mode="none" (z-score ask adapt was dead code)
        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="velvet_strat_v26_opt", position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5200.0, "maker_size_bid": 20, "maker_size_ask": 5}),
        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="velvet_strat_v26_opt", position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5300.0, "maker_size_bid": 20, "maker_size_ask": 5}),

        # VEV_5400: passive only, prevent_crossing=True
        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="velvet_strat_v26_opt", position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5400.0, "maker_size_bid": 20, "maker_size_ask": 5,
                    "prevent_crossing": True}),

        "VEV_5500": None, "VEV_6000": None, "VEV_6500": None,

        # VELVETFRUIT: passive MM, delta hedge removed (zero ablation impact)
        "VELVETFRUIT_EXTRACT": ProductConfig(symbol="VELVETFRUIT_EXTRACT",
            strategy="velvet_strat_v26_mm", position_limit=200, params=_VELVET_V26_MM_PARAMS),
    },
}


# ── tibo_velvet_v27: SmileIVScaler for OTM/NTM VEV strikes ──────────────────
# Replaces VEV_5100/5200/5300/5400 with SmileIVScalerV27:
#   - LOO polynomial smile fit → fair IV per strike
#   - EWMA residual baseline + z-score
#   - Aggressively buy when cheap vs smile (resid_z <= -0.9)
#   - Exit when IV mean-reverts (resid_z >= 0.6 or price edge met)
#   - Passive maker around smile reference price
# Unchanged from v26: VELVETFRUIT, VEV_4000, VEV_4500, VEV_5000

_SMILE_SCALPER_V27_BASE = dict(
    tte_days_initial=5.0,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    timestamp_units_per_day=1_000_000,
    ts_increment=100,
    last_ts_value=999900,
    log_flush_ts=1000,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    # IV / smile params
    prior_vol=0.0125,
    implied_vol_prior=0.0125,
    smile_degree=2,
    smile_min_points=4,
    sigma_floor=0.005,
    sigma_cap=0.10,
    # Residual EWMA
    resid_ewma_alpha=0.03,
    resid_std_init=0.0015,
    resid_std_floor=0.0005,
    # Active rank gate
    active_reference_spot=5250.0,
    active_expand_every=120.0,
    active_base_count=6,
    active_max_extra_count=2,
    # Trading params
    soft_position_limit=150,
    entry_position_cap=60,
    take_size=20,
    maker_size=10,
    maker_edge=2.0,
    take_price_edge=2.0,
    reduce_price_edge=1.0,
    take_zscore=0.9,
    reduce_zscore=0.6,
    cheap_reset_z=0.35,
    inventory_skew=3.0,
    min_quote_price=1.0,
    resid_warmup_ticks=60,
    maker_join_best=True,
    inactive_unwind_bias=1,
    take_cooldown_ts=0,
    position_limit=300,
)

MEMBER_OVERRIDES["tibo_velvet_v27"] = {
    3: {
        "HYDROGEL_PACK": None,

        # VEV_4000: deep ITM, symmetric passive MM — unchanged from v26
        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="velvet_strat_v26_opt", position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 4000.0, "maker_size_bid": 20, "maker_size_ask": 20,
                    "ask_offset_neutral": 1, "ask_offset_sell": 1}),

        # VEV_4500/5000: skip gate OFF — ablation confirmed +4,591 — unchanged from v26
        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="gamma_scalp_v26", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 4500, "skip_when_expensive": False}),
        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="gamma_scalp_v26", position_limit=300,
            params={**_V24_GAMMA_BASE, "strike": 5000, "skip_when_expensive": False}),

        # VEV_5100/5200/5300/5400: SmileIVScaler (replaces GammaScalp skip=True + passive MM)
        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="smile_iv_scaler_v27", position_limit=300,
            params={**_SMILE_SCALPER_V27_BASE, "strike": 5100}),
        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="smile_iv_scaler_v27", position_limit=300,
            params={**_SMILE_SCALPER_V27_BASE, "strike": 5200}),
        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="smile_iv_scaler_v27", position_limit=300,
            params={**_SMILE_SCALPER_V27_BASE, "strike": 5300}),
        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="smile_iv_scaler_v27", position_limit=300,
            params={**_SMILE_SCALPER_V27_BASE, "strike": 5400}),

        "VEV_5500": None, "VEV_6000": None, "VEV_6500": None,

        # VELVETFRUIT: unchanged from v26
        "VELVETFRUIT_EXTRACT": ProductConfig(symbol="VELVETFRUIT_EXTRACT",
            strategy="velvet_strat_v26_mm", position_limit=200, params=_VELVET_V26_MM_PARAMS),
    },
}


# ── tibo_theo_v7: Theo's velvettuned_v7 as a member config ───────────────────
# Params copied verbatim from velvettuned_v7.py PRODUCTS dict.
# HYDROGEL excluded. VEV_4000–VEV_5500 all use TheoV7GammaScalp.

_THEO_V7_VEV_BASE = dict(
    boost_when_cheap=False,
    edge_ticks=0.0,
    enable_takers=False,
    entry_size=30,
    entry_size_boost=1.5,
    implied_vol_prior=0.0125,
    inv_bias_per_unit=0.02,
    iv_ewma_alpha=0.3,
    last_ts_value=999900,
    log_flush_ts=1000,
    maker_edge=2,
    maker_size=20,
    min_quote_price=2.0,
    passive_bid_size=24,
    penny_improve_around_mkt=True,
    prior_vol=0.0125,
    sigma_cap=0.1,
    sigma_floor=0.005,
    skip_when_expensive=True,
    take_edge=3.0,
    take_size=40,
    target_qty=300,
    timestamp_units_per_day=1_000_000,
    ts_increment=100,
    tte_days_initial=5.0,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    unwind_tte_threshold=1.5,
    use_smile=True,
    zscore_boost_threshold=1.0,
    zscore_window=500,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
)

_THEO_V7_VELVET_PARAMS = dict(
    anchor_alpha=0.02,
    anchor_drift_bound=2.0,
    anchor_price=5250.0,
    ar_gain=0.3,
    ar_shift_source="mid_smooth",
    full_capacity_on_empty=True,
    guard_inventory_dist=40.0,
    guard_max_dist=80.0,
    guard_min_dist=0.0,
    guard_near_band=0.0,
    guard_reversion_threshold=7.5,
    guard_trend_alpha=0.45,
    inventory_aversion_gamma=0.001,
    last_ts_value=999900,
    log_flush_ts=1000,
    maker_size=30,
    maker_size_base_pct=0.4,
    passive_unwind_skew_ticks=1,
    passive_unwind_trigger=0.38,
    pct_kept_for_takers=0.005,
    take_edge_hi=1.2,
    take_edge_lo=0.6,
    tighten_ticks=1,
    toxic_size_frac=0.68,
    toxic_threshold=0.6,
    toxic_window=8,
    ts_increment=100,
    unwind_take_edge=3.0,
)

MEMBER_OVERRIDES["tibo_theo_v7"] = {
    3: {
        "HYDROGEL_PACK": None,

        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT", strategy="theo_v7_velvet_mm",
            position_limit=200, params=_THEO_V7_VELVET_PARAMS),

        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4000,
                "zscore_skip_threshold": 1.5}),
        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4500,
                "zscore_skip_threshold": 2.0}),
        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5000,
                "zscore_skip_threshold": 1.0}),
        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5100,
                "zscore_skip_threshold": 0.5}),
        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5200,
                "zscore_skip_threshold": 2.0}),
        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5300,
                "zscore_skip_threshold": 2.0}),
        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5400,
                "zscore_skip_threshold": 1.0}),
        "VEV_5500": ProductConfig(symbol="VEV_5500", strategy="theo_v7_gamma_scalp",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5500,
                "zscore_skip_threshold": 0.5}),

        "VEV_6000": None, "VEV_6500": None,
    },
}


# ── tibo_velvet_v28: best-of-both v7 + v26 ablation fixes ────────────────────
# v7 wins: VELVETFRUIT (GuardedAnchor), VEV_4000 (GammaScalp active taker)
# v26 wins: VEV_5200/5300/5400 (passive bid-heavy), VEV_5000 skip=False

MEMBER_OVERRIDES["tibo_velvet_v28"] = {
    3: {
        "HYDROGEL_PACK": None,

        # VELVETFRUIT: v7's GuardedAnchorMM (unchanged from v7)
        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT", strategy="velvet_strat_v28_mm",
            position_limit=200, params=_THEO_V7_VELVET_PARAMS),

        # VEV_4000: v7 GammaScalp, skip=True thresh=1.5 (unchanged)
        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="gamma_scalp_v28",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4000,
                "zscore_skip_threshold": 1.5}),

        # VEV_4500: v7 GammaScalp, skip=True thresh=2.0 (near-equiv to skip=False)
        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="gamma_scalp_v28",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4500,
                "zscore_skip_threshold": 2.0}),

        # VEV_5000: skip=False (v26 ablation: +2,265 vs skip=True thresh=0.5)
        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="gamma_scalp_v28",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5000,
                "skip_when_expensive": False}),

        # VEV_5100: keep skip=True thresh=0.5 (ablation confirmed: removing costs -2,410)
        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="gamma_scalp_v28",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5100,
                "zscore_skip_threshold": 0.5}),

        # VEV_5200/5300/5400: switch to passive bid-heavy (v26 wins: +6.2k total)
        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="velvet_strat_v28_opt",
            position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5200.0,
                    "maker_size_bid": 20, "maker_size_ask": 5}),
        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="velvet_strat_v28_opt",
            position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5300.0,
                    "maker_size_bid": 20, "maker_size_ask": 5}),
        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="velvet_strat_v28_opt",
            position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5400.0,
                    "maker_size_bid": 20, "maker_size_ask": 5,
                    "prevent_crossing": True}),

        # VEV_5500: keep v7 GammaScalp
        "VEV_5500": ProductConfig(symbol="VEV_5500", strategy="gamma_scalp_v28",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5500,
                "zscore_skip_threshold": 0.5}),

        "VEV_6000": None, "VEV_6500": None,
    },
}


# ── tibo_velvet_v28_dyn_*: v28 with dynamic slow-anchor on VELVETFRUIT ───────
# Replace fixed anchor=5250 with a slow EWMA of mid.  Three alpha values:
#   slow   (alpha=0.00005, HL ~14000 ticks = ~1.4 days)
#   medium (alpha=0.0002,  HL ~ 3500 ticks = ~0.35 days)
#   fast   (alpha=0.0008,  HL ~  866 ticks = ~0.09 days)
# All other params identical to v28.  anchor_alpha=0 (no fast-drift on top),
# anchor_drift_bound=0 (dynamic anchor is already smooth enough).

def _v28_dyn_velvet_params(alpha: float) -> dict:
    return dict(
        _THEO_V7_VELVET_PARAMS,
        anchor_price=5250.0,          # seed value only (overridden dynamically)
        anchor_alpha=0.0,             # disable fast anchor drift
        anchor_drift_bound=0.0,       # no drift bound
        anchor_slow_alpha=alpha,
    )

def _make_v28_dyn(alpha: float) -> Dict:
    vf = ProductConfig(
        symbol="VELVETFRUIT_EXTRACT", strategy="dynamic_anchor_mm",
        position_limit=200, params=_v28_dyn_velvet_params(alpha))
    base = dict(MEMBER_OVERRIDES["tibo_velvet_v28"][3])
    base["VELVETFRUIT_EXTRACT"] = vf
    return {3: base}

MEMBER_OVERRIDES["tibo_velvet_v28_dyn_slow"]   = _make_v28_dyn(0.00005)
MEMBER_OVERRIDES["tibo_velvet_v28_dyn_medium"]  = _make_v28_dyn(0.0002)
MEMBER_OVERRIDES["tibo_velvet_v28_dyn_fast"]    = _make_v28_dyn(0.0008)


# ── tibo_velvet_v29: v28 + Leo's IV residual gate on VEV_5300 ──────────────────

_V29_IV_GATE_BASE = dict(
    iv_residual_gate=True,
    iv_skip_threshold=0.0010,
    iv_boost_threshold=0.0010,
    iv_delta_threshold=0.0003,
    iv_ewma_fast_alpha=0.10,
    iv_ewma_slow_alpha=0.02,
    iv_passive_boost=1.5,
)

_tibo_velvet_v29 = dict(MEMBER_OVERRIDES["tibo_velvet_v28"][3])
_tibo_velvet_v29["VEV_5300"] = ProductConfig(
    symbol="VEV_5300",
    strategy="gamma_scalp_v28",
    position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_V29_IV_GATE_BASE, "strike": 5300, "skip_when_expensive": False},
)
MEMBER_OVERRIDES["tibo_velvet_v29"] = {3: _tibo_velvet_v29}


# ── tibo_velvet_v29_*: product-isolated option idea probes ──────────────────
# Keep VELVETFRUIT + all untouched options identical to v29, then swap exactly
# one option so attribution stays clean in compare runs.

_V29_VEV5000_WITH_ASK = {
    **_THEO_V7_VEV_BASE,
    "strike": 5000,
    "skip_when_expensive": False,
    "passive_ask_size": 5,
    "ask_only_above_fair": True,
    "ask_min_position": 20,
}

_tibo_v29_vev5000_with_ask = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v29_vev5000_with_ask["VEV_5000"] = ProductConfig(
    symbol="VEV_5000",
    strategy="gamma_scalp_with_ask_v40",
    position_limit=300,
    params=_V29_VEV5000_WITH_ASK,
)
MEMBER_OVERRIDES["tibo_velvet_v29_vev5000_with_ask"] = {3: _tibo_v29_vev5000_with_ask}

_V29_VEV5000_SMILE_ASK = {
    **_V29_VEV5000_WITH_ASK,
    "target_qty": 280,
    "fair_vol_mode": "smile_iv",
    "fair_vol_scale": 1.0,
}

_tibo_v29_vev5000_smile_ask = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v29_vev5000_smile_ask["VEV_5000"] = ProductConfig(
    symbol="VEV_5000",
    strategy="gamma_scalp_with_ask_v40",
    position_limit=300,
    params=_V29_VEV5000_SMILE_ASK,
)
MEMBER_OVERRIDES["tibo_velvet_v29_vev5000_smile_ask"] = {3: _tibo_v29_vev5000_smile_ask}

_V29_VEV5000_SMILE_MM = dict(
    implied_vol_prior=0.0125,
    fair_vol_mode="smile_iv",
    base_size=15,
    bid_size_mult=1.5,
    inventory_skew_ticks=0,
    min_spread_to_quote=2,
    min_quote_price=2.0,
    taker_buy_edge=0.0,
    taker_sell_edge=0.0,
    max_taker_size=10,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    tte_days_initial=5.0,
    timestamp_units_per_day=1_000_000,
    ts_increment=100,
    last_ts_value=999900,
    log_flush_ts=1000,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    sigma_floor=0.005,
    sigma_cap=0.10,
    prior_vol=0.0125,
    smile_degree=2,
    smile_min_points=4,
    active_base_count=6,
    active_max_extra_count=2,
    active_expand_every=120.0,
    active_reference_spot=5250.0,
    strike=5000,
)

_tibo_v29_vev5000_smile_mm = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v29_vev5000_smile_mm["VEV_5000"] = ProductConfig(
    symbol="VEV_5000",
    strategy="symmetric_option_mm_v40",
    position_limit=300,
    params=_V29_VEV5000_SMILE_MM,
)
MEMBER_OVERRIDES["tibo_velvet_v29_vev5000_smile_mm"] = {3: _tibo_v29_vev5000_smile_mm}

_V29_VEV5400_SMILE_VALUE = {
    **_THEO_V7_VEV_BASE,
    "strike": 5400,
    "skip_when_expensive": False,
    "target_qty": 220,
    "entry_size": 20,
    "passive_bid_size": 18,
    "edge_ticks": -2.0,
    "fair_vol_mode": "smile_iv",
    "sell_when_very_expensive": True,
    "zscore_sell_threshold": 1.2,
    "sell_size_pct": 0.12,
}

_tibo_v29_vev5400_smile_value = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v29_vev5400_smile_value["VEV_5400"] = ProductConfig(
    symbol="VEV_5400",
    strategy="gamma_scalp_v28",
    position_limit=300,
    params=_V29_VEV5400_SMILE_VALUE,
)
MEMBER_OVERRIDES["tibo_velvet_v29_vev5400_smile_value"] = {3: _tibo_v29_vev5400_smile_value}

_V29_VEV4000_SYM_MM = {
    "implied_vol_prior": 0.0125,
    "fair_vol_mode": "fixed",
    "base_size": 18,
    "bid_size_mult": 1.0,
    "inventory_skew_ticks": 1,
    "min_spread_to_quote": 4,
    "min_quote_price": 2.0,
    "taker_buy_edge": 0.0,
    "taker_sell_edge": 0.0,
    "max_taker_size": 10,
    "underlying_symbol": "VELVETFRUIT_EXTRACT",
    "tte_days_initial": 5.0,
    "timestamp_units_per_day": 1_000_000,
    "ts_increment": 100,
    "last_ts_value": 999900,
    "log_flush_ts": 1000,
    "historical_tte_by_day": {0: 8.0, 1: 7.0, 2: 6.0},
    "sigma_floor": 0.005,
    "sigma_cap": 0.10,
    "prior_vol": 0.0125,
    "smile_degree": 2,
    "smile_min_points": 4,
    "active_base_count": 6,
    "active_max_extra_count": 2,
    "active_expand_every": 120.0,
    "active_reference_spot": 5250.0,
    "strike": 4000,
}

_tibo_v29_vev4000_sym_mm = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v29_vev4000_sym_mm["VEV_4000"] = ProductConfig(
    symbol="VEV_4000",
    strategy="symmetric_option_mm_v40",
    position_limit=300,
    params=_V29_VEV4000_SYM_MM,
)
MEMBER_OVERRIDES["tibo_velvet_v29_vev4000_sym_mm"] = {3: _tibo_v29_vev4000_sym_mm}


# ══════════════════════════════════════════════════════════════════════════════
#  v40+: True 2-sided market making experiments
#  Base: tibo_velvet_v28 (VELVETFRUIT unchanged in all v40 variants)
#
#  Spread analysis (3-day historical):
#    VEV_4000: avg 21 ticks  VEV_4500: avg 16  VEV_5000: avg 6
#    VEV_5100: avg 4-5       VEV_5200: avg 3   VEV_5300: avg 2
#    VEV_5400/5500: avg 1    (too tight to MM)
#
#  Experiments:
#    v40  — SymmetricOptionMM (pure 2-sided, fixed sigma=0.0125) for 5000+5100
#    v41  — GammaScalpWithAsk (accumulate bias + passive ask) for 5000+5100
#    v42  — SymmetricOptionMM with smile_iv for 5100 (best fair value)
#    v43  — ask_adapt mode (VEVOptionMMV3 with zscore_exec_mode=ask_adapt) for 5200+5300
#    v44  — Best combo across v40-v43
# ══════════════════════════════════════════════════════════════════════════════

_V40_SYM_MM_BASE = dict(
    implied_vol_prior=0.0125,
    fair_vol_mode="fixed",
    base_size=15,
    bid_size_mult=1.0,       # symmetric (1.0) — can set >1 for long bias
    inventory_skew_ticks=0,
    min_spread_to_quote=2,
    min_quote_price=2.0,
    taker_buy_edge=0.0,      # no taker: too aggressive per live lesson
    taker_sell_edge=0.0,
    max_taker_size=10,
    underlying_symbol="VELVETFRUIT_EXTRACT",
    tte_days_initial=5.0,
    timestamp_units_per_day=1_000_000,
    ts_increment=100,
    last_ts_value=999900,
    log_flush_ts=1000,
    historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
    sigma_floor=0.005,
    sigma_cap=0.10,
    prior_vol=0.0125,
    smile_degree=2,
    smile_min_points=4,
    active_base_count=6,
    active_max_extra_count=2,
    active_expand_every=120.0,
    active_reference_spot=5250.0,
)

# v40: SymmetricOptionMM (neutral, fixed sigma) for VEV_5000 and VEV_5100
_tibo_v40 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v40["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="symmetric_option_mm_v40", position_limit=300,
    params={**_V40_SYM_MM_BASE, "strike": 5000, "base_size": 15, "bid_size_mult": 1.0})
_tibo_v40["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="symmetric_option_mm_v40", position_limit=300,
    params={**_V40_SYM_MM_BASE, "strike": 5100, "base_size": 12, "bid_size_mult": 1.0})
MEMBER_OVERRIDES["tibo_velvet_v40"] = {3: _tibo_v40}

# v40b: SymmetricOptionMM long-biased (bid 2x ask) for VEV_5000/5100
_tibo_v40b = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v40b["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="symmetric_option_mm_v40", position_limit=300,
    params={**_V40_SYM_MM_BASE, "strike": 5000, "base_size": 12, "bid_size_mult": 2.0})
_tibo_v40b["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="symmetric_option_mm_v40", position_limit=300,
    params={**_V40_SYM_MM_BASE, "strike": 5100, "base_size": 12, "bid_size_mult": 2.0})
MEMBER_OVERRIDES["tibo_velvet_v40b"] = {3: _tibo_v40b}

# v41: GammaScalpWithAsk for VEV_5000 (accumulate + small passive ask)
_tibo_v41 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v41["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, "strike": 5000, "skip_when_expensive": False,
            "passive_ask_size": 5, "ask_only_above_fair": True, "ask_min_position": 20})
MEMBER_OVERRIDES["tibo_velvet_v41"] = {3: _tibo_v41}

# v41b: GammaScalpWithAsk for VEV_5100 too
_tibo_v41b = dict(MEMBER_OVERRIDES["tibo_velvet_v41"][3])
_tibo_v41b["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, "strike": 5100,
            "zscore_skip_threshold": 0.5,
            "passive_ask_size": 5, "ask_only_above_fair": True, "ask_min_position": 20})
MEMBER_OVERRIDES["tibo_velvet_v41b"] = {3: _tibo_v41b}

# v41c: GammaScalpWithAsk bigger ask size (8) for VEV_5000+5100
_tibo_v41c = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v41c["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, "strike": 5000, "skip_when_expensive": False,
            "passive_ask_size": 8, "ask_only_above_fair": True, "ask_min_position": 20})
_tibo_v41c["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, "strike": 5100,
            "zscore_skip_threshold": 0.5,
            "passive_ask_size": 8, "ask_only_above_fair": True, "ask_min_position": 20})
MEMBER_OVERRIDES["tibo_velvet_v41c"] = {3: _tibo_v41c}

# v42: SymmetricOptionMM with smile_iv for VEV_5100 (LOO smile fair value)
_tibo_v42 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v42["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="symmetric_option_mm_v40", position_limit=300,
    params={**_V40_SYM_MM_BASE, "strike": 5100, "base_size": 12,
            "fair_vol_mode": "smile_iv", "bid_size_mult": 1.5})
MEMBER_OVERRIDES["tibo_velvet_v42"] = {3: _tibo_v42}

# v42b: SymmetricOptionMM smile_iv for VEV_5000 and VEV_5100
_tibo_v42b = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v42b["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="symmetric_option_mm_v40", position_limit=300,
    params={**_V40_SYM_MM_BASE, "strike": 5000, "base_size": 15,
            "fair_vol_mode": "smile_iv", "bid_size_mult": 1.5})
_tibo_v42b["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="symmetric_option_mm_v40", position_limit=300,
    params={**_V40_SYM_MM_BASE, "strike": 5100, "base_size": 12,
            "fair_vol_mode": "smile_iv", "bid_size_mult": 1.5})
MEMBER_OVERRIDES["tibo_velvet_v42b"] = {3: _tibo_v42b}

# v43: VEV_5200/5300 with zscore ask-adapt (sell into VELVETFRUIT strength)
# Uses existing VEVOptionMMV3 with ask_adapt mode enabled
_tibo_v43 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v43["VEV_5200"] = ProductConfig(
    symbol="VEV_5200", strategy="velvet_strat_v28_opt", position_limit=300,
    params={**_VEV_OPT_V26_BASE, "strike": 5200.0,
            "maker_size_bid": 20, "maker_size_ask": 5,
            "zscore_exec_mode": "ask_adapt",   # enable z-score sell on expensive
            "zscore_threshold": 1.0})
_tibo_v43["VEV_5300"] = ProductConfig(
    symbol="VEV_5300", strategy="velvet_strat_v28_opt", position_limit=300,
    params={**_VEV_OPT_V26_BASE, "strike": 5300.0,
            "maker_size_bid": 20, "maker_size_ask": 5,
            "zscore_exec_mode": "ask_adapt",
            "zscore_threshold": 1.0})
MEMBER_OVERRIDES["tibo_velvet_v43"] = {3: _tibo_v43}

# v43b: tighter z threshold (0.5) for ask_adapt on VEV_5200/5300
_tibo_v43b = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v43b["VEV_5200"] = ProductConfig(
    symbol="VEV_5200", strategy="velvet_strat_v28_opt", position_limit=300,
    params={**_VEV_OPT_V26_BASE, "strike": 5200.0,
            "maker_size_bid": 20, "maker_size_ask": 10,
            "zscore_exec_mode": "ask_adapt",
            "zscore_threshold": 0.5})
_tibo_v43b["VEV_5300"] = ProductConfig(
    symbol="VEV_5300", strategy="velvet_strat_v28_opt", position_limit=300,
    params={**_VEV_OPT_V26_BASE, "strike": 5300.0,
            "maker_size_bid": 20, "maker_size_ask": 10,
            "zscore_exec_mode": "ask_adapt",
            "zscore_threshold": 0.5})
MEMBER_OVERRIDES["tibo_velvet_v43b"] = {3: _tibo_v43b}

# v44: GammaScalpWithAsk for VEV_4500 (wider spread = more spread income)
_tibo_v44 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v44["VEV_4500"] = ProductConfig(
    symbol="VEV_4500", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, "strike": 4500,
            "zscore_skip_threshold": 2.0,
            "passive_ask_size": 8, "ask_only_above_fair": True, "ask_min_position": 30})
MEMBER_OVERRIDES["tibo_velvet_v44"] = {3: _tibo_v44}


# ── tibo_velvet_v45+: taker-sell experiments ──────────────────────────────────
# Key insight from v40-v44: passive asks don't fill in realistic backtest.
# Only taker sells (at best_bid) fill reliably. Testing here:
#   v45  — taker sell on VEV_5100 (z>1.5, sell 10%)
#   v45b — z>1.0, sell 15%
#   v46  — taker sell on VEV_5000 (z>1.5)
#   v46b — taker sell on both 5000+5100
#   v47  — taker sell on VEV_4500 (wider spread = better spread ratio)
#   v48  — taker sell on 4500+5000+5100 (full sweep)

_TAKER_SELL_BASE = dict(
    taker_sell_enabled=True,
    taker_sell_zscore=1.5,
    taker_sell_size_pct=0.10,
    taker_sell_max_size=20,
    taker_sell_cooldown_ts=500,
)

_tibo_v45 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v45["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 5100,
            "zscore_skip_threshold": 0.5})
MEMBER_OVERRIDES["tibo_velvet_v45"] = {3: _tibo_v45}

_tibo_v45b = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v45b["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 5100,
            "zscore_skip_threshold": 0.5,
            "taker_sell_zscore": 1.0, "taker_sell_size_pct": 0.15})
MEMBER_OVERRIDES["tibo_velvet_v45b"] = {3: _tibo_v45b}

_tibo_v46 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v46["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 5000,
            "skip_when_expensive": False})
MEMBER_OVERRIDES["tibo_velvet_v46"] = {3: _tibo_v46}

_tibo_v46b = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v46b["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 5000,
            "skip_when_expensive": False})
_tibo_v46b["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 5100,
            "zscore_skip_threshold": 0.5})
MEMBER_OVERRIDES["tibo_velvet_v46b"] = {3: _tibo_v46b}

_tibo_v47 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v47["VEV_4500"] = ProductConfig(
    symbol="VEV_4500", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 4500,
            "zscore_skip_threshold": 2.0,
            "taker_sell_zscore": 2.0, "taker_sell_size_pct": 0.10,
            "taker_sell_max_size": 20})
MEMBER_OVERRIDES["tibo_velvet_v47"] = {3: _tibo_v47}

_tibo_v48 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v48["VEV_4500"] = ProductConfig(
    symbol="VEV_4500", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 4500,
            "zscore_skip_threshold": 2.0, "taker_sell_zscore": 2.0})
_tibo_v48["VEV_5000"] = ProductConfig(
    symbol="VEV_5000", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 5000,
            "skip_when_expensive": False, "taker_sell_zscore": 1.5})
_tibo_v48["VEV_5100"] = ProductConfig(
    symbol="VEV_5100", strategy="gamma_scalp_with_ask_v40", position_limit=300,
    params={**_THEO_V7_VEV_BASE, **_TAKER_SELL_BASE, "strike": 5100,
            "zscore_skip_threshold": 0.5, "taker_sell_zscore": 1.5})
MEMBER_OVERRIDES["tibo_velvet_v48"] = {3: _tibo_v48}


# ══════════════════════════════════════════════════════════════════════════════
#  v30: four targeted ideas not tested in v29/v40-v48
#  Base: tibo_velvet_v29. Each config swaps exactly ONE option vs v29.
# ══════════════════════════════════════════════════════════════════════════════

# Shared smile params (added to _THEO_V7_VEV_BASE for smile_iv mode)
_V30_SMILE_EXTRA = dict(
    smile_degree=2,
    smile_min_points=4,
    active_base_count=6,
    active_max_extra_count=2,
    active_expand_every=120.0,
    active_reference_spot=5250.0,
)

# ── Idea 1: VEV_4500 — smile-calibrated GammaScalp ────────────────────────
# Previous: GammaScalp skip=True, thresh=2.0, fixed sigma=0.0125 → 18,802
# Change: fair_vol_mode="smile_iv". For K=4500 (slightly ITM), smile typically
# predicts higher IV than 0.0125 → fair price higher → taker buys more active.
_tibo_v30_4500_smile = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v30_4500_smile["VEV_4500"] = ProductConfig(
    symbol="VEV_4500",
    strategy="gamma_scalp_smile_v30_vev4500",
    position_limit=300,
    params={
        **_THEO_V7_VEV_BASE,
        **_V30_SMILE_EXTRA,
        "strike": 4500,
        "zscore_skip_threshold": 2.0,
        "fair_vol_mode": "smile_iv",
    },
)
MEMBER_OVERRIDES["tibo_velvet_v30_4500_smile"] = {3: _tibo_v30_4500_smile}

# ── Idea 2: VEV_5100 — gentle gamma + tiny passive ask ────────────────────
# Previous v42 (pure SymmetricOptionMM) lost -12.9k — abandoned accumulation bias.
# This keeps full GammaScalp accumulation and adds a tiny passive ask (size=4)
# only when position >= 80 AND market ask > BS fair.
_tibo_v30_5100_ask = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v30_5100_ask["VEV_5100"] = ProductConfig(
    symbol="VEV_5100",
    strategy="gamma_scalp_with_ask_v30_vev5100",
    position_limit=300,
    params={
        **_THEO_V7_VEV_BASE,
        "strike": 5100,
        "zscore_skip_threshold": 0.5,
        "passive_ask_size": 4,
        "ask_min_position": 80,
        "ask_only_above_fair": True,
        "taker_sell_enabled": False,
    },
)
MEMBER_OVERRIDES["tibo_velvet_v30_5100_ask"] = {3: _tibo_v30_5100_ask}

# ── Idea 3: VEV_5200 — smile-calibrated accumulator ──────────────────────
# Previous: VEVOptionMMV28 (passive bid-heavy, no fair value) → 11,882
# Change: GammaScalp with smile_iv, skip=False, edge_ticks=3 so the taker
# fires when market ask is still below smile-fair + 3 ticks. Passive bid kept.
_tibo_v30_5200_smile = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v30_5200_smile["VEV_5200"] = ProductConfig(
    symbol="VEV_5200",
    strategy="gamma_scalp_smile_v30_vev5200",
    position_limit=300,
    params={
        **_THEO_V7_VEV_BASE,
        **_V30_SMILE_EXTRA,
        "strike": 5200,
        "skip_when_expensive": False,
        "fair_vol_mode": "smile_iv",
        "edge_ticks": 3.0,
        "entry_size": 20,
        "passive_bid_size": 20,
    },
)
MEMBER_OVERRIDES["tibo_velvet_v30_5200_smile"] = {3: _tibo_v30_5200_smile}

# ── Idea 4: VEV_4000 — delta-one MM using VELVETFRUIT microprice ──────────
# Previous v29_vev4000_sym_mm used generic SymmetricOptionMM (2-sided, bad).
# DeltaOneMMV30 uses VELVETFRUIT top-of-book microprice for fair value and
# scales passive bid size by order book imbalance (bid-heavy → bigger bid).
_tibo_v30_4000_delta1 = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v30_4000_delta1["VEV_4000"] = ProductConfig(
    symbol="VEV_4000",
    strategy="delta_one_mm_v30",
    position_limit=300,
    params={
        "strike": 4000,
        "implied_vol_prior": 0.0125,
        "target_qty": 300,
        "entry_size": 30,
        "passive_bid_size": 24,
        "edge_ticks": 0.0,
        "unwind_tte_threshold": 1.5,
        "min_quote_price": 2.0,
        "imbalance_bid_boost": 1.8,
        "imbalance_bid_reduce": 0.4,
        "imbalance_tick_threshold": 0.3,
        "underlying_symbol": "VELVETFRUIT_EXTRACT",
        "tte_days_initial": 5.0,
        "historical_tte_by_day": {0: 8.0, 1: 7.0, 2: 6.0},
        "timestamp_units_per_day": 1_000_000,
        "ts_increment": 100,
        "last_ts_value": 999900,
        "log_flush_ts": 1000,
        "sigma_floor": 0.005,
        "sigma_cap": 0.10,
        "prior_vol": 0.0125,
        "smile_degree": 2,
        "smile_min_points": 4,
    },
)
MEMBER_OVERRIDES["tibo_velvet_v30_4000_delta1"] = {3: _tibo_v30_4000_delta1}


# ── Theo's HYDROGEL strategy (r3_hydro_v7b_guarded_loose) ─────────────────────
# Ported from Theo's self-contained submission file.
# Uses R3GuardedAnchorMMStrategy (same class as VELVETFRUIT) with:
#   - anchor_price=10000   (HYDROGEL mean-reverts to 10000)
#   - looser guard (reversion_threshold=3.0 vs 7.5 for VELVET)
#   - tighter take edges (lo=0.3, hi=0.8 vs lo=0.6, hi=1.2 for VELVET)
#   - smaller ar_gain=0.2 (vs 0.3 for VELVET)

_HYDRO_V7B_PARAMS = dict(
    anchor_alpha=0.02,
    anchor_drift_bound=1.5,
    anchor_price=10000.0,
    ar_gain=0.2,
    ar_shift_source="mid_smooth",
    full_capacity_on_empty=True,
    guard_inventory_dist=40.0,
    guard_max_dist=80.0,
    guard_min_dist=0.0,
    guard_near_band=0.0,
    guard_reversion_threshold=3.0,
    guard_trend_alpha=0.45,
    inventory_aversion_gamma=0.001,
    last_ts_value=999900,
    log_flush_ts=1000,
    maker_size=30,
    maker_size_base_pct=0.15,    # 30/200 — matches maker_size intent
    passive_unwind_skew_ticks=1,
    passive_unwind_trigger=0.38,
    pct_kept_for_takers=0.005,
    take_edge_hi=0.8,
    take_edge_lo=0.3,
    tighten_ticks=1,
    toxic_size_frac=0.68,
    toxic_threshold=0.6,
    toxic_window=8,
    ts_increment=100,
    unwind_take_edge=3.0,
)

# Standalone HYDROGEL-only config (useful for single-product backtest)
MEMBER_OVERRIDES["hydro_v7b"] = {
    3: {
        "HYDROGEL_PACK": ProductConfig(
            symbol="HYDROGEL_PACK", strategy="r3_guarded_anchor_mm",
            position_limit=200, params=_HYDRO_V7B_PARAMS),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None, "VEV_4500": None, "VEV_5000": None, "VEV_5100": None,
        "VEV_5200": None, "VEV_5300": None, "VEV_5400": None, "VEV_5500": None,
        "VEV_6000": None, "VEV_6500": None,
    }
}

# Combined: tibo's v29 (VELVETFRUIT + VEV options) + Theo's hydro v7b (HYDROGEL)
_tibo_v29_plus_hydro = dict(MEMBER_OVERRIDES["tibo_velvet_v29"][3])
_tibo_v29_plus_hydro["HYDROGEL_PACK"] = ProductConfig(
    symbol="HYDROGEL_PACK", strategy="r3_guarded_anchor_mm",
    position_limit=200, params=_HYDRO_V7B_PARAMS)
MEMBER_OVERRIDES["tibo_v29_plus_hydro"] = {3: _tibo_v29_plus_hydro}


# ── v100: canonical standalone configs — no intermediate wrapper chain ────────
# Strategy keys map directly onto the canonical implementation classes:
#   velvet_mm_v100      → VelvetMMV100(R3GuardedAnchorMMStrategy)
#   gamma_scalp_v100    → GammaScalpV100(GammaScalpZGatedMixinStrategy)
#   vev_option_mm_v100  → VEVOptionMMV100(VEVOptionMMV3)
#   hydro_mm_v100       → HydroMMV100(R3GuardedAnchorMMStrategy)
# Params are identical to tibo_velvet_v29 / hydro_v7b — pure refactor.

MEMBER_OVERRIDES["tibo_velvet_v100"] = {
    3: {
        "HYDROGEL_PACK": None,

        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT", strategy="velvet_mm_v100",
            position_limit=200, params=_THEO_V7_VELVET_PARAMS),

        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="gamma_scalp_v100",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4000,
                "zscore_skip_threshold": 1.5}),

        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="gamma_scalp_v100",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4500,
                "zscore_skip_threshold": 2.0}),

        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="gamma_scalp_v100",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5000,
                "skip_when_expensive": False}),

        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="gamma_scalp_v100",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5100,
                "zscore_skip_threshold": 0.5}),

        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="vev_option_mm_v100",
            position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5200.0,
                    "maker_size_bid": 20, "maker_size_ask": 5}),

        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="gamma_scalp_v100",
            position_limit=300,
            params={**_THEO_V7_VEV_BASE, **_V29_IV_GATE_BASE, "strike": 5300,
                    "skip_when_expensive": False}),

        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="vev_option_mm_v100",
            position_limit=300,
            params={**_VEV_OPT_V26_BASE, "strike": 5400.0,
                    "maker_size_bid": 20, "maker_size_ask": 5,
                    "prevent_crossing": True}),

        "VEV_5500": ProductConfig(symbol="VEV_5500", strategy="gamma_scalp_v100",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5500,
                "zscore_skip_threshold": 0.5}),

        "VEV_6000": None, "VEV_6500": None,
    },
}

MEMBER_OVERRIDES["hydro_v100"] = {
    3: {
        "HYDROGEL_PACK": ProductConfig(
            symbol="HYDROGEL_PACK", strategy="hydro_mm_v100",
            position_limit=200, params=_HYDRO_V7B_PARAMS),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None, "VEV_4500": None, "VEV_5000": None, "VEV_5100": None,
        "VEV_5200": None, "VEV_5300": None, "VEV_5400": None, "VEV_5500": None,
        "VEV_6000": None, "VEV_6500": None,
    }
}

MEMBER_OVERRIDES["hydro_v200"] = {
    3: {
        "HYDROGEL_PACK": ProductConfig(
            symbol="HYDROGEL_PACK", strategy="hydro_mm_v200",
            position_limit=200, params=_HYDRO_V7B_PARAMS),
        "VELVETFRUIT_EXTRACT": None,
        "VEV_4000": None, "VEV_4500": None, "VEV_5000": None, "VEV_5100": None,
        "VEV_5200": None, "VEV_5300": None, "VEV_5400": None, "VEV_5500": None,
        "VEV_6000": None, "VEV_6500": None,
    }
}

_tibo_v100_full = dict(MEMBER_OVERRIDES["tibo_velvet_v100"][3])
_tibo_v100_full["HYDROGEL_PACK"] = ProductConfig(
    symbol="HYDROGEL_PACK", strategy="hydro_mm_v100",
    position_limit=200, params=_HYDRO_V7B_PARAMS)
MEMBER_OVERRIDES["tibo_v100_full"] = {3: _tibo_v100_full}

MEMBER_OVERRIDES["tibo_v200_full"] = {
    3: {
        "HYDROGEL_PACK": ProductConfig(
            symbol="HYDROGEL_PACK", strategy="hydro_mm_v200",
            position_limit=200, params=_HYDRO_V7B_PARAMS),

        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT", strategy="velvet_mm_v200",
            position_limit=200, params=_THEO_V7_VELVET_PARAMS),

        "VEV_4000": ProductConfig(symbol="VEV_4000", strategy="gamma_scalp_v200",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4000,
                "zscore_skip_threshold": 1.5}),

        "VEV_4500": ProductConfig(symbol="VEV_4500", strategy="gamma_scalp_v200",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 4500,
                "zscore_skip_threshold": 2.0}),

        "VEV_5000": ProductConfig(symbol="VEV_5000", strategy="gamma_scalp_v200",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5000,
                "skip_when_expensive": False}),

        "VEV_5100": ProductConfig(symbol="VEV_5100", strategy="gamma_scalp_v200",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5100,
                "zscore_skip_threshold": 0.5}),

        "VEV_5200": ProductConfig(symbol="VEV_5200", strategy="gamma_scalp_v200",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5200,
                "zscore_skip_threshold": 2.0}),

        "VEV_5300": ProductConfig(symbol="VEV_5300", strategy="gamma_scalp_v200",
            position_limit=300,
            params={**_THEO_V7_VEV_BASE, **_V29_IV_GATE_BASE, "strike": 5300,
                    "skip_when_expensive": False}),

        "VEV_5400": ProductConfig(symbol="VEV_5400", strategy="gamma_scalp_v200",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5400,
                "zscore_skip_threshold": 1.0}),

        "VEV_5500": ProductConfig(symbol="VEV_5500", strategy="gamma_scalp_v200",
            position_limit=300, params={**_THEO_V7_VEV_BASE, "strike": 5500,
                "zscore_skip_threshold": 0.5}),

        "VEV_6000": None, "VEV_6500": None,
    }
}


# ──────────────────────────────────────────────────────────────────────────────
# R4 STARTING POINT — best HYDRO (v7b_guarded_loose) + best VELVET (v57)
#                     + best options (mix v62 Tibo 2-sided MM + IV gate)
#
# Built 2026-04-26 as starting baseline for Round 4.
# Backtest target: should match or beat final_sub_v100 (240,918 PnL / 56,858 DD / 4.237 ratio).
# ──────────────────────────────────────────────────────────────────────────────

# HYDRO best params (v7b_guarded_loose: guard threshold 3.0 + toxic + unwind)
_R4_HYDRO_BEST_PARAMS = dict(
    strategy="r3_guarded_anchor_mm",
    position_limit=200,
    quote_trace_enabled=True,
    # toxic + unwind layers
    toxic_threshold=0.6, toxic_window=8, toxic_size_frac=0.68,
    passive_unwind_skew_ticks=1, passive_unwind_trigger=0.38,
    inventory_aversion_gamma=0.001,
    pct_kept_for_takers=0.005,
    # guard params (LOOSE = threshold 3.0)
    guard_trend_alpha=0.45,
    guard_reversion_threshold=3.0,
    guard_inventory_dist=40.0,
    guard_min_dist=0.0,
    guard_max_dist=80.0,
    guard_near_band=0.0,
)


# R4 TTE override: live=4 days, backtest days 1/2/3 = 7/6/5
_R4_TTE_OVERRIDE = dict(
    tte_days_initial=4.0,
    historical_tte_by_day={1: 7.0, 2: 6.0, 3: 5.0},
)


# Helper: build option params with R4 TTE override applied last
def _r4_gamma_params(z_skip=0.5, with_iv_gate=False):
    base = _gamma_zgated_with_iv_gate(z_skip=z_skip) if with_iv_gate else _gamma_zgated_params(target_qty=300, z_skip_threshold=z_skip)
    base.update(_R4_TTE_OVERRIDE)  # override TTE for R4
    return base


def _r4_tibo_vev_mm(strike, prevent_crossing=False):
    """Tibo's 2-sided MM with R4 TTE."""
    cfg = _tibo_vev_mm(strike, prevent_crossing=prevent_crossing)
    # cfg is a ProductConfig — need to update its params
    new_params = dict(cfg.params)
    new_params["tte_days_initial"] = 4.0
    new_params["historical_tte_by_day"] = {1: 7.0, 2: 6.0, 3: 5.0}
    return ProductConfig(symbol=cfg.symbol, strategy=cfg.strategy,
                         position_limit=cfg.position_limit, params=new_params)


# r4_combined_best — same as r3_combined_best but for ROUND_4
MEMBER_OVERRIDES["r4_combined_best"] = {
    4: {
        # HYDROGEL = v7b_guarded_loose
        "HYDROGEL_PACK": _override(
            ROUND_4["HYDROGEL_PACK"],
            **_R4_HYDRO_BEST_PARAMS,
        ),
        # VELVET = v57 (R3GuardedAnchor + toxic + passive unwind)
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_4["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V7_GUARDED_VELVET_PARAMS,
        ),
        # VEV options = v62 mix: per-strike z + Tibo 2-sided MM on 5200/5400
        "VEV_4000": _override(
            ROUND_4["VEV_4000"], position_limit=300, strike=4000,
            **_r4_gamma_params(z_skip=0.5, with_iv_gate=False),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_4[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_r4_gamma_params(z_skip=0.5, with_iv_gate=True),
            )
            for strike in [4500, 5000, 5100]
        },
        # 5200, 5400 use Tibo's 2-sided passive MM
        "VEV_5200": _r4_tibo_vev_mm(5200),
        "VEV_5300": _override(
            ROUND_4["VEV_5300"], position_limit=300, strike=5300,
            **_r4_gamma_params(z_skip=0.8, with_iv_gate=True),
        ),
        "VEV_5400": _r4_tibo_vev_mm(5400, prevent_crossing=True),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# r4_oracle_overfit — MAXIMUM OVERFIT to R4 day 3 first 10%
# Hardcodes optimal trades pre-computed from D3 data.
# Expected backtest PnL: ~+115,720 on D3 first 10% only.
# ⚠️ WORKS ONLY IF live data == R4 day 3 first 10% (verified 100% match).
MEMBER_OVERRIDES["r4_oracle_overfit"] = {
    4: {
        "HYDROGEL_PACK": _override(
            ROUND_4["HYDROGEL_PACK"],
            strategy="oracle_replay_r4d3",
            position_limit=200,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_4["VELVETFRUIT_EXTRACT"],
            strategy="oracle_replay_r4d3",
            position_limit=200,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_4[f"VEV_{strike}"],
                strategy="oracle_replay_r4d3",
                position_limit=300,
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=999900,
            )
            for strike in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
        },
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# R4 VARIANTS — re-test all R3 ideas on R4 data (velvet+options only)
# ──────────────────────────────────────────────────────────────────────────────

# v52 R4: minimal R3GuardedAnchor (no toxic, no unwind) — baseline
MEMBER_OVERRIDES["r4_v52_minimal"] = {
    4: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_4["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_GUARDED_VELVET_PARAMS,  # base R3 (no toxic, no unwind)
        ),
        "VEV_4000": _override(
            ROUND_4["VEV_4000"], position_limit=300, strike=4000,
            **_r4_gamma_params(z_skip=0.5, with_iv_gate=False),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_4[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_r4_gamma_params(z_skip=0.5, with_iv_gate=True),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# v57 R4: + toxic flow + passive unwind (no 5300/5400)
MEMBER_OVERRIDES["r4_v57_best_ratio"] = {
    4: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_4["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V7_GUARDED_VELVET_PARAMS,
        ),
        "VEV_4000": _override(
            ROUND_4["VEV_4000"], position_limit=300, strike=4000,
            **_r4_gamma_params(z_skip=0.5, with_iv_gate=False),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_4[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_r4_gamma_params(z_skip=0.5, with_iv_gate=True),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        **{f"VEV_{k}": None for k in [5300, 5400, 5500, 6000, 6500]},
    },
}


# v58 R4: v57 + VEV_5300 (with iv_gate z=0.8)
MEMBER_OVERRIDES["r4_v58_balanced"] = {
    4: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_4["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V7_GUARDED_VELVET_PARAMS,
        ),
        "VEV_4000": _override(
            ROUND_4["VEV_4000"], position_limit=300, strike=4000,
            **_r4_gamma_params(z_skip=0.5, with_iv_gate=False),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_4[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_r4_gamma_params(z_skip=0.5, with_iv_gate=True),
            )
            for strike in [4500, 5000, 5100, 5200]
        },
        "VEV_5300": _override(
            ROUND_4["VEV_5300"], position_limit=300, strike=5300,
            **_r4_gamma_params(z_skip=0.8, with_iv_gate=True),
        ),
        **{f"VEV_{k}": None for k in [5400, 5500, 6000, 6500]},
    },
}


# v55 R4: full strikes 4000-5500 with per-strike z (Theo v6 thresholds)
_R4_THEO_V6_Z_SKIP = {4000: 1.5, 4500: 2.0, 5000: 1.0, 5100: 0.5, 5200: 2.0, 5300: 2.0, 5400: 1.0, 5500: 0.5}
MEMBER_OVERRIDES["r4_v55_full_strikes"] = {
    4: {
        "HYDROGEL_PACK": None,
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_4["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V7_GUARDED_VELVET_PARAMS,
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_4[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_r4_gamma_params(z_skip=_R4_THEO_V6_Z_SKIP[strike], with_iv_gate=False),
            )
            for strike in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500]
        },
        **{f"VEV_{k}": None for k in [6000, 6500]},
    },
}


# v62 R4 = current baseline = r4_velvet_options_only (Tibo's MM on 5200/5400)
# Already exists below


# r4_velvet_options_only — HYDROGEL DISABLED (was -104k in R4 D3)
MEMBER_OVERRIDES["r4_velvet_options_only"] = {
    4: {
        "HYDROGEL_PACK": None,  # ⚠️ disable — was bleeding -104k in R4 backtest
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_4["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V7_GUARDED_VELVET_PARAMS,
        ),
        "VEV_4000": _override(
            ROUND_4["VEV_4000"], position_limit=300, strike=4000,
            **_r4_gamma_params(z_skip=0.5, with_iv_gate=False),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_4[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_r4_gamma_params(z_skip=0.5, with_iv_gate=True),
            )
            for strike in [4500, 5000, 5100]
        },
        "VEV_5200": _r4_tibo_vev_mm(5200),
        "VEV_5300": _override(
            ROUND_4["VEV_5300"], position_limit=300, strike=5300,
            **_r4_gamma_params(z_skip=0.8, with_iv_gate=True),
        ),
        "VEV_5400": _r4_tibo_vev_mm(5400, prevent_crossing=True),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


# =============================================================================
# R4 EOD UNWIND — fix D3 last-5% crash (-53k bleed: VELVET drops 0.86%, options
# long bleed 30-50%). Adds end-of-day inventory unwind to baseline.
# Params:
#   eod_unwind_start_pct = 0.85     → start unwinding at 85% of day
#   eod_unwind_aggressive_pct = 0.93 → switch to aggressive (taker) at 93%
#   eod_unwind_full_flat_pct = 0.99 → target 0 position by 99%
# =============================================================================
_R4_EOD_PARAMS = dict(
    eod_unwind_start_pct=0.85,
    eod_unwind_aggressive_pct=0.93,
    eod_unwind_full_flat_pct=0.99,
)


def _with_eod(cfg):
    """Merge EOD params into an existing ProductConfig.params dict."""
    if cfg is None:
        return None
    new_params = dict(cfg.params)
    new_params.update(_R4_EOD_PARAMS)
    return _override(cfg, **new_params)


# r4_velvet_eod_v1 — baseline + EOD inventory unwind (last 15% of day = flatten)
MEMBER_OVERRIDES["r4_velvet_eod_v1"] = {
    4: {
        sym: _with_eod(cfg)
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_eod_aggressive — earlier start, more aggressive flatten
MEMBER_OVERRIDES["r4_velvet_eod_aggressive"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                eod_unwind_start_pct=0.75,
                eod_unwind_aggressive_pct=0.88,
                eod_unwind_full_flat_pct=0.97,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_eod_v4 — last 5% only (matches the D3 crash window exactly)
MEMBER_OVERRIDES["r4_velvet_eod_v4"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                eod_unwind_start_pct=0.95,
                eod_unwind_aggressive_pct=0.97,
                eod_unwind_full_flat_pct=0.995,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_eod_v5 — last 3% only (very late start, tries to capture max upside)
MEMBER_OVERRIDES["r4_velvet_eod_v5"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                eod_unwind_start_pct=0.97,
                eod_unwind_aggressive_pct=0.985,
                eod_unwind_full_flat_pct=0.998,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_eod_v1_trend — eod_v1 + trend_gate on VELVET (block BUYs when downtrend + already long)
MEMBER_OVERRIDES["r4_velvet_eod_v1_trend"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                eod_unwind_start_pct=0.85,
                eod_unwind_aggressive_pct=0.93,
                eod_unwind_full_flat_pct=0.99,
                trend_gate_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                trend_gate_long_block_pos=50,
                trend_ema_fast_alpha=0.05,
                trend_ema_slow_alpha=0.005,
                trend_threshold=1.0,
                trend_warmup_ticks=200,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_eod_conservative — only last 8% flatten
MEMBER_OVERRIDES["r4_velvet_eod_conservative"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                eod_unwind_start_pct=0.92,
                eod_unwind_aggressive_pct=0.96,
                eod_unwind_full_flat_pct=0.995,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# =============================================================================
# R4 CONDITIONAL VARIANTS (no time-based EOD) — react to market state
# =============================================================================

# r4_velvet_trend_only — baseline + trend gate on VELVET only (no EOD)
# Block BUYs when (EMA_fast - EMA_slow) < -trend_threshold AND position >= trend_gate_long_block_pos
MEMBER_OVERRIDES["r4_velvet_trend_only"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                trend_gate_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                trend_gate_long_block_pos=50,
                trend_ema_fast_alpha=0.05,
                trend_ema_slow_alpha=0.005,
                trend_threshold=0.5,        # lowered from 1.0 to actually fire
                trend_warmup_ticks=200,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_trend_aggressive — trend_only with threshold=0.3 (more sensitive)
MEMBER_OVERRIDES["r4_velvet_trend_aggressive"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                trend_gate_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                trend_gate_long_block_pos=30,
                trend_ema_fast_alpha=0.10,
                trend_ema_slow_alpha=0.01,
                trend_threshold=0.3,
                trend_warmup_ticks=100,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_stoploss_v1 — baseline + intraday stop-loss (per-product flatten on big drawdown)
# Stop-loss = 30k drawdown from per-product peak, min peak 5k before fires
MEMBER_OVERRIDES["r4_velvet_stoploss_v1"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                stop_loss_drawdown_pnl=30000,
                stop_loss_min_peak=5000,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_stoploss_tight — tighter 15k drawdown (more sensitive)
MEMBER_OVERRIDES["r4_velvet_stoploss_tight"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                stop_loss_drawdown_pnl=15000,
                stop_loss_min_peak=3000,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_dhedge_v1 — delta-hedge VELVET to net out option deltas
# When we're long calls, target VELVET position drifts negative (short underlying).
# Should auto-protect against the D3 crash (long calls + falling underlying = bleed).
MEMBER_OVERRIDES["r4_velvet_dhedge_v1"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                delta_hedge_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                delta_hedge_strength=1.0,        # full hedge
                delta_hedge_implied_vol=0.0125,  # match option prior_vol
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_dhedge_partial — half-hedge (50% of option delta)
MEMBER_OVERRIDES["r4_velvet_dhedge_partial"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                delta_hedge_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                delta_hedge_strength=0.5,
                delta_hedge_implied_vol=0.0125,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_vwap_gate — block BUYs when mid below rolling VWAP and already long
# Discovery: on D3, mid finishes -27 below VWAP(50k window) — clean trend signal
# that EMA fast/slow missed. Should protect against the D3 crash.
MEMBER_OVERRIDES["r4_velvet_vwap_gate"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                vwap_gate_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                vwap_gate_long_block_pos=50,
                vwap_threshold=8.0,
                vwap_min_volume=50.0,
                vwap_decay_alpha=0.005,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_vwap_gate_tight — tighter threshold (fires more often)
MEMBER_OVERRIDES["r4_velvet_vwap_gate_tight"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                vwap_gate_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                vwap_gate_long_block_pos=30,
                vwap_threshold=4.0,
                vwap_min_volume=30.0,
                vwap_decay_alpha=0.01,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cond_unwind — VWAP-triggered active unwind on VELVET only
# Tuned params for sparse VELVET trade flow (~0.65 qty/tick avg):
#   - min_vol = 0.1 (was 50, never fired)
#   - decay_alpha = 0.02 (faster EMA, ~35-tick half-life)
MEMBER_OVERRIDES["r4_velvet_cond_unwind"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                cond_unwind_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cond_unwind_min_pos=50,
                cond_unwind_chunk_pct=0.05,
                cond_unwind_use_vwap=True,
                vwap_threshold=8.0,
                vwap_min_volume=0.1,
                vwap_decay_alpha=0.02,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cond_unwind_strict — VWAP gate only fires if signal persistent (D3 only)
# Higher threshold (25) + longer rolling window (200000 = 20%) to suppress noise
MEMBER_OVERRIDES["r4_velvet_cond_unwind_strict"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                cond_unwind_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cond_unwind_min_pos=100,        # only fire when > 100 long
                cond_unwind_chunk_pct=0.03,
                cond_unwind_use_vwap=True,
                vwap_threshold=25.0,            # strict threshold (only crash signal)
                vwap_min_volume=50.0,
                vwap_window_ts=200000,          # 20% rolling window (less noisy)
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cond_unwind_aggressive — bigger unwind chunks (10%/tick)
MEMBER_OVERRIDES["r4_velvet_cond_unwind_aggressive"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                cond_unwind_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cond_unwind_min_pos=30,
                cond_unwind_chunk_pct=0.10,
                cond_unwind_use_vwap=True,
                vwap_threshold=4.0,
                vwap_min_volume=30.0,
                vwap_decay_alpha=0.01,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cond_unwind_all_products — also enabled on options (which got crushed on D3)
MEMBER_OVERRIDES["r4_velvet_cond_unwind_all"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                cond_unwind_enabled=True,  # All products
                cond_unwind_min_pos=50,
                cond_unwind_chunk_pct=0.05,
                cond_unwind_use_vwap=True,
                vwap_threshold=8.0,
                vwap_min_volume=50.0,
                vwap_decay_alpha=0.005,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# =============================================================================
# R4 COUNTERPARTY-BIAS VARIANTS — alpha from trader-flow lead-lag analysis
# Lead-lag analysis shows:
#   - Mark 55 + Mark 67 net flow predicts NEXT-50-tick return positively (rho +0.14, +0.12)
#   - Mark 01 + Mark 14 net flow predicts negatively (rho -0.17, -0.15) → FADE them
# Hit rates: Mark 55 BUY signal = 60% (n=57), Mark 67 BUY signal = 54% (n=59)
# =============================================================================

# r4_velvet_cp_bias_v1 — counterparty bias via DIRECT PRICE SHIFT (post-orders)
# Calibrated for actual signal magnitudes seen in data (5-30 typically per 100 ticks)
MEMBER_OVERRIDES["r4_velvet_cp_bias_v1"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,            # 100-tick rolling
                cp_signal_threshold=5.0,       # fire on modest flow
                cp_max_anchor_offset=2.0,      # cap shift at 2 ticks (avoid book crossing)
                cp_anchor_scale_per_unit=0.10, # 10 signal units = 1 tick shift
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cp_bias_aggressive — bigger shifts (3 ticks max)
MEMBER_OVERRIDES["r4_velvet_cp_bias_aggressive"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=3.0,       # fire on small flow
                cp_max_anchor_offset=3.0,
                cp_anchor_scale_per_unit=0.20, # 5 signal units = 1 tick shift
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cp_bias_long_window — longer rolling (300 ticks)
MEMBER_OVERRIDES["r4_velvet_cp_bias_long_window"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=30000,            # 300 ticks
                cp_signal_threshold=50.0,
                cp_max_anchor_offset=8.0,
                cp_anchor_scale_per_unit=0.06,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cp_bias_max — extreme params to verify signal does anything at all
MEMBER_OVERRIDES["r4_velvet_cp_bias_max"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=1.0,         # fire on any flow
                cp_max_anchor_offset=20.0,       # huge offset
                cp_anchor_scale_per_unit=1.0,    # 1 tick per unit signal
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cp_bias_fade_mark01 — fade Mark 01 ONLY (strongest signal: rho=-0.17, 77% fade hit)
MEMBER_OVERRIDES["r4_velvet_cp_bias_fade_mark01"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=3.0,
                cp_max_anchor_offset=3.0,
                cp_anchor_scale_per_unit=0.20,
                cp_trader_weights={"Mark 01": -1.0},  # Only fade Mark 01
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cp_bias_follow_mark55 — follow Mark 55 ONLY (rho=+0.14, 60% hit, n=57)
MEMBER_OVERRIDES["r4_velvet_cp_bias_follow_mark55"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=3.0,
                cp_max_anchor_offset=3.0,
                cp_anchor_scale_per_unit=0.20,
                cp_trader_weights={"Mark 55": 1.0},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cp_bias_fade_mark49 — fade Mark 49 (DIRECTIONAL SELLER, counterparty of Mark 67 ρ=-0.78)
MEMBER_OVERRIDES["r4_velvet_cp_bias_fade_mark49"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=3.0,
                cp_max_anchor_offset=3.0,
                cp_anchor_scale_per_unit=0.20,
                cp_trader_weights={"Mark 49": -1.0},  # Mark 49 sell → bullish
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cp_bias_fade_mark49_strong — same as fade_mark49 but bigger offset
MEMBER_OVERRIDES["r4_velvet_cp_bias_fade_mark49_strong"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=2.0,
                cp_max_anchor_offset=5.0,         # bigger cap
                cp_anchor_scale_per_unit=0.30,    # bigger scale
                cp_trader_weights={"Mark 49": -1.0},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cp_bias_fade_mark49_long — longer window (300 ticks)
MEMBER_OVERRIDES["r4_velvet_cp_bias_fade_mark49_long"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=30000,    # 300 ticks
                cp_signal_threshold=5.0,
                cp_max_anchor_offset=3.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cp_bias_fade_sellers — fade BOTH Mark 49 + Mark 22 (directional sellers)
MEMBER_OVERRIDES["r4_velvet_cp_bias_fade_sellers"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=3.0,
                cp_max_anchor_offset=3.0,
                cp_anchor_scale_per_unit=0.20,
                cp_trader_weights={"Mark 49": -1.0, "Mark 22": -1.0},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cp_bias_fade_mark49_tight — smaller threshold, smaller scale (capture more events)
MEMBER_OVERRIDES["r4_velvet_cp_bias_fade_mark49_tight"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cp_bias_fade_mark49_short_window — 50-tick window (faster reaction)
MEMBER_OVERRIDES["r4_velvet_cp_bias_fade_mark49_short_window"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=5000,
                cp_signal_threshold=2.0,
                cp_max_anchor_offset=3.0,
                cp_anchor_scale_per_unit=0.20,
                cp_trader_weights={"Mark 49": -1.0},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cp_bias_fade_mark67 — counter-test: fade Mark 67 (the WINNER 67% buyer)
# If Mark 67 buys → bias DOWN. Should LOSE because Mark 67 is the smart buyer.
MEMBER_OVERRIDES["r4_velvet_cp_bias_fade_mark67"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=3.0,
                cp_max_anchor_offset=3.0,
                cp_anchor_scale_per_unit=0.20,
                cp_trader_weights={"Mark 67": -1.0},  # Fade Mark 67
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_cp_bias_follow_mark49 — INVERSE of fade_mark49 — sanity check
MEMBER_OVERRIDES["r4_velvet_cp_bias_follow_mark49"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=3.0,
                cp_max_anchor_offset=3.0,
                cp_anchor_scale_per_unit=0.20,
                cp_trader_weights={"Mark 49": +1.0},  # Follow Mark 49 (should LOSE)
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_mark49_all — fade Mark 49 on VELVET + all VEV options
# Each product has its own per-product Mark 49 trades to track
MEMBER_OVERRIDES["r4_velvet_fade_mark49_all"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=True,
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_mark01_options — fade Mark 01 on options (he LOSES on VEV_5300/5400/5500)
# But Mark 01 is balanced MM on VELVET, so don't apply there
MEMBER_OVERRIDES["r4_velvet_fade_mark01_options"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym.startswith("VEV_")),  # ONLY options
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 01": -1.0},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_mark49_velvet_mark01_options — combine both winning fades
# fade_mark49 on VELVET (best signal there), fade_mark01 on options
MEMBER_OVERRIDES["r4_velvet_combo_fade"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=True,
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights=(
                    {"Mark 49": -1.0} if sym == "VELVETFRUIT_EXTRACT"
                    else {"Mark 01": -1.0}
                ),
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_49_14 — fade Mark 49 + fade Mark 14 (second weak fade signal)
MEMBER_OVERRIDES["r4_velvet_fade_49_14"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_49_01 — fade Mark 49 + fade Mark 01 (both negative-correlation fades)
MEMBER_OVERRIDES["r4_velvet_fade_49_01"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 01": -0.3},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_optimal_marks — use ALL signals with empirically-derived weights
# Weights = correlation rho (positive = follow, negative = fade)
MEMBER_OVERRIDES["r4_velvet_optimal_marks"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={
                    "Mark 55": +0.14,    # follow (rho=+0.14)
                    "Mark 67": +0.12,    # follow (rho=+0.12)
                    "Mark 01": -0.17,    # fade (rho=-0.17)
                    "Mark 14": -0.15,    # fade
                    "Mark 49": -1.0,    # fade Mark 49 (proven winner — strong weight)
                    "Mark 22": -0.06,    # weak fade
                },
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_49_14_balanced — equal weights on Mark 49 + Mark 14
MEMBER_OVERRIDES["r4_velvet_fade_49_14_balanced"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -1.0},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_49_14_22 — also add Mark 22 (the third seller)
MEMBER_OVERRIDES["r4_velvet_fade_49_14_22"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5, "Mark 22": -0.3},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_49_14_55 — fade Mark 49 + Mark 14 + Mark 55 (the high-vol losing MM)
MEMBER_OVERRIDES["r4_velvet_fade_49_14_55"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5, "Mark 55": -0.3},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_49_14_strong — bigger offset cap on the WIN
MEMBER_OVERRIDES["r4_velvet_fade_49_14_strong"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=4.0,
                cp_anchor_scale_per_unit=0.20,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_49_14_w03 — Mark 14 weight 0.3
MEMBER_OVERRIDES["r4_velvet_fade_49_14_w03"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.3},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_49_14_w07 — Mark 14 weight 0.7
MEMBER_OVERRIDES["r4_velvet_fade_49_14_w07"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.7},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_49_14_thresh2 — higher threshold (only fire on big signals)
MEMBER_OVERRIDES["r4_velvet_fade_49_14_thresh2"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=2.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_49_14_window200 — 200-tick window (doubled)
MEMBER_OVERRIDES["r4_velvet_fade_49_14_window200"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=20000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_49_14_cap1 — max offset 1 (smaller shift)
MEMBER_OVERRIDES["r4_velvet_fade_49_14_cap1"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=1.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_49_14_scale10 — smaller scale (less aggressive)
MEMBER_OVERRIDES["r4_velvet_fade_49_14_scale10"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.10,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade_49_14_scale20 — bigger scale
MEMBER_OVERRIDES["r4_velvet_fade_49_14_scale20"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=3.0, cp_anchor_scale_per_unit=0.20,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_per_product_fades — per-product Marks based on per-strike trader analysis
# VELVET: fade 49 + 14 (winning combo)
# VEV_4000: fade Mark 38 (he LOSES -7.5k vs Mark 14 +7.4k)
# VEV_5300/5400/5500: fade Mark 01 (he LOSES vs Mark 22)
def _per_product_cp_weights(sym):
    if sym == "VELVETFRUIT_EXTRACT":
        return {"Mark 49": -1.0, "Mark 14": -0.5}
    elif sym == "VEV_4000":
        return {"Mark 38": -1.0}
    elif sym in ("VEV_5300", "VEV_5400", "VEV_5500"):
        return {"Mark 01": -1.0}
    elif sym in ("VEV_6000", "VEV_6500"):
        return {"Mark 01": -1.0}  # mirror trade losers
    else:
        return None


MEMBER_OVERRIDES["r4_velvet_per_product_fades"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(_per_product_cp_weights(sym) is not None),
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights=(_per_product_cp_weights(sym) or {}),
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_per_product_velvet_only — same logic but ONLY VELVET (skip option fades to control)
MEMBER_OVERRIDES["r4_velvet_per_product_velvet_only"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade01_follow55 — based on PROPER short-term lead-lag analysis
# Mark 01 rho=-0.11 (fade), Mark 55 rho=+0.11 (follow)
MEMBER_OVERRIDES["r4_velvet_fade01_follow55"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 01": -1.0, "Mark 55": 1.0},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_fade01_follow55_vev5300 — also fade Mark 22 on VEV_5300 (rho -0.11)
def _vev5300_fade(sym):
    if sym == "VELVETFRUIT_EXTRACT":
        return {"Mark 01": -1.0, "Mark 55": 1.0}
    elif sym == "VEV_5300":
        return {"Mark 22": -1.0}
    return None


MEMBER_OVERRIDES["r4_velvet_per_product_v2"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(_vev5300_fade(sym) is not None),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights=(_vev5300_fade(sym) or {}),
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_combo_4_signals — combine fade_49_14 (which won) + fade_01 + follow_55
MEMBER_OVERRIDES["r4_velvet_combo_4_signals"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={
                    "Mark 49": -1.0,
                    "Mark 14": -0.5,
                    "Mark 01": -0.5,
                    "Mark 55": +0.5,
                },
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_obi_size_v1 — OBI size tilt on VELVET (not price)
# When OBI > 0.005: BUY orders get 1.5x size, SELL get 0.7x
# Captures alpha without spread cost from price tilt
MEMBER_OVERRIDES["r4_velvet_obi_size_v1"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_size_levels=3,
                obi_size_threshold=0.005,
                obi_size_boost_factor=1.5,
                obi_size_reduce_factor=0.7,
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_obi_size_aggressive — bigger boost (2x), bigger reduce (0.4x)
MEMBER_OVERRIDES["r4_velvet_obi_size_aggressive"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_size_levels=3,
                obi_size_threshold=0.003,
                obi_size_boost_factor=2.0,
                obi_size_reduce_factor=0.4,
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_combo_obi_fade — combine OBI size tilt + fade_49_14 price shift
MEMBER_OVERRIDES["r4_velvet_combo_obi_fade"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                # OBI size tilt
                obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_size_levels=3,
                obi_size_threshold=0.005,
                obi_size_boost_factor=1.5,
                obi_size_reduce_factor=0.7,
                # cp_bias fade_49_14 (kept from winning config)
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_combo_obi_fade_v2 — bigger OBI boost in combo
MEMBER_OVERRIDES["r4_velvet_combo_obi_fade_v2"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_size_levels=3,
                obi_size_threshold=0.003,        # lower threshold (more triggers)
                obi_size_boost_factor=2.0,       # 2x size boost
                obi_size_reduce_factor=0.5,      # 0.5x reduction
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_combo_obi_fade_options — also enable OBI on options
MEMBER_OVERRIDES["r4_velvet_combo_obi_fade_options"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_size_enabled=True,  # ALL products
                obi_size_levels=3,
                obi_size_threshold=0.005,
                obi_size_boost_factor=1.5,
                obi_size_reduce_factor=0.7,
                # cp_bias only on VELVET (Mark 49 doesn't trade options)
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_combo_obi_fade_w01 — combo + add Mark 01 fade (predicts D3 crash)
# Mark 01 BUYS heavily in D3 last 10% before the crash. Fade him.
MEMBER_OVERRIDES["r4_velvet_combo_obi_fade_w01"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_size_levels=3,
                obi_size_threshold=0.005,
                obi_size_boost_factor=1.5,
                obi_size_reduce_factor=0.7,
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5, "Mark 01": -0.3},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_combo_obi_fade_w01_strong — Mark 01 weight -0.5
MEMBER_OVERRIDES["r4_velvet_combo_obi_fade_w01_strong"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_size_levels=3,
                obi_size_threshold=0.005,
                obi_size_boost_factor=1.5,
                obi_size_reduce_factor=0.7,
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5, "Mark 01": -0.5},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_combo_obi_fade_w01_only_strong — only fade_01 + obi (drop 49+14)
MEMBER_OVERRIDES["r4_velvet_combo_obi_fade_w01_only"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_size_levels=3,
                obi_size_threshold=0.005,
                obi_size_boost_factor=1.5,
                obi_size_reduce_factor=0.7,
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 01": -1.0},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_combo_obi_fade_w01_w02 — Mark 01 weight -0.2
MEMBER_OVERRIDES["r4_velvet_combo_obi_fade_w01_w02"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_size_levels=3, obi_size_threshold=0.005,
                obi_size_boost_factor=1.5, obi_size_reduce_factor=0.7,
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5, "Mark 01": -0.2},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_combo_obi_fade_w01_w04 — Mark 01 weight -0.4
MEMBER_OVERRIDES["r4_velvet_combo_obi_fade_w01_w04"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_size_levels=3, obi_size_threshold=0.005,
                obi_size_boost_factor=1.5, obi_size_reduce_factor=0.7,
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5, "Mark 01": -0.4},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_combo_4marks — add Mark 67 follow (the smart buyer)
MEMBER_OVERRIDES["r4_velvet_combo_4marks"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_size_levels=3, obi_size_threshold=0.005,
                obi_size_boost_factor=1.5, obi_size_reduce_factor=0.7,
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5, "Mark 01": -0.3, "Mark 67": +0.3},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_combo_obi_fade_w01_thresh2 — fire less often (threshold 2.0)
MEMBER_OVERRIDES["r4_velvet_combo_obi_fade_w01_thresh2"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_size_levels=3, obi_size_threshold=0.005,
                obi_size_boost_factor=1.5, obi_size_reduce_factor=0.7,
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000, cp_signal_threshold=2.0,
                cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5, "Mark 01": -0.3},
            ) if cfg is not None else None
        ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_combo_w01_w015 / w025 — fine tune Mark 01 weight
def _make_combo_variant(name, w01):
    MEMBER_OVERRIDES[name] = {
        4: {
            sym: (
                _override(
                    cfg,
                    **dict(cfg.params),
                    obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                    obi_size_levels=3, obi_size_threshold=0.005,
                    obi_size_boost_factor=1.5, obi_size_reduce_factor=0.7,
                    counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                    cp_window_ts=10000, cp_signal_threshold=1.0,
                    cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                    cp_trader_weights={"Mark 49": -1.0, "Mark 14": -0.5, "Mark 01": w01},
                ) if cfg is not None else None
            ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
        },
    }


_make_combo_variant("r4_velvet_combo_w01_w015", -0.15)
_make_combo_variant("r4_velvet_combo_w01_w025", -0.25)
_make_combo_variant("r4_velvet_combo_w01_w010", -0.10)
_make_combo_variant("r4_velvet_combo_w01_w030", -0.30)


# r4_velvet_v4_plus_M22 — add Mark 22 fade to v4
def _v4_with_extras(weights):
    return {
        4: {
            sym: (
                _override(
                    cfg,
                    **dict(cfg.params),
                    obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                    obi_size_levels=3, obi_size_threshold=0.005,
                    obi_size_boost_factor=1.5, obi_size_reduce_factor=0.7,
                    counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                    cp_window_ts=10000, cp_signal_threshold=1.0,
                    cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                    cp_trader_weights=weights,
                ) if cfg is not None else None
            ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
        },
    }


MEMBER_OVERRIDES["r4_velvet_v4_plus_M22"] = _v4_with_extras({"Mark 49": -1.0, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.2})
MEMBER_OVERRIDES["r4_velvet_v4_plus_M55"] = _v4_with_extras({"Mark 49": -1.0, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 55": +0.2})
MEMBER_OVERRIDES["r4_velvet_v4_plus_M67"] = _v4_with_extras({"Mark 49": -1.0, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 67": +0.2})
MEMBER_OVERRIDES["r4_velvet_v4_M14_w03"] = _v4_with_extras({"Mark 49": -1.0, "Mark 14": -0.3, "Mark 01": -0.2})
MEMBER_OVERRIDES["r4_velvet_v4_M14_w07"] = _v4_with_extras({"Mark 49": -1.0, "Mark 14": -0.7, "Mark 01": -0.2})
MEMBER_OVERRIDES["r4_velvet_v4_M49_w08"] = _v4_with_extras({"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2})
MEMBER_OVERRIDES["r4_velvet_v4_M49_w12"] = _v4_with_extras({"Mark 49": -1.2, "Mark 14": -0.5, "Mark 01": -0.2})
MEMBER_OVERRIDES["r4_velvet_v4_M49_w15"] = _v4_with_extras({"Mark 49": -1.5, "Mark 14": -0.5, "Mark 01": -0.2})


# Tune Mark 49 weight more
MEMBER_OVERRIDES["r4_velvet_v4_M49_w06"] = _v4_with_extras({"Mark 49": -0.6, "Mark 14": -0.5, "Mark 01": -0.2})
MEMBER_OVERRIDES["r4_velvet_v4_M49_w07"] = _v4_with_extras({"Mark 49": -0.7, "Mark 14": -0.5, "Mark 01": -0.2})
MEMBER_OVERRIDES["r4_velvet_v4_M49_w09"] = _v4_with_extras({"Mark 49": -0.9, "Mark 14": -0.5, "Mark 01": -0.2})

# Combine M49=0.8 with other tunings
MEMBER_OVERRIDES["r4_velvet_v5_M49w08_M14w03"] = _v4_with_extras({"Mark 49": -0.8, "Mark 14": -0.3, "Mark 01": -0.2})
MEMBER_OVERRIDES["r4_velvet_v5_M49w08_M14w07"] = _v4_with_extras({"Mark 49": -0.8, "Mark 14": -0.7, "Mark 01": -0.2})
MEMBER_OVERRIDES["r4_velvet_v5_M49w08_M01w015"] = _v4_with_extras({"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.15})
MEMBER_OVERRIDES["r4_velvet_v5_M49w08_M01w025"] = _v4_with_extras({"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.25})


# r4_LIVE_ALPHA_PROBE_SHADOW — sit BEHIND queue (queue 2nd) to observe Mark 14/01 in action
MEMBER_OVERRIDES["r4_LIVE_ALPHA_PROBE_SHADOW"] = {
    4: {
        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT", strategy="live_alpha_probe_shadow",
            position_limit=200,
            params=dict(log_flush_ts=1000, ts_increment=100, last_ts_value=999900),
        ),
        "HYDROGEL_PACK": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# r4_LIVE_ALPHA_PROBE_ONOFF — 50t ON / 50t OFF cycles to capture natural Mark↔Mark flow
MEMBER_OVERRIDES["r4_LIVE_ALPHA_PROBE_ONOFF"] = {
    4: {
        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT", strategy="live_alpha_probe_onoff",
            position_limit=200,
            params=dict(log_flush_ts=1000, ts_increment=100, last_ts_value=999900),
        ),
        "HYDROGEL_PACK": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# r4_LIVE_ALPHA_PROBE_SIZE — cycle SIZE (1, 5, 30, 100, 200) at constant penny-improve price
MEMBER_OVERRIDES["r4_LIVE_ALPHA_PROBE_SIZE"] = {
    4: {
        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT", strategy="live_alpha_probe_size",
            position_limit=200,
            params=dict(log_flush_ts=1000, ts_increment=100, last_ts_value=999900),
        ),
        "HYDROGEL_PACK": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# r4_LIVE_ALPHA_PROBE_EXTREME — 5-phase provocative probe (RESEARCH)
# 1000 ticks split into 200-tick phases:
#   P1 DARK (no quotes) — baseline naturally trading
#   P2 TIGHT MM (penny-improve, size 30)
#   P3 MEGA BID (bid at mid+2, size 100, NO ASK) — provoke sellers
#   P4 MEGA ASK (ask at mid-2, size 100, NO BID) — provoke buyers
#   P5 NORMAL MM (penny-improve, size 30)
# Tracks per-phase per-Mark fills to surface hidden interactions
MEMBER_OVERRIDES["r4_LIVE_ALPHA_PROBE_EXTREME"] = {
    4: {
        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT",
            strategy="live_alpha_probe_extreme",
            position_limit=200,
            params=dict(
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=999900,
            ),
        ),
        "HYDROGEL_PACK": None,
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# r4_LIVE_ALPHA_PROBE — research-only submission to study LIVE counterparty patterns
# Use this in the LIVE round to capture per-Mark fill data, then iterate next round.
# Posts simple passive MM on VELVET (penny-improve), tracks who fills our quotes.
MEMBER_OVERRIDES["r4_LIVE_ALPHA_PROBE"] = {
    4: {
        "VELVETFRUIT_EXTRACT": ProductConfig(
            symbol="VELVETFRUIT_EXTRACT",
            strategy="live_alpha_probe",
            position_limit=200,
            params=dict(
                probe_size=30,
                log_flush_ts=1000,
                ts_increment=100,
                last_ts_value=999900,
            ),
        ),
        "HYDROGEL_PACK": None,  # skip, focus on VELVET
        **{f"VEV_{k}": None for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    },
}


# =============================================================================
# v6 EXPERIMENTS — derived from live probe analysis (PROBES_LIVE_ANALYSIS.md)
# =============================================================================

# v6.1 — v5 + Mark 55 fade (-0.3) — Mark 55 is NET SELLER in live (61-64% sells)
MEMBER_OVERRIDES["r4_v6_M55_fade"] = _v4_with_extras({
    "Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 55": -0.3
})

# v6.2 — v5 + Mark 67 follow (+0.2) — Mark 67 NEVER sells (pure buyer)
MEMBER_OVERRIDES["r4_v6_M67_follow"] = _v4_with_extras({
    "Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 67": +0.2
})

# v6.3 — v5 + Mark 22 fade (-0.3) — confirmed pure seller in live
MEMBER_OVERRIDES["r4_v6_M22_fade"] = _v4_with_extras({
    "Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.3
})

# v6.4 — combine all live insights: M55 fade + M67 follow + M22 fade
MEMBER_OVERRIDES["r4_v6_full_live"] = _v4_with_extras({
    "Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2,
    "Mark 55": -0.3, "Mark 67": +0.2, "Mark 22": -0.3,
})

# v6 with POSITION SKEW on options (fixes R3 stuck-long issue)
# When option position > +100, ask is shifted -1 tick (more aggressive sell)
# When position < -100, bid is shifted +1 tick (more aggressive buy)
def _v6_with_pos_skew(weights, skew_threshold=100, skew_offset=1):
    """v5 winning weights + position skew on ALL options (not VELVET)."""
    base = MEMBER_OVERRIDES["r4_velvet_options_only"][4]
    return {
        4: {
            sym: (
                _override(
                    cfg,
                    **dict(cfg.params),
                    obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                    obi_size_levels=3, obi_size_threshold=0.005,
                    obi_size_boost_factor=1.5, obi_size_reduce_factor=0.7,
                    counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                    cp_window_ts=10000, cp_signal_threshold=1.0,
                    cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                    cp_trader_weights=weights,
                    # Position skew ONLY on options
                    pos_skew_enabled=(sym.startswith("VEV_")),
                    pos_skew_threshold=skew_threshold,
                    pos_skew_offset=skew_offset,
                ) if cfg is not None else None
            ) for sym, cfg in base.items()
        },
    }


MEMBER_OVERRIDES["r4_v6_pos_skew_v5"] = _v6_with_pos_skew(
    {"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2}, 100, 1
)
MEMBER_OVERRIDES["r4_v6_pos_skew_aggressive"] = _v6_with_pos_skew(
    {"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2}, 50, 2
)
MEMBER_OVERRIDES["r4_v6_pos_skew_tight"] = _v6_with_pos_skew(
    {"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2}, 150, 1
)


# v6.5-v6.8 — Mark 14 fine-grid around -0.5
MEMBER_OVERRIDES["r4_v6_M14_w03"] = _v4_with_extras({"Mark 49": -0.8, "Mark 14": -0.3, "Mark 01": -0.2})
MEMBER_OVERRIDES["r4_v6_M14_w04"] = _v4_with_extras({"Mark 49": -0.8, "Mark 14": -0.4, "Mark 01": -0.2})
MEMBER_OVERRIDES["r4_v6_M14_w06"] = _v4_with_extras({"Mark 49": -0.8, "Mark 14": -0.6, "Mark 01": -0.2})
MEMBER_OVERRIDES["r4_v6_M14_w07"] = _v4_with_extras({"Mark 49": -0.8, "Mark 14": -0.7, "Mark 01": -0.2})


# v7 — Volume-conditional firing for Mark 49
# Idea: only apply Mark 49 fade when his rolling-window |volume| > z*std above mean.
# When Mark 49 is silent or trading small → 0 contribution (instead of -0.8 always).
# When Mark 49 dumps big (informed flow) → full -0.8 fade applies.
def _v7_conditional(cond_traders, zthresh=2.0, weights=None, baseline=0.0,
                    stats_window_ts=50000, min_samples=50):
    if weights is None:
        weights = {"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2}
    return {
        4: {
            sym: (
                _override(
                    cfg,
                    **dict(cfg.params),
                    obi_size_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                    obi_size_levels=3, obi_size_threshold=0.005,
                    obi_size_boost_factor=1.5, obi_size_reduce_factor=0.7,
                    counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                    cp_window_ts=10000, cp_signal_threshold=1.0,
                    cp_max_anchor_offset=2.0, cp_anchor_scale_per_unit=0.15,
                    cp_trader_weights=weights,
                    cp_conditional_traders=list(cond_traders),
                    cp_conditional_zthresh=zthresh,
                    cp_conditional_stats_window_ts=stats_window_ts,
                    cp_conditional_min_samples=min_samples,
                    cp_conditional_baseline_weight=baseline,
                ) if cfg is not None else None
            ) for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
        },
    }


# Conditional fire on Mark 49 only (the strongest signal, weight -0.8)
MEMBER_OVERRIDES["r4_v7_M49cond_z15"] = _v7_conditional(["Mark 49"], zthresh=1.5)
MEMBER_OVERRIDES["r4_v7_M49cond_z20"] = _v7_conditional(["Mark 49"], zthresh=2.0)
MEMBER_OVERRIDES["r4_v7_M49cond_z25"] = _v7_conditional(["Mark 49"], zthresh=2.5)

# Conditional fire on Mark 49 with longer history window (1000 ticks)
MEMBER_OVERRIDES["r4_v7_M49cond_z20_w100k"] = _v7_conditional(
    ["Mark 49"], zthresh=2.0, stats_window_ts=100000
)

# Conditional fire on Mark 14 too (in case Mark 14 also has bursts)
MEMBER_OVERRIDES["r4_v7_M49M14cond_z20"] = _v7_conditional(
    ["Mark 49", "Mark 14"], zthresh=2.0
)

# Conditional with soft baseline (z below threshold → -0.2 instead of 0)
MEMBER_OVERRIDES["r4_v7_M49cond_z20_soft"] = _v7_conditional(
    ["Mark 49"], zthresh=2.0, baseline=-0.2
)


# v8 — ADD Mark 67 follow conditionally on top of v5 weights
# Hypothesis: Mark 67 is PURE BUYER. Most of the time he doesn't trade.
# When he does trade BIG, that's informed flow worth following.
# Approach: weight +1.0 (conditional) — fires only when |vol| > z*sigma above mean.
MEMBER_OVERRIDES["r4_v8_M67cond_z20"] = _v7_conditional(
    ["Mark 67"], zthresh=2.0,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 67": +1.0}
)
MEMBER_OVERRIDES["r4_v8_M67cond_z15"] = _v7_conditional(
    ["Mark 67"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 67": +1.0}
)
MEMBER_OVERRIDES["r4_v8_M67cond_z25"] = _v7_conditional(
    ["Mark 67"], zthresh=2.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 67": +1.0}
)

# v8b — ADD Mark 22 fade conditionally (Mark 22 is PURE SELLER)
# When he dumps anomalously hard, fade with -0.5
MEMBER_OVERRIDES["r4_v8_M22cond_z20"] = _v7_conditional(
    ["Mark 22"], zthresh=2.0,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.5}
)

# v8c — Combine M67 follow + M22 fade, both conditional
MEMBER_OVERRIDES["r4_v8_M67M22cond_z20"] = _v7_conditional(
    ["Mark 67", "Mark 22"], zthresh=2.0,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2,
             "Mark 67": +1.0, "Mark 22": -0.5}
)

# v8d — Lower weight for follow signal (less aggressive)
MEMBER_OVERRIDES["r4_v8_M67cond_z20_w05"] = _v7_conditional(
    ["Mark 67"], zthresh=2.0,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 67": +0.5}
)

# v8e — M22 fade variants (M22cond_z20 was +581 vs v5)
MEMBER_OVERRIDES["r4_v8_M22cond_z15"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.5}
)
MEMBER_OVERRIDES["r4_v8_M22cond_z25"] = _v7_conditional(
    ["Mark 22"], zthresh=2.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.5}
)
MEMBER_OVERRIDES["r4_v8_M22cond_z20_w03"] = _v7_conditional(
    ["Mark 22"], zthresh=2.0,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.3}
)
MEMBER_OVERRIDES["r4_v8_M22cond_z20_w07"] = _v7_conditional(
    ["Mark 22"], zthresh=2.0,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.7}
)
MEMBER_OVERRIDES["r4_v8_M22cond_z20_w10"] = _v7_conditional(
    ["Mark 22"], zthresh=2.0,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -1.0}
)
# Soft baseline: M22 weight = -0.2 always, ramps to -0.5 when anomalous
MEMBER_OVERRIDES["r4_v8_M22cond_z20_soft"] = _v7_conditional(
    ["Mark 22"], zthresh=2.0, baseline=-0.2,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.5}
)
# Always-on M22 fade (no conditional) — does the conditional matter?
MEMBER_OVERRIDES["r4_v8_M22_always"] = _v4_with_extras({
    "Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.5
})

# v9 — Fine-tune around the M22cond_z20_w03 winner (+1,281 PnL)
# Best so far: cond_traders=["Mark 22"] z=2.0 weight={M22:-0.3}
MEMBER_OVERRIDES["r4_v9_M22cond_z15_w03"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.3}
)
MEMBER_OVERRIDES["r4_v9_M22cond_z18_w03"] = _v7_conditional(
    ["Mark 22"], zthresh=1.8,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.3}
)
MEMBER_OVERRIDES["r4_v9_M22cond_z25_w03"] = _v7_conditional(
    ["Mark 22"], zthresh=2.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.3}
)
MEMBER_OVERRIDES["r4_v9_M22cond_z20_w025"] = _v7_conditional(
    ["Mark 22"], zthresh=2.0,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.25}
)
MEMBER_OVERRIDES["r4_v9_M22cond_z20_w035"] = _v7_conditional(
    ["Mark 22"], zthresh=2.0,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.35}
)
MEMBER_OVERRIDES["r4_v9_M22cond_z20_w04"] = _v7_conditional(
    ["Mark 22"], zthresh=2.0,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4}
)

# v9b — Even looser threshold variants (z=1.5 w=-0.3 was the new best)
MEMBER_OVERRIDES["r4_v9_M22cond_z10_w03"] = _v7_conditional(
    ["Mark 22"], zthresh=1.0,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.3}
)
MEMBER_OVERRIDES["r4_v9_M22cond_z12_w03"] = _v7_conditional(
    ["Mark 22"], zthresh=1.2,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.3}
)
MEMBER_OVERRIDES["r4_v9_M22cond_z15_w035"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.35}
)
MEMBER_OVERRIDES["r4_v9_M22cond_z15_w04"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4}
)
MEMBER_OVERRIDES["r4_v9_M22cond_z15_w025"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.25}
)


# v10 — REDUCED position_limits on stuck-long options (structural fix, non-overfit).
# Day 3 PnL on options is -7,335 because all option positions end LONG.
# Reducing limit from 300 to 150 on the most-stuck options halves the delta exposure.
def _v10_with_options_limit(option_limit_overrides):
    """v9 config + override position_limit on specific options."""
    base = MEMBER_OVERRIDES["r4_v9_M22cond_z15_w04"][4]
    return {
        4: {
            sym: (
                _override(
                    cfg,
                    **{k: v for k, v in cfg.params.items() if k != "position_limit"},
                    position_limit=option_limit_overrides.get(sym, cfg.position_limit),
                ) if cfg is not None else None
            ) for sym, cfg in base.items()
        }
    }


# Reduce the worst-stuck options (5100, 5200) from 300 → 150
MEMBER_OVERRIDES["r4_v10_lim150_5100_5200"] = _v10_with_options_limit({
    "VEV_5100": 150, "VEV_5200": 150,
})

# More aggressive: reduce to 100 for all VEV_5xxx
MEMBER_OVERRIDES["r4_v10_lim100_all5xxx"] = _v10_with_options_limit({
    "VEV_5000": 100, "VEV_5100": 100, "VEV_5200": 100,
    "VEV_5300": 100, "VEV_5400": 100,
})

# Conservative: just lower VEV_5100/5200 to 200 (the most stuck)
MEMBER_OVERRIDES["r4_v10_lim200_5100_5200"] = _v10_with_options_limit({
    "VEV_5100": 200, "VEV_5200": 200,
})

# Full options reduction to 200
MEMBER_OVERRIDES["r4_v10_lim200_all5xxx"] = _v10_with_options_limit({
    "VEV_5000": 200, "VEV_5100": 200, "VEV_5200": 200,
    "VEV_5300": 200, "VEV_5400": 200,
})


# v11 — Add TINY live-tune weights (M55=-0.05, M67=+0.05) — neutrality check.
# Live data showed M55 net seller, M67 pure buyer. Backtest data is balanced.
# If tiny weights don't impact backtest PnL, keep them as "ready to scale" for live.
MEMBER_OVERRIDES["r4_v11_v9_plus_M55_M67_tiny"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4,
             "Mark 55": -0.05, "Mark 67": +0.05}
)
MEMBER_OVERRIDES["r4_v11_v9_plus_M55_only_tiny"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4,
             "Mark 55": -0.1}
)
MEMBER_OVERRIDES["r4_v11_v9_plus_M67_only_tiny"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4,
             "Mark 67": +0.1}
)

# v11b — Conditional with HIGH zthresh on M55/M67 — should be near-neutral on backtest
# but ready to fire if LIVE shows different (rarer) anomalies than historical.
MEMBER_OVERRIDES["r4_v11_M22_M55cond_z30"] = _v7_conditional(
    ["Mark 22", "Mark 55"], zthresh=3.0,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4,
             "Mark 55": -0.5}
)
MEMBER_OVERRIDES["r4_v11_M22_M67cond_z30"] = _v7_conditional(
    ["Mark 22", "Mark 67"], zthresh=3.0,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4,
             "Mark 67": +0.5}
)
# Note: this requires v7 conditional with PER-TRADER zthresh (not implemented yet).
# For now, both M22 and M55 share zthresh=3.0 which is too strict for M22 (was 1.5).
# So this variant LIKELY underperforms even v9. Need per-trader thresholds.

# Cleaner: set very small absolute weights (1/10 of "tiny")
MEMBER_OVERRIDES["r4_v11_M22_M55_M67_micro"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4,
             "Mark 55": -0.01, "Mark 67": +0.01}
)
MEMBER_OVERRIDES["r4_v11_M22_M55_micro"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4,
             "Mark 55": -0.01}
)
MEMBER_OVERRIDES["r4_v11_M22_M67_micro"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4,
             "Mark 67": +0.01}
)


# v12 — Trader-PnL-driven weights (TRADE LIKE THE WINNERS)
# DATA-DRIVEN finding from scripts/trader_alpha_hunt.py:
#   Mark 14 = INFORMED (+49,713 implied PnL, +22.89/trade) ← we were FADING this!
#   Mark 01 = INFORMED (+10,278 / +5.58)                    ← we were fading
#   Mark 67 = INFORMED (+1,746 / +10.58)                    ← we ignore
#   Mark 49 = noise/loses (-1,190 / -9.75)                   ← keep fading (correct)
#   Mark 22 = noise/loses (-3,688 / -2.33)                   ← keep fading (correct)
#   Mark 55 = noise (-13,204 / -11.02)                       ← could fade
#   Mark 38 = ANTI-INFO (-43,656 / -29.54)                   ← FADE HARD (we ignore!)

# v12a — INVERSE Mark 14 (FOLLOW informed instead of FADE)
MEMBER_OVERRIDES["r4_v12_M14_follow_w05"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": +0.5, "Mark 01": -0.2, "Mark 22": -0.4}
)
MEMBER_OVERRIDES["r4_v12_M14_follow_w03"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": +0.3, "Mark 01": -0.2, "Mark 22": -0.4}
)
MEMBER_OVERRIDES["r4_v12_M14_neutral"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": 0.0, "Mark 01": -0.2, "Mark 22": -0.4}
)

# v12b — INVERSE Mark 01 too (also informed, was being faded)
MEMBER_OVERRIDES["r4_v12_M14_M01_follow"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": +0.5, "Mark 01": +0.2, "Mark 22": -0.4}
)

# v12c — ADD Mark 38 fade (the worst trader, was ignored)
MEMBER_OVERRIDES["r4_v12_M38_fade_w05"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4,
             "Mark 38": -0.5}
)
MEMBER_OVERRIDES["r4_v12_M38_fade_w08"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4,
             "Mark 38": -0.8}
)

# v12d — Full data-driven weights: follow informed + fade noise
MEMBER_OVERRIDES["r4_v12_data_driven"] = _v7_conditional(
    ["Mark 22"], zthresh=1.5,
    weights={
        "Mark 14": +0.5,   # follow (top informed)
        "Mark 01": +0.2,   # follow (informed)
        "Mark 67": +0.3,   # follow (informed)
        "Mark 49": -0.8,   # fade (noise — keep)
        "Mark 22": -0.4,   # fade conditional (keep)
        "Mark 38": -0.8,   # fade (worst trader)
        "Mark 55": -0.3,   # fade (noise)
    }
)


# ═══════════════════════════════════════════════════════════════
# v13 — PER-PRODUCT cp_bias weights (the user-requested feature)
# ═══════════════════════════════════════════════════════════════
# Insight: Mark 14 informed on HYDRO/VEV_4000/VELVET, but FADING him on VELVET
# wins (because we're MM passive — when M14 buys, we sell into him before drift).
# Mark 38 ONLY trades HYDRO + VEV_4000 (worthless on VELVET).
# Mark 01 ↔ Mark 22 dyad on VEV_5300+ : Mark 01 buys deep OTM, Mark 22 sells.
#
# Per-product weights from data (and adjusted for our MM dynamics):
#   HYDRO:    Mark 14 +0.5 (follow informed), Mark 38 -0.5 (fade worst)
#   VEV_4000: Mark 14 +0.5 (follow), Mark 38 -0.5 (fade)
#   VEV_5xxx: Mark 01 +0.3 (follow informed), Mark 22 -0.3 (fade noise)
#   VELVET:   keep v9 weights — fade makes more sense in MM passive context
#
# Overlay: _apply_cp_bias in base.py applies these per-product when
#          counterparty_bias_enabled is True for that product.

def _v13_per_product_weights(velvet_weights, hydro_weights, vev4000_weights,
                             vev5xxx_weights, deep_otm_weights):
    """Build a member config with per-product cp_bias weights.

    Args:
      velvet_weights: dict trader -> weight applied to VELVET
      hydro_weights: dict trader -> weight applied to HYDROGEL_PACK
      vev4000_weights: dict trader -> weight applied to VEV_4000 / VEV_4500
      vev5xxx_weights: dict trader -> weight applied to VEV_5000-5400
      deep_otm_weights: dict trader -> weight applied to VEV_5500/6000/6500

    Re-uses v9 base (M22 conditional fade z=1.5 w=-0.4) for VELVET.
    """
    # Start from v9 base (which has VELVET cp_bias setup)
    base_v9 = _v7_conditional(
        ["Mark 22"], zthresh=1.5,
        weights=velvet_weights,
    )[4]

    out = {}
    for sym, cfg in base_v9.items():
        if cfg is None:
            out[sym] = None
            continue
        # Choose product-specific weights
        if sym == "VELVETFRUIT_EXTRACT":
            # already configured by _v7_conditional
            out[sym] = cfg
            continue
        if sym == "HYDROGEL_PACK":
            w = hydro_weights
        elif sym in ("VEV_4000", "VEV_4500"):
            w = vev4000_weights
        elif sym in ("VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400"):
            w = vev5xxx_weights
        elif sym in ("VEV_5500", "VEV_6000", "VEV_6500"):
            w = deep_otm_weights
        else:
            w = None
        if w:
            params = {k: v for k, v in cfg.params.items()
                      if k not in ("position_limit", "counterparty_bias_enabled",
                                   "cp_window_ts", "cp_signal_threshold",
                                   "cp_max_anchor_offset", "cp_anchor_scale_per_unit",
                                   "cp_trader_weights")}
            out[sym] = _override(
                cfg,
                **params,
                counterparty_bias_enabled=True,
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights=w,
            )
        else:
            out[sym] = cfg
    return {4: out}


# v13a — base case: enable cp_bias on options with light per-product weights
MEMBER_OVERRIDES["r4_v13_per_product_v1"] = _v13_per_product_weights(
    velvet_weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4},
    hydro_weights={"Mark 14": +0.5, "Mark 38": -0.5},  # follow M14, fade M38
    vev4000_weights={"Mark 14": +0.3, "Mark 38": -0.3},
    vev5xxx_weights={"Mark 01": +0.3, "Mark 22": -0.3, "Mark 14": +0.2},
    deep_otm_weights={"Mark 01": +0.3, "Mark 22": -0.3},
)

# v13b — same but FADE Mark 14 (consistent with v9 finding)
MEMBER_OVERRIDES["r4_v13_per_product_M14_fade"] = _v13_per_product_weights(
    velvet_weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4},
    hydro_weights={"Mark 14": -0.5, "Mark 38": -0.5},  # both faded
    vev4000_weights={"Mark 14": -0.3, "Mark 38": -0.3},
    vev5xxx_weights={"Mark 01": -0.3, "Mark 22": -0.3},
    deep_otm_weights={"Mark 01": -0.3, "Mark 22": -0.3},
)

# v13c — only options (skip HYDRO since it's currently None=disabled)
MEMBER_OVERRIDES["r4_v13_options_only_follow"] = _v13_per_product_weights(
    velvet_weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4},
    hydro_weights={},  # HYDROGEL is None anyway
    vev4000_weights={"Mark 14": +0.3, "Mark 38": -0.3},
    vev5xxx_weights={"Mark 01": +0.3, "Mark 22": -0.3},
    deep_otm_weights={"Mark 01": +0.3, "Mark 22": -0.3},
)

# v13d — only options FADE both (test that fade dominates again)
MEMBER_OVERRIDES["r4_v13_options_only_fade"] = _v13_per_product_weights(
    velvet_weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4},
    hydro_weights={},
    vev4000_weights={"Mark 14": -0.3, "Mark 38": -0.3},
    vev5xxx_weights={"Mark 01": -0.3, "Mark 22": -0.3},
    deep_otm_weights={"Mark 01": -0.3, "Mark 22": -0.3},
)

# v13e — options TINY (almost neutral, just for safety check that overlay works)
MEMBER_OVERRIDES["r4_v13_options_tiny"] = _v13_per_product_weights(
    velvet_weights={"Mark 49": -0.8, "Mark 14": -0.5, "Mark 01": -0.2, "Mark 22": -0.4},
    hydro_weights={},
    vev4000_weights={"Mark 14": +0.05, "Mark 38": -0.05},
    vev5xxx_weights={"Mark 01": +0.05, "Mark 22": -0.05},
    deep_otm_weights={"Mark 01": +0.05, "Mark 22": -0.05},
)


# ═══════════════════════════════════════════════════════════════
# v14 — RE-ENABLE HYDROGEL with cp_bias on Mark 14 / Mark 38 dyad
# ═══════════════════════════════════════════════════════════════
# HYDROGEL was disabled (-104k in R4 D3 without cp_bias).
# But Mark 14 makes +34,581 and Mark 38 loses -34,466 on HYDRO.
# If we MM with bias toward following M14 / fading M38, we may capture spread + dyad alpha.

def _v14_with_hydro(hydro_weights, hydro_signal_threshold=1.0,
                    hydro_max_offset=2.0, hydro_scale=0.15):
    """v9 base + HYDROGEL_PACK enabled with mm_first_v4_combo + cp_bias."""
    base = MEMBER_OVERRIDES["r4_v9_M22cond_z15_w04"][4]
    out = dict(base)
    # Enable HYDROGEL with the v4_F5 template, plus cp_bias
    hydro_cfg = _override(
        ROUND_3["HYDROGEL_PACK"],
        strategy="mm_first_v4_combo",
        position_limit=80,
        **_R3_HYDROGEL_PARAMS,
        counterparty_bias_enabled=True,
        cp_window_ts=10000,
        cp_signal_threshold=hydro_signal_threshold,
        cp_max_anchor_offset=hydro_max_offset,
        cp_anchor_scale_per_unit=hydro_scale,
        cp_trader_weights=hydro_weights,
    )
    out["HYDROGEL_PACK"] = hydro_cfg
    return {4: out}


# v14a — HYDRO enabled with M14 follow + M38 fade
MEMBER_OVERRIDES["r4_v14_hydro_M14p5_M38m5"] = _v14_with_hydro({
    "Mark 14": +0.5, "Mark 38": -0.5,
})

# v14b — only fade Mark 38 (don't follow Mark 14, just fade the loser)
MEMBER_OVERRIDES["r4_v14_hydro_M38_only"] = _v14_with_hydro({
    "Mark 38": -0.5,
})

# v14c — only follow Mark 14 (don't fade Mark 38)
MEMBER_OVERRIDES["r4_v14_hydro_M14_only"] = _v14_with_hydro({
    "Mark 14": +0.5,
})

# v14d — both fade (consistent with v9 M14 fade finding)
MEMBER_OVERRIDES["r4_v14_hydro_both_fade"] = _v14_with_hydro({
    "Mark 14": -0.5, "Mark 38": -0.5,
})

# v14e — HYDRO without cp_bias — baseline measurement (for sanity)
MEMBER_OVERRIDES["r4_v14_hydro_no_cp_bias"] = _v14_with_hydro({})  # empty weights = no signal


# ═══════════════════════════════════════════════════════════════
# v15 — ENABLE deep OTM options VEV_5500/6000/6500
# ═══════════════════════════════════════════════════════════════
# Mark 01 ↔ Mark 22 dyad on these strikes:
#   VEV_5500: M01 +1042 BUYS, M22 -1069 SELLS
#   VEV_6000: M01 +1105 BUYS, M22 -1105 SELLS
#   VEV_6500: M01 +1105 BUYS, M22 -1105 SELLS
# These options are cheap (price 1-5 ticks) but flow is HUGE.
# Test: enable as passive MM with cp_bias following M01 / fading M22.

def _v15_with_deep_otm(deep_otm_weights, deep_otm_size=20, deep_otm_edge=1):
    """v9 base + VEV_5500/6000/6500 enabled with passive MM strategy + cp_bias."""
    base = MEMBER_OVERRIDES["r4_v9_M22cond_z15_w04"][4]
    out = dict(base)
    for strike in [5500, 6000, 6500]:
        sym = f"VEV_{strike}"
        cfg = _r3_v24_passive_option(
            strike,
            maker_size=deep_otm_size,
            maker_edge=deep_otm_edge,
            min_quote_price=1.0,
            use_smile=False,
        )
        params = dict(cfg.params)
        params.pop("position_limit", None)
        if deep_otm_weights:
            cfg_with_cp = _override(
                cfg,
                **params,
                position_limit=cfg.position_limit,
                counterparty_bias_enabled=True,
                cp_window_ts=10000,
                cp_signal_threshold=1.0,
                cp_max_anchor_offset=2.0,
                cp_anchor_scale_per_unit=0.15,
                cp_trader_weights=deep_otm_weights,
            )
        else:
            cfg_with_cp = cfg
        out[sym] = cfg_with_cp
    return {4: out}


# v15a — deep OTM with cp_bias: follow M01, fade M22
MEMBER_OVERRIDES["r4_v15_deep_otm_M01p3_M22m3"] = _v15_with_deep_otm({
    "Mark 01": +0.3, "Mark 22": -0.3,
})

# v15b — deep OTM without cp_bias (baseline test of the strategy alone)
MEMBER_OVERRIDES["r4_v15_deep_otm_no_cp"] = _v15_with_deep_otm({})

# v15c — deep OTM with stronger weights
MEMBER_OVERRIDES["r4_v15_deep_otm_strong"] = _v15_with_deep_otm({
    "Mark 01": +0.5, "Mark 22": -0.5,
})

# v15d — deep OTM with smaller maker_size (less risk)
MEMBER_OVERRIDES["r4_v15_deep_otm_size10"] = _v15_with_deep_otm(
    {"Mark 01": +0.3, "Mark 22": -0.3}, deep_otm_size=10
)

# v15e — deep OTM larger maker_edge (only fill on bigger moves)
MEMBER_OVERRIDES["r4_v15_deep_otm_edge2"] = _v15_with_deep_otm(
    {"Mark 01": +0.3, "Mark 22": -0.3}, deep_otm_edge=2
)


# ═══════════════════════════════════════════════════════════════
# v16 — INVENTORY-BASED UNWIND on options (non-overfit risk mgmt)
# ═══════════════════════════════════════════════════════════════
# Issue: VEV_5100/5200/4000 stuck at +300 (max) on all 3 days.
# Solution: when |pos| > 80% limit, add takers to reduce toward 50%.
# This is RISK-management, not time-tuning.

def _v16_with_inv_unwind(threshold_pct=0.8, target_pct=0.5, max_per_tick=10,
                          apply_to_velvet=False):
    """v9 base + inventory unwind on all options (and optionally VELVET)."""
    base = MEMBER_OVERRIDES["r4_v9_M22cond_z15_w04"][4]
    out = {}
    for sym, cfg in base.items():
        if cfg is None:
            out[sym] = None
            continue
        if sym.startswith("VEV_") or (apply_to_velvet and sym == "VELVETFRUIT_EXTRACT"):
            params = {k: v for k, v in cfg.params.items()
                      if k not in ("position_limit", "inv_unwind_enabled",
                                   "inv_unwind_threshold_pct", "inv_unwind_target_pct",
                                   "inv_unwind_max_per_tick")}
            out[sym] = _override(
                cfg,
                **params,
                inv_unwind_enabled=True,
                inv_unwind_threshold_pct=threshold_pct,
                inv_unwind_target_pct=target_pct,
                inv_unwind_max_per_tick=max_per_tick,
            )
        else:
            out[sym] = cfg
    return {4: out}


# v16a — moderate: fire at 80%, target 50%, 10/tick
MEMBER_OVERRIDES["r4_v16_unwind_80_50_10"] = _v16_with_inv_unwind(0.8, 0.5, 10)

# v16b — earlier kick-in (70%)
MEMBER_OVERRIDES["r4_v16_unwind_70_50_10"] = _v16_with_inv_unwind(0.7, 0.5, 10)

# v16c — aggressive: fire at 60%, target 30%, 20/tick
MEMBER_OVERRIDES["r4_v16_unwind_60_30_20"] = _v16_with_inv_unwind(0.6, 0.3, 20)

# v16d — very late kick-in (90%) — only avoid hitting limit
MEMBER_OVERRIDES["r4_v16_unwind_90_70_5"] = _v16_with_inv_unwind(0.9, 0.7, 5)

# v16e — soft: 80%/60%/5 (gentle, low fill rate)
MEMBER_OVERRIDES["r4_v16_unwind_80_60_5"] = _v16_with_inv_unwind(0.8, 0.6, 5)

# v16f — ALSO apply on VELVET (shouldn't matter, VELVET balanced already)
MEMBER_OVERRIDES["r4_v16_unwind_all_80_50_10"] = _v16_with_inv_unwind(
    0.8, 0.5, 10, apply_to_velvet=True
)


# ═══════════════════════════════════════════════════════════════
# v17 — PASSIVE INVENTORY UNWIND (capture spread instead of pay)
# ═══════════════════════════════════════════════════════════════
# v16 used takers (pay spread) → DD reduced but PnL chute too.
# v17: post a PASSIVE order on the unwind side. If filled → unwind at gain.
# If not filled → no cost. Best of both worlds (in theory).

def _v17_with_passive_unwind(threshold_pct=0.7, target_pct=0.5,
                               passive_size=30, passive_offset=0):
    """v9 base + passive inventory unwind on options."""
    base = MEMBER_OVERRIDES["r4_v9_M22cond_z15_w04"][4]
    out = {}
    for sym, cfg in base.items():
        if cfg is None:
            out[sym] = None
            continue
        if sym.startswith("VEV_"):
            params = {k: v for k, v in cfg.params.items()
                      if k not in ("position_limit", "inv_unwind_enabled",
                                   "inv_unwind_threshold_pct", "inv_unwind_target_pct",
                                   "inv_unwind_max_per_tick", "inv_unwind_mode",
                                   "inv_unwind_passive_size", "inv_unwind_passive_offset")}
            out[sym] = _override(
                cfg,
                **params,
                inv_unwind_enabled=True,
                inv_unwind_threshold_pct=threshold_pct,
                inv_unwind_target_pct=target_pct,
                inv_unwind_max_per_tick=10,
                inv_unwind_mode="passive",
                inv_unwind_passive_size=passive_size,
                inv_unwind_passive_offset=passive_offset,
            )
        else:
            out[sym] = cfg
    return {4: out}


# v17a — passive unwind at best_opposite (no improve)
MEMBER_OVERRIDES["r4_v17_passive_70_50"] = _v17_with_passive_unwind(0.7, 0.5)

# v17b — passive at best_opposite-1 (penny-improve, more aggressive but capture spread)
MEMBER_OVERRIDES["r4_v17_passive_70_50_pi"] = _v17_with_passive_unwind(0.7, 0.5, passive_offset=-1)

# v17c — earlier kick-in 60%
MEMBER_OVERRIDES["r4_v17_passive_60_40"] = _v17_with_passive_unwind(0.6, 0.4)

# v17d — both modes (taker + passive in same tick)
def _v17_both_mode(threshold_pct=0.8, target_pct=0.5, max_taker=5, passive_size=30):
    base = MEMBER_OVERRIDES["r4_v9_M22cond_z15_w04"][4]
    out = {}
    for sym, cfg in base.items():
        if cfg is None:
            out[sym] = None
            continue
        if sym.startswith("VEV_"):
            params = {k: v for k, v in cfg.params.items()
                      if k not in ("position_limit", "inv_unwind_enabled",
                                   "inv_unwind_threshold_pct", "inv_unwind_target_pct",
                                   "inv_unwind_max_per_tick", "inv_unwind_mode",
                                   "inv_unwind_passive_size", "inv_unwind_passive_offset")}
            out[sym] = _override(
                cfg,
                **params,
                inv_unwind_enabled=True,
                inv_unwind_threshold_pct=threshold_pct,
                inv_unwind_target_pct=target_pct,
                inv_unwind_max_per_tick=max_taker,
                inv_unwind_mode="both",
                inv_unwind_passive_size=passive_size,
                inv_unwind_passive_offset=0,
            )
        else:
            out[sym] = cfg
    return {4: out}


MEMBER_OVERRIDES["r4_v17_both_80_50"] = _v17_both_mode(0.8, 0.5, max_taker=5, passive_size=30)
MEMBER_OVERRIDES["r4_v17_both_70_50"] = _v17_both_mode(0.7, 0.5, max_taker=5, passive_size=30)


# ═══════════════════════════════════════════════════════════════
# v18 — EXTEND inventory unwind to VELVET (current champion only has it on options)
# ═══════════════════════════════════════════════════════════════
# v17b VELVET is hitting 197-198 / 200 = 98.5% of limit on all 3 days.
# Add passive penny-improve unwind on VELVET too. Params adapted for VELVET
# (more frequent trades, balanced flow → can use earlier kick-in safely).

def _v18_with_velvet_unwind(velvet_threshold=0.7, velvet_target=0.5,
                             velvet_passive_size=40, velvet_offset=-1):
    """v17b base + passive unwind ALSO on VELVET."""
    base = MEMBER_OVERRIDES["r4_v17_passive_70_50_pi"][4]
    out = {}
    for sym, cfg in base.items():
        if cfg is None:
            out[sym] = None
            continue
        if sym == "VELVETFRUIT_EXTRACT":
            params = {k: v for k, v in cfg.params.items()
                      if k not in ("position_limit", "inv_unwind_enabled",
                                   "inv_unwind_threshold_pct", "inv_unwind_target_pct",
                                   "inv_unwind_max_per_tick", "inv_unwind_mode",
                                   "inv_unwind_passive_size", "inv_unwind_passive_offset")}
            out[sym] = _override(
                cfg,
                **params,
                inv_unwind_enabled=True,
                inv_unwind_threshold_pct=velvet_threshold,
                inv_unwind_target_pct=velvet_target,
                inv_unwind_max_per_tick=10,
                inv_unwind_mode="passive",
                inv_unwind_passive_size=velvet_passive_size,
                inv_unwind_passive_offset=velvet_offset,
            )
        else:
            out[sym] = cfg
    return {4: out}


# v18a — VELVET unwind 70/50 with penny-improve (same params as options)
MEMBER_OVERRIDES["r4_v18_velvet_unwind_70_50"] = _v18_with_velvet_unwind(0.7, 0.5)

# v18b — VELVET earlier kick-in 60/40
MEMBER_OVERRIDES["r4_v18_velvet_unwind_60_40"] = _v18_with_velvet_unwind(0.6, 0.4)

# v18c — VELVET aggressive 50/30
MEMBER_OVERRIDES["r4_v18_velvet_unwind_50_30"] = _v18_with_velvet_unwind(0.5, 0.3)


# v19 — REDUCE VELVET position_limit on top of v17b (defensive simple)
def _v19_with_velvet_lim(velvet_lim):
    base = MEMBER_OVERRIDES["r4_v17_passive_70_50_pi"][4]
    out = {}
    for sym, cfg in base.items():
        if cfg is None:
            out[sym] = None; continue
        if sym == "VELVETFRUIT_EXTRACT":
            params = {k: v for k, v in cfg.params.items() if k != "position_limit"}
            out[sym] = _override(cfg, **params, position_limit=velvet_lim)
        else:
            out[sym] = cfg
    return {4: out}


MEMBER_OVERRIDES["r4_v19_velvet_lim150"] = _v19_with_velvet_lim(150)
MEMBER_OVERRIDES["r4_v19_velvet_lim100"] = _v19_with_velvet_lim(100)


# v20 — VOL-BASED SIZE REDUCTION on options (defensive against Day 3 crash)
def _v20_with_vol_cut(threshold=0.005, factor=0.5, window=50, apply_to_options=True):
    base = MEMBER_OVERRIDES["r4_v17_passive_70_50_pi"][4]
    out = {}
    for sym, cfg in base.items():
        if cfg is None:
            out[sym] = None; continue
        if (apply_to_options and sym.startswith("VEV_")) or (not apply_to_options):
            params = {k: v for k, v in cfg.params.items()
                      if k not in ("position_limit", "vol_size_cut_enabled",
                                   "vol_size_cut_threshold", "vol_size_cut_factor",
                                   "vol_size_cut_window")}
            out[sym] = _override(
                cfg, **params,
                vol_size_cut_enabled=True,
                vol_size_cut_threshold=threshold,
                vol_size_cut_factor=factor,
                vol_size_cut_window=window,
            )
        else:
            out[sym] = cfg
    return {4: out}


MEMBER_OVERRIDES["r4_v20_vol_cut_options"] = _v20_with_vol_cut(0.005, 0.5)
MEMBER_OVERRIDES["r4_v20_vol_cut_aggressive"] = _v20_with_vol_cut(0.003, 0.3)
MEMBER_OVERRIDES["r4_v20_vol_cut_loose"] = _v20_with_vol_cut(0.010, 0.5)
MEMBER_OVERRIDES["r4_v20_vol_cut_007"] = _v20_with_vol_cut(0.007, 0.5)
MEMBER_OVERRIDES["r4_v20_vol_cut_008"] = _v20_with_vol_cut(0.008, 0.5)


# v21 — v20_008 + drop VEVOptionMMV3 strategy (use gamma_scalp_zgated for VEV_5200/5400)
def _v21_unify_options():
    base = MEMBER_OVERRIDES["r4_v20_vol_cut_008"][4]
    out = {}
    for sym, cfg in base.items():
        if cfg is None:
            out[sym] = None; continue
        if sym in ("VEV_5200", "VEV_5400"):
            # Use gamma_scalp_zgated like other options
            new_cfg = _r3_v24_gamma_option(int(sym.split("_")[1]))
            params = dict(new_cfg.params)
            params.pop("position_limit", None)
            # Inherit cp_bias / inv_unwind / vol_size_cut from base
            params["counterparty_bias_enabled"] = cfg.params.get("counterparty_bias_enabled", False)
            params["cp_trader_weights"] = cfg.params.get("cp_trader_weights", {})
            params["cp_window_ts"] = cfg.params.get("cp_window_ts", 10000)
            params["cp_signal_threshold"] = cfg.params.get("cp_signal_threshold", 1.0)
            params["cp_max_anchor_offset"] = cfg.params.get("cp_max_anchor_offset", 2.0)
            params["cp_anchor_scale_per_unit"] = cfg.params.get("cp_anchor_scale_per_unit", 0.15)
            params["inv_unwind_enabled"] = cfg.params.get("inv_unwind_enabled", False)
            params["inv_unwind_threshold_pct"] = cfg.params.get("inv_unwind_threshold_pct", 0.7)
            params["inv_unwind_target_pct"] = cfg.params.get("inv_unwind_target_pct", 0.5)
            params["inv_unwind_mode"] = cfg.params.get("inv_unwind_mode", "passive")
            params["inv_unwind_passive_size"] = cfg.params.get("inv_unwind_passive_size", 30)
            params["inv_unwind_passive_offset"] = cfg.params.get("inv_unwind_passive_offset", -1)
            params["vol_size_cut_enabled"] = cfg.params.get("vol_size_cut_enabled", False)
            params["vol_size_cut_threshold"] = cfg.params.get("vol_size_cut_threshold", 0.008)
            params["vol_size_cut_factor"] = cfg.params.get("vol_size_cut_factor", 0.5)
            out[sym] = _override(new_cfg, **params)
        else:
            out[sym] = cfg
    return {4: out}


MEMBER_OVERRIDES["r4_v21_unified_options"] = _v21_unify_options()


# v22 — v20 (current best) WITHOUT cp_bias (measure trader-ID contribution per day)
def _v22_no_cp_bias():
    base = MEMBER_OVERRIDES["r4_v20_vol_cut_008"][4]
    out = {}
    for sym, cfg in base.items():
        if cfg is None:
            out[sym] = None; continue
        params = {k: v for k, v in cfg.params.items()
                  if k not in ("position_limit", "counterparty_bias_enabled",
                               "cp_trader_weights", "cp_conditional_traders")}
        out[sym] = _override(cfg, **params,
                             counterparty_bias_enabled=False,
                             cp_trader_weights={},
                             cp_conditional_traders=[])
    return {4: out}


MEMBER_OVERRIDES["r4_v22_no_cp_bias"] = _v22_no_cp_bias()


# v23 — v20 + cp_bias REGIME GATE (disable cp_bias in trending regime → save Day 3)
def _v23_with_regime_gate(vol_thresh=0.008, drift_thresh=0.005):
    base = MEMBER_OVERRIDES["r4_v20_vol_cut_008"][4]
    out = {}
    for sym, cfg in base.items():
        if cfg is None:
            out[sym] = None; continue
        params = {k: v for k, v in cfg.params.items()
                  if k not in ("position_limit", "cp_regime_gate_enabled",
                               "cp_regime_vol_thresh", "cp_regime_drift_thresh")}
        out[sym] = _override(cfg, **params,
                             cp_regime_gate_enabled=True,
                             cp_regime_vol_thresh=vol_thresh,
                             cp_regime_drift_thresh=drift_thresh)
    return {4: out}


MEMBER_OVERRIDES["r4_v23_regime_gate"] = _v23_with_regime_gate(0.008, 0.005)
MEMBER_OVERRIDES["r4_v23_regime_gate_loose"] = _v23_with_regime_gate(0.012, 0.008)
MEMBER_OVERRIDES["r4_v23_regime_gate_tight"] = _v23_with_regime_gate(0.005, 0.003)


# v23b — drift-only gate with LONG buffer (300 ticks)
def _v23b_with_long_drift(drift_thresh=0.005, trend_window=300):
    base = MEMBER_OVERRIDES["r4_v20_vol_cut_008"][4]
    out = {}
    for sym, cfg in base.items():
        if cfg is None:
            out[sym] = None; continue
        params = {k: v for k, v in cfg.params.items()
                  if k not in ("position_limit", "cp_regime_gate_enabled",
                               "cp_regime_drift_thresh", "trend_window")}
        out[sym] = _override(cfg, **params,
                             cp_regime_gate_enabled=True,
                             cp_regime_drift_thresh=drift_thresh,
                             trend_window=trend_window)
    return {4: out}


MEMBER_OVERRIDES["r4_v23b_drift_005"] = _v23b_with_long_drift(0.005, 300)
MEMBER_OVERRIDES["r4_v23b_drift_008"] = _v23b_with_long_drift(0.008, 300)
MEMBER_OVERRIDES["r4_v23b_drift_010"] = _v23b_with_long_drift(0.010, 300)
MEMBER_OVERRIDES["r4_v23b_drift_005_w500"] = _v23b_with_long_drift(0.005, 500)


# v24 — CROSS-ASSET BIAS: Mark 14 VELVET flow → fade VEV_5100/5200/4500
# Data: corr Mark 14 VELVET flow ↔ VEV_5200 50t-return = -0.106 over 642 points (strong)
def _v24_cross_asset(target_options, weight=-0.5, threshold=5.0, scale=0.10, window=10000):
    base = MEMBER_OVERRIDES["r4_v20_vol_cut_008"][4]
    out = {}
    for sym, cfg in base.items():
        if cfg is None:
            out[sym] = None; continue
        if sym in target_options:
            params = {k: v for k, v in cfg.params.items()
                      if k not in ("position_limit", "cross_asset_enabled",
                                   "cross_asset_source_symbol", "cross_asset_source_trader",
                                   "cross_asset_weight", "cross_asset_window_ts",
                                   "cross_asset_threshold", "cross_asset_max_offset",
                                   "cross_asset_scale")}
            out[sym] = _override(cfg, **params,
                                  cross_asset_enabled=True,
                                  cross_asset_source_symbol="VELVETFRUIT_EXTRACT",
                                  cross_asset_source_trader="Mark 14",
                                  cross_asset_weight=weight,
                                  cross_asset_window_ts=window,
                                  cross_asset_threshold=threshold,
                                  cross_asset_max_offset=2.0,
                                  cross_asset_scale=scale)
        else:
            out[sym] = cfg
    return {4: out}


# Apply on the 3 options where Mark 14 cross-asset corr is strongest
MEMBER_OVERRIDES["r4_v24_xa_M14_velvet"] = _v24_cross_asset(
    ("VEV_5100", "VEV_5200", "VEV_4500"), weight=-0.5
)
MEMBER_OVERRIDES["r4_v24_xa_w03"] = _v24_cross_asset(
    ("VEV_5100", "VEV_5200", "VEV_4500"), weight=-0.3
)
MEMBER_OVERRIDES["r4_v24_xa_w02"] = _v24_cross_asset(
    ("VEV_5100", "VEV_5200", "VEV_4500"), weight=-0.2
)
# Only the most-correlated target (VEV_5200)
MEMBER_OVERRIDES["r4_v24_xa_5200_only"] = _v24_cross_asset(
    ("VEV_5200",), weight=-0.5
)


# v26 — v24 + heavier Mark 01 fade (LIVE shows Mark 01 -18.28/trade anti-informed)
def _v26_with_M01(m01_weight):
    base = MEMBER_OVERRIDES["r4_v24_xa_5200_only"][4]
    out = {}
    for sym, cfg in base.items():
        if cfg is None:
            out[sym] = None; continue
        params = dict(cfg.params)
        if "cp_trader_weights" in params and isinstance(params["cp_trader_weights"], dict):
            new_weights = dict(params["cp_trader_weights"])
            if "Mark 01" in new_weights:
                new_weights["Mark 01"] = m01_weight
            params["cp_trader_weights"] = new_weights
        params.pop("position_limit", None)
        out[sym] = _override(cfg, **params)
    return {4: out}


MEMBER_OVERRIDES["r4_v26_M01_w05"] = _v26_with_M01(-0.5)
MEMBER_OVERRIDES["r4_v26_M01_w08"] = _v26_with_M01(-0.8)
MEMBER_OVERRIDES["r4_v26_M01_w03"] = _v26_with_M01(-0.3)


# v25 — v24 5200_only + switch VEV_5200/5400 to gamma_scalp_zgated (drop VEVOptionMMV3 = -27KB)
def _v25_unified_options():
    base = MEMBER_OVERRIDES["r4_v24_xa_5200_only"][4]
    out = {}
    for sym, cfg in base.items():
        if cfg is None:
            out[sym] = None; continue
        if sym in ("VEV_5200", "VEV_5400"):
            new_cfg = _r3_v24_gamma_option(int(sym.split("_")[1]))
            params = {k: v for k, v in cfg.params.items()
                      if k not in ("position_limit", "strategy")
                      and not k.startswith("strike")}
            params.update({
                "tte_days_initial": new_cfg.params.get("tte_days_initial", 5.0),
                "historical_tte_by_day": new_cfg.params.get("historical_tte_by_day"),
                "timestamp_units_per_day": new_cfg.params.get("timestamp_units_per_day", 1000000),
                "implied_vol_prior": new_cfg.params.get("implied_vol_prior", 0.0125),
                "prior_vol": new_cfg.params.get("prior_vol", 0.0125),
                "sigma_floor": new_cfg.params.get("sigma_floor", 0.005),
                "sigma_cap": new_cfg.params.get("sigma_cap", 0.10),
                "min_quote_price": new_cfg.params.get("min_quote_price", 2.0),
                "edge_ticks": new_cfg.params.get("edge_ticks", 0.0),
                "target_qty": new_cfg.params.get("target_qty", 300),
                "strike": int(sym.split("_")[1]),
            })
            out[sym] = _override(new_cfg, position_limit=300, **params)
        else:
            out[sym] = cfg
    return {4: out}


MEMBER_OVERRIDES["r4_v25_unified"] = _v25_unified_options()


# r4_velvet_cp_bias_pure_followers — only follow Mark 55 + Mark 67, ignore fades
MEMBER_OVERRIDES["r4_velvet_cp_bias_pure_followers"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                counterparty_bias_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                cp_window_ts=10000,
                cp_signal_threshold=20.0,
                cp_max_anchor_offset=6.0,
                cp_anchor_scale_per_unit=0.08,
                cp_trader_weights={"Mark 55": 1.0, "Mark 67": 1.0},
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# =============================================================================
# R4 OBI TAKER OVERLAY — directional alpha from L3 book imbalance
# Predictive analysis: L3 OBI > 0 → next 50 ticks +7.8 ret (88% hit), <0 → -7.6 (11% hit)
# =============================================================================

# r4_velvet_obi_v1 — OBI taker on VELVET only, conservative size + cooldown
MEMBER_OVERRIDES["r4_velvet_obi_v1"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_taker_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_taker_levels=3,
                obi_taker_threshold=0.005,
                obi_taker_size=5,
                obi_taker_cooldown_ticks=10,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_obi_aggressive — bigger size, lower cooldown
MEMBER_OVERRIDES["r4_velvet_obi_aggressive"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_taker_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_taker_levels=3,
                obi_taker_threshold=0.003,
                obi_taker_size=10,
                obi_taker_cooldown_ticks=5,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_obi_strict — higher threshold (only fire on extreme imbalance)
MEMBER_OVERRIDES["r4_velvet_obi_strict"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_taker_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_taker_levels=3,
                obi_taker_threshold=0.010,
                obi_taker_size=8,
                obi_taker_cooldown_ticks=20,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_obi_passive — quote-bias version (shift bid/ask 1 tick when OBI extreme)
MEMBER_OVERRIDES["r4_velvet_obi_passive"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_passive_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_passive_levels=3,
                obi_passive_threshold=0.005,
                obi_passive_tick_offset=1,
                obi_passive_anti_offset=1,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_obi_passive_aggressive — wider shifts
MEMBER_OVERRIDES["r4_velvet_obi_passive_aggressive"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_passive_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_passive_levels=3,
                obi_passive_threshold=0.003,
                obi_passive_tick_offset=2,
                obi_passive_anti_offset=2,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# r4_velvet_obi_l1 — use L1 imbalance instead of L3 (different signal)
MEMBER_OVERRIDES["r4_velvet_obi_l1"] = {
    4: {
        sym: (
            _override(
                cfg,
                **dict(cfg.params),
                obi_taker_enabled=(sym == "VELVETFRUIT_EXTRACT"),
                obi_taker_levels=1,
                obi_taker_threshold=0.20,    # L1 imbalance has wider range
                obi_taker_size=5,
                obi_taker_cooldown_ticks=10,
            )
            if cfg is not None else None
        )
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}


# =============================================================================
# R4 CHEAP DEEP-OTM HEDGE — buy small VEV_6000/6500 long (price = 0.5 = worthless)
# Asymmetric payoff: cost 0.5/contract, +5/contract if VELVET drops 5%+
# Acts as crash insurance for the 199 VELVET + 300 VEV_5xxx long positions.
# =============================================================================

# r4_velvet_otm_hedge_small — long 100 of VEV_6000 + VEV_6500 each
# Use simple option_mm_bs with small target & buy-only-passive
def _otm_hedge_params():
    return dict(
        strategy="option_mm_bs",
        # Target a long bias by lowering ask side aggressiveness
        position_limit=100,
        strike=0,  # set per strike below
        tte_days_initial=4.0,
        ticks_per_day=10000,
        timestamp_units_per_day=1000000,
        historical_tte_by_day={1: 7.0, 2: 6.0, 3: 5.0},
        prior_vol=0.0125,
        maker_edge=1,
        maker_size=10,    # small size
        take_edge=10.0,   # very high — won't fire
        take_size=0,      # no takers
        use_smile=False,
        iv_ewma_alpha=0.3,
        sigma_floor=0.005,
        sigma_cap=0.10,
        min_quote_price=0.4,  # quote even at 0.5 (default 2.0 skips)
        inv_bias_per_unit=0.0,  # no skew
        enable_takers=False,
        penny_improve_around_mkt=True,
        underlying_symbol="VELVETFRUIT_EXTRACT",
        log_flush_ts=1000,
        ts_increment=100,
        last_ts_value=999900,
    )


MEMBER_OVERRIDES["r4_velvet_otm_hedge_small"] = {
    4: {
        sym: cfg
        for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
    },
}
# Add VEV_6000 and VEV_6500 with small position MM
for k in (6000, 6500):
    MEMBER_OVERRIDES["r4_velvet_otm_hedge_small"][4][f"VEV_{k}"] = _override(
        ROUND_4[f"VEV_{k}"], position_limit=100, strike=k, **{kk: vv for kk, vv in _otm_hedge_params().items() if kk not in ("position_limit", "strike", "strategy")},
    )


# r4_velvet_otm_forced_v1 — FORCED-ENTRY OTM hedge (taker BUY at start of day)
# Buys 100 long VEV_6000 + 100 long VEV_6500 in the first 1000 ticks each day
# Asymmetric: cost ~50 per day per strike, wins +500 if VELVET drops 5%+
MEMBER_OVERRIDES["r4_velvet_otm_forced_v1"] = {
    4: {
        **{
            sym: cfg
            for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
        },
    },
}
for k in (6000, 6500):
    MEMBER_OVERRIDES["r4_velvet_otm_forced_v1"][4][f"VEV_{k}"] = ProductConfig(
        symbol=f"VEV_{k}",
        strategy="forced_long_buyer",
        position_limit=100,
        params=dict(
            target_long=100,
            buy_chunk_size=5,
            max_entry_ticks=2000,   # 20% of day to accumulate
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
    )


# r4_velvet_otm_forced_big — bigger OTM hedge (200 each + take 4500/5500 too)
MEMBER_OVERRIDES["r4_velvet_otm_forced_big"] = {
    4: {
        **{
            sym: cfg
            for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
        },
    },
}
for k in (6000, 6500):
    MEMBER_OVERRIDES["r4_velvet_otm_forced_big"][4][f"VEV_{k}"] = ProductConfig(
        symbol=f"VEV_{k}",
        strategy="forced_long_buyer",
        position_limit=200,
        params=dict(
            target_long=200,
            buy_chunk_size=10,
            max_entry_ticks=2000,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
    )


# r4_velvet_otm_forced_5500 — also force long on VEV_5500 (price ~6, more sensitive)
MEMBER_OVERRIDES["r4_velvet_otm_forced_5500"] = {
    4: {
        **{
            sym: cfg
            for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
        },
    },
}
for k in (5500, 6000, 6500):
    MEMBER_OVERRIDES["r4_velvet_otm_forced_5500"][4][f"VEV_{k}"] = ProductConfig(
        symbol=f"VEV_{k}",
        strategy="forced_long_buyer",
        position_limit=100,
        params=dict(
            target_long=100,
            buy_chunk_size=5,
            max_entry_ticks=2000,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
    )


# =============================================================================
# R4 VEV_5300 SIZING TUNE — match z_skip 0.5 (current 0.8)
# Currently +1,535 PnL with z_skip=0.8 (gate restrictive). Try z_skip=0.5 like 4500-5100.
# =============================================================================
MEMBER_OVERRIDES["r4_velvet_v5300_z05"] = {
    4: {
        **{
            sym: cfg
            for sym, cfg in MEMBER_OVERRIDES["r4_velvet_options_only"][4].items()
        },
        "VEV_5300": _override(
            ROUND_4["VEV_5300"], position_limit=300, strike=5300,
            **_r4_gamma_params(z_skip=0.5, with_iv_gate=True),
        ),
    },
}


# r3_combined_best — combine our best on each product, validate vs final_sub_v100
MEMBER_OVERRIDES["r3_combined_best"] = {
    3: {
        # HYDROGEL = v7b_guarded_loose
        "HYDROGEL_PACK": _override(
            _R3_HYDROGEL_V4_F5,
            **_R4_HYDRO_BEST_PARAMS,
        ),
        # VELVET = v57 (R3GuardedAnchor + toxic + passive unwind)
        "VELVETFRUIT_EXTRACT": _override(
            ROUND_3["VELVETFRUIT_EXTRACT"],
            **_R3_THEO_V7_GUARDED_VELVET_PARAMS,
        ),
        # VEV options = v62 mix: per-strike z + Tibo 2-sided MM on 5200/5400
        "VEV_4000": _override(
            ROUND_3["VEV_4000"], position_limit=300, strike=4000,
            **_gamma_zgated_params(target_qty=300, z_skip_threshold=0.5),
        ),
        **{
            f"VEV_{strike}": _override(
                ROUND_3[f"VEV_{strike}"], position_limit=300, strike=strike,
                **_gamma_zgated_with_iv_gate(z_skip=0.5),
            )
            for strike in [4500, 5000, 5100]
        },
        # 5200, 5400 use Tibo's 2-sided passive MM (better than gamma_scalp on far-OTM)
        "VEV_5200": _tibo_vev_mm(5200),
        "VEV_5300": _override(
            ROUND_3["VEV_5300"], position_limit=300, strike=5300,
            **_gamma_zgated_with_iv_gate(z_skip=0.8),
        ),
        "VEV_5400": _tibo_vev_mm(5400, prevent_crossing=True),
        **{f"VEV_{k}": None for k in [5500, 6000, 6500]},
    },
}


_PEBBLES_ALL = ["PEBBLES_L", "PEBBLES_M", "PEBBLES_S", "PEBBLES_XL", "PEBBLES_XS"]

MEMBER_OVERRIDES["tibo_r5_v5"] = {
    5: {
        # ── PEBBLES: conservation taker arb on XL/XS; naive MM on L/M/S ───
        **{
            sym: ProductConfig(
                symbol=sym, strategy="pebbles_arb_v1", position_limit=10,
                params=dict(
                    partner_products=[p for p in _PEBBLES_ALL if p != sym],
                    sum_target=50000.0,
                    edge_ticks=7.0,
                    passive_half_spread=6.0,
                    taker_size=10,
                    passive_size=5,
                    ewma_alpha=0.05,
                    position_limit=10,
                    last_ts_value=999900,
                ),
            )
            for sym in ["PEBBLES_XL", "PEBBLES_XS"]
        },
        "PEBBLES_L": ProductConfig(symbol="PEBBLES_L", strategy="naive_tight_mm", position_limit=10, params=_R5_PEBBLES_MM),
        "PEBBLES_M": ProductConfig(symbol="PEBBLES_M", strategy="naive_tight_mm", position_limit=10, params=_R5_PEBBLES_MM),
        "PEBBLES_S": ProductConfig(symbol="PEBBLES_S", strategy="naive_tight_mm", position_limit=10, params=_R5_PEBBLES_MM),
        # ── ROBOT_DISHES: AR1 mean-reversion (AR1=-0.232, thresh=20 beats MM)
        "ROBOT_DISHES": ProductConfig(
            symbol="ROBOT_DISHES", strategy="ar1_mean_rev_v1", position_limit=10,
            params=dict(
                entry_threshold=20.0,
                taker_size=10,
                passive_size=0,
                exit_ticks=0,
                position_limit=10,
                last_ts_value=999900,
            ),
        ),
        # ── SNACKPACK: naive MM (pairs strategy tested and underperforms) ──
        **{
            sym: ProductConfig(symbol=sym, strategy="naive_tight_mm", position_limit=10, params=dict(
                maker_size=3, tighten_ticks=1, log_flush_ts=1000, ts_increment=100, last_ts_value=999900,
            ))
            for sym in ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO", "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"]
        },
        # ── Skip: consistently loses all 3 historical days (large intraday swing/reversal trap) ─
        "SLEEP_POD_LAMB_WOOL": None,
    }
}


# ── Round 5 — Tibo's trend-following strategies ──────────────────────────────

def _r5_trend_v2(sym: str, ema_hl: int = 100, threshold: float = 80.0, exit_thr: float = 30.0, warmup: int = 0) -> ProductConfig:
    return ProductConfig(
        symbol=sym,
        strategy="trend_follow_v2",
        position_limit=10,
        params=dict(
            ema_half_life=ema_hl,
            threshold=threshold,
            exit_threshold=exit_thr,
            warmup_ticks=warmup,
            position_limit=10,
            ts_increment=100,
            last_ts_value=999900,
            log_flush_ts=1000,
        ),
    )



# ── Round 5 — tibo_r5_v6: v5 + trend_v2 where it beats naive_mm ──────────────
# 3-day realistic backtest: 733,918 PnL (+142,704 over tibo_r5_v5's 591,214)
# trend_v2 wins: MICROCHIP_SQUARE (+46k), PANEL_1X2 (+31k), ROBOT_MOPPING (+25k),
#   PEBBLES_XS (+14k), UV_VISOR_AMBER (+7k), SLEEP_POD_NYLON (+5k),
#   SLEEP_POD_POLYESTER (+5k), SLEEP_POD_COTTON (+3k), ROBOT_IRONING (+3k),
#   OXYGEN_SHAKE_GARLIC (+3k)
# v5 strategy kept where it wins: PEBBLES_XL (arb), PANEL_1X4, SLEEP_POD_SUEDE,
#   TRANSLATOR_VOID_BLUE, MICROCHIP_TRIANGLE, PANEL_2X4, MICROCHIP_OVAL, GALAXY_SOUNDS_BLACK_HOLES
MEMBER_OVERRIDES["tibo_r5_v6"] = {
    5: {
        # ── PEBBLES: arb on XL only; trend_v2 on XS (beats arb by +13,701); naive MM on L/M/S ──
        **{
            sym: ProductConfig(
                symbol=sym, strategy="pebbles_arb_v1", position_limit=10,
                params=dict(
                    partner_products=[p for p in _PEBBLES_ALL if p != sym],
                    sum_target=50000.0, edge_ticks=7.0, passive_half_spread=6.0,
                    taker_size=10, passive_size=5, ewma_alpha=0.05,
                    position_limit=10, last_ts_value=999900,
                ),
            )
            for sym in ["PEBBLES_XL"]
        },
        "PEBBLES_XS": _r5_trend_v2("PEBBLES_XS", ema_hl=150, threshold=250, exit_thr=80),
        "PEBBLES_L": ProductConfig(symbol="PEBBLES_L", strategy="naive_tight_mm", position_limit=10, params=_R5_PEBBLES_MM),
        "PEBBLES_M": ProductConfig(symbol="PEBBLES_M", strategy="naive_tight_mm", position_limit=10, params=_R5_PEBBLES_MM),
        "PEBBLES_S": ProductConfig(symbol="PEBBLES_S", strategy="naive_tight_mm", position_limit=10, params=_R5_PEBBLES_MM),
        # ── ROBOT_DISHES: AR1 mean-reversion (best single product, +140k) ────
        "ROBOT_DISHES": ProductConfig(
            symbol="ROBOT_DISHES", strategy="ar1_mean_rev_v1", position_limit=10,
            params=dict(entry_threshold=20.0, taker_size=10, passive_size=0,
                        exit_ticks=0, position_limit=10, last_ts_value=999900),
        ),
        # ── SNACKPACK: naive MM (all 5) ──────────────────────────────────────
        **{
            sym: ProductConfig(symbol=sym, strategy="naive_tight_mm", position_limit=10, params=dict(
                maker_size=3, tighten_ticks=1, log_flush_ts=1000, ts_increment=100, last_ts_value=999900,
            ))
            for sym in ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
                        "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"]
        },
        # ── Skip SLEEP_POD_LAMB_WOOL (intra-day spike, consistently loses) ───
        "SLEEP_POD_LAMB_WOOL": None,
        # ── trend_v2 winners (beat naive_mm in v5) ──────────────────────────
        "UV_VISOR_AMBER": _r5_trend_v2("UV_VISOR_AMBER", ema_hl=100, threshold=80, exit_thr=30),
        "ROBOT_MOPPING": _r5_trend_v2("ROBOT_MOPPING", ema_hl=150, threshold=100, exit_thr=40),
        "SLEEP_POD_COTTON": _r5_trend_v2("SLEEP_POD_COTTON", ema_hl=100, threshold=80, exit_thr=30),
        "SLEEP_POD_NYLON": _r5_trend_v2("SLEEP_POD_NYLON", ema_hl=100, threshold=80, exit_thr=30),
        "SLEEP_POD_POLYESTER": _r5_trend_v2("SLEEP_POD_POLYESTER", ema_hl=150, threshold=600, exit_thr=150),
        "PANEL_1X2": _r5_trend_v2("PANEL_1X2", ema_hl=100, threshold=80, exit_thr=30),
        "ROBOT_IRONING": _r5_trend_v2("ROBOT_IRONING", ema_hl=150, threshold=100, exit_thr=40),
        "OXYGEN_SHAKE_GARLIC": _r5_trend_v2("OXYGEN_SHAKE_GARLIC", ema_hl=150, threshold=700, exit_thr=150),
        "MICROCHIP_SQUARE": _r5_trend_v2("MICROCHIP_SQUARE", ema_hl=100, threshold=250, exit_thr=80),
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# best_v7 — Round 5 best composite strategy (self-contained, no inheritance)
# 3-day realistic backtest: ~741,720 PnL
# Improvements over v6 (733,918):
#   +4,986 — SNACKPACK maker_size 3→5 (all 3 days positive, safe to increase)
#   +2,816 — 11 other all-positive naive_tight_mm products maker_size 3→5
#   Total delta: +7,802
# Task 2 rejected: PEBBLES_L/M conservation taker-only = 712k < 734k (naive_mm wins)
# ══════════════════════════════════════════════════════════════════════════════

_BEST_V7_TREND_PARAMS = dict(
    ts_increment=100, last_ts_value=999900, log_flush_ts=1000,
)

def _v7_mm(sym: str, size: int = 3) -> ProductConfig:
    return ProductConfig(symbol=sym, strategy="naive_tight_mm", position_limit=10,
                         params=dict(maker_size=size, tighten_ticks=1,
                                     log_flush_ts=1000, ts_increment=100, last_ts_value=999900))

def _v7_trend(sym: str, ema_hl: int, threshold: float, exit_thr: float, warmup: int = 0) -> ProductConfig:
    return ProductConfig(symbol=sym, strategy="trend_follow_v2", position_limit=10,
                         params=dict(ema_half_life=ema_hl, threshold=threshold,
                                     exit_threshold=exit_thr, warmup_ticks=warmup,
                                     position_limit=10, **_BEST_V7_TREND_PARAMS))

def _v7_pebbles_arb(sym: str) -> ProductConfig:
    return ProductConfig(symbol=sym, strategy="pebbles_arb_v1", position_limit=10,
                         params=dict(partner_products=[p for p in _PEBBLES_ALL if p != sym],
                                     sum_target=50000.0, edge_ticks=7.0, passive_half_spread=6.0,
                                     taker_size=10, passive_size=5, ewma_alpha=0.05,
                                     position_limit=10, last_ts_value=999900))

MEMBER_OVERRIDES["best_v7"] = {
    5: {
        # ── PEBBLES: conservation arb on XL; trend_v2 on XS; naive MM on L/M/S ─
        "PEBBLES_XL": _v7_pebbles_arb("PEBBLES_XL"),
        "PEBBLES_XS": _v7_trend("PEBBLES_XS", ema_hl=150, threshold=250, exit_thr=80),
        "PEBBLES_L":  _v7_mm("PEBBLES_L"),
        "PEBBLES_M":  _v7_mm("PEBBLES_M"),
        "PEBBLES_S":  _v7_mm("PEBBLES_S"),
        # ── ROBOT_DISHES: AR1 mean-reversion (thresh=20, +140k) ─────────────────
        "ROBOT_DISHES": ProductConfig(
            symbol="ROBOT_DISHES", strategy="ar1_mean_rev_v1", position_limit=10,
            params=dict(entry_threshold=20.0, taker_size=10, passive_size=0,
                        exit_ticks=0, position_limit=10, last_ts_value=999900),
        ),
        # ── SNACKPACK: all naive MM size=5 (all 3 days positive, saturation at 5) ─
        "SNACKPACK_CHOCOLATE":  _v7_mm("SNACKPACK_CHOCOLATE",  size=5),
        "SNACKPACK_VANILLA":    _v7_mm("SNACKPACK_VANILLA",    size=5),
        "SNACKPACK_PISTACHIO":  _v7_mm("SNACKPACK_PISTACHIO",  size=5),
        "SNACKPACK_STRAWBERRY": _v7_mm("SNACKPACK_STRAWBERRY", size=5),
        "SNACKPACK_RASPBERRY":  _v7_mm("SNACKPACK_RASPBERRY",  size=5),
        # ── Skip: intra-day spike reversal trap, -30k all 3 historical days ─────
        "SLEEP_POD_LAMB_WOOL": None,
        # ── Trend followers (beat naive_mm in v5/v6 head-to-head) ────────────────
        "UV_VISOR_AMBER":       _v7_trend("UV_VISOR_AMBER",       ema_hl=100, threshold=80,  exit_thr=30),
        "ROBOT_MOPPING":        _v7_trend("ROBOT_MOPPING",        ema_hl=150, threshold=100, exit_thr=40),
        "SLEEP_POD_COTTON":     _v7_trend("SLEEP_POD_COTTON",     ema_hl=100, threshold=80,  exit_thr=30),
        "SLEEP_POD_NYLON":      _v7_trend("SLEEP_POD_NYLON",      ema_hl=100, threshold=80,  exit_thr=30),
        "SLEEP_POD_POLYESTER":  _v7_trend("SLEEP_POD_POLYESTER",  ema_hl=150, threshold=600, exit_thr=150),
        "PANEL_1X2":            _v7_trend("PANEL_1X2",            ema_hl=100, threshold=80,  exit_thr=30),
        "ROBOT_IRONING":        _v7_trend("ROBOT_IRONING",        ema_hl=150, threshold=100, exit_thr=40),
        "OXYGEN_SHAKE_GARLIC":  _v7_trend("OXYGEN_SHAKE_GARLIC",  ema_hl=150, threshold=700, exit_thr=150),
        "MICROCHIP_SQUARE":     _v7_trend("MICROCHIP_SQUARE",     ema_hl=100, threshold=250, exit_thr=80),
        # ── All-positive naive MM products: size=5 (market saturation, 5=7) ─────
        "PANEL_1X4":                  _v7_mm("PANEL_1X4",                  size=5),
        "OXYGEN_SHAKE_CHOCOLATE":     _v7_mm("OXYGEN_SHAKE_CHOCOLATE",     size=5),
        "OXYGEN_SHAKE_EVENING_BREATH":_v7_mm("OXYGEN_SHAKE_EVENING_BREATH",size=5),
        "TRANSLATOR_VOID_BLUE":       _v7_mm("TRANSLATOR_VOID_BLUE",       size=5),
        "PANEL_2X4":                  _v7_mm("PANEL_2X4",                  size=5),
        "UV_VISOR_ORANGE":            _v7_mm("UV_VISOR_ORANGE",            size=5),
        "OXYGEN_SHAKE_MORNING_BREATH":_v7_mm("OXYGEN_SHAKE_MORNING_BREATH",size=5),
        "MICROCHIP_OVAL":             _v7_mm("MICROCHIP_OVAL",             size=5),
        "UV_VISOR_RED":               _v7_mm("UV_VISOR_RED",               size=5),
        "GALAXY_SOUNDS_DARK_MATTER":  _v7_mm("GALAXY_SOUNDS_DARK_MATTER",  size=5),
        "PANEL_2X2":                  _v7_mm("PANEL_2X2",                  size=5),
    }
}
# All other 24 products fall through to base ROUND_5 config (naive_tight_mm maker_size=3)
# ── Round 5 — tibo_r5_v7_2: v6 + stop losers + UV_VISOR_YELLOW ───────────────
# 3-day realistic backtest: 817,194 PnL (+83,276 over tibo_r5_v6's 733,918)
# Changes vs v6:
#   - PEBBLES_L/M: None (-11.5k/-14.8k saved). Arb tested but worse (arb fires too aggressively because fair≈mid always).
#   - 6 losers → None: UV_VISOR_MAGENTA -7.3k, TRANSLATOR_SPACE_GRAY -11.2k, PANEL_4X4 -10.7k,
#       GALAXY_SOUNDS_SOLAR_FLAMES -6k, TRANSLATOR_GRAPHITE_MIST -4.4k, ROBOT_VACUUMING -2.7k
#   - UV_VISOR_YELLOW: trend_v2 th=700 → +19,285 (was naive_mm +4,592). threshold=700 avoids
#       day3 false-short (EMA dip reaches -633, below 700 → no entry).
MEMBER_OVERRIDES["tibo_r5_v7_2"] = {
    5: {
        **MEMBER_OVERRIDES["tibo_r5_v6"][5],
        # ── PEBBLES L/M: set to None (lose with both naive_mm and arb) ──────────────
        "PEBBLES_L": None,
        "PEBBLES_M": None,
        # ── Stop the bleeding: set big losers to None ────────────────────────────────
        "UV_VISOR_MAGENTA": None,
        "TRANSLATOR_SPACE_GRAY": None,
        "PANEL_4X4": None,
        "GALAXY_SOUNDS_SOLAR_FLAMES": None,
        "TRANSLATOR_GRAPHITE_MIST": None,
        "ROBOT_VACUUMING": None,
        # ── UV_VISOR_YELLOW: threshold=700 avoids day3 false-short (min_signal=-633) ──
        # day2: long +8k, day3: no entry (EMA only reaches -633 < 700), day4: short +11k
        "UV_VISOR_YELLOW": _r5_trend_v2("UV_VISOR_YELLOW", ema_hl=100, threshold=700, exit_thr=150),
    },
}


# ── Round 5 — tibo_r5_v7_2_best: best_v7 (maker_size=5) + v7_2 (stop losers + YELLOW) ──
# 3-day realistic backtest: 824,996 PnL (+91,078 vs v6 733,918)
# best_v7 contributions: maker_size 3→5 on 16 all-positive products (+7,802 vs v6)
# v7_2 contributions: 8 losers→None (+68.6k vs v6), UV_VISOR_YELLOW trend_v2 th=700 (+14.7k)
MEMBER_OVERRIDES["tibo_r5_v7_2_best"] = {
    5: {
        **MEMBER_OVERRIDES["best_v7"][5],
        # ── v7_2: set all losing products to None ────────────────────────────────────
        "PEBBLES_L": None,           # -11,500 in v6 (overrides best_v7's naive_mm)
        "PEBBLES_M": None,           # -14,756 in v6
        "UV_VISOR_MAGENTA": None,    # -7,314 in v6
        "TRANSLATOR_SPACE_GRAY": None,  # -11,188 in v6
        "PANEL_4X4": None,           # -10,672 in v6
        "GALAXY_SOUNDS_SOLAR_FLAMES": None,  # -6,034 in v6
        "TRANSLATOR_GRAPHITE_MIST": None,    # -4,418 in v6
        "ROBOT_VACUUMING": None,     # -2,700 in v6
        # ── v7_2: UV_VISOR_YELLOW trend_v2 th=700 (day3 EMA dip=-633 < 700 → no entry) ──
        "UV_VISOR_YELLOW": _v7_trend("UV_VISOR_YELLOW", ema_hl=100, threshold=700, exit_thr=150),
    },
}


# ── Round 5 — v8_a: restore 6 live-profitable products at halved position limit ──
# Mitigation A: keep TRANSLATOR_SPACE_GRAY + PEBBLES_M at None (consistently bad),
# restore the 6 wrongly-removed products with limit=5 to cap max inventory loss.
# Tradeoff: backtest ~-20k vs v7_2_best, but ~+7k on live day compared to v7_2_best.
def _v8_mm_conservative(sym: str) -> ProductConfig:
    return ProductConfig(symbol=sym, strategy="naive_tight_mm", position_limit=5,
                         params=dict(maker_size=3, tighten_ticks=1,
                                     log_flush_ts=1000, ts_increment=100, last_ts_value=999900))

MEMBER_OVERRIDES["tibo_r5_v8_a"] = {
    5: {
        **MEMBER_OVERRIDES["tibo_r5_v7_2_best"][5],
        # Restore 6 wrongly-removed products with position_limit=5 (half of standard 10)
        # They were profitable in live day: PANEL_4X4 +5567, GRAPHITE_MIST +4191,
        # SOLAR_FLAMES +2306, ROBOT_VACUUMING +979, UV_VISOR_MAGENTA +598, PEBBLES_L +337
        "PANEL_4X4":                    _v8_mm_conservative("PANEL_4X4"),
        "TRANSLATOR_GRAPHITE_MIST":     _v8_mm_conservative("TRANSLATOR_GRAPHITE_MIST"),
        "GALAXY_SOUNDS_SOLAR_FLAMES":   _v8_mm_conservative("GALAXY_SOUNDS_SOLAR_FLAMES"),
        "ROBOT_VACUUMING":              _v8_mm_conservative("ROBOT_VACUUMING"),
        "UV_VISOR_MAGENTA":             _v8_mm_conservative("UV_VISOR_MAGENTA"),
        "PEBBLES_L":                    _v8_mm_conservative("PEBBLES_L"),
        # TRANSLATOR_SPACE_GRAY and PEBBLES_M stay None (lost in live too)
    },
}

MEMBER_OVERRIDES["best_v7_live_mmfix4"] = {
    5: {
        **MEMBER_OVERRIDES["best_v7"][5],
        # Narrower live fix than mmfix3:
        # - keep the close-only flatten mechanic
        # - drop GALAXY_SOUNDS_PLANETARY_RINGS because it worsened day-4 backtest
        # - keep only symbols that were live-negative, weak on day-4 backtest,
        #   and improved under the close-only intervention
        "TRANSLATOR_SPACE_GRAY": ProductConfig(
            symbol="TRANSLATOR_SPACE_GRAY",
            strategy="late_flatten_tight_mm_v1",
            position_limit=10,
            params=dict(maker_size=3, tighten_ticks=1, log_flush_ts=1000, ts_increment=100, last_ts_value=999900,
                        late_passive_unwind_start_ts=99700, late_taker_unwind_start_ts=99900,
                        late_unwind_qty=2, late_unwind_pos_gate=5),
        ),
        "PANEL_2X2": ProductConfig(
            symbol="PANEL_2X2",
            strategy="late_flatten_tight_mm_v1",
            position_limit=10,
            params=dict(maker_size=5, tighten_ticks=1, log_flush_ts=1000, ts_increment=100, last_ts_value=999900,
                        late_passive_unwind_start_ts=99700, late_taker_unwind_start_ts=99900,
                        late_unwind_qty=2, late_unwind_pos_gate=5),
        ),
        "UV_VISOR_YELLOW": ProductConfig(
            symbol="UV_VISOR_YELLOW",
            strategy="late_flatten_tight_mm_v1",
            position_limit=10,
            params=dict(maker_size=3, tighten_ticks=1, log_flush_ts=1000, ts_increment=100, last_ts_value=999900,
                        late_passive_unwind_start_ts=99700, late_taker_unwind_start_ts=99900,
                        late_unwind_qty=2, late_unwind_pos_gate=5),
        ),
    }
}
# Goal: tiny close-only intervention on the clearest live MM leaks.


def get_round_config(round_num: int, member: str = "champion") -> Dict[str, ProductConfig]:
    """Build the product config for a given round + member."""
    base = dict(ROUNDS.get(round_num, {}))
    overrides = MEMBER_OVERRIDES.get(member, {}).get(round_num, {})
    for symbol, cfg in overrides.items():
        if cfg is None:
            base.pop(symbol, None)
        else:
            base[symbol] = cfg
    return base

def _v8_coint_mm(sym: str, partner: str, z_win: int, entry_z: float,
                 passive_size: int = 3) -> ProductConfig:
    """CointMMV1 helper for best_v8 config."""
    return ProductConfig(
        symbol=sym, strategy="coint_mm_v1", position_limit=10,
        params=dict(partner_product=partner, mean_half_life=5000,
                    z_window=z_win, entry_z=entry_z, exit_z=0.0,
                    taker_size=10, passive_size=passive_size, tighten_ticks=1,
                    position_limit=10, last_ts_value=999900))


MEMBER_OVERRIDES["best_v8"] = {
    5: {
        # ── PEBBLES: conservation arb on XL; trend_v2 on XS; naive MM on L/M/S ─
        "PEBBLES_XL": _v7_pebbles_arb("PEBBLES_XL"),
        "PEBBLES_XS": _v7_trend("PEBBLES_XS", ema_hl=150, threshold=250, exit_thr=80),
        "PEBBLES_L":  _v7_mm("PEBBLES_L"),
        "PEBBLES_M":  _v7_mm("PEBBLES_M"),
        "PEBBLES_S":  _v7_mm("PEBBLES_S"),
        # ── ROBOT_DISHES: AR1 mean-reversion (+140k) ─────────────────────────
        "ROBOT_DISHES": ProductConfig(
            symbol="ROBOT_DISHES", strategy="ar1_mean_rev_v1", position_limit=10,
            params=dict(entry_threshold=20.0, taker_size=10, passive_size=0,
                        exit_ticks=0, position_limit=10, last_ts_value=999900),
        ),
        # ── MICROCHIP: passive MM for OVAL/TRIANGLE (coint unstable in live)
        # RECT still reads SQUARE as partner (≈0 delta, low risk)
        "MICROCHIP_OVAL":     _v7_mm("MICROCHIP_OVAL",     size=5),
        "MICROCHIP_TRIANGLE": _v7_mm("MICROCHIP_TRIANGLE", size=3),
        "MICROCHIP_RECTANGLE":_v8_coint_mm("MICROCHIP_RECTANGLE","MICROCHIP_SQUARE", z_win=1000, entry_z=1.2, passive_size=3),
        "MICROCHIP_SQUARE":   _v7_trend("MICROCHIP_SQUARE", ema_hl=100, threshold=250, exit_thr=80),
        # ── ROBOT: LAUNDRY↔VACUUMING cointegration pair (held in live) ───────
        "ROBOT_LAUNDRY":   _v8_coint_mm("ROBOT_LAUNDRY",   "ROBOT_VACUUMING", z_win=2000, entry_z=1.5, passive_size=3),
        "ROBOT_VACUUMING": _v8_coint_mm("ROBOT_VACUUMING", "ROBOT_LAUNDRY",   z_win=2000, entry_z=1.5, passive_size=3),
        # ── SNACKPACK: naive MM size=5 (all-positive days) ────────────────────
        "SNACKPACK_CHOCOLATE":  _v7_mm("SNACKPACK_CHOCOLATE",  size=5),
        "SNACKPACK_VANILLA":    _v7_mm("SNACKPACK_VANILLA",    size=5),
        "SNACKPACK_PISTACHIO":  _v7_mm("SNACKPACK_PISTACHIO",  size=5),
        "SNACKPACK_STRAWBERRY": _v7_mm("SNACKPACK_STRAWBERRY", size=5),
        "SNACKPACK_RASPBERRY":  _v7_mm("SNACKPACK_RASPBERRY",  size=5),
        # ── Skip SLEEP_POD_LAMB_WOOL (intraday spike trap) ───────────────────
        "SLEEP_POD_LAMB_WOOL": None,
        # ── Trend followers ────────────────────────────────────────────────────
        "UV_VISOR_AMBER":       _v7_trend("UV_VISOR_AMBER",      ema_hl=100, threshold=80,  exit_thr=30),
        "ROBOT_MOPPING":        _v7_trend("ROBOT_MOPPING",       ema_hl=150, threshold=100, exit_thr=40),
        "SLEEP_POD_COTTON":     _v7_trend("SLEEP_POD_COTTON",    ema_hl=100, threshold=80,  exit_thr=30),
        "SLEEP_POD_NYLON":      _v7_trend("SLEEP_POD_NYLON",     ema_hl=100, threshold=80,  exit_thr=30),
        "SLEEP_POD_POLYESTER":  _v7_trend("SLEEP_POD_POLYESTER", ema_hl=150, threshold=600, exit_thr=150),
        "PANEL_1X2":            _v7_trend("PANEL_1X2",           ema_hl=100, threshold=80,  exit_thr=30),
        "ROBOT_IRONING":        _v7_trend("ROBOT_IRONING",       ema_hl=150, threshold=100, exit_thr=40),
        "OXYGEN_SHAKE_GARLIC":  _v7_trend("OXYGEN_SHAKE_GARLIC", ema_hl=150, threshold=700, exit_thr=150),
        # ── All-positive naive MM products: size=5 ────────────────────────────
        "PANEL_1X4":                   _v7_mm("PANEL_1X4",                   size=5),
        "OXYGEN_SHAKE_CHOCOLATE":      _v7_mm("OXYGEN_SHAKE_CHOCOLATE",      size=5),
        "OXYGEN_SHAKE_EVENING_BREATH": _v7_mm("OXYGEN_SHAKE_EVENING_BREATH", size=5),
        "TRANSLATOR_VOID_BLUE":        _v7_mm("TRANSLATOR_VOID_BLUE",        size=5),
        "PANEL_2X4":                   _v7_mm("PANEL_2X4",                   size=5),
        "UV_VISOR_ORANGE":             _v7_mm("UV_VISOR_ORANGE",             size=5),
        "OXYGEN_SHAKE_MORNING_BREATH": _v7_mm("OXYGEN_SHAKE_MORNING_BREATH", size=5),
        "UV_VISOR_RED":                _v7_mm("UV_VISOR_RED",                size=5),
        "GALAXY_SOUNDS_DARK_MATTER":   _v7_mm("GALAXY_SOUNDS_DARK_MATTER",   size=5),
        "PANEL_2X2":                   _v7_mm("PANEL_2X2",                   size=5),
    }
}
# All other 24 products fall through to base ROUND_5 config (naive_tight_mm size=3)


def _late_flatten_mm(sym: str, maker_size: int = 3) -> ProductConfig:
    """naive_tight_mm with end-of-session inventory flatten (from best_v7_live_mmfix4)."""
    return ProductConfig(
        symbol=sym, strategy="late_flatten_tight_mm_v1", position_limit=10,
        params=dict(maker_size=maker_size, tighten_ticks=1,
                    log_flush_ts=1000, ts_increment=100, last_ts_value=999900,
                    late_passive_unwind_start_ts=99700,
                    late_taker_unwind_start_ts=99900,
                    late_unwind_qty=2, late_unwind_pos_gate=5))


# ── best_v9: best_v8 + live MM fix (from best_v7_live_mmfix4) ────────────────
# Merges two lines of work:
#   - best_v8: coint_mm on ROBOT_LAUNDRY/VACUUMING + RECT, revised MICROCHIP to naive_mm
#   - best_v7_live_mmfix4: close-only inventory flatten on 3 products that had
#     carry losses in live (TRANSLATOR_SPACE_GRAY, PANEL_2X2, UV_VISOR_YELLOW)
# The flatten logic doesn't fire in normal backtest ticks but removes the
# end-of-session MTM drag that appeared in the live logs.
MEMBER_OVERRIDES["best_v9"] = {
    5: {
        **MEMBER_OVERRIDES["best_v8"][5],
        # Live MM fix: replace naive_tight_mm with late_flatten_tight_mm_v1
        # for 3 products that repeatedly carried inventory into a falling close
        "TRANSLATOR_SPACE_GRAY": _late_flatten_mm("TRANSLATOR_SPACE_GRAY", maker_size=3),
        "PANEL_2X2":             _late_flatten_mm("PANEL_2X2",             maker_size=5),
        "UV_VISOR_YELLOW":       _late_flatten_mm("UV_VISOR_YELLOW",       maker_size=3),
    }
}


# ── best_v10: merge of best_v9 (1st/3rd analyst) + tibo_r5_v8_a (2nd analyst) ──
#
# Conflict resolutions (user decision 2026-04-29):
#   TRANSLATOR_SPACE_GRAY → None (v8_a wins: consistently bad in both backtest −11k AND live −6,777)
#   UV_VISOR_YELLOW       → trend_v2 th=700 (v8_a wins: +19,285 vs naive_mm +4,592 in backtest)
#   ROBOT_VACUUMING       → coint_mm_v1 (v9 wins: cointegration held in live, 0 delta)
#   PEBBLES_M             → None (v8_a wins: −14,756 backtest AND −357 live)
#   PANEL_2X2             → naive_mm size=5 (v8_a wins: no late_flatten needed)
#
# Non-conflicting additions from v8_a (halved position limit for live-volatile products):
#   PANEL_4X4, TRANSLATOR_GRAPHITE_MIST, GALAXY_SOUNDS_SOLAR_FLAMES,
#   UV_VISOR_MAGENTA, PEBBLES_L → naive_mm limit=5
MEMBER_OVERRIDES["best_v10"] = {
    5: {
        **MEMBER_OVERRIDES["best_v9"][5],
        # ── Conflict resolutions (v8_a wins) ─────────────────────────────────
        "TRANSLATOR_SPACE_GRAY": None,                                            # v9 had late_flatten → None
        "UV_VISOR_YELLOW":       _v7_trend("UV_VISOR_YELLOW", ema_hl=100, threshold=700, exit_thr=150),  # v9 had late_flatten → trend_v2
        "PEBBLES_M":             None,                                            # v9 had naive_mm → None
        "PANEL_2X2":             _v7_mm("PANEL_2X2", size=5),                    # v9 had late_flatten → naive_mm
        # ── Non-conflicting v8_a additions (halved limit for volatile products) ─
        "PANEL_4X4":                  _v8_mm_conservative("PANEL_4X4"),
        "TRANSLATOR_GRAPHITE_MIST":   _v8_mm_conservative("TRANSLATOR_GRAPHITE_MIST"),
        "GALAXY_SOUNDS_SOLAR_FLAMES": _v8_mm_conservative("GALAXY_SOUNDS_SOLAR_FLAMES"),
        "UV_VISOR_MAGENTA":           _v8_mm_conservative("UV_VISOR_MAGENTA"),
        "PEBBLES_L":                  _v8_mm_conservative("PEBBLES_L"),
    }
}




MEMBER_OVERRIDES["best_v12_A1_A3"] = {
    5: {
        **MEMBER_OVERRIDES["best_v10"][5],
        # A3: reduce PANEL_2X2 maker_size 5→3 (carry risk reduction)
        "PANEL_2X2": ProductConfig(
            symbol="PANEL_2X2", strategy="naive_tight_mm", position_limit=10,
            params=dict(maker_size=3, tighten_ticks=1, log_flush_ts=1000,
                        ts_increment=100, last_ts_value=999900)),
        # A3: reduce ROBOT_LAUNDRY passive_size 3→1 (less passive inventory on coint leg)
        "ROBOT_LAUNDRY": ProductConfig(
            symbol="ROBOT_LAUNDRY", strategy="coint_mm_v1", position_limit=10,
            params=dict(partner_product="ROBOT_VACUUMING", mean_half_life=5000,
                        z_window=2000, entry_z=1.5, exit_z=0.0,
                        taker_size=10, passive_size=1, tighten_ticks=1,
                        position_limit=10, last_ts_value=999900)),
    }
}


# ── A2 cross-group strategy helpers ──────────────────────────────────────────
# Signal groups: SLEEP_POD avg EMA (vs session start) → GALAXY_SOUNDS direction
# Inverted signal: ROBOT avg EMA (vs session start) → inverse GS direction
_SP_GROUP = [
    "SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
    "SLEEP_POD_NYLON", "SLEEP_POD_COTTON",
]
_RB_GROUP = [
    "ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
    "ROBOT_LAUNDRY", "ROBOT_IRONING",
]

def _v13_cg_A2(sym: str, sp_thr: float, rb_thr: float = 0,
               ema_hl: float = 100, passive_size: int = 3,
               taker_size: int = 10) -> ProductConfig:
    """cross_group_trend_A2 config: SP (+ optional inverted RB) → target product."""
    params = dict(
        signal_products=_SP_GROUP,
        signal_ema_hl=ema_hl,
        signal_threshold=sp_thr,
        signal_exit=sp_thr / 3,
        taker_size=taker_size,
        passive_size=passive_size,
        position_limit=10,
        last_ts_value=999900,
    )
    if rb_thr > 0:
        params["signal2_products"] = _RB_GROUP
        params["signal2_threshold"] = rb_thr
    return ProductConfig(symbol=sym, strategy="cross_group_trend_A2",
                         position_limit=10, params=params)


# ── A2 test configs: cross-group signal for GALAXY_SOUNDS products ────────────
# ── best_v13_A2: self-contained final config (A2 analyst) ────────────────────
# Baseline: best_v12_A1_A3 = 851,678 PnL
# A2 changes:
#   GALAXY_SOUNDS_BLACK_HOLES → cross_group_trend_A2 (SP signal thr=80 + RB inverted thr=30)
#     Backtest: +41,708 vs naive_mm +15,420 → +26,288 improvement
#   GALAXY_SOUNDS_DARK_MATTER → cross_group_trend_A2 (SP signal thr=300 only)
#     Backtest: +16,904 vs naive_mm +7,558 → +9,346 improvement
# Total improvement: +35,634 → best_v13_A2 = 887,312 PnL
#
# Signal: SLEEP_POD group avg EMA vs session start (stable across days,
#   86% cross-day corr with GALAXY_SOUNDS, -75% with ROBOT)
# For BLACK_HOLES: combined SP>80 AND RB<-30 (robust, all 3 days positive)
# For DARK_MATTER: SP>300 alone sufficient (low noise, all 3 days positive)
#
# Why cross-group beats naive_mm here:
#   On "downtrend days" (SP down → GS down), naive_mm accumulates long inventory
#   that gets marked down badly (live v10: DARK_MATTER -3,834, BLACK_HOLES -5,223).
#   Cross-group strategy detects the regime early and goes SHORT → avoids the loss.
def _sc_mm(sym: str, size: int = 3, limit: int = 10) -> ProductConfig:
    """Self-contained naive_tight_mm shorthand for best_v13_A2."""
    return ProductConfig(symbol=sym, strategy="naive_tight_mm", position_limit=limit,
                         params=dict(maker_size=size, tighten_ticks=1,
                                     log_flush_ts=1000, ts_increment=100, last_ts_value=999900))

def _sc_trend(sym: str, ema_hl: float, thr: float, exit_thr: float,
              warmup: int = 0) -> ProductConfig:
    """Self-contained trend_follow_v2 shorthand for best_v13_A2."""
    return ProductConfig(symbol=sym, strategy="trend_follow_v2", position_limit=10,
                         params=dict(ema_half_life=ema_hl, threshold=thr, exit_threshold=exit_thr,
                                     warmup_ticks=warmup, position_limit=10,
                                     ts_increment=100, last_ts_value=999900, log_flush_ts=1000))

MEMBER_OVERRIDES["best_v13_A2"] = {
    5: {
        # ── PEBBLES ──────────────────────────────────────────────────────────
        "PEBBLES_XL": ProductConfig(
            symbol="PEBBLES_XL", strategy="pebbles_arb_v1", position_limit=10,
            params=dict(partner_products=["PEBBLES_L", "PEBBLES_M", "PEBBLES_S", "PEBBLES_XS"],
                        sum_target=50000.0, edge_ticks=7.0, passive_half_spread=6.0,
                        taker_size=10, passive_size=5, ewma_alpha=0.05,
                        position_limit=10, last_ts_value=999900)),
        "PEBBLES_XS":  _sc_trend("PEBBLES_XS", ema_hl=150, thr=250, exit_thr=80),
        "PEBBLES_L":   _sc_mm("PEBBLES_L",  size=3, limit=5),
        # PEBBLES_M: None (removed — consistently losing in backtest AND live)
        "PEBBLES_M":   None,
        "PEBBLES_S":   _sc_mm("PEBBLES_S",  size=3),
        # ── ROBOT ─────────────────────────────────────────────────────────────
        "ROBOT_DISHES": ProductConfig(
            symbol="ROBOT_DISHES", strategy="ar1_mean_rev_v1", position_limit=10,
            params=dict(entry_threshold=20.0, taker_size=10, passive_size=0,
                        exit_ticks=0, position_limit=10, last_ts_value=999900)),
        "ROBOT_MOPPING":  _sc_trend("ROBOT_MOPPING",  ema_hl=150, thr=100, exit_thr=40),
        "ROBOT_IRONING":  _sc_trend("ROBOT_IRONING",  ema_hl=150, thr=100, exit_thr=40),
        "ROBOT_LAUNDRY": ProductConfig(
            symbol="ROBOT_LAUNDRY", strategy="coint_mm_v1", position_limit=10,
            params=dict(partner_product="ROBOT_VACUUMING", mean_half_life=5000,
                        z_window=2000, entry_z=1.5, exit_z=0.0,
                        taker_size=10, passive_size=1, tighten_ticks=1,
                        position_limit=10, last_ts_value=999900)),  # A3: passive_size 3→1
        "ROBOT_VACUUMING": ProductConfig(
            symbol="ROBOT_VACUUMING", strategy="coint_mm_v1", position_limit=10,
            params=dict(partner_product="ROBOT_LAUNDRY", mean_half_life=5000,
                        z_window=2000, entry_z=1.5, exit_z=0.0,
                        taker_size=10, passive_size=3, tighten_ticks=1,
                        position_limit=10, last_ts_value=999900)),
        # ── GALAXY_SOUNDS ─────────────────────────────────────────────────────
        # A2: cross-group strategy using SLEEP_POD avg as directional signal
        "GALAXY_SOUNDS_BLACK_HOLES":  _v13_cg_A2("GALAXY_SOUNDS_BLACK_HOLES", sp_thr=80,  rb_thr=30),
        "GALAXY_SOUNDS_DARK_MATTER":  _v13_cg_A2("GALAXY_SOUNDS_DARK_MATTER",  sp_thr=300),
        "GALAXY_SOUNDS_PLANETARY_RINGS": _sc_mm("GALAXY_SOUNDS_PLANETARY_RINGS", size=3),  # A3: size=3
        "GALAXY_SOUNDS_SOLAR_FLAMES":    _sc_mm("GALAXY_SOUNDS_SOLAR_FLAMES",    size=3, limit=5),
        "GALAXY_SOUNDS_SOLAR_WINDS":     _sc_mm("GALAXY_SOUNDS_SOLAR_WINDS",     size=3),
        # ── SLEEP_POD ─────────────────────────────────────────────────────────
        "SLEEP_POD_LAMB_WOOL": None,  # intra-day spike trap, consistently loses
        "SLEEP_POD_COTTON":    _sc_trend("SLEEP_POD_COTTON",    ema_hl=100, thr=80,  exit_thr=30),
        "SLEEP_POD_NYLON":     _sc_trend("SLEEP_POD_NYLON",     ema_hl=100, thr=80,  exit_thr=30),
        "SLEEP_POD_POLYESTER": _sc_trend("SLEEP_POD_POLYESTER", ema_hl=150, thr=600, exit_thr=150),
        "SLEEP_POD_SUEDE":     _sc_mm("SLEEP_POD_SUEDE", size=3),
        # ── MICROCHIP ─────────────────────────────────────────────────────────
        "MICROCHIP_SQUARE":   _sc_trend("MICROCHIP_SQUARE", ema_hl=100, thr=250, exit_thr=80),
        "MICROCHIP_OVAL":     _sc_mm("MICROCHIP_OVAL",     size=5),
        "MICROCHIP_TRIANGLE": _sc_mm("MICROCHIP_TRIANGLE", size=3),
        "MICROCHIP_CIRCLE":   _sc_mm("MICROCHIP_CIRCLE",   size=3),
        "MICROCHIP_RECTANGLE": ProductConfig(
            symbol="MICROCHIP_RECTANGLE", strategy="coint_mm_v1", position_limit=10,
            params=dict(partner_product="MICROCHIP_SQUARE", mean_half_life=5000,
                        z_window=1000, entry_z=1.2, exit_z=0.0,
                        taker_size=10, passive_size=3, tighten_ticks=1,
                        position_limit=10, last_ts_value=999900)),
        # ── PANEL ─────────────────────────────────────────────────────────────
        "PANEL_1X2": _sc_trend("PANEL_1X2", ema_hl=100, thr=80, exit_thr=30),
        "PANEL_1X4": _sc_mm("PANEL_1X4", size=5),
        "PANEL_2X2": _sc_mm("PANEL_2X2", size=3),  # A3: size 5→3
        "PANEL_2X4": _sc_mm("PANEL_2X4", size=5),
        "PANEL_4X4": _sc_mm("PANEL_4X4", size=3, limit=5),
        # ── UV_VISOR ──────────────────────────────────────────────────────────
        "UV_VISOR_AMBER":   _sc_trend("UV_VISOR_AMBER", ema_hl=100, thr=80, exit_thr=30),
        "UV_VISOR_YELLOW":  _sc_trend("UV_VISOR_YELLOW", ema_hl=100, thr=700, exit_thr=150),
        "UV_VISOR_ORANGE":  _sc_mm("UV_VISOR_ORANGE",  size=5),
        "UV_VISOR_RED":     _sc_mm("UV_VISOR_RED",     size=5),
        "UV_VISOR_MAGENTA": _sc_mm("UV_VISOR_MAGENTA", size=3, limit=5),
        # ── OXYGEN_SHAKE ──────────────────────────────────────────────────────
        "OXYGEN_SHAKE_GARLIC":          _sc_trend("OXYGEN_SHAKE_GARLIC", ema_hl=150, thr=700, exit_thr=150),
        "OXYGEN_SHAKE_CHOCOLATE":       _sc_mm("OXYGEN_SHAKE_CHOCOLATE",       size=5),
        "OXYGEN_SHAKE_EVENING_BREATH":  _sc_mm("OXYGEN_SHAKE_EVENING_BREATH",  size=5),
        "OXYGEN_SHAKE_MORNING_BREATH":  _sc_mm("OXYGEN_SHAKE_MORNING_BREATH",  size=5),
        "OXYGEN_SHAKE_MINT":            _sc_mm("OXYGEN_SHAKE_MINT",            size=3),
        # ── SNACKPACK ─────────────────────────────────────────────────────────
        "SNACKPACK_CHOCOLATE":  _sc_mm("SNACKPACK_CHOCOLATE",  size=5),
        "SNACKPACK_VANILLA":    _sc_mm("SNACKPACK_VANILLA",    size=5),
        "SNACKPACK_PISTACHIO":  _sc_mm("SNACKPACK_PISTACHIO",  size=5),
        "SNACKPACK_STRAWBERRY": _sc_mm("SNACKPACK_STRAWBERRY", size=5),
        "SNACKPACK_RASPBERRY":  _sc_mm("SNACKPACK_RASPBERRY",  size=5),
        # ── TRANSLATOR ────────────────────────────────────────────────────────
        "TRANSLATOR_VOID_BLUE":        _sc_mm("TRANSLATOR_VOID_BLUE",        size=5),
        "TRANSLATOR_ASTRO_BLACK":      _sc_mm("TRANSLATOR_ASTRO_BLACK",      size=3),
        "TRANSLATOR_ECLIPSE_CHARCOAL": _sc_mm("TRANSLATOR_ECLIPSE_CHARCOAL", size=3),
        "TRANSLATOR_GRAPHITE_MIST":    _sc_mm("TRANSLATOR_GRAPHITE_MIST",    size=3, limit=5),
        "TRANSLATOR_SPACE_GRAY": None,  # consistently loses in both backtest and live
    }
}

# ── v14 helpers ───────────────────────────────────────────────────────────────
def _sc_trend14(sym: str, ema_hl: float, thr: float, exit_thr: float, direction: int = 0) -> ProductConfig:
    return ProductConfig(symbol=sym, strategy="trend_follow_v2", position_limit=10,
                         params=dict(ema_half_life=ema_hl, threshold=thr, exit_threshold=exit_thr,
                                     direction=direction,
                                     position_limit=10, ts_increment=100, last_ts_value=999900, log_flush_ts=1000))

# ── test_v14_dir_A2: directional TFv2 test (Theo-informed directions) ─────────
# Theo's directions from v12: MICROCHIP_OVAL=-10, MICROCHIP_TRIANGLE=-10,
# UV_VISOR_RED=+10, SLEEP_POD_SUEDE=+10, SLEEP_POD_POLYESTER=+10,
# OXYGEN_SHAKE_GARLIC=+10, PEBBLES_XS=-10
_v14_base = MEMBER_OVERRIDES["best_v13_A2"][5].copy()
_v14_dir = {
    **_v14_base,
    # Theo SHORT: MICROCHIP products always trend down
    "MICROCHIP_OVAL":     _sc_trend14("MICROCHIP_OVAL",     ema_hl=100, thr=60,  exit_thr=20, direction=-1),
    "MICROCHIP_TRIANGLE": _sc_trend14("MICROCHIP_TRIANGLE", ema_hl=100, thr=60,  exit_thr=20, direction=-1),
    # Theo LONG: UV_VISOR_RED always trends up
    "UV_VISOR_RED":       _sc_trend14("UV_VISOR_RED",       ema_hl=100, thr=60,  exit_thr=20, direction=+1),
    # Theo LONG: SLEEP_POD products trend up — bidirectional was losing when it went short
    "SLEEP_POD_SUEDE":    _sc_trend14("SLEEP_POD_SUEDE",    ema_hl=100, thr=60,  exit_thr=20, direction=+1),
    "SLEEP_POD_POLYESTER": _sc_trend14("SLEEP_POD_POLYESTER", ema_hl=150, thr=200, exit_thr=80, direction=+1),
    # Theo LONG: OXYGEN_SHAKE_GARLIC
    "OXYGEN_SHAKE_GARLIC": _sc_trend14("OXYGEN_SHAKE_GARLIC", ema_hl=150, thr=200, exit_thr=80, direction=+1),
    # Theo SHORT: PEBBLES_XS — existing TFv2 but lock direction to avoid wrong-way entries
    "PEBBLES_XS":          _sc_trend14("PEBBLES_XS",          ema_hl=150, thr=100, exit_thr=30, direction=-1),
    # ROBOT_IRONING: keep existing TFv2 bidirectional (momentum strategy in Theo, unclear direction)
    "ROBOT_IRONING":       _sc_trend14("ROBOT_IRONING",       ema_hl=100, thr=50,  exit_thr=20),
    # PEBBLES_S: keep naive_mm (38k baseline >> Theo's 19k directional) — no change
}
MEMBER_OVERRIDES["test_v14_dir_A2"] = {5: _v14_dir}

# ── best_v14_A2 (OLD — session_start mode) — kept for reference ───────────────
_v14_best = {
    **_v14_base,
    "MICROCHIP_OVAL":      _sc_trend14("MICROCHIP_OVAL",      ema_hl=100, thr=60,  exit_thr=20, direction=-1),
    "MICROCHIP_TRIANGLE":  _sc_trend14("MICROCHIP_TRIANGLE",  ema_hl=100, thr=60,  exit_thr=20, direction=-1),
    "PEBBLES_XS":          _sc_trend14("PEBBLES_XS",          ema_hl=150, thr=100, exit_thr=30, direction=-1),
    "OXYGEN_SHAKE_GARLIC": _sc_trend14("OXYGEN_SHAKE_GARLIC", ema_hl=150, thr=200, exit_thr=80, direction=+1),
    "ROBOT_IRONING":       _sc_trend14("ROBOT_IRONING",       ema_hl=100, thr=50,  exit_thr=20),
}
MEMBER_OVERRIDES["best_v14_A2"] = {5: _v14_best}

# ── v15: EMA-cross + trailing stop — generalises to non-monotonic live days ────
# Root cause analysis from v12_A2 live log:
#   PEBBLES_XS=0 live: price crossed -100 at tick 17 but then rallied to +200;
#     slow EMA averaged out, never triggered. EMA-cross detects the DOWN momentum
#     regardless of the initial counter-move.
#   OXYGEN_SHAKE_GARLIC=0 live: price was negative for 90% of session, recovered
#     to +278 in last 65 ticks; slow EMA anchored at -394 couldn't follow. EMA-cross
#     fast/slow divergence fires even on late-session momentum.
#   MICROCHIP_OVAL: price went UP first (+100 at tick 41) before falling -452;
#     session-start EMA pulled up, delayed SHORT entry. EMA-cross detects reversal sooner.
# Trail stop: exits when price reverses trail_stop_thr from extremum rather than
#   waiting for EMA to cross back past session_start ± exit_thr — limits losses on
#   reversal days while letting profitable trades run.
def _sc_cross15(sym: str, fast_hl: float, slow_hl: float, thr: float,
                exit_thr: float, trail: float, direction: int = 0) -> ProductConfig:
    return ProductConfig(symbol=sym, strategy="trend_follow_v2", position_limit=10,
                         params=dict(
                             signal_mode="ema_cross",
                             ema_fast_hl=fast_hl, ema_slow_hl=slow_hl,
                             threshold=thr, exit_threshold=exit_thr,
                             trail_stop_thr=trail, direction=direction,
                             position_limit=10, ts_increment=100,
                             last_ts_value=999900, log_flush_ts=1000))

_v15_best = {
    **_v14_base,
    # MICROCHIP: consistently fall session-long. EMA-cross detects early downward push
    # even after brief opening counter-move. SHORT-only prevents long entries on up days.
    "MICROCHIP_OVAL":      _sc_cross15("MICROCHIP_OVAL",      fast_hl=30, slow_hl=500,
                                        thr=40, exit_thr=20, trail=60, direction=-1),
    "MICROCHIP_TRIANGLE":  _sc_cross15("MICROCHIP_TRIANGLE",  fast_hl=30, slow_hl=500,
                                        thr=40, exit_thr=20, trail=60, direction=-1),
    # PEBBLES_XS: dipped early then rallied, final net negative. EMA-cross catches
    # downward momentum when it builds, trail stop exits quickly if it reverses.
    "PEBBLES_XS":          _sc_cross15("PEBBLES_XS",          fast_hl=30, slow_hl=300,
                                        thr=40, exit_thr=20, trail=60, direction=-1),
    # OXYGEN_SHAKE_GARLIC: positive most of 3 BT days but can recover late in live.
    # EMA-cross (fast_hl=20 for responsiveness) fires even on late-session recovery.
    "OXYGEN_SHAKE_GARLIC": _sc_cross15("OXYGEN_SHAKE_GARLIC", fast_hl=20, slow_hl=300,
                                        thr=60, exit_thr=20, trail=80, direction=+1),
    # ROBOT_IRONING: clean monotonic trends. Keep session_start mode (lower overhead)
    # but with thr=50 improvement from v14.
    "ROBOT_IRONING":       _sc_trend14("ROBOT_IRONING",       ema_hl=100, thr=50,
                                        exit_thr=20),
}
MEMBER_OVERRIDES["best_v15_A2"] = {5: _v15_best}

# ── best_v16_A2: session_start + reference_update + trail_stop ─────────────────
# Fixes the two live failure modes of v14 without destroying backtest:
#   1. PEBBLES_XS/MICROCHIP: counter-move at open pulls EMA away from reference →
#      add reference_update_interval=800 so reference resets to EMA after 800 flat
#      ticks; when price finally trends, signal fires from the updated (closer) base.
#      In backtest, we enter in position before tick 800 → update never fires → unchanged.
#   2. OXYGEN_SHAKE_GARLIC: negative for 90% of session (EMA anchored at bottom);
#      reference_update_interval=800 resets reference to the low; when price spikes,
#      signal = EMA - (low_reference) > threshold → fires even on a late recovery.
#      In backtest Day3 (continuously falling), reference chases price down → signal
#      never crosses +threshold → 0 PnL (avoids the -8,215 Day3 loss from v14).
#   3. trail_stop_thr: protective measure — exits when price gives back trail ticks
#      from the extremum rather than waiting for full reversal. Reduces loss on days
#      where we enter but the trend doesn't sustain.
def _sc_v16(sym: str, ema_hl: float, thr: float, exit_thr: float,
             trail: float, ref_interval: int, direction: int = 0) -> ProductConfig:
    return ProductConfig(symbol=sym, strategy="trend_follow_v2", position_limit=10,
                         params=dict(ema_half_life=ema_hl, threshold=thr,
                                     exit_threshold=exit_thr, trail_stop_thr=trail,
                                     reference_update_interval=ref_interval,
                                     direction=direction, position_limit=10,
                                     ts_increment=100, last_ts_value=999900,
                                     log_flush_ts=1000))

_v16_best = {
    **_v14_base,
    # MICROCHIP: tend to fall from session open; faster EMA (hl=50) reduces lag
    # on the initial UP counter-move; ref_update catches mid-session reversals.
    "MICROCHIP_OVAL":      _sc_v16("MICROCHIP_OVAL",      ema_hl=50, thr=50,
                                    exit_thr=20, trail=60, ref_interval=800, direction=-1),
    "MICROCHIP_TRIANGLE":  _sc_v16("MICROCHIP_TRIANGLE",  ema_hl=50, thr=50,
                                    exit_thr=20, trail=60, ref_interval=800, direction=-1),
    # PEBBLES_XS: volatile but net-short most days; ref_update essential for live.
    "PEBBLES_XS":          _sc_v16("PEBBLES_XS",          ema_hl=50, thr=60,
                                    exit_thr=20, trail=80, ref_interval=800, direction=-1),
    # OXYGEN_SHAKE_GARLIC: positive days trend up but sometimes only in last 20%.
    # ref_update=800 resets to low reference; trail=100 locks partial gains.
    "OXYGEN_SHAKE_GARLIC": _sc_v16("OXYGEN_SHAKE_GARLIC", ema_hl=50, thr=80,
                                    exit_thr=20, trail=100, ref_interval=800, direction=+1),
    # ROBOT_IRONING: clean monotonic trends, no counter-move issue; session_start works.
    "ROBOT_IRONING":       _sc_trend14("ROBOT_IRONING",       ema_hl=100, thr=50,
                                        exit_thr=20),
}
MEMBER_OVERRIDES["best_v16_A2"] = {5: _v16_best}

# ── best_v17_A2: cherry-pick best params per product ─────────────────────────
# MICROCHIP_TRIANGLE reverted to v14 params: it correctly got 0 live (price went
# UP all day, direction=-1 prevented loss — no over-fitting problem to fix).
# The v16 faster EMA + ref_update caused excessive round-trip losses in backtest
# (-13,536 Day2 vs -9,163 in v14) because the product is volatile on Day2.
_v17_best = {
    **_v14_base,
    "MICROCHIP_OVAL":      _sc_v16("MICROCHIP_OVAL",      ema_hl=50, thr=50,
                                    exit_thr=20, trail=60, ref_interval=800, direction=-1),
    "MICROCHIP_TRIANGLE":  _sc_trend14("MICROCHIP_TRIANGLE", ema_hl=100, thr=60,
                                        exit_thr=20, direction=-1),
    "PEBBLES_XS":          _sc_v16("PEBBLES_XS",          ema_hl=50, thr=60,
                                    exit_thr=20, trail=80, ref_interval=800, direction=-1),
    "OXYGEN_SHAKE_GARLIC": _sc_v16("OXYGEN_SHAKE_GARLIC", ema_hl=50, thr=80,
                                    exit_thr=20, trail=100, ref_interval=800, direction=+1),
    "ROBOT_IRONING":       _sc_trend14("ROBOT_IRONING",    ema_hl=100, thr=50,
                                        exit_thr=20),
}
MEMBER_OVERRIDES["best_v17_A2"] = {5: _v17_best}

# ── best_v18_A2: live-validated cherry-pick ────────────────────────────────────
# Diagnosis from v17 live (26k) vs v13 live (28k):
#   MICROCHIP_OVAL/TRIANGLE directional TFv2 backfired live:
#     - TRIANGLE: price went UP, direction=-1 got 0 vs naive_mm 3,036 (spread income lost)
#     - OVAL: fast EMA entered SHORT on -94 brief dip; trail fired at -1,470 loss;
#             re-entry recovered most but still -1,392 vs naive_mm's steady +2,619
#   PEBBLES_XS: fast ema_hl=50 entered SHORT on early dip; price recovered to +138;
#     trail fired at -1,730 realized; ended -1,252 vs v13/v14 0 (no entry = no loss)
#   Fix: MICROCHIP_OVAL + TRIANGLE → naive_mm (direction-agnostic, always makes spread)
#        PEBBLES_XS → v14 params (ema_hl=150 thr=100: slow enough not to fire on brief dips)
#   Keep: OXYGEN_SHAKE_GARLIC (ref_update fixed 0→2,458 live), ROBOT_IRONING (thr=50 improved)
_v18_best = {
    **_v14_base,
    "MICROCHIP_OVAL":      _sc_mm("MICROCHIP_OVAL",      size=5),
    "MICROCHIP_TRIANGLE":  _sc_mm("MICROCHIP_TRIANGLE",  size=3),
    "PEBBLES_XS":          _sc_trend14("PEBBLES_XS",     ema_hl=150, thr=100,
                                        exit_thr=30, direction=-1),
    "OXYGEN_SHAKE_GARLIC": _sc_v16("OXYGEN_SHAKE_GARLIC", ema_hl=50, thr=80,
                                    exit_thr=20, trail=100, ref_interval=800, direction=+1),
    "ROBOT_IRONING":       _sc_trend14("ROBOT_IRONING",   ema_hl=100, thr=50,
                                        exit_thr=20),
}
MEMBER_OVERRIDES["best_v18_A2"] = {5: _v18_best}
