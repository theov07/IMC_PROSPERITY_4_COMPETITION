import pandas as pd
import sys
import os
from pathlib import Path
from typing import List, Dict, Any, Iterable

# Add repository root to path to import datamodel
ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from datamodel import OrderDepth, Trade, Symbol, Listing, TradingState, Observation

class DataLoader:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir

    def load_prices(self, file_name: str) -> pd.DataFrame:
        """Loads price data from a CSV file."""
        file_path = os.path.join(self.data_dir, file_name)
        return pd.read_csv(file_path, sep=';')

    def load_trades(self, file_name: str) -> pd.DataFrame:
        """Loads trade data from a CSV file."""
        file_path = os.path.join(self.data_dir, file_name)
        return pd.read_csv(file_path, sep=';')

    def load_trade_objects(self, file_name: str) -> List[Trade]:
        """Loads trades and converts rows to Trade objects from datamodel."""
        df = self.load_trades(file_name)
        trades: List[Trade] = []

        for _, row in df.iterrows():
            timestamp = int(row['timestamp'])
            symbol = str(row['symbol'])
            price = int(float(row['price']))
            quantity = int(row['quantity'])
            buyer = str(row['buyer']) if pd.notna(row['buyer']) and row['buyer'] != '' else None
            seller = str(row['seller']) if pd.notna(row['seller']) and row['seller'] != '' else None

            trades.append(
                Trade(
                    symbol=symbol,
                    price=price,
                    quantity=quantity,
                    buyer=buyer,
                    seller=seller,
                    timestamp=timestamp,
                )
            )

        return trades

    def row_to_order_depth(self, row: pd.Series) -> OrderDepth:
        """Converts a row from the prices DataFrame to an OrderDepth object."""
        order_depth = OrderDepth()
        
        # Parse buy orders (bid)
        for i in range(1, 4):
            bid_price_col = f'bid_price_{i}'
            bid_volume_col = f'bid_volume_{i}'
            
            if bid_price_col in row and not pd.isna(row[bid_price_col]):
                price = int(row[bid_price_col])
                volume = int(row[bid_volume_col])
                order_depth.buy_orders[price] = volume
                
        # Parse sell orders (ask)
        for i in range(1, 4):
            ask_price_col = f'ask_price_{i}'
            ask_volume_col = f'ask_volume_{i}'
            
            if ask_price_col in row and not pd.isna(row[ask_price_col]):
                price = int(row[ask_price_col])
                volume = int(row[ask_volume_col])
                # Sell orders should be negative in OrderDepth according to the datamodel description, 
                # but in the CSV volume is usually positive. 
                # The datamodel docs say: "in the sell_orders property, the quantities specified will be negative."
                # So we should negate the volume here.
                order_depth.sell_orders[price] = -volume
                
        return order_depth

    def get_order_depths(self, df: pd.DataFrame) -> Dict[int, Dict[Symbol, OrderDepth]]:
        """
        Converts the dataframe to a dictionary of timestamps -> product -> OrderDepth.
        This is useful if you want to replay the simulation.
        """
        history = {}
        for _, row in df.iterrows():
            timestamp = int(row['timestamp'])
            product = row['product']
            
            if timestamp not in history:
                history[timestamp] = {}
            
            history[timestamp][product] = self.row_to_order_depth(row)
            
        return history

    def build_listings(self, products: Iterable[str], denomination: str = "XIRECS") -> Dict[Symbol, Listing]:
        """Creates Listing objects for each product."""
        listings: Dict[Symbol, Listing] = {}
        for product in sorted(set(products)):
            listings[product] = Listing(symbol=product, product=product, denomination=denomination)
        return listings

    def group_trades_by_timestamp(self, trades: List[Trade]) -> Dict[int, Dict[Symbol, List[Trade]]]:
        """Groups Trade objects by timestamp and symbol for TradingState snapshots."""
        grouped: Dict[int, Dict[Symbol, List[Trade]]] = {}
        for trade in trades:
            grouped.setdefault(trade.timestamp, {}).setdefault(trade.symbol, []).append(trade)
        return grouped

    def build_trading_state_snapshots(
        self,
        order_depth_history: Dict[int, Dict[Symbol, OrderDepth]],
        listings: Dict[Symbol, Listing],
        market_trades: List[Trade],
    ) -> Dict[int, TradingState]:
        """Builds TradingState snapshots using datamodel objects (no own_trades/positions)."""
        trades_by_time = self.group_trades_by_timestamp(market_trades)
        observations = Observation(plainValueObservations={}, conversionObservations={})

        snapshots: Dict[int, TradingState] = {}
        for timestamp, order_depths in order_depth_history.items():
            snapshots[timestamp] = TradingState(
                traderData="",
                timestamp=timestamp,
                listings=listings,
                order_depths=order_depths,
                own_trades={},
                market_trades=trades_by_time.get(timestamp, {}),
                position={},
                observations=observations,
            )

        return snapshots
