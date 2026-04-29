"""Basket / group abstraction for R5: 10 wiki-defined groups + helpers.

Modules:
  groups       : GROUPS dict + group lookups
  context      : SharedR5Context (per-tick computed group indices, vol, etc.)
  basket_base  : base class for basket-aware strategies
"""
from prosperity.baskets.groups import GROUPS, group_of, GROUP_NAMES
from prosperity.baskets.context import SharedR5Context, get_or_create_context
from prosperity.baskets.etf import GroupETF, PCAPortfolio, PCA_PORTFOLIOS

__all__ = [
    "GROUPS",
    "GROUP_NAMES",
    "group_of",
    "SharedR5Context",
    "get_or_create_context",
    "GroupETF",
    "PCAPortfolio",
    "PCA_PORTFOLIOS",
]
