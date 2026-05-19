import os
import sys
from pathlib import Path

# Add repository root to path to import local modules
current_dir = Path(__file__).resolve().parent
root_dir = current_dir.parents[2]
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from research.shared.visualizer.data_loader import DataLoader
from research.shared.visualizer.visualizer import MarketVisualizer
from datamodel import Symbol

def main():
    datas_dir = root_dir / "data"
    output_dir = root_dir / "artifacts" / "visualizer_output"
    
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    loader = DataLoader(str(datas_dir))
    visualizer = MarketVisualizer()
    animate = os.getenv("VIZ_ANIMATE", "0") == "1"

    # Process Price Data (Order Depths)
    price_files = [f for f in os.listdir(datas_dir) if f.startswith('prices') and f.endswith('.csv')]
    
    for p_file in price_files:
        print(f"Processing {p_file}...")
        df_prices = loader.load_prices(p_file)

        # Convert to OrderDepth objects (DataModel usage)
        print("  Converting to OrderDepth objects (DataModel usage)...")
        history = loader.get_order_depths(df_prices)

        products = sorted(df_prices['product'].unique())
        for product in products:
            print(f"  Visualizing mid-price for {product}...")
            save_path = output_dir / f"{p_file.replace('.csv', '')}_{product}_mid_price.png"
            visualizer.plot_mid_prices(history, product, str(save_path))

            print(f"  Visualizing liquidity for {product}...")
            save_path = output_dir / f"{p_file.replace('.csv', '')}_{product}_liquidity.png"
            visualizer.plot_liquidity_over_time(history, product, str(save_path))

            print(f"  Visualizing orderbook imbalance for {product}...")
            save_path = output_dir / f"{p_file.replace('.csv', '')}_{product}_imbalance.png"
            visualizer.plot_orderbook_imbalance(history, product, str(save_path))

            print(f"  Visualizing volatility for {product}...")
            save_path = output_dir / f"{p_file.replace('.csv', '')}_{product}_volatility.png"
            visualizer.plot_volatility(history, product, window=50, save_path=str(save_path))

            if animate:
                print(f"  Generating orderbook animation for {product}...")
                save_path = output_dir / f"{p_file.replace('.csv', '')}_{product}_orderbook.mp4"
                visualizer.animate_orderbook(history, product, save_path=str(save_path))

    # Process Trades Data (Trade objects)
    trade_files = [f for f in os.listdir(datas_dir) if f.startswith('trades') and f.endswith('.csv')]
    for t_file in trade_files:
        print(f"Processing trades file {t_file}...")
        trades = loader.load_trade_objects(t_file)

        products = sorted({trade.symbol for trade in trades})
        for product in products:
            print(f"  Visualizing trades for {product}...")
            save_path = output_dir / f"{t_file.replace('.csv', '')}_{product}_trades.png"
            visualizer.plot_trades(trades, product, str(save_path))

            print(f"  Visualizing VWAP for {product}...")
            save_path = output_dir / f"{t_file.replace('.csv', '')}_{product}_vwap.png"
            visualizer.plot_vwap(trades, product, str(save_path))

            print(f"  Visualizing VPIN for {product}...")
            save_path = output_dir / f"{t_file.replace('.csv', '')}_{product}_vpin.png"
            visualizer.plot_vpin(trades, product, bucket_volume=500, save_path=str(save_path))

    print(f"Analysis complete. Results saved in {output_dir}")

if __name__ == "__main__":
    main()
