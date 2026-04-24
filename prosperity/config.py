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
            strategy="velvet_delta_hedger",
            position_limit=200,
            underlying_symbol="VELVETFRUIT_EXTRACT",
            hedge_strikes=[4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500],
            strike_prefix="VEV_",
            tte_days_initial=5.0,
            timestamp_units_per_day=1000000,
            historical_tte_by_day={0: 8.0, 1: 7.0, 2: 6.0},
            target_delta=0.0,
            hedge_taker_edge=30.0,
            max_hedge_size=50,
            passive_base_size=30,
            passive_skew_per_delta=0.5,
            quote_inside_book=True,
            sigma_floor=0.005,
            sigma_cap=0.10,
            prior_vol=0.0215,
            log_flush_ts=1000,
            ts_increment=100,
            last_ts_value=999900,
        ),
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
