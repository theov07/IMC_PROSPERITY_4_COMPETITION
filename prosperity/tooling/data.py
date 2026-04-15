from __future__ import annotations

from io import StringIO
from pathlib import Path
import re
from typing import Dict, Iterable, List

import pandas as pd

from datamodel import ConversionObservation, Listing, Observation, OrderDepth, Symbol, Trade, TradingState


class MarketDataLoader:
    ROUND_FILE_RE = re.compile(r"^(prices|trades)_round_(?P<round>\d+)_day_.+\.csv$")
    STANDARD_PRICE_COLUMNS = {
        "day",
        "timestamp",
        "product",
        "mid_price",
        "profit_and_loss",
        *(f"bid_price_{level}" for level in range(1, 4)),
        *(f"bid_volume_{level}" for level in range(1, 4)),
        *(f"ask_price_{level}" for level in range(1, 4)),
        *(f"ask_volume_{level}" for level in range(1, 4)),
    }

    CONVERSION_FIELD_ALIASES = {
        "bidPrice": ["bidPrice", "conversion_bid_price", "conversion_bidPrice", "observation_bid_price", "observation_bidPrice"],
        "askPrice": ["askPrice", "conversion_ask_price", "conversion_askPrice", "observation_ask_price", "observation_askPrice"],
        "transportFees": ["transportFees", "transport_fees", "conversion_transport_fees", "observation_transport_fees"],
        "exportTariff": ["exportTariff", "export_tariff", "conversion_export_tariff", "observation_export_tariff"],
        "importTariff": ["importTariff", "import_tariff", "conversion_import_tariff", "observation_import_tariff"],
        "sunlight": ["sunlight", "sunlightIndex", "sunlight_index"],
        "humidity": ["humidity", "humidityIndex", "humidity_index"],
    }

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)

    def _resolve_file_path(self, file_name: str | Path) -> Path:
        path = Path(file_name)
        if path.is_absolute():
            return path

        root_candidate = self.data_dir / path
        match = self.ROUND_FILE_RE.match(path.name)
        if match:
            round_dir_candidate = self.data_dir / f"round_{match.group('round')}" / path.name
            if round_dir_candidate.exists():
                return round_dir_candidate
        if root_candidate.exists():
            return root_candidate
        return root_candidate

    def _round_dir(self, round_num: int) -> Path:
        round_dir = self.data_dir / f"round_{round_num}"
        return round_dir if round_dir.exists() and round_dir.is_dir() else self.data_dir

    def load_prices(self, file_name: str) -> pd.DataFrame:
        return pd.read_csv(self._resolve_file_path(file_name), sep=";")

    def load_trades(self, file_name: str) -> pd.DataFrame:
        return pd.read_csv(self._resolve_file_path(file_name), sep=";")

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
    def _coerce_float(value) -> float | None:
        if pd.isna(value):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _first_present_float(cls, row: pd.Series, aliases: List[str]) -> float | None:
        for alias in aliases:
            if alias in row.index:
                value = cls._coerce_float(row[alias])
                if value is not None:
                    return value
        return None

    @classmethod
    def row_to_observation_values(cls, row: pd.Series) -> Dict[str, float]:
        values: Dict[str, float] = {}
        for column, raw_value in row.items():
            if column in cls.STANDARD_PRICE_COLUMNS:
                continue
            value = cls._coerce_float(raw_value)
            if value is None:
                continue
            values[column] = value
        return values

    @classmethod
    def row_to_conversion_observation(cls, row: pd.Series) -> ConversionObservation | None:
        resolved = {
            field: cls._first_present_float(row, aliases)
            for field, aliases in cls.CONVERSION_FIELD_ALIASES.items()
        }
        mandatory = ["bidPrice", "askPrice", "transportFees", "exportTariff", "importTariff"]
        if any(resolved[field] is None for field in mandatory):
            return None

        extra_kwargs = {}
        alias_columns = {
            alias
            for aliases in cls.CONVERSION_FIELD_ALIASES.values()
            for alias in aliases
        }
        for column, value in cls.row_to_observation_values(row).items():
            if column in alias_columns:
                continue
            extra_kwargs[column] = value

        return ConversionObservation(
            bidPrice=resolved["bidPrice"],
            askPrice=resolved["askPrice"],
            transportFees=resolved["transportFees"],
            exportTariff=resolved["exportTariff"],
            importTariff=resolved["importTariff"],
            sunlight=resolved["sunlight"] or 0.0,
            humidity=resolved["humidity"] or 0.0,
            **extra_kwargs,
        )

    def observation_history(self, prices_df: pd.DataFrame) -> Dict[int, Observation]:
        history: Dict[int, Observation] = {}

        for _, row in prices_df.iterrows():
            timestamp = int(row["timestamp"])
            product = str(row["product"])
            observation = history.setdefault(timestamp, Observation(plainValueObservations={}, conversionObservations={}))

            conversion_observation = self.row_to_conversion_observation(row)
            if conversion_observation is not None:
                observation.conversionObservations[product] = conversion_observation

            plain_value = self._first_present_float(row, ["observation", "observation_value", "plain_value", "plainValue"])
            if plain_value is not None:
                observation.plainValueObservations[product] = int(plain_value)

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
        for file_path in self._round_dir(round_num).glob(f"{prefix}*.csv"):
            days.append(file_path.stem.replace(prefix, ""))
        return sorted(days, key=lambda d: int(d))

    @staticmethod
    def empty_observation() -> Observation:
        return Observation(plainValueObservations={}, conversionObservations={})


def dataframe_from_semicolon_text(raw_text: str) -> pd.DataFrame:
    if not raw_text.strip():
        return pd.DataFrame()
    return pd.read_csv(StringIO(raw_text), sep=";")
