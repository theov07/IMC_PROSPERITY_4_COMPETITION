"""Strategy registry — maps strategy names to classes lazily."""

from __future__ import annotations

import sys
from importlib import import_module, util
from pathlib import Path
from typing import Any, Dict, Tuple, Type

from prosperity.strategies.base.base import BaseStrategy

_REGISTRY: Dict[str, Type[BaseStrategy]] = {}

_STRATEGY_SPECS: Dict[str, Tuple[str, str]] = {
    "market_maker": ("prosperity.strategies.base.market_maker", "MarketMakerStrategy"),
    "pair_trader": ("prosperity.strategies.round_5.pair_trader", "PairTraderStrategy"),
    "inventory_aware_mm": ("prosperity.strategies.round_5.inventory_mm", "InventoryAwareMMStrategy"),
    "zscore_mm": ("prosperity.strategies.round_5.zscore_mm", "ZScoreMMStrategy"),
    "basket_aware_mm": ("prosperity.strategies.round_5.basket_mm", "BasketAwareMMStrategy"),
    "tracking_error_mm": ("prosperity.strategies.round_5.tracking_error_mm", "TrackingErrorMMStrategy"),
    "pair_skip_mm": ("prosperity.strategies.round_5.pair_skip_mm", "PairSkipMMStrategy"),
    "pair_skip_lag_mm": ("prosperity.strategies.round_5.pair_skip_lag_mm", "PairSkipLagMMStrategy"),
    "impulse_pause_mm": ("prosperity.strategies.round_5.impulse_pause_mm", "ImpulsePauseMMStrategy"),
    "tracking_error_skip_mm": ("prosperity.strategies.round_5.tracking_error_skip_mm", "TrackingErrorSkipMMStrategy"),
    "multi_pair_skip_mm": ("prosperity.strategies.round_5.multi_pair_skip_mm", "MultiPairSkipMMStrategy"),
    "tick_reversal_skip_mm": ("prosperity.strategies.round_5.tick_reversal_skip_mm", "TickReversalSkipMMStrategy"),
    "adaptive_regime_mm": ("prosperity.strategies.round_5.adaptive_regime_mm", "AdaptiveRegimeMMStrategy"),
    "inventory_carry_mm": ("prosperity.strategies.round_5.inventory_carry_mm", "InventoryCarryMMStrategy"),
    "pca_residual_mr": ("prosperity.strategies.round_5.pca_residual_mr", "PCAResidualMRStrategy"),
    "zscore_mr_adaptive": ("prosperity.strategies.round_5.zscore_mr_adaptive", "ZScoreMRAdaptiveStrategy"),
    "top_down_filter_mm": ("prosperity.strategies.round_5.top_down_filter_mm", "TopDownFilterMMStrategy"),
    "real_mm": ("prosperity.strategies.round_5.real_mm", "RealMMStrategy"),
    "vol_adjusted_mm": ("prosperity.strategies.round_5.vol_adjusted_mm", "VolAdjustedMMStrategy"),
    "naive_tight_mm": ("prosperity.strategies.round_1.naive_tight_mm", "NaiveTightMarketMakerStrategy"),
    "naive_tight_mm_v2": ("prosperity.strategies.naive_tight_mm_v2", "NaiveTightMarketMakerV2Strategy"),
    "naive_tight_mm_v3": ("prosperity.strategies.naive_tight_mm_v3", "NaiveTightMarketMakerV3Strategy"),
    "naive_tight_mm_v4": ("prosperity.strategies.naive_tight_mm_v4", "NaiveTightMarketMakerV4Strategy"),
    "naive_tight_mm_v5": ("prosperity.strategies.naive_tight_mm_v5", "NaiveTightMarketMakerV5Strategy"),
    "naive_tight_mm_v6": ("prosperity.strategies.naive_tight_mm_v6", "NaiveTightMarketMakerV6Strategy"),
    "naive_tight_mm_v7": ("prosperity.strategies.naive_tight_mm_v7", "NaiveTightMarketMakerV7Strategy"),
    "naive_tight_mm_v8": ("prosperity.strategies.naive_tight_mm_v8", "NaiveTightMarketMakerV8Strategy"),
    "naive_tight_mm_v9": ("prosperity.strategies.naive_tight_mm_v9", "NaiveTightMarketMakerV9Strategy"),
    "naive_tight_mm_v10": ("prosperity.strategies.naive_tight_mm_v10", "NaiveTightMarketMakerV10Strategy"),
    "naive_tight_mm_v11": ("prosperity.strategies.naive_tight_mm_v11", "NaiveTightMarketMakerV11Strategy"),
    "naive_tight_mm_v12": ("prosperity.strategies.naive_tight_mm_v12", "NaiveTightMarketMakerV12Strategy"),
    "naive_tight_mm_v14": ("prosperity.strategies.naive_tight_mm_v14", "NaiveTightMarketMakerV14Strategy"),
    "naive_tight_mm_v15": ("prosperity.strategies.naive_tight_mm_v15", "NaiveTightMarketMakerV15Strategy"),
    "naive_tight_mm_v16": ("prosperity.strategies.naive_tight_mm_v16", "NaiveTightMarketMakerV16Strategy"),
    "naive_tight_mm_v17": ("prosperity.strategies.naive_tight_mm_v17", "NaiveTightMarketMakerV17Strategy"),
    "trend_biased_mm_v18": ("prosperity.strategies.naive_tight_mm_v18", "TrendBiasedMMV18Strategy"),
    "book_following_trend_mm_v19": ("prosperity.strategies.naive_tight_mm_v19", "BookFollowingTrendMMV19Strategy"),
    "book_following_trend_mm_v20": ("prosperity.strategies.naive_tight_mm_v20", "BookFollowingTrendMMV20Strategy"),
    "book_following_trend_mm_v21": ("prosperity.strategies.naive_tight_mm_v21", "BookFollowingTrendMMV21Strategy"),
    "naive_tight_mm_v23": ("prosperity.strategies.naive_tight_mm_v23", "NaiveTightMarketMakerV23Strategy"),
    "naive_tight_mm_v24": ("prosperity.strategies.naive_tight_mm_v24", "NaiveTightMarketMakerV24Strategy"),
    "trend_carry_mm_v25": ("prosperity.strategies.naive_tight_mm_v25", "TrendCarryMMV25Strategy"),
    "trend_carry_mm_v26": ("prosperity.strategies.naive_tight_mm_v26", "TrendCarryMMV26Strategy"),
    "trend_carry_mm_v34": ("prosperity.strategies.round_1.naive_tight_mm_v34", "TrendCarryMMV34Strategy"),
    "trend_carry_mm_v37": ("prosperity.strategies.round_1.naive_tight_mm_v37", "TrendCarryMMV37Strategy"),
    "trend_carry_mm_v38": ("prosperity.strategies.round_1.naive_tight_mm_v38", "TrendCarryMMV38Strategy"),
    "trend_carry_mm_v41": ("prosperity.strategies.round_1.naive_tight_mm_v41", "TrendCarryMMV41Strategy"),
    "round1_regression_top_book": ("prosperity.strategies.round_1.regression_top_book", "Round1RegressionTopBookStrategy"),
    "round1_regression_mm_v3": ("prosperity.strategies.round_1.regression_mm_v3", "Round1RegressionMMV3Strategy"),
    "round1_regression_mm_v4": ("prosperity.strategies.round_1.regression_mm_v4", "Round1RegressionMMV4Strategy"),
    "round1_regression_mm_v5": ("prosperity.strategies.round_1.regression_mm_v5", "Round1RegressionMMV5Strategy"),
    "leo_fusion_a": ("prosperity.strategies.round_1.leo_fusion_a", "LeoFusionAStrategy"),
    "leo_fusion_b": ("prosperity.strategies.round_1.leo_fusion_b", "LeoFusionBStrategy"),
    "leo_fusion_b_v3": ("prosperity.strategies.round_1.leo_fusion_b_v3", "LeoFusionBV3Strategy"),
    "leo_fusion_b_v4": ("prosperity.strategies.round_1.leo_fusion_b_v4", "LeoFusionBV4Strategy"),
    "leo_fusion_b_v5": ("prosperity.strategies.round_1.leo_fusion_b_v5", "LeoFusionBV5Strategy"),
    "leo_fusion_b_v6": ("prosperity.strategies.round_1.leo_fusion_b_v6", "LeoFusionBV6Strategy"),
    "leo_fusion_b_v7": ("prosperity.strategies.round_1.leo_fusion_b_v7", "LeoFusionBV7Strategy"),
    "leo_fusion_b_v8": ("prosperity.strategies.round_1.leo_fusion_b_v8", "LeoFusionBV8Strategy"),
    "leo_fusion_b_v10": ("prosperity.strategies.round_1.leo_fusion_b_v10", "LeoFusionBV10Strategy"),
    "leo_fusion_b_gap": ("prosperity.strategies.round_1.leo_fusion_b_gap", "LeoFusionBGapStrategy"),
    "leo_fusion_b_scout": ("prosperity.strategies.round_1.leo_fusion_b_scout", "LeoFusionBScoutStrategy"),
    "osmium_mr_artifact": ("prosperity.strategies.round_1.osmium_mr_artifact", "OsmiumMeanRevStrategy"),
    "leo_fusion_c": ("prosperity.strategies.round_1.leo_fusion_c", "LeoFusionCStrategy"),
    "leo_fusion_d": ("prosperity.strategies.round_1.leo_fusion_d", "LeoFusionDStrategy"),
    "avellaneda_stoikov": ("prosperity.strategies.base.avellaneda_stoikov", "AvellanedaStoikovStrategy"),
    "mm_first": ("prosperity.strategies.metal_winner.mm_first", "MMFirstStrategy"),
    "mm_first_v2": ("prosperity.strategies.metal_winner.mm_first_v2", "MMFirstStrategy"),
    "mm_first_v3": ("prosperity.strategies.round_2.tibo.mm_first_v3", "MMFirstStrategy"),
    "mm_first": ("prosperity.strategies.round_1.metal_winner.mm_first", "MMFirstStrategy"),
    "mm_first_v2": ("prosperity.strategies.round_1.metal_winner.mm_first_v2", "MMFirstStrategy"),
    "mean_reversion": ("prosperity.strategies.round_1.mean_reversion", "MeanReversionStrategy"),
    "zscore": ("prosperity.strategies.round_1.metal_winner.zscore", "ZScoreStrategy"),
    "buy_and_hold": ("prosperity.strategies.base.buy_and_hold", "BuyAndHoldStrategy"),
    "stat_arb": ("prosperity.strategies.base.stat_arb", "StatArbStrategy"),
    "black_scholes": ("prosperity.strategies.base.black_scholes", "BlackScholesStrategy"),
    "conversion_arb": ("prosperity.strategies.base.conversion_arb", "ConversionArbStrategy"),
    "signal_trader": ("prosperity.strategies.signal_trader", "SignalTraderStrategy"),
    "trend_carry_window": ("prosperity.strategies.round_1.trend_carry_window", "TrendCarryWindowStrategy"),
    "trend_carry_window_v2": ("prosperity.strategies.trend_carry_window_v2", "TrendCarryWindowV2Strategy"),
    "osmium_mr": ("prosperity.strategies.round_1.osmium_mr_artifact", "OsmiumMeanRevStrategy"),
    "osmium_mr_v2": ("prosperity.strategies.round_1.osmium_mr_v2", "OsmiumMeanRevV2Strategy"),
    "theo_best_generalized": ("prosperity.strategies.round_1.theo_best_generalized", "TheoGeneralizedStrategy"),
    "theo_root_ask_gap_generalised": (
        "prosperity.strategies.round_2.theo.theo_root_ask_gap_generalised",
        "TheoRootAskGapGeneralisedStrategy",
    ),
    "osmium_modulaire": ("prosperity.strategies.round_2.leo.osmium_modulaire", "OsmiumModulaireStrategy"),
    "pepper_modulaire": ("prosperity.strategies.round_2.leo.pepper_modulaire", "PepperModulaireStrategy"),
    "ask_exploit_modulaire": ("prosperity.strategies.round_2.theo.ask_exploit_modulaire", "AskExploitModulaireStrategy"),
    "aco_mm_modulaire": ("prosperity.strategies.round_2.leo.aco_mm_modulaire", "AcoMMModulaireStrategy"),
    "mm_first_v4_combo": ("prosperity.strategies.round_2.leo.mm_first_v4_combo", "MMFirstV4ComboStrategy"),
    "theo_best_clean_generalized":    ("prosperity.strategies.round_2.theo.theo_best_clean_generalized", "TheoBestCleanGeneralizedStrategy"),
    "theo_best_clean_generalized_v2": ("prosperity.strategies.round_2.theo.theo_best_clean_generalized", "TheoBestCleanGeneralizedV2Strategy"),
    "theo_best_clean_generalized_v3": ("prosperity.strategies.round_2.theo.theo_best_clean_generalized", "TheoBestCleanGeneralizedV3Strategy"),
    "theo_best_clean_generalized_v4": ("prosperity.strategies.round_2.theo.theo_best_clean_generalized", "TheoBestCleanGeneralizedV4Strategy"),
    # ── Round 3 ──
    "option_mm_bs": ("prosperity.strategies.round_3.option_mm_bs", "OptionMMBSStrategy"),
    # ── HEAD-only (keen-tharp worktree) ──
    "r3_gamma_scalp_zgated": ("prosperity.strategies.round_3.velvet_option_layers", "GammaScalpZGatedStrategy"),
    "r3_smile_iv_scalper": ("prosperity.strategies.round_3.velvet_option_layers", "SmileIVScalperStrategy"),
    "r3_live_defensive_mm": ("prosperity.strategies.round_3.live_defensive_mm", "R3LiveDefensiveMMStrategy"),
    "r3_hydro_reversion_mm": ("prosperity.strategies.round_3.hydro_reversion_mm", "R3HydroReversionMMStrategy"),
    # ── origin/main ──
    "r3_gamma_scalp_zgated": ("prosperity.strategies.round_3.velvet_option_layers", "GammaScalpZGatedStrategy"),
    "r3_smile_iv_scalper": ("prosperity.strategies.round_3.velvet_option_layers", "SmileIVScalperStrategy"),
    "r3_live_defensive_mm": ("prosperity.strategies.round_3.live_defensive_mm", "R3LiveDefensiveMMStrategy"),
    "r3_hydro_reversion_mm": ("prosperity.strategies.round_3.hydro_reversion_mm", "R3HydroReversionMMStrategy"),
    "option_skew_signal_mm": ("prosperity.strategies.round_3.option_skew_signal_mm", "OptionSkewSignalMMStrategy"),
    "option_skew_dynamic_mm": ("prosperity.strategies.round_3.option_skew_dynamic_mm", "OptionSkewDynamicMMStrategy"),
    "option_live_probe_mm": ("prosperity.strategies.round_3.option_live_probe_mm", "OptionLiveProbeMMStrategy"),
    "diagnostic_probe_mm": ("prosperity.strategies.round_3.diagnostic_probe_mm", "DiagnosticProbeMMStrategy"),
    "vev_option_mm_v3": ("prosperity.strategies.round_3.vev_option_mm_v3", "VEVOptionMMV3Strategy"),
    "gamma_scalp_zgated": ("prosperity.strategies.round_3.gamma_scalp_zgated", "GammaScalpZGatedStrategy"),
    "vega_neutral_pair_mm": ("prosperity.strategies.round_3.vega_neutral_pair_mm", "VegaNeutralPairMMStrategy"),
    "velvet_mr_taker_overlay": ("prosperity.strategies.round_3.velvet_mr_taker_overlay", "VelvetMRTakerOverlayStrategy"),
    "iv_momentum_mm": ("prosperity.strategies.round_3.iv_momentum_mm", "IVMomentumMMStrategy"),
    "velvet_r2_exhaustion_mm": ("prosperity.strategies.round_3.velvet_r2_exhaustion_mm", "VelvetR2ExhaustionMMStrategy"),
    "velvet_delta_hedger": ("prosperity.strategies.round_3.velvet_delta_hedger", "VelvetDeltaHedgerStrategy"),
    "vol_harvest": ("prosperity.strategies.round_3.vol_harvest", "VolHarvestStrategy"),
    "anchor_adaptive": ("prosperity.strategies.round_3.anchor_adaptive", "AnchorAdaptiveStrategy"),
    "gamma_scalp": ("prosperity.strategies.round_3.gamma_scalp", "GammaScalpStrategy"),
    "hydrogel_mm": ("prosperity.strategies.round_3.hydrogel_mm", "HydrogelMMStrategy"),
    "hydrogel_mean_rev_taker": ("prosperity.strategies.round_3.hydrogel_mean_rev_taker", "HydrogelMeanRevTakerStrategy"),
    "hydrogel_oracle_inspired": ("prosperity.strategies.round_3.hydrogel_oracle_inspired", "HydrogelOracleInspiredStrategy"),
    "hydrogel_asym_mm": ("prosperity.strategies.round_3.hydrogel_asym_mm", "HydrogelAsymMMStrategy"),
    "hydrogel_follow_mm": ("prosperity.strategies.round_3.hydrogel_follow_mm", "HydrogelFollowMMStrategy"),
    "hydrogel_ladder_mm": ("prosperity.strategies.round_3.hydrogel_ladder_mm", "HydrogelLadderMMStrategy"),
    "hydrogel_ladder_v2": ("prosperity.strategies.round_3.hydrogel_ladder_v2", "HydrogelLadderV2Strategy"),
    "hydrogel_reversion_mm": ("prosperity.strategies.round_3.hydrogel_reversion_mm", "HydrogelReversionMMStrategy"),
    "hydrogel_combo_mm": ("prosperity.strategies.round_3.hydrogel_combo_mm", "HydrogelComboMMStrategy"),
    "hydrogel_guarded_reversion_mm": (
        "prosperity.strategies.round_3.hydrogel_guarded_reversion_mm",
        "HydrogelGuardedReversionMMStrategy",
    ),
    "r4_hydro_mark14_mm": ("prosperity.strategies.round_4.hydro_mark14_mm", "R4HydroMark14MMStrategy"),
    "r4_hydro_guarded_mark_skew": (
        "prosperity.strategies.round_4.hydro_guarded_mark_skew",
        "R4HydroGuardedMarkSkewStrategy",
    ),
    "r4_hydro_mv_v6_invaware": (
        "prosperity.strategies.round_4.hydro_mv_v6_invaware",
        "R4HydroMVV6InvAwareStrategy",
    ),
    "r4_hydro_mv_v9_adaptive_fair": (
        "prosperity.strategies.round_4.hydro_mv_v9_adaptive_fair",
        "R4HydroMVV9AdaptiveFairStrategy",
    ),
    "r4_hydro_mv_v10_live_defensive": (
        "prosperity.strategies.round_4.hydro_mv_v10_live_defensive",
        "R4HydroMVV10LiveDefensiveStrategy",
    ),
    "r4_hydro_mv_v11_early_kill_fairsoft": (
        "prosperity.strategies.round_4.hydro_mv_v11_early_kill_fairsoft",
        "R4HydroMVV11EarlyKillFairSoftStrategy",
    ),
    "r4_hydro_mv_v12_vol_tail_kill": (
        "prosperity.strategies.round_4.hydro_mv_v12_vol_tail_kill",
        "R4HydroMVV12VolTailKillStrategy",
    ),
    "r4_hydro_mv_v11_mark_oracle": (
        "prosperity.strategies.round_4.hydro_mv_v11_mark_oracle",
        "R4HydroMVV11MarkOracleStrategy",
    ),
    "hydro_velvet_spread_skew_mm": (
        "prosperity.strategies.round_3.hydro_velvet_spread_skew_mm",
        "HydroVelvetSpreadSkewMMStrategy",
    ),
    "hydrogel_exhaustion_taker": (
        "prosperity.strategies.round_3.hydrogel_exhaustion_taker",
        "HydrogelExhaustionTakerStrategy",
    ),
    "hydrogel_passive_regime_mm": (
        "prosperity.strategies.round_3.hydrogel_passive_regime_mm",
        "HydrogelPassiveRegimeMMStrategy",
    ),
    "oracle_day2_replay": (
        "prosperity.strategies.round_3.oracle_day2_replay",
        "OracleDay2ReplayStrategy",
    ),
    "oracle_day2_l1_replay": (
        "prosperity.strategies.round_3.oracle_day2_l1_replay",
        "OracleDay2L1ReplayStrategy",
    ),
    "ms_regime_delta": ("prosperity.strategies.round_3.ms_regime_switching", "MSRegimeDeltaOneStrategy"),
    "ms_regime_option": ("prosperity.strategies.round_3.ms_regime_switching", "MSRegimeOptionMMStrategy"),
    "theo_best_clean_generalized_v7": ("prosperity.strategies.round_2.theo.theo_v7_continuous", "TheoBestCleanGeneralizedV7Strategy"),
    "theo_r3_vol_arb_v1": ("prosperity.strategies.round_3.theo.theo_r3_vol_arb_v1", "TheoR3VolArbV1Strategy"),
    # ── Tibo Round 3 ──
    "gamma_scalp_zgated":  ("prosperity.strategies.round_3.tibo.gamma_scalp_zgated", "GammaScalpZGatedStrategy"),
    "velvet_strat":        ("prosperity.strategies.round_3.tibo.velvet_strat",    "VelvetStratV1"),
    "velvet_strat_v25_mm":  ("prosperity.strategies.round_3.tibo.velvet_strat_v25", "VelvetMMV25"),
    "velvet_strat_v25_opt": ("prosperity.strategies.round_3.tibo.velvet_strat_v25", "VEVOptionMMV25"),
    "gamma_scalp_v25":      ("prosperity.strategies.round_3.tibo.velvet_strat_v25", "GammaScalpV25"),
    "velvet_strat_v26_mm":  ("prosperity.strategies.round_3.tibo.velvet_strat_v26", "VelvetMMV26"),
    "velvet_strat_v26_opt": ("prosperity.strategies.round_3.tibo.velvet_strat_v26", "VEVOptionMMV26"),
    "gamma_scalp_v26":      ("prosperity.strategies.round_3.tibo.velvet_strat_v26", "GammaScalpV26"),
    "velvet_strat_v2_mm":  ("prosperity.strategies.round_3.tibo.velvet_strat_v2", "VelvetMMV2"),
    "velvet_strat_v2_opt": ("prosperity.strategies.round_3.tibo.velvet_strat_v2", "VEVOptionMMV2"),
    "velvet_strat_v3_mm":  ("prosperity.strategies.round_3.tibo.velvet_strat_v3", "VelvetMMV3"),
    "velvet_strat_v3_opt": ("prosperity.strategies.round_3.tibo.velvet_strat_v3", "VEVOptionMMV3"),
    "smile_iv_scalper":          ("prosperity.strategies.round_3.tibo.smile_iv_scalper", "SmileIVScalerStrategy"),
    "smile_iv_scaler_v27":       ("prosperity.strategies.round_3.tibo.velvet_strat_v27", "SmileIVScalerV27"),
    "gamma_scalp_zgated_mixin":  ("prosperity.strategies.round_3.tibo.smile_iv_scalper", "GammaScalpZGatedMixinStrategy"),
    "theo_v7_velvet_mm":         ("prosperity.strategies.round_3.tibo.velvet_strat_theo_v7", "TheoV7VelvetMM"),
    "theo_v7_gamma_scalp":       ("prosperity.strategies.round_3.tibo.velvet_strat_theo_v7", "TheoV7GammaScalp"),
    "r3_guarded_anchor_mm":      ("prosperity.strategies.round_3.tibo.mm_first_v4_combo", "R3GuardedAnchorMMStrategy"),
    "dynamic_anchor_mm":         ("prosperity.strategies.round_3.tibo.mm_first_v4_combo", "DynamicAnchorMMStrategy"),
    "velvet_strat_v28_mm":       ("prosperity.strategies.round_3.tibo.velvet_strat_v28", "TheoV7VelvetMMV28"),
    "gamma_scalp_v28":           ("prosperity.strategies.round_3.tibo.velvet_strat_v28", "TheoV7GammaScalpV28"),
    "velvet_strat_v28_opt":      ("prosperity.strategies.round_3.tibo.velvet_strat_v28", "VEVOptionMMV28"),
    # v40: true 2-sided MM
    "symmetric_option_mm_v40":   ("prosperity.strategies.round_3.tibo.velvet_strat_v40", "SymmetricOptionMMV40"),
    "gamma_scalp_with_ask_v40":  ("prosperity.strategies.round_3.tibo.velvet_strat_v40", "GammaScalpWithAskV40"),
    # v30: four targeted option ideas
    "gamma_scalp_smile_v30_vev4500":    ("prosperity.strategies.round_3.tibo.velvet_strat_v30", "GammaScalpSmileV30VEV4500"),
    "gamma_scalp_with_ask_v30_vev5100": ("prosperity.strategies.round_3.tibo.velvet_strat_v30", "GammaScalpWithAskV30VEV5100"),
    "gamma_scalp_smile_v30_vev5200":    ("prosperity.strategies.round_3.tibo.velvet_strat_v30", "GammaScalpSmileV30VEV5200"),
    "delta_one_mm_v30":                 ("prosperity.strategies.round_3.tibo.velvet_strat_v30", "DeltaOneMMV30"),
    # v100: canonical standalone (direct imports, no intermediate wrapper chain)
    "velvet_mm_v100":      ("prosperity.strategies.round_3.tibo.velvet_strat_v100", "VelvetMMV100"),
    "gamma_scalp_v100":    ("prosperity.strategies.round_3.tibo.velvet_strat_v100", "GammaScalpV100"),
    "vev_option_mm_v100":  ("prosperity.strategies.round_3.tibo.velvet_strat_v100", "VEVOptionMMV100"),
    "hydro_mm_v100":       ("prosperity.strategies.round_3.tibo.velvet_strat_v100", "HydroMMV100"),
    # v200: hybrid hydro + velvet port
    "velvet_mm_v200":      ("prosperity.strategies.round_3.tibo.velvet_strat_v200", "VelvetMMV200"),
    "gamma_scalp_v200":    ("prosperity.strategies.round_3.tibo.velvet_strat_v200", "GammaScalpV200"),
    # v200: HYDROGEL standalone
    "hydro_mm_v200":       ("prosperity.strategies.round_3.tibo.hydro_strat_v200", "HydroMMV200"),
    # ── HEAD-only Round 3 (kept) ──
    "theo_r3_vol_arb_v1": ("prosperity.strategies.round_3.theo.theo_r3_vol_arb_v1", "TheoR3VolArbV1Strategy"),
    # ── Round 4 ──
    "oracle_replay_r4d3": ("prosperity.strategies.round_4.oracle_replay_d3", "OracleReplayR4D3Strategy"),
    "forced_long_buyer": ("prosperity.strategies.round_4.forced_long_buyer", "ForcedLongBuyerStrategy"),
    "live_alpha_probe": ("prosperity.strategies.round_4.live_alpha_probe", "LiveAlphaProbeStrategy"),
    "live_alpha_probe_extreme": ("prosperity.strategies.round_4.live_alpha_probe_extreme", "LiveAlphaProbeExtremeStrategy"),
    "live_alpha_probe_shadow": ("prosperity.strategies.round_4.live_alpha_probe_shadow", "LiveAlphaProbeShadowStrategy"),
    "live_alpha_probe_onoff": ("prosperity.strategies.round_4.live_alpha_probe_onoff", "LiveAlphaProbeOnOffStrategy"),
    "live_alpha_probe_size": ("prosperity.strategies.round_4.live_alpha_probe_size", "LiveAlphaProbeSizeStrategy"),
    # ── Tibo Round 3 ──
    "gamma_scalp_zgated":  ("prosperity.strategies.round_3.tibo.gamma_scalp_zgated", "GammaScalpZGatedStrategy"),
    "velvet_strat":        ("prosperity.strategies.round_3.tibo.velvet_strat",    "VelvetStratV1"),
    "velvet_strat_v25_mm":  ("prosperity.strategies.round_3.tibo.velvet_strat_v25", "VelvetMMV25"),
    "velvet_strat_v25_opt": ("prosperity.strategies.round_3.tibo.velvet_strat_v25", "VEVOptionMMV25"),
    "gamma_scalp_v25":      ("prosperity.strategies.round_3.tibo.velvet_strat_v25", "GammaScalpV25"),
    "velvet_strat_v26_mm":  ("prosperity.strategies.round_3.tibo.velvet_strat_v26", "VelvetMMV26"),
    "velvet_strat_v26_opt": ("prosperity.strategies.round_3.tibo.velvet_strat_v26", "VEVOptionMMV26"),
    "gamma_scalp_v26":      ("prosperity.strategies.round_3.tibo.velvet_strat_v26", "GammaScalpV26"),
    "velvet_strat_v2_mm":  ("prosperity.strategies.round_3.tibo.velvet_strat_v2", "VelvetMMV2"),
    "velvet_strat_v2_opt": ("prosperity.strategies.round_3.tibo.velvet_strat_v2", "VEVOptionMMV2"),
    "velvet_strat_v3_mm":  ("prosperity.strategies.round_3.tibo.velvet_strat_v3", "VelvetMMV3"),
    "velvet_strat_v3_opt": ("prosperity.strategies.round_3.tibo.velvet_strat_v3", "VEVOptionMMV3"),
    "smile_iv_scalper":          ("prosperity.strategies.round_3.tibo.smile_iv_scalper", "SmileIVScalerStrategy"),
    "smile_iv_scaler_v27":       ("prosperity.strategies.round_3.tibo.velvet_strat_v27", "SmileIVScalerV27"),
    "gamma_scalp_zgated_mixin":  ("prosperity.strategies.round_3.tibo.smile_iv_scalper", "GammaScalpZGatedMixinStrategy"),
    "theo_v7_velvet_mm":         ("prosperity.strategies.round_3.tibo.velvet_strat_theo_v7", "TheoV7VelvetMM"),
    "theo_v7_gamma_scalp":       ("prosperity.strategies.round_3.tibo.velvet_strat_theo_v7", "TheoV7GammaScalp"),
    "r3_guarded_anchor_mm":      ("prosperity.strategies.round_3.tibo.mm_first_v4_combo", "R3GuardedAnchorMMStrategy"),
    "dynamic_anchor_mm":         ("prosperity.strategies.round_3.tibo.mm_first_v4_combo", "DynamicAnchorMMStrategy"),
    "velvet_strat_v28_mm":       ("prosperity.strategies.round_3.tibo.velvet_strat_v28", "TheoV7VelvetMMV28"),
    "gamma_scalp_v28":           ("prosperity.strategies.round_3.tibo.velvet_strat_v28", "TheoV7GammaScalpV28"),
    "velvet_strat_v28_opt":      ("prosperity.strategies.round_3.tibo.velvet_strat_v28", "VEVOptionMMV28"),
    # v40: true 2-sided MM
    "symmetric_option_mm_v40":   ("prosperity.strategies.round_3.tibo.velvet_strat_v40", "SymmetricOptionMMV40"),
    "gamma_scalp_with_ask_v40":  ("prosperity.strategies.round_3.tibo.velvet_strat_v40", "GammaScalpWithAskV40"),
    # v30: four targeted option ideas
    "gamma_scalp_smile_v30_vev4500":    ("prosperity.strategies.round_3.tibo.velvet_strat_v30", "GammaScalpSmileV30VEV4500"),
    "gamma_scalp_with_ask_v30_vev5100": ("prosperity.strategies.round_3.tibo.velvet_strat_v30", "GammaScalpWithAskV30VEV5100"),
    "gamma_scalp_smile_v30_vev5200":    ("prosperity.strategies.round_3.tibo.velvet_strat_v30", "GammaScalpSmileV30VEV5200"),
    "delta_one_mm_v30":                 ("prosperity.strategies.round_3.tibo.velvet_strat_v30", "DeltaOneMMV30"),
    # v100: canonical standalone (direct imports, no intermediate wrapper chain)
    "velvet_mm_v100":      ("prosperity.strategies.round_3.tibo.velvet_strat_v100", "VelvetMMV100"),
    "gamma_scalp_v100":    ("prosperity.strategies.round_3.tibo.velvet_strat_v100", "GammaScalpV100"),
    "vev_option_mm_v100":  ("prosperity.strategies.round_3.tibo.velvet_strat_v100", "VEVOptionMMV100"),
    "hydro_mm_v100":       ("prosperity.strategies.round_3.tibo.velvet_strat_v100", "HydroMMV100"),
    # v200: hybrid hydro + velvet port
    "velvet_mm_v200":      ("prosperity.strategies.round_3.tibo.velvet_strat_v200", "VelvetMMV200"),
    "gamma_scalp_v200":    ("prosperity.strategies.round_3.tibo.velvet_strat_v200", "GammaScalpV200"),
    # v200: HYDROGEL standalone
    "hydro_mm_v200":       ("prosperity.strategies.round_3.tibo.hydro_strat_v200", "HydroMMV200"),
    # v200r4: HYDROGEL standalone (round 4 — direct BaseStrategy subclass, same logic)
    "hydro_mm_v200_r4":    ("prosperity.strategies.round_4.tibo.hydro_strat_v200", "HydroMMV200"),
    # mv_v1: z-score mean-reversion + Mark 14 gate
    "hydro_mv_v1":                 ("prosperity.strategies.round_4.tibo.hydro_mv_v1", "HydroMVV1"),
    # mv_v2: AR model mean-reversion
    "hydro_mv_v2":                 ("prosperity.strategies.round_4.tibo.hydro_mv_v2", "HydroMVV2"),
    # mv_v3: AR + Mark 14 integration (4 modes)
    "hydro_mv_v3":                 ("prosperity.strategies.round_4.tibo.hydro_mv_v3", "HydroMVV3"),
    # mv_v4: best v3 + optional v200 features
    "hydro_mv_v4":                 ("prosperity.strategies.round_4.tibo.hydro_mv_v4", "HydroMVV4"),
    # mv_v5: passive MM core + v201 features ablation
    "hydro_mv_v5":                 ("prosperity.strategies.round_4.tibo.hydro_mv_v5", "HydroMVV5"),
    # mv_v6: dynamic anchor variants (slow_ewma / rolling_median / regime_switch / inv_protected)
    "hydro_mv_v6":                 ("prosperity.strategies.round_4.tibo.hydro_mv_v6", "HydroMVV6"),
    # mv_v7: two-component MM (anchor AR taker + fast passive MM both sides)
    "hydro_mv_v7":                 ("prosperity.strategies.round_4.tibo.hydro_mv_v7", "HydroMVV7"),
    # mv_v8: hysteresis on AR taker + inventory-skewed MM
    "hydro_mv_v8":                 ("prosperity.strategies.round_4.tibo.hydro_mv_v8", "HydroMVV8"),
    # mv_v9: v6b + hard cap ALL orders + M14 cumulative gate + inv skew
    "hydro_mv_v9":                 ("prosperity.strategies.round_4.tibo.hydro_mv_v9", "HydroMVV9"),
    # mv_v10: active MM with hard inventory cap + vol gate
    "hydro_mv_v10":                ("prosperity.strategies.round_4.tibo.hydro_mv_v10", "HydroMVV10"),
    # mv_v11: v9 base + M38 streak gate (data-driven: M38 is the aggressor)
    "hydro_mv_v11":                ("prosperity.strategies.round_4.tibo.hydro_mv_v11", "HydroMVV11"),
    # mv_v12: v9 base + M14 VEV_4000 cross-asset hedge signal
    "hydro_mv_v12":                ("prosperity.strategies.round_4.tibo.hydro_mv_v12", "HydroMVV12"),
    # mv_v13: dual gate = v9 M14-HYDRO gate + v12 VEV_4000 hedge gate
    "hydro_mv_v13":                ("prosperity.strategies.round_4.tibo.hydro_mv_v13", "HydroMVV13"),
    # v201: Mark 14 informed-trader gate (3 variants)
    "hydro_mm_v201_ruled":         ("prosperity.strategies.round_4.tibo.hydro_strat_v201", "HydroMMV201Ruled"),
    "hydro_mm_v201_influenced":    ("prosperity.strategies.round_4.tibo.hydro_strat_v201_influenced", "HydroMMV201Influenced"),
    "hydro_mm_v201_cancel_against":("prosperity.strategies.round_4.tibo.hydro_strat_v201", "HydroMMV201CancelAgainst"),
    "r4_gamma_scalp_zgated_slim": ("prosperity.strategies.round_4.gamma_scalp_zgated_slim", "R4GammaScalpZGatedSlimStrategy"),
    "r4_hydro_reversion_mm_slim": ("prosperity.strategies.round_4.hydro_reversion_mm_slim", "R4HydroReversionMMSlimStrategy"),

    # ── Round 5 — Tibo ────────────────────────────────────────────────────────
    "snackpack_pairs_v1":          ("prosperity.strategies.round_5.tibo.snackpack_pairs_v1", "SnackpackPairsV1"),
    "pebbles_arb_v1":              ("prosperity.strategies.round_5.tibo.pebbles_arb_v1", "PebblesArbV1"),
    "ar1_mean_rev_v1":             ("prosperity.strategies.round_5.tibo.ar1_mean_rev_v1", "AR1MeanRevV1"),
    "trend_follow_v1": ("prosperity.strategies.round_5.tibo.trend_follow_v1", "TrendFollowV1"),
    "trend_follow_v2": ("prosperity.strategies.round_5.tibo.trend_follow_v2", "TrendFollowV2"),
    "coint_pairs_v1":  ("prosperity.strategies.round_5.tibo.coint_pairs_v1", "CointPairsV1"),
    "coint_mm_v1":     ("prosperity.strategies.round_5.tibo.coint_mm_v1", "CointMMV1"),
    "late_flatten_tight_mm_v1": ("prosperity.strategies.round_5.tibo.late_flatten_tight_mm_v1", "LateFlattenTightMMV1"),
    "snackpack_cross_mm_v1_A1": ("prosperity.strategies.round_5.tibo.snackpack_cross_mm_A1", "SnackpackCrossMMV1_A1"),
    "cross_group_trend_A2": ("prosperity.strategies.round_5.tibo.cross_group_trend_A2", "CrossGroupTrendA2"),
}


