import matplotlib.pyplot as plt
from typing import Dict, List, Iterable
import sys
import os

# Add parent directory to path to import datamodel
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datamodel import OrderDepth, Trade, Symbol

class MarketVisualizer:
    def __init__(self):
        pass

    def plot_mid_prices(self, history: Dict[int, Dict[Symbol, OrderDepth]], product: Symbol, save_path: str = None):
        """Plots mid, best bid and best ask using OrderDepth objects."""
        timestamps: List[int] = []
        mids: List[float] = []
        best_bids: List[int] = []
        best_asks: List[int] = []

        for timestamp in sorted(history.keys()):
            if product not in history[timestamp]:
                continue
            order_depth = history[timestamp][product]
            if not order_depth.buy_orders or not order_depth.sell_orders:
                continue

            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            mid = (best_bid + best_ask) / 2

            timestamps.append(timestamp)
            best_bids.append(best_bid)
            best_asks.append(best_ask)
            mids.append(mid)

        if not timestamps:
            print(f"No order book data found for product {product}")
            return

        plt.figure(figsize=(12, 6))
        plt.plot(timestamps, mids, label='Mid Price')
        plt.plot(timestamps, best_bids, label='Best Bid', alpha=0.6, linestyle='--')
        plt.plot(timestamps, best_asks, label='Best Ask', alpha=0.6, linestyle='--')

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
            
            # Example snapshot plot (optional) - skipped by default to avoid too many files.
            # This method is left as a hook for deeper order book exploration.
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

    def plot_trades(self, trades: Iterable[Trade], product: Symbol, save_path: str = None):
        """Plots executed trades for a product using Trade objects."""
        filtered = [trade for trade in trades if trade.symbol == product]

        if not filtered:
            print(f"No trades found for product {product}")
            return

        timestamps = [trade.timestamp for trade in filtered]
        prices = [trade.price for trade in filtered]
        sizes = [max(10, min(80, abs(trade.quantity) * 4)) for trade in filtered]

        plt.figure(figsize=(12, 6))
        plt.scatter(timestamps, prices, label='Trades', alpha=0.6, s=sizes, c='blue')

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
