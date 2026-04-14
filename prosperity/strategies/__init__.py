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
    from prosperity.strategies.avellaneda_stoikov import AvellanedaStoikovStrategy
    from prosperity.strategies.mm_first import MMFirstStrategy
    from prosperity.strategies.buy_and_hold import BuyAndHoldStrategy
    from prosperity.strategies.stat_arb import StatArbStrategy
    from prosperity.strategies.black_scholes import BlackScholesStrategy
    from prosperity.strategies.conversion_arb import ConversionArbStrategy
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
    _REGISTRY["avellaneda_stoikov"] = AvellanedaStoikovStrategy
    _REGISTRY["mm_first"] = MMFirstStrategy
    _REGISTRY["buy_and_hold"] = BuyAndHoldStrategy
    _REGISTRY["stat_arb"] = StatArbStrategy
    _REGISTRY["black_scholes"] = BlackScholesStrategy
    _REGISTRY["conversion_arb"] = ConversionArbStrategy
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