def _package_dir(module_path: str) -> Path:
    parts = module_path.split(".")
    if len(parts) < 3 or parts[:2] != ["prosperity", "strategies"]:
        raise ModuleNotFoundError(module_path)
    package_parts = parts[2:-1]
    return Path(__file__).resolve().parent.joinpath(*package_parts)


def _import_with_pyc_fallback(module_path: str):
    try:
        return import_module(module_path)
    except ModuleNotFoundError as exc:
        package_dir = _package_dir(module_path)
        module_name = module_path.rsplit(".", 1)[-1]
        pyc_name = f"{module_name}.cpython-{sys.version_info.major}{sys.version_info.minor}.pyc"
        pyc_path = package_dir / "__pycache__" / pyc_name
        if not pyc_path.exists():
            raise exc
        spec = util.spec_from_file_location(module_path, pyc_path)
        if spec is None or spec.loader is None:
            raise exc
        module = util.module_from_spec(spec)
        sys.modules[module_path] = module
        spec.loader.exec_module(module)
        return module


def get_strategy_class(name: str) -> Type[BaseStrategy]:
    if name in _REGISTRY:
        return _REGISTRY[name]
    if name not in _STRATEGY_SPECS:
        raise ValueError(f"Unknown strategy: {name!r}. Available: {list(_STRATEGY_SPECS.keys())}")
    module_path, class_name = _STRATEGY_SPECS[name]
    module = _import_with_pyc_fallback(module_path)
    try:
        cls = getattr(module, class_name)
    except AttributeError as exc:
        raise AttributeError(f"{module_path} does not define {class_name}") from exc
    _REGISTRY[name] = cls
    return cls


def build_strategy(name: str, product: str, params: Dict[str, Any]) -> BaseStrategy:
    cls = get_strategy_class(name)
    return cls(product=product, params=params)
