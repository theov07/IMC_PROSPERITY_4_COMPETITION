from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd

from datamodel import Listing, Observation, OrderDepth, Symbol, Trade, TradingState


class MarketDataLoader:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)

    def load_prices(self, file_name: str) -> pd.DataFrame:
        return pd.read_csv(self.data_dir / file_name, sep=";")

    def load_trades(self, file_name: str) -> pd.DataFrame:
        return pd.read_csv(self.data_dir / file_name, sep=";")

    def load_trade_objects(self, file_name: str) -> List[Trade]:
        trades_df = self.load_trades(file_name)
        trades: List[Trade] = []

        for _, row in trades_df.iterrows():
            trades.append(
                Trade(
                    symbol=str(row["symbol"]),
                    price=int(float(row["price"])),
                    quantity=int(row["quantity"]),
                    buyer=str(row["buyer"]) if pd.notna(row["buyer"]) and row["buyer"] != "" else None,
                    seller=str(row["seller"]) if pd.notna(row["seller"]) and row["seller"] != "" else None,
                    timestamp=int(row["timestamp"]),
                )
            )

        return trades

    @staticmethod
    def row_to_order_depth(row: pd.Series) -> OrderDepth:
        order_depth = OrderDepth()

        for level in range(1, 4):
            bid_price_key = f"bid_price_{level}"
            bid_volume_key = f"bid_volume_{level}"
            ask_price_key = f"ask_price_{level}"
            ask_volume_key = f"ask_volume_{level}"

            if bid_price_key in row and pd.notna(row[bid_price_key]):
                order_depth.buy_orders[int(row[bid_price_key])] = int(row[bid_volume_key])

            if ask_price_key in row and pd.notna(row[ask_price_key]):
                order_depth.sell_orders[int(row[ask_price_key])] = -int(row[ask_volume_key])

        return order_depth

    def order_depth_history(self, prices_df: pd.DataFrame) -> Dict[int, Dict[Symbol, OrderDepth]]:
        history: Dict[int, Dict[Symbol, OrderDepth]] = {}

        for _, row in prices_df.iterrows():
            timestamp = int(row["timestamp"])
            product = str(row["product"])
            history.setdefault(timestamp, {})[product] = self.row_to_order_depth(row)

        return history

    @staticmethod
    def build_listings(products: Iterable[str], denomination: str = "XIRECS") -> Dict[Symbol, Listing]:
        return {
            product: Listing(symbol=product, product=product, denomination=denomination)
            for product in sorted(set(products))
        }

    @staticmethod
    def group_trades_by_timestamp(trades: List[Trade]) -> Dict[int, Dict[Symbol, List[Trade]]]:
        grouped: Dict[int, Dict[Symbol, List[Trade]]] = {}
        for trade in trades:
            grouped.setdefault(trade.timestamp, {}).setdefault(trade.symbol, []).append(trade)
        return grouped

    def available_days(self, round_num: int = 0) -> List[str]:
        days = []
        prefix = f"prices_round_{round_num}_day_"
        for file_path in self.data_dir.glob(f"{prefix}*.csv"):
            days.append(file_path.stem.replace(prefix, ""))
        return sorted(days)

    @staticmethod
    def empty_observation() -> Observation:
        return Observation(plainValueObservations={}, conversionObservations={})


def dataframe_from_semicolon_text(raw_text: str) -> pd.DataFrame:
    if not raw_text.strip():
        return pd.DataFrame()
    return pd.read_csv(StringIO(raw_text), sep=";")

