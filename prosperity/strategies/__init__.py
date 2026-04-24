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
    "velvet_delta_hedger": ("prosperity.strategies.round_3.velvet_delta_hedger", "VelvetDeltaHedgerStrategy"),
    "vol_harvest": ("prosperity.strategies.round_3.vol_harvest", "VolHarvestStrategy"),
    "anchor_adaptive": ("prosperity.strategies.round_3.anchor_adaptive", "AnchorAdaptiveStrategy"),
    "gamma_scalp": ("prosperity.strategies.round_3.gamma_scalp", "GammaScalpStrategy"),
    "hydrogel_mm": ("prosperity.strategies.round_3.hydrogel_mm", "HydrogelMMStrategy"),
    "hydrogel_mean_rev_taker": ("prosperity.strategies.round_3.hydrogel_mean_rev_taker", "HydrogelMeanRevTakerStrategy"),
    "hydrogel_oracle_inspired": ("prosperity.strategies.round_3.hydrogel_oracle_inspired", "HydrogelOracleInspiredStrategy"),
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
