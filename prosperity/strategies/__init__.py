"""Strategy registry — maps strategy names to classes."""

from __future__ import annotations

from typing import Any, Dict, Type

from prosperity.strategies.base import BaseStrategy

_REGISTRY: Dict[str, Type[BaseStrategy]] = {}
_LOADED = False


def _load_registry():
    global _LOADED
    if _LOADED:
        return
    from prosperity.strategies.market_maker import MarketMakerStrategy
    from prosperity.strategies.naive_tight_mm import NaiveTightMarketMakerStrategy
    from prosperity.strategies.naive_tight_mm_v2 import NaiveTightMarketMakerV2Strategy
    from prosperity.strategies.naive_tight_mm_v3 import NaiveTightMarketMakerV3Strategy
    from prosperity.strategies.naive_tight_mm_v4 import NaiveTightMarketMakerV4Strategy
    from prosperity.strategies.naive_tight_mm_v5 import NaiveTightMarketMakerV5Strategy
    from prosperity.strategies.naive_tight_mm_v6 import NaiveTightMarketMakerV6Strategy
    from prosperity.strategies.naive_tight_mm_v7 import NaiveTightMarketMakerV7Strategy
    from prosperity.strategies.naive_tight_mm_v8 import NaiveTightMarketMakerV8Strategy
    from prosperity.strategies.naive_tight_mm_v9 import NaiveTightMarketMakerV9Strategy
    from prosperity.strategies.naive_tight_mm_v10 import NaiveTightMarketMakerV10Strategy
    from prosperity.strategies.naive_tight_mm_v11 import NaiveTightMarketMakerV11Strategy
    from prosperity.strategies.naive_tight_mm_v12 import NaiveTightMarketMakerV12Strategy
    from prosperity.strategies.naive_tight_mm_v14 import NaiveTightMarketMakerV14Strategy
    from prosperity.strategies.naive_tight_mm_v15 import NaiveTightMarketMakerV15Strategy
    from prosperity.strategies.naive_tight_mm_v16 import NaiveTightMarketMakerV16Strategy
    from prosperity.strategies.naive_tight_mm_v17 import NaiveTightMarketMakerV17Strategy
    from prosperity.strategies.naive_tight_mm_v18 import TrendBiasedMMV18Strategy
    from prosperity.strategies.naive_tight_mm_v20 import BookFollowingTrendMMV20Strategy
    from prosperity.strategies.naive_tight_mm_v21 import BookFollowingTrendMMV21Strategy
    from prosperity.strategies.naive_tight_mm_v23 import NaiveTightMarketMakerV23Strategy
    from prosperity.strategies.naive_tight_mm_v24 import NaiveTightMarketMakerV24Strategy
    from prosperity.strategies.round_1.regression_top_book import Round1RegressionTopBookStrategy
    from prosperity.strategies.round_1.regression_mm_v3 import Round1RegressionMMV3Strategy
    from prosperity.strategies.round_1.regression_mm_v4 import Round1RegressionMMV4Strategy
    from prosperity.strategies.round_1.regression_mm_v5 import Round1RegressionMMV5Strategy
    from prosperity.strategies.round_1.leo_fusion_a import LeoFusionAStrategy
    from prosperity.strategies.round_1.leo_fusion_b import LeoFusionBStrategy
    from prosperity.strategies.round_1.leo_fusion_c import LeoFusionCStrategy
    from prosperity.strategies.round_1.leo_fusion_d import LeoFusionDStrategy
    from prosperity.strategies.avellaneda_stoikov import AvellanedaStoikovStrategy
    from prosperity.strategies.mm_first import MMFirstStrategy
    from prosperity.strategies.mean_reversion import MeanReversionStrategy
    from prosperity.strategies.zscore import ZScoreStrategy
    from prosperity.strategies.buy_and_hold import BuyAndHoldStrategy
    from prosperity.strategies.stat_arb import StatArbStrategy
    from prosperity.strategies.black_scholes import BlackScholesStrategy
    from prosperity.strategies.conversion_arb import ConversionArbStrategy
    from prosperity.strategies.naive_tight_mm_v19 import BookFollowingTrendMMV19Strategy
    from prosperity.strategies.signal_trader import SignalTraderStrategy

    _REGISTRY["market_maker"] = MarketMakerStrategy
    _REGISTRY["naive_tight_mm"] = NaiveTightMarketMakerStrategy
    _REGISTRY["naive_tight_mm_v2"] = NaiveTightMarketMakerV2Strategy
    _REGISTRY["naive_tight_mm_v3"] = NaiveTightMarketMakerV3Strategy
    _REGISTRY["naive_tight_mm_v4"] = NaiveTightMarketMakerV4Strategy
    _REGISTRY["naive_tight_mm_v5"] = NaiveTightMarketMakerV5Strategy
    _REGISTRY["naive_tight_mm_v6"] = NaiveTightMarketMakerV6Strategy
    _REGISTRY["naive_tight_mm_v7"] = NaiveTightMarketMakerV7Strategy
    _REGISTRY["naive_tight_mm_v8"] = NaiveTightMarketMakerV8Strategy
    _REGISTRY["naive_tight_mm_v9"] = NaiveTightMarketMakerV9Strategy
    _REGISTRY["naive_tight_mm_v10"] = NaiveTightMarketMakerV10Strategy
    _REGISTRY["naive_tight_mm_v11"] = NaiveTightMarketMakerV11Strategy
    _REGISTRY["naive_tight_mm_v12"] = NaiveTightMarketMakerV12Strategy
    _REGISTRY["naive_tight_mm_v14"] = NaiveTightMarketMakerV14Strategy
    _REGISTRY["naive_tight_mm_v15"] = NaiveTightMarketMakerV15Strategy
    _REGISTRY["naive_tight_mm_v16"] = NaiveTightMarketMakerV16Strategy
    _REGISTRY["naive_tight_mm_v17"] = NaiveTightMarketMakerV17Strategy
    _REGISTRY["trend_biased_mm_v18"] = TrendBiasedMMV18Strategy
    _REGISTRY["book_following_trend_mm_v20"] = BookFollowingTrendMMV20Strategy
    _REGISTRY["book_following_trend_mm_v21"] = BookFollowingTrendMMV21Strategy
    _REGISTRY["naive_tight_mm_v23"] = NaiveTightMarketMakerV23Strategy
    _REGISTRY["naive_tight_mm_v24"] = NaiveTightMarketMakerV24Strategy
    _REGISTRY["round1_regression_top_book"] = Round1RegressionTopBookStrategy
    _REGISTRY["round1_regression_mm_v3"] = Round1RegressionMMV3Strategy
    _REGISTRY["round1_regression_mm_v4"] = Round1RegressionMMV4Strategy
    _REGISTRY["round1_regression_mm_v5"] = Round1RegressionMMV5Strategy
    _REGISTRY["leo_fusion_a"] = LeoFusionAStrategy
    _REGISTRY["leo_fusion_b"] = LeoFusionBStrategy
    _REGISTRY["leo_fusion_c"] = LeoFusionCStrategy
    _REGISTRY["leo_fusion_d"] = LeoFusionDStrategy
    _REGISTRY["avellaneda_stoikov"] = AvellanedaStoikovStrategy
    _REGISTRY["mm_first"] = MMFirstStrategy
    _REGISTRY["mean_reversion"] = MeanReversionStrategy
    _REGISTRY["zscore"] = ZScoreStrategy
    _REGISTRY["buy_and_hold"] = BuyAndHoldStrategy
    _REGISTRY["stat_arb"] = StatArbStrategy
    _REGISTRY["black_scholes"] = BlackScholesStrategy
    _REGISTRY["conversion_arb"] = ConversionArbStrategy
    _REGISTRY["book_following_trend_mm_v19"] = BookFollowingTrendMMV19Strategy
    _REGISTRY["signal_trader"] = SignalTraderStrategy
    _LOADED = True


def get_strategy_class(name: str) -> Type[BaseStrategy]:
    _load_registry()
    if name not in _REGISTRY:
        raise ValueError(f"Unknown strategy: {name!r}. Available: {list(_REGISTRY.keys())}")
    return _REGISTRY[name]


def build_strategy(name: str, product: str, params: Dict[str, Any]) -> BaseStrategy:
    cls = get_strategy_class(name)
    return cls(product=product, params=params)
