"""Bot behavior analysis — detect predictable/insider trading bots.

Processes market_trades across ticks to build profiles of each bot:
  - Trade frequency and sizing
  - Directional bias (net buyer/seller)
  - Price impact (average trade price vs mid at time of trade)
  - Timing patterns (does the bot trade before price moves?)

Use during the research phase to identify which bots to track.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

from datamodel import Trade


class BotProfile:
    __slots__ = ("name", "buy_count", "sell_count", "buy_volume", "sell_volume",
                 "buy_value", "sell_value", "price_impacts")

    def __init__(self, name: str):
        self.name = name
        self.buy_count = 0
        self.sell_count = 0
        self.buy_volume = 0
        self.sell_volume = 0
        self.buy_value = 0.0
        self.sell_value = 0.0
        self.price_impacts: List[float] = []

    @property
    def net_volume(self) -> int:
        return self.buy_volume - self.sell_volume

    @property
    def avg_buy_price(self) -> float:
        return self.buy_value / self.buy_volume if self.buy_volume > 0 else 0.0

    @property
    def avg_sell_price(self) -> float:
        return self.sell_value / self.sell_volume if self.sell_volume > 0 else 0.0

    @property
    def total_trades(self) -> int:
        return self.buy_count + self.sell_count

    def avg_price_impact(self) -> float:
        if not self.price_impacts:
            return 0.0
        return sum(self.price_impacts) / len(self.price_impacts)

    def summary(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "net_volume": self.net_volume,
            "avg_buy_price": round(self.avg_buy_price, 2),
            "avg_sell_price": round(self.avg_sell_price, 2),
            "avg_price_impact": round(self.avg_price_impact(), 4),
            "total_trades": self.total_trades,
        }


class BotDetector:
    """Accumulates trade data and builds bot profiles."""

    def __init__(self):
        self.profiles: Dict[str, Dict[str, BotProfile]] = defaultdict(dict)  # symbol -> name -> profile
        self._mid_history: Dict[str, List[Tuple[int, float]]] = defaultdict(list)

    def record_mid(self, symbol: str, timestamp: int, mid_price: float):
        self._mid_history[symbol].append((timestamp, mid_price))

    def process_trades(self, symbol: str, trades: List[Trade], current_mid: float | None = None):
        profs = self.profiles[symbol]

        for trade in trades:
            for name, is_buyer in [(trade.buyer, True), (trade.seller, False)]:
                if not name or name == "SUBMISSION":
                    continue

                if name not in profs:
                    profs[name] = BotProfile(name)

                p = profs[name]
                if is_buyer:
                    p.buy_count += 1
                    p.buy_volume += trade.quantity
                    p.buy_value += trade.price * trade.quantity
                else:
                    p.sell_count += 1
                    p.sell_volume += trade.quantity
                    p.sell_value += trade.price * trade.quantity

                if current_mid is not None:
                    impact = (trade.price - current_mid) * (1 if is_buyer else -1)
                    p.price_impacts.append(impact)

    def predictive_score(self, symbol: str, lookforward: int = 5) -> Dict[str, float]:
        """Compute how predictive each bot's trades are of future price moves.

        Higher score = bot's buys tend to precede price increases.
        Call this in research after processing all data.
        """
        mids = self._mid_history.get(symbol, [])
        if len(mids) < lookforward + 1:
            return {}

        mid_by_ts = {ts: m for ts, m in mids}
        timestamps = sorted(mid_by_ts.keys())
        ts_to_idx = {ts: i for i, ts in enumerate(timestamps)}

        scores: Dict[str, float] = {}
        for name, profile in self.profiles.get(symbol, {}).items():
            # We'd need per-trade timestamps to compute this properly
            # For now return net directional bias as a proxy
            total = profile.buy_volume + profile.sell_volume
            if total > 0:
                scores[name] = profile.net_volume / total
            else:
                scores[name] = 0.0

        return scores

    def rank_bots(self, symbol: str) -> List[Dict[str, Any]]:
        """Return bot profiles sorted by trade count (most active first)."""
        profs = self.profiles.get(symbol, {})
        ranked = sorted(profs.values(), key=lambda p: p.total_trades, reverse=True)
        return [p.summary() for p in ranked]
