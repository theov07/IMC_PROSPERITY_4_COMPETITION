import os
import sys

# Add parent directory to path to import local modules
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from vizualizer.data_loader import DataLoader
from vizualizer.visualizer import MarketVisualizer
from datamodel import Listing, OrderDepth, Trade, Symbol

def main():
    datas_dir = os.path.join(parent_dir, 'DATAS')
    output_dir = os.path.join(current_dir, 'output')
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    loader = DataLoader(datas_dir)
    visualizer = MarketVisualizer()

    # Process Price Data (Order Depths)
    price_files = [f for f in os.listdir(datas_dir) if f.startswith('prices') and f.endswith('.csv')]
    
    for p_file in price_files:
        print(f"Processing {p_file}...")
        df_prices = loader.load_prices(p_file)
        
        # 1. Visualize using Pandas directly (Mid Price)
        products = df_prices['product'].unique()
        for product in products:
            print(f"  Visualizing mid-price for {product}...")
            save_path = os.path.join(output_dir, f"{p_file.replace('.csv', '')}_{product}_mid_price.png")
            visualizer.plot_mid_prices(df_prices, product, save_path)
            
        # 2. Visualize using DataModel classes (Liquidity / Spread)
        # Convert DataFrame to Dict[Time, Dict[Product, OrderDepth]]
        print("  Converting to OrderDepth objects (DataModel usage)...")
        history = loader.get_order_depths(df_prices)
        
        for product in products:
            print(f"  Visualizing liquidity for {product}...")
            save_path = os.path.join(output_dir, f"{p_file.replace('.csv', '')}_{product}_liquidity.png")
            visualizer.plot_liquidity_over_time(history, product, save_path)

    # Process Trades Data
    trade_files = [f for f in os.listdir(datas_dir) if f.startswith('trades') and f.endswith('.csv')]
    for t_file in trade_files:
        print(f"Processing trades file {t_file}...")
        df_trades = loader.load_trades(t_file)
        
        # Visualize trades
        products = df_trades['symbol'].unique()
        for product in products:
            print(f"  Visualizing trades for {product}...")
            save_path = os.path.join(output_dir, f"{t_file.replace('.csv', '')}_{product}_trades.png")
            visualizer.plot_trades(df_trades, product, save_path)

    print(f"Analysis complete. Results saved in {output_dir}")

if __name__ == "__main__":
    main()
