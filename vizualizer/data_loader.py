import pandas as pd
import sys
import os
from typing import List, Dict, Any

# Add parent directory to path to import datamodel
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datamodel import OrderDepth, Trade, Symbol

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
