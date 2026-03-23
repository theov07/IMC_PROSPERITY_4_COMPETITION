import os
import sys
from typing import Dict, List, Tuple

import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Add parent directory to path to import local modules
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from vizualizer.data_loader import DataLoader
from vizualizer.visualizer import MarketVisualizer
from datamodel import OrderDepth, Trade, Symbol


def extract_day(file_name: str) -> str:
    parts = file_name.replace('.csv', '').split('day_')
    return parts[-1] if len(parts) > 1 else file_name


def build_vwap(trades_df: pd.DataFrame) -> pd.DataFrame:
    trades_df = trades_df.sort_values('timestamp').copy()
    trades_df['dollar'] = trades_df['price'] * trades_df['quantity']
    trades_df['cum_qty'] = trades_df['quantity'].cumsum()
    trades_df['cum_dollar'] = trades_df['dollar'].cumsum()
    trades_df['vwap'] = trades_df['cum_dollar'] / trades_df['cum_qty']
    return trades_df


def build_vpin(trades_df: pd.DataFrame, bucket_volume: int = 500) -> pd.DataFrame:
    df = trades_df.sort_values('timestamp').copy()
    if df.empty:
        return pd.DataFrame(columns=['timestamp', 'vpin'])

    price_changes = df['price'].diff().fillna(0)
    signs = np.sign(price_changes)
    signs = pd.Series(signs).replace(0, np.nan).ffill().fillna(1)
    df['signed_volume'] = df['quantity'] * signs

    bucket_end_times: List[int] = []
    vpin_values: List[float] = []
    buy_volume = 0
    sell_volume = 0
    bucket_acc = 0

    for _, row in df.iterrows():
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

    return pd.DataFrame({'timestamp': bucket_end_times, 'vpin': vpin_values})


def build_depth_frame(order_depth: OrderDepth, levels: int = 3) -> Tuple[List[int], List[int], List[int], List[int]]:
    bids = sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)[:levels]
    asks = sorted(order_depth.sell_orders.items(), key=lambda x: x[0])[:levels]
    bid_prices = [p for p, _ in bids]
    bid_vols = [v for _, v in bids]
    ask_prices = [p for p, _ in asks]
    ask_vols = [abs(v) for _, v in asks]
    return bid_prices, bid_vols, ask_prices, ask_vols


def build_depth_curve(order_depth: OrderDepth) -> Tuple[List[int], List[int], List[int], List[int]]:
    """Returns cumulative depth curves for bids and asks (Binance-style)."""
    bids = sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)
    asks = sorted(order_depth.sell_orders.items(), key=lambda x: x[0])

    bid_prices = [p for p, _ in bids]
    bid_cum = np.cumsum([v for _, v in bids]).tolist()

    ask_prices = [p for p, _ in asks]
    ask_cum = np.cumsum([abs(v) for _, v in asks]).tolist()

    return bid_prices, bid_cum, ask_prices, ask_cum


def load_data() -> Dict[str, Dict[str, object]]:
    datas_dir = os.path.join(parent_dir, 'DATAS')
    loader = DataLoader(datas_dir)
    visualizer = MarketVisualizer()

    price_files = sorted([f for f in os.listdir(datas_dir) if f.startswith('prices') and f.endswith('.csv')])
    trade_files = sorted([f for f in os.listdir(datas_dir) if f.startswith('trades') and f.endswith('.csv')])

    price_by_day = {extract_day(f): f for f in price_files}
    trade_by_day = {extract_day(f): f for f in trade_files}

    days = sorted(set(price_by_day.keys()) & set(trade_by_day.keys()))

    data: Dict[str, Dict[str, object]] = {}
    for day in days:
        price_file = price_by_day[day]
        trade_file = trade_by_day[day]

        df_prices = loader.load_prices(price_file)
        history = loader.get_order_depths(df_prices)
        products = sorted(df_prices['product'].unique())

        trades = loader.load_trade_objects(trade_file)

        data[day] = {
            'price_file': price_file,
            'trade_file': trade_file,
            'history': history,
            'products': products,
            'trades': trades,
            'visualizer': visualizer,
        }

    return data


data_store = load_data()

app = dash.Dash(__name__)

