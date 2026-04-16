"""Merge Tibo OSMIUM + Theo ROOT into one submission."""

with open('C:/Users/LéoRENAULT/Downloads/tibo_best_osmium/206027.py', 'r', encoding='utf-8') as f:
    tibo_lines = f.read().split('\n')
with open('C:/Users/LéoRENAULT/Downloads/theo_best_root/223356.py', 'r', encoding='utf-8') as f:
    theo_lines = f.read().split('\n')

# Part 1: Tibo's file up to config (imports + market + persistence + BaseStrategy + MMFirstStrategy)
part1 = '\n'.join(tibo_lines[:883])

# Part 2: Theo's unique strategies (Round1RegressionMMV5Strategy + TheoVraiStratStrategy)
# Lines 298 (comment) to 800 (end of TheoVraiStratStrategy)
part2 = '\n'.join(theo_lines[298:801])

# Part 3: Combined config
config = """# ── Config ────────────────────────────────────────────────────────────────────

PRODUCTS = {'ASH_COATED_OSMIUM': {'OB_cleared_shift': 75,
                       'gap_trigger_confirm_ticks': 1,
                       'gap_trigger_max_vol_pct': 0.1,
                       'gap_trigger_min': 10,
                       'last_ts_value': 99900,
                       'log_flush_ts': 1000,
                       'maker_size': 20,
                       'maker_size_base_pct': 0.5,
                       'mid_smooth_half_life': 10,
                       'mid_smooth_window': 50,
                       'pct_kept_for_takers': 0.1,
                       'position_limit': 80,
                       'quote_trace_enabled': True,
                       'strategy': 'mm_first_v2',
                       'take_edge': 0.6,
                       'taker_buy_threshold': 9990,
                       'taker_sell_threshold': 10025,
                       'tighten_ticks': 1,
                       'ts_increment': 100,
                       'zscore_gap_gate': 1.5,
                       'zscore_max_scale': 5.0,
                       'zscore_size_scale': 0.5,
                       'zscore_threshold': 1,
                       'zscore_window': 50},
    'INTARIAN_PEPPER_ROOT': {
    'aggravate_cut': 0.04,
    'ask_spread_bull': 9.0,
    'bid_spread_bull': 1.0,
    'block_size': 200,
    'bootstrap_confidence': 0.55,
    'bull_threshold': 1.0,
    'cheap_buy_boost_per_z': 0.18,
    'cheap_residual_z': 0.9,
    'fastfill_buy_edge_boost': 0.0,
    'fastfill_deep_take_guard_end_ts': 1000,
    'fastfill_deep_take_max_gap_ticks': 1,
    'fastfill_end_ts': 12000,
    'fastfill_min_passive_buy': 10,
    'fastfill_target': 80,
    'last_ts_value': 999900,
    'log_flush_ts': 1000,
    'maker_size': 80,
    'max_bid_extra_ticks': 2,
    'min_completed_blocks': 5,
    'neut_spread_ask': 5.0,
    'neut_spread_bid': 2.0,
    'one_sided_target_gap': 24,
    'position_limit': 80,
    'reg_horizon': 25,
    'reg_r2_cap': 0.98,
    'reg_r2_floor': 0.85,
    'reg_residual_reversion': 0.25,
    'reg_rmse_floor': 1.0,
    'resid_inv_per_z': 14.0,
    'rich_residual_z': 1.0,
    'rich_sell_boost_per_z': 0.14,
    'seed_slope': 0.1015,
    'startup_end_ts': 30000,
    'startup_target': 80,
    'strategy': 'theo_vrai_strat',
    'strong_trend_ticks': 0.9,
    'take_buy_edge_bull': -8.0,
    'take_buy_edge_neut': 2.0,
    'take_sell_edge_neut': 2.0,
    'target_gap_scale': 26.0,
    'trend_buy_boost_per_tick': 0.24,
    'trend_inv_per_tick': 16.0,
    'trend_inventory_cap': 80,
    'trend_sell_boost_per_tick': 0.2,
    'ts_increment': 100,
    'unwind_take_edge': 10.0,
    'very_strong_trend_ticks': 1.6,
    'fv_alpha': 0.05,
    'short_alpha': 0.22,
    'slope_window': 20,
    'trim_reference_slope_weight': 0.15,
    'trim_start_position': 79,
    'trim_floor_position': 78,
    'trim_extension_threshold': 0.75,
    'trim_signal_edge': 1.0,
    'trim_sell_size': 1,
    'trim_cooldown_ticks': 20,
    'trim_take_position': 80,
    'trim_take_edge': 2.0,
    'trim_take_stretch': 999.0,
    'trim_take_sell_size': 1,
    'trim_ask_local_edge': 0.0,
    'rebuy_block_ticks': 25,
    'hold_sell_size': 1,
    'hold_sell_offset': 0,
    'empty_side_shift': 85,
}}

STRATEGY_CLASSES = {"mm_first_v2": MMFirstStrategy, "theo_vrai_strat": TheoVraiStratStrategy}

# ── Trader ────────────────────────────────────────────────────────────────────

class Trader:
    def __init__(self):
        self.strategies = {}
        for symbol, cfg in PRODUCTS.items():
            strat_name = cfg["strategy"]
            params = {k: v for k, v in cfg.items() if k != "strategy"}
            cls = STRATEGY_CLASSES[strat_name]
            self.strategies[symbol] = cls(product=symbol, params=params)

    def bid(self) -> int:
        return 15

    def run(self, state: TradingState):
        saved = load_state(state.traderData)
        product_memories = saved.setdefault("products", {})
        result = {}
        total_conversions = 0
        for product, strategy in self.strategies.items():
            if product not in state.order_depths:
                continue
            memory = product_memories.setdefault(product, {})
            orders, conversions = strategy.on_tick(state, memory)
            result[product] = orders
            total_conversions += conversions
        saved["last_timestamp"] = state.timestamp
        return result, total_conversions, dump_state(saved)
"""

output = part1 + '\n\n' + part2 + '\n\n' + config
with open('artifacts/submissions/tibo_osmium_theo_root_submission.py', 'w', encoding='utf-8') as f:
    f.write(output)
print(f'Written {len(output)} bytes')
