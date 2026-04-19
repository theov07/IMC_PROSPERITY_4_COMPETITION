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
                mid_smooth_window=50,
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