app.layout = html.Div(
    [
        html.H2('Prosperity Round 0 — Interactive Dashboard'),
        html.Div(
            [
                html.Label('Day'),
                dcc.Dropdown(
                    id='day-dropdown',
                    options=[{'label': f'Day {day}', 'value': day} for day in data_store.keys()],
                    value=next(iter(data_store.keys())) if data_store else None,
                    clearable=False,
                ),
            ],
            style={'width': '200px', 'display': 'inline-block', 'marginRight': '20px'},
        ),
        html.Div(
            [
                html.Label('Product'),
                dcc.Dropdown(id='product-dropdown', clearable=False),
            ],
            style={'width': '200px', 'display': 'inline-block'},
        ),
        html.Br(),
        html.Div(
            [
                dcc.Checklist(
                    id='play-toggle',
                    options=[{'label': 'Play', 'value': 'play'}],
                    value=[],
                    style={'display': 'inline-block', 'marginRight': '20px'},
                ),
                html.Label('Speed'),
                dcc.Dropdown(
                    id='speed-dropdown',
                    options=[
                        {'label': 'Fast (200ms)', 'value': 200},
                        {'label': 'Normal (500ms)', 'value': 500},
                        {'label': 'Slow (1000ms)', 'value': 1000},
                    ],
                    value=500,
                    clearable=False,
                    style={'width': '200px', 'display': 'inline-block', 'marginLeft': '10px'},
                ),
            ],
            style={'marginBottom': '10px'},
        ),
        html.Label('Timestamp'),
        dcc.Slider(id='timestamp-slider', min=0, max=1, step=1, value=0),
        dcc.Interval(id='play-interval', interval=500, n_intervals=0, disabled=True),
        dcc.Graph(id='price-graph'),
        dcc.Graph(id='liquidity-graph'),
        dcc.Graph(id='trade-graph'),
        dcc.Graph(id='orderbook-graph'),
    ],
    style={'maxWidth': '1200px', 'margin': '0 auto'},
)


@app.callback(
    [
        Output('product-dropdown', 'options'),
        Output('product-dropdown', 'value'),
        Output('timestamp-slider', 'min'),
        Output('timestamp-slider', 'max'),
        Output('timestamp-slider', 'value'),
        Output('timestamp-slider', 'marks'),
    ],
    [Input('day-dropdown', 'value')],
)
def update_products(day: str):
    if not day or day not in data_store:
        return [], None, 0, 1, 0, {}

    products = data_store[day]['products']
    history = data_store[day]['history']
    timestamps = sorted(history.keys())
    if not timestamps:
        return [], None, 0, 1, 0, {}

    marks = {0: str(timestamps[0]), len(timestamps) - 1: str(timestamps[-1])}

    return (
        [{'label': p, 'value': p} for p in products],
        products[0],
        0,
        len(timestamps) - 1,
        0,
        marks,
    )


@app.callback(
    [Output('play-interval', 'disabled'), Output('play-interval', 'interval')],
    [Input('play-toggle', 'value'), Input('speed-dropdown', 'value')],
)
def update_playback(play_toggle: List[str], speed: int):
    is_playing = 'play' in (play_toggle or [])
    return (not is_playing, speed or 500)


@app.callback(
    Output('timestamp-slider', 'value', allow_duplicate=True),
    [Input('play-interval', 'n_intervals')],
    [State('day-dropdown', 'value'), State('timestamp-slider', 'value')],
    prevent_initial_call=True,
)
def advance_timestamp(_n: int, day: str, current_idx: int):
    if not day or day not in data_store:
        return current_idx

    history = data_store[day]['history']
    timestamps = sorted(history.keys())
    if not timestamps:
        return current_idx

    next_idx = (current_idx + 1) % len(timestamps)
    return next_idx


