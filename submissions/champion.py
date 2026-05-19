"""Public baseline submission wrapper."""

from prosperity.strategies.trader import Trader as _BaseTrader


class Trader(_BaseTrader):
    def __init__(self):
        super().__init__(round_num=0, member="champion")
