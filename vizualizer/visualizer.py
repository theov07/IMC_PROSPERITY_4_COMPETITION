import matplotlib.pyplot as plt
from matplotlib import animation
from typing import Dict, List, Iterable, Tuple
import sys
import os
import numpy as np
import pandas as pd

# Add parent directory to path to import datamodel
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datamodel import OrderDepth, Trade, Symbol

class MarketVisualizer:
    def __init__(self):
        pass

    def _orderbook_series(self, history: Dict[int, Dict[Symbol, OrderDepth]], product: Symbol) -> pd.DataFrame:
        """Builds a time series DataFrame from OrderDepth objects."""
        rows = []
        for timestamp in sorted(history.keys()):
            if product not in history[timestamp]:
                continue

            order_depth = history[timestamp][product]
            if not order_depth.buy_orders or not order_depth.sell_orders:
                continue

            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            mid = (best_bid + best_ask) / 2
            bid_vol = sum(order_depth.buy_orders.values())
            ask_vol = sum(abs(v) for v in order_depth.sell_orders.values())
            spread = best_ask - best_bid
            imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) else 0

            rows.append(
                {
                    "timestamp": timestamp,
                    "mid": mid,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "bid_volume": bid_vol,
                    "ask_volume": ask_vol,
                    "spread": spread,
                    "imbalance": imbalance,
                }
            )

        return pd.DataFrame(rows)

    def _trade_series(self, trades: Iterable[Trade], product: Symbol) -> pd.DataFrame:
        """Builds a DataFrame from Trade objects."""
        rows = [
            {"timestamp": t.timestamp, "price": t.price, "quantity": t.quantity}
            for t in trades
            if t.symbol == product
        ]
        return pd.DataFrame(rows)

    def plot_mid_prices(self, history: Dict[int, Dict[Symbol, OrderDepth]], product: Symbol, save_path: str = None):
        """Plots mid, best bid and best ask using OrderDepth objects."""
        series = self._orderbook_series(history, product)

        if series.empty:
            print(f"No order book data found for product {product}")
            return

        plt.figure(figsize=(12, 6))
        plt.plot(series['timestamp'], series['mid'], label='Mid Price')
        plt.plot(series['timestamp'], series['best_bid'], label='Best Bid', alpha=0.6, linestyle='--')
        plt.plot(series['timestamp'], series['best_ask'], label='Best Ask', alpha=0.6, linestyle='--')

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
        series = self._orderbook_series(history, product)
        if series.empty:
            print(f"No order book data found for product {product}")
            return

        # Plotting
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
        
        ax1.plot(series['timestamp'], series['bid_volume'], label='Total Bid Volume', color='green')
        ax1.plot(series['timestamp'], series['ask_volume'], label='Total Ask Volume', color='red')
        ax1.set_title(f'Liquidity (Total Volume) - {product}')
        ax1.set_ylabel('Volume')
        ax1.legend()
        ax1.grid(True)
        
        ax2.plot(series['timestamp'], series['spread'], label='Spread', color='blue')
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

    def plot_orderbook_imbalance(self, history: Dict[int, Dict[Symbol, OrderDepth]], product: Symbol, save_path: str = None):
        """Plots order book imbalance over time."""
        series = self._orderbook_series(history, product)
        if series.empty:
            print(f"No order book data found for product {product}")
            return

        plt.figure(figsize=(12, 5))
        plt.plot(series['timestamp'], series['imbalance'], color='purple')
        plt.axhline(0, color='black', linestyle='--', linewidth=1)
        plt.title(f'Order Book Imbalance - {product}')
        plt.xlabel('Timestamp')
        plt.ylabel('Imbalance')
        plt.grid(True)

        if save_path:
            plt.savefig(save_path)
            print(f"Plot saved to {save_path}")
        else:
            plt.show()
        plt.close()

    def plot_volatility(self, history: Dict[int, Dict[Symbol, OrderDepth]], product: Symbol, window: int = 50, save_path: str = None):
        """Plots rolling volatility (std of log returns) based on mid prices."""
        series = self._orderbook_series(history, product)
        if series.empty:
            print(f"No order book data found for product {product}")
            return

        series['log_return'] = np.log(series['mid']).diff()
        series['volatility'] = series['log_return'].rolling(window).std()

        plt.figure(figsize=(12, 5))
        plt.plot(series['timestamp'], series['volatility'], color='orange')
        plt.title(f'Rolling Volatility (window={window}) - {product}')
        plt.xlabel('Timestamp')
        plt.ylabel('Volatility')
        plt.grid(True)

        if save_path:
            plt.savefig(save_path)
            print(f"Plot saved to {save_path}")
        else:
            plt.show()
        plt.close()

    def plot_vwap(self, trades: Iterable[Trade], product: Symbol, save_path: str = None):
        """Plots VWAP over time using Trade objects."""
        df = self._trade_series(trades, product)
        if df.empty:
            print(f"No trades found for product {product}")
            return

        df = df.sort_values('timestamp')
        df['dollar'] = df['price'] * df['quantity']
        df['cum_qty'] = df['quantity'].cumsum()
        df['cum_dollar'] = df['dollar'].cumsum()
        df['vwap'] = df['cum_dollar'] / df['cum_qty']

        plt.figure(figsize=(12, 5))
        plt.plot(df['timestamp'], df['vwap'], label='VWAP', color='teal')
        plt.title(f'VWAP - {product}')
        plt.xlabel('Timestamp')
        plt.ylabel('VWAP')
        plt.grid(True)

        if save_path:
            plt.savefig(save_path)
            print(f"Plot saved to {save_path}")
        else:
            plt.show()
        plt.close()

    def plot_vpin(self, trades: Iterable[Trade], product: Symbol, bucket_volume: int = 500, save_path: str = None):
        """Plots VPIN (Volume-synchronized Probability of Informed Trading)."""
        df = self._trade_series(trades, product)
        if df.empty:
            print(f"No trades found for product {product}")
            return

        df = df.sort_values('timestamp').reset_index(drop=True)
        price_changes = df['price'].diff().fillna(0)
        signs = np.sign(price_changes)
        signs = signs.replace(0, np.nan).ffill().fillna(1)

        df['signed_volume'] = df['quantity'] * signs

        bucket_end_times: List[int] = []
        vpin_values: List[float] = []
        buy_volume = 0
        sell_volume = 0
        bucket_acc = 0

        for i, row in df.iterrows():
            vol = row['quantity']
            signed = row['signed_volume']

            if signed >= 0:
                buy_volume += vol
            else:
                sell_volume += vol

            bucket_acc += vol

            if bucket_acc >= bucket_volume:
                vpin = abs(buy_volume - sell_volume) / bucket_acc if bucket_acc else 0
                vpin_values.append(vpin)
                bucket_end_times.append(int(row['timestamp']))

                buy_volume = 0
                sell_volume = 0
                bucket_acc = 0

        if not vpin_values:
            print(f"Not enough volume to compute VPIN for {product}")
            return

        plt.figure(figsize=(12, 5))
        plt.plot(bucket_end_times, vpin_values, color='brown')
        plt.title(f'VPIN (bucket={bucket_volume}) - {product}')
        plt.xlabel('Timestamp')
        plt.ylabel('VPIN')
        plt.grid(True)

        if save_path:
            plt.savefig(save_path)
            print(f"Plot saved to {save_path}")
        else:
            plt.show()
        plt.close()

    def animate_orderbook(
        self,
        history: Dict[int, Dict[Symbol, OrderDepth]],
        product: Symbol,
        save_path: str = None,
        levels: int = 3,
        max_frames: int = 200,
    ):
        """Creates a dynamic view (animation) of the order book over time."""
        timestamps = sorted(history.keys())
        if not timestamps:
            print(f"No order book data found for product {product}")
            return

        step = max(1, len(timestamps) // max_frames)
        sampled = timestamps[::step]

        fig, ax = plt.subplots(figsize=(10, 6))

        def draw(frame_index: int):
            timestamp = sampled[frame_index]
            if product not in history[timestamp]:
                return

            od = history[timestamp][product]
            bids = sorted(od.buy_orders.items(), key=lambda x: x[0], reverse=True)[:levels]
            asks = sorted(od.sell_orders.items(), key=lambda x: x[0])[:levels]

            ax.clear()
            if bids:
                ax.bar([p for p, _ in bids], [v for _, v in bids], color='green', alpha=0.6, label='Bid')
            if asks:
                ax.bar([p for p, _ in asks], [abs(v) for _, v in asks], color='red', alpha=0.6, label='Ask')

            ax.set_title(f'Order Book - {product} @ {timestamp}')
            ax.set_xlabel('Price')
            ax.set_ylabel('Volume')
            ax.legend()
            ax.grid(True)

        ani = animation.FuncAnimation(fig, draw, frames=len(sampled), interval=80)

        if save_path:
            try:
                if save_path.endswith('.gif'):
                    ani.save(save_path, writer='pillow', fps=12)
                else:
                    ani.save(save_path, writer='ffmpeg', fps=12)
                print(f"Animation saved to {save_path}")
            except Exception as exc:
                print(f"Failed to save animation ({exc}). Showing interactively instead.")
                plt.show()
        else:
            plt.show()

        plt.close(fig)