@app.callback(
    [
        Output('price-graph', 'figure'),
        Output('liquidity-graph', 'figure'),
        Output('trade-graph', 'figure'),
        Output('orderbook-graph', 'figure'),
    ],
    [
        Input('day-dropdown', 'value'),
        Input('product-dropdown', 'value'),
        Input('timestamp-slider', 'value'),
    ],
)
def update_graphs(day: str, product: Symbol, timestamp: int):
    if not day or day not in data_store or not product:
        empty = go.Figure()
        return empty, empty, empty, empty

    history = data_store[day]['history']
    trades = data_store[day]['trades']
    visualizer = data_store[day]['visualizer']

    orderbook_df = visualizer._orderbook_series(history, product)
    trades_df = visualizer._trade_series(trades, product)

    timestamps = sorted(history.keys())
    if not timestamps:
        empty = go.Figure()
        return empty, empty, empty, empty

    if timestamp < 0 or timestamp >= len(timestamps):
        ts_value = timestamps[0]
    else:
        ts_value = timestamps[timestamp]

    price_fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08)
    price_fig.add_trace(go.Scatter(x=orderbook_df['timestamp'], y=orderbook_df['mid'], name='Mid'), row=1, col=1)
    price_fig.add_trace(go.Scatter(x=orderbook_df['timestamp'], y=orderbook_df['best_bid'], name='Best Bid'), row=1, col=1)
    price_fig.add_trace(go.Scatter(x=orderbook_df['timestamp'], y=orderbook_df['best_ask'], name='Best Ask'), row=1, col=1)
    price_fig.add_trace(go.Scatter(x=orderbook_df['timestamp'], y=orderbook_df['imbalance'], name='Imbalance'), row=2, col=1)
    price_fig.add_vline(x=ts_value, line_width=1, line_dash='dash', line_color='gray')
    price_fig.update_layout(height=500, title=f'Price & Imbalance — {product}')

    liquidity_fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08)
    liquidity_fig.add_trace(go.Scatter(x=orderbook_df['timestamp'], y=orderbook_df['bid_volume'], name='Bid Vol'), row=1, col=1)
    liquidity_fig.add_trace(go.Scatter(x=orderbook_df['timestamp'], y=orderbook_df['ask_volume'], name='Ask Vol'), row=1, col=1)
    liquidity_fig.add_trace(go.Scatter(x=orderbook_df['timestamp'], y=orderbook_df['spread'], name='Spread'), row=2, col=1)
    liquidity_fig.add_vline(x=ts_value, line_width=1, line_dash='dash', line_color='gray')
    liquidity_fig.update_layout(height=500, title=f'Liquidity & Spread — {product}')

    trades_fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08)
    if not trades_df.empty:
        window = 5000
        filtered_trades = trades_df[(trades_df['timestamp'] >= ts_value - window) & (trades_df['timestamp'] <= ts_value + window)]
        if filtered_trades.empty:
            filtered_trades = trades_df

        trades_fig.add_trace(
            go.Scatter(x=filtered_trades['timestamp'], y=filtered_trades['price'], mode='markers', name='Trades'),
            row=1,
            col=1,
        )
        vwap_df = build_vwap(trades_df)
        trades_fig.add_trace(go.Scatter(x=vwap_df['timestamp'], y=vwap_df['vwap'], name='VWAP'), row=1, col=1)

        vpin_df = build_vpin(trades_df)
        if not vpin_df.empty:
            trades_fig.add_trace(go.Scatter(x=vpin_df['timestamp'], y=vpin_df['vpin'], name='VPIN'), row=2, col=1)

    trades_fig.add_vline(x=ts_value, line_width=1, line_dash='dash', line_color='gray')

    trades_fig.update_layout(height=500, title=f'Trades, VWAP & VPIN — {product}')

    orderbook_fig = go.Figure()
    if ts_value in history and product in history[ts_value]:
        od = history[ts_value][product]
        bid_prices, bid_cum, ask_prices, ask_cum = build_depth_curve(od)
        orderbook_fig.add_trace(
            go.Scatter(x=bid_prices, y=bid_cum, mode='lines', fill='tozeroy', name='Bid Depth', line=dict(color='green'))
        )
        orderbook_fig.add_trace(
            go.Scatter(x=ask_prices, y=ask_cum, mode='lines', fill='tozeroy', name='Ask Depth', line=dict(color='red'))
        )

    orderbook_fig.update_layout(title=f'Order Book Snapshot — {product} @ {ts_value}', height=400)

    return price_fig, liquidity_fig, trades_fig, orderbook_fig


if __name__ == '__main__':
    app.run(debug=True)
