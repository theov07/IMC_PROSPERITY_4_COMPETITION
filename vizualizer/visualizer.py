import matplotlib.pyplot as plt
import pandas as pd
from typing import Dict, List
import sys
import os

# Add parent directory to path to import datamodel
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datamodel import OrderDepth, Trade, Symbol

class MarketVisualizer:
    def __init__(self):
        pass

    def plot_mid_prices(self, price_data: pd.DataFrame, product: Symbol, save_path: str = None):
        """Plots the mid price of a product over time."""
        product_data = price_data[price_data['product'] == product]
        
        if product_data.empty:
            print(f"No data found for product {product}")
            return

        plt.figure(figsize=(12, 6))
        plt.plot(product_data['timestamp'], product_data['mid_price'], label='Mid Price')
        
        # Plot Best Bid and Best Ask
        plt.plot(product_data['timestamp'], product_data['bid_price_1'], label='Best Bid', alpha=0.5, linestyle='--')
        plt.plot(product_data['timestamp'], product_data['ask_price_1'], label='Best Ask', alpha=0.5, linestyle='--')
        
        plt.title(f'Price History - {product}')
        plt.xlabel('Timestamp')
        plt.ylabel('Price')
        plt.legend()
        plt.grid(True)
        
        if save_path:
            plt.savefig(save_path)
            print(f"Plot saved to {save_path}")
        else:
            plt.show()
        plt.close()

    def plot_order_book_depth(self, history: Dict[int, Dict[Symbol, OrderDepth]], product: Symbol, timestamp_range: tuple = None):
        """
        Visualizes the order book depth at specific timestamps using the OrderDepth objects.
        This demonstrates usage of datamodel classes.
        """
        timestamps = sorted(history.keys())
        if timestamp_range:
             timestamps = [t for t in timestamps if timestamp_range[0] <= t <= timestamp_range[1]]
        
        # Sample every N timestamps to avoid clutter if too many
        step = max(1, len(timestamps) // 20)
        sample_timestamps = timestamps[::step]
        
        for t in sample_timestamps:
            if product not in history[t]:
                continue
                
            order_depth = history[t][product]
            
            # Extract data from OrderDepth object
            bids = order_depth.buy_orders
            asks = order_depth.sell_orders
            
            # Visualization logic for a single snapshot (e.g., bar chart of volume at price)
            # This would generate too many plots. 
            # Instead, let's aggregate 'liquidity' or 'spread' from OrderDepth objects and plot that.
            pass

    def plot_liquidity_over_time(self, history: Dict[int, Dict[Symbol, OrderDepth]], product: Symbol, save_path: str = None):
        """
        Iterates over the history of OrderDepth objects to calculate and plot total liquidity (volume) over time.
        """
        timestamps = []
        total_bid_volume = []
        total_ask_volume = []
        spreads = []

        sorted_times = sorted(history.keys())
        
        for t in sorted_times:
            if product in history[t]:
                od = history[t][product]
                
                # Calculate metrics using the OrderDepth class attributes
                bid_vol = sum(od.buy_orders.values())
                ask_vol = sum(abs(v) for v in od.sell_orders.values()) # sell orders are negative
                
                best_bid = max(od.buy_orders.keys()) if od.buy_orders else 0
                best_ask = min(od.sell_orders.keys()) if od.sell_orders else 0
                
                spread = best_ask - best_bid if (best_bid and best_ask) else 0

                timestamps.append(t)
                total_bid_volume.append(bid_vol)
                total_ask_volume.append(ask_vol)
                spreads.append(spread)

        # Plotting
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
        
        ax1.plot(timestamps, total_bid_volume, label='Total Bid Volume', color='green')
        ax1.plot(timestamps, total_ask_volume, label='Total Ask Volume', color='red')
        ax1.set_title(f'Liquidity (Total Volume) - {product}')
        ax1.set_ylabel('Volume')
        ax1.legend()
        ax1.grid(True)
        
        ax2.plot(timestamps, spreads, label='Spread', color='blue')
        ax2.set_title(f'Bid-Ask Spread - {product}')
        ax2.set_xlabel('Timestamp')
        ax2.set_ylabel('Spread')
        ax2.legend()
        ax2.grid(True)
        
        if save_path:
            plt.savefig(save_path)
            print(f"Plot saved to {save_path}")
        else:
            plt.show()
        plt.close()

    def plot_trades(self, trade_data: pd.DataFrame, product: Symbol, save_path: str = None):
        """Plots executed trades for a product."""
        product_trades = trade_data[trade_data['symbol'] == product]
        
        if product_trades.empty:
            print(f"No trades found for product {product}")
            return

        plt.figure(figsize=(12, 6))
        
        # Plot buy trades
        buy_trades = product_trades[product_trades['quantity'] > 0] # Assuming quantity > 0 is buy? Actually checking buyer column is safer if quantity is always positive.
        # Check datamodel: "self.buyer ... will only be non-empty strings if the algorithm itself is the buyer"
        # But this is market data. "market_trades" are trades done by others.
        # The CSV has `buyer`, `seller`, `quantity`.
        # Quantity is always positive in Trade object.
        # We need to distinguish if it was a buy or sell from the taker's perspective?
        # Usually we just plot price.
        
        plt.scatter(product_trades['timestamp'], product_trades['price'], label='Trades', alpha=0.6, s=10, c='blue')
        
        plt.title(f'Trade Execution History - {product}')
        plt.xlabel('Timestamp')
        plt.ylabel('Price')
        plt.legend()
        plt.grid(True)
        
        if save_path:
            plt.savefig(save_path)
            print(f"Plot saved to {save_path}")
        else:
            plt.show()
        plt.close()
