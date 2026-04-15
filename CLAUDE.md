# AI Agent Onboarding — IMC Prosperity 4

This document is the primary briefing for any AI agent picking up work on this repo.
Read it fully before touching any code. It supersedes the README for agent-specific guidance.

---

## What This Is

**IMC Prosperity 4** is an algorithmic trading competition. Each round, IMC reveals new products and historical price/trade data. Teams submit a single Python file (`Trader` class) that runs as a live bot — it receives the order book every 100ms and returns orders.

The competition rewards **PnL** (realized + marked-to-market). Each product has a position limit (usually 80 units). The key tension is: capture spread as a market maker vs. take directional risk on price signals.

**Our team**: Tibo, Leo, Theo — each member has their own strategy branch and config entry.  
**Current round**: Round 1. Products: `ASH_COATED_OSMIUM` (mean-reverting) and `INTARIAN_PEPPER_ROOT` (trending). Round 0 products (EMERALDS, TOMATOES) are no longer active.

---

## Repository Map

```
IMC_PROSPERITY_4_COMPETITION/
├── backtest.py              ← CLI entry point for backtesting
├── main.py                  ← local runner (calls submissions/champion.py)
├── datamodel.py             ← Prosperity API: Order, TradingState, OrderDepth, Trade, etc.
├── Makefile                 ← shortcuts for common commands
├── prosperity/
│   ├── config.py            ← ALL strategy configs and per-member overrides (2240 lines)
│   ├── market.py            ← BookSnapshot dataclass + snapshot_from_order_depth()
│   ├── persistence.py       ← load_state() / dump_state() (JSON traderData)
│   └── strategies/
│       ├── base.py          ← BaseStrategy abstract class (all helpers live here)
│       ├── __init__.py      ← strategy registry + build_strategy()
│       ├── mm_first.py      ← Tibo's primary strategy (penny-improve + gap exploit)
│       ├── mean_reversion.py← Tibo's mean-reversion strategy (rolling quantile bands)
│       ├── avellaneda_stoikov.py ← inventory-optimal quoting model
│       ├── market_maker.py  ← round-0 anchor-price market maker (legacy, production-grade)
│       ├── naive_tight_mm*.py   ← Leo's v1–v24 iteration series
│       ├── stat_arb.py, black_scholes.py, conversion_arb.py, signal_trader.py
│       ├── buy_and_hold.py  ← baseline for comparison
│       └── round_1/
│           ├── regression_top_book.py
│           ├── regression_mm_v3.py
│           ├── regression_mm_v4.py
│           └── regression_mm_v5.py
│   └── tooling/
│       ├── backtest.py      ← replay engine (BacktestEngine, TradeMatchingMode)
│       ├── grid_search.py   ← parameter sweep
│       ├── compare.py       ← side-by-side strategy comparison
│       ├── dashboard.py     ← interactive web UI
│       ├── logs.py          ← official log parser
│       └── reconcile.py     ← official vs local backtest diff
├── scripts/
│   └── export_submission.py ← inlines all modules into a single file for IMC upload
├── submissions/             ← thin dispatcher wrappers per member (used for backtesting)
├── data/
│   ├── round_0/             ← prices_round_0_day_{-2,-1}.csv, trades_round_0_day_{-2,-1}.csv
│   └── round_1/             ← prices/trades for days -2, -1, 0
├── logs/                    ← official competition logs (JSON)
├── artifacts/               ← generated outputs (backtest JSON, charts, submissions)
├── team/                    ← per-member workspaces and shared playbook
└── docs/                    ← wiki and legacy material
```

---

## Architecture: How the System Works End-to-End

### 1. Config system

Everything configurable lives in `prosperity/config.py`. The pattern is:

```python
# Base round config (one entry per product)
ROUND_1: Dict[str, ProductConfig] = {
    "ASH_COATED_OSMIUM": ProductConfig(symbol=..., strategy="naive_tight_mm", position_limit=80, params={...}),
}

# Per-member overrides
MEMBER_OVERRIDES["tibo_mm_first"] = {
    1: {
        "ASH_COATED_OSMIUM": _override(ROUND_1["ASH_COATED_OSMIUM"],
            strategy="mm_first",
            inv_step_threshold=0.9,
            take_edge=1,
            ...
        ),
    }
}

# Retrieve config for a member
config = get_round_config(round_num=1, member="tibo_mm_first")
# → Dict[symbol, ProductConfig]
```

`_override(base, **kwargs)` merges kwargs into the base params dict and optionally changes strategy/position_limit.

**To add a new strategy config**: add a new key to `MEMBER_OVERRIDES`. Never modify the base `ROUND_*` dicts — those are the canonical defaults everyone inherits from.

### 2. Strategy lifecycle

Every strategy inherits `BaseStrategy` and implements one method:

```python
class MyStrategy(BaseStrategy):
    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:  # (orders, conversions)
        ...
```

`on_tick()` in BaseStrategy handles the boilerplate (snapshot creation, memory wiring) and calls `compute_orders()`.

**Memory**: a per-product dict that persists across ticks via JSON in `traderData`. Use it for rolling buffers, EWMA state, counters, etc. It's passed in as `memory` — read and write to it directly. Never store large objects; the serialized traderData string must stay under IMC's size limit.

**Key BaseStrategy helpers** (call these instead of re-implementing):
- `self._smooth_mid(mid, memory)` — EWMA smoother; params: `mid_smooth_window` (default 20), `mid_smooth_half_life`
- `self._update_volatility(mid, memory)` — realized vol from returns + EWMA; params: `sigma_window`, `sigma_floor`, `sigma_half_life`
- `self._microprice(book)` — volume-weighted microprice across all levels; falls back to previous if one side empty
- `self.position_limit()` — from `self.params["position_limit"]`
- `self.buy_capacity(position)` / `self.sell_capacity(position)` — remaining room each side
- `self.log_quote_snapshot(state, memory, bid_price, ask_price, extras={})` — emit JSON trace for dashboard
- `self.log_taker_fill(state, memory, side, price, quantity)` — emit taker fill trace

**Inventory-adaptive sizing pattern** (used in mm_first, mean_reversion):
```python
base_size = float(self.params.get("maker_size_base_pct", 0.5)) * limit
bid_size = int(base_size * (1.0 - position / limit))  # shrinks when long
ask_size = int(base_size * (1.0 + position / limit))  # shrinks when short
```

### 3. Registering a new strategy

Three files must be updated when adding a strategy:

1. **Create** `prosperity/strategies/my_strategy.py` with a class inheriting `BaseStrategy`
2. **Register** in `prosperity/strategies/__init__.py`:
   ```python
   # In _load_registry():
   from prosperity.strategies.my_strategy import MyStrategy
   _REGISTRY["my_strategy"] = MyStrategy
   ```
3. **Register** in `scripts/export_submission.py` `STRATEGY_REGISTRY`:
   ```python
   "my_strategy": ("prosperity/strategies/my_strategy.py", "MyStrategy"),
   ```
4. **Add config** in `prosperity/config.py` under `MEMBER_OVERRIDES`

### 4. Backtesting

```bash
python backtest.py --strategy tibo_mm_first --round 1 --days -2 -1 --match-trades realistic
python backtest.py --strategy tibo_mm_first --round 1 --days -2 --match-trades realistic --product ASH_COATED_OSMIUM
```
use the flag --match-trades realistic by default.

**Fill modes** — choose with `--match-trades` / `--execution-rule`:
| Mode | What it does | When to use |
|---|---|---|
| `queue` (default) | Queue-position heuristic: fills passive orders, reduces by size already at that price level | General development |
| `realistic` | Queue-ahead at exact price + proportional fill on through-trades | **Tibo's preferred mode** — closest to live |
| `all` | Fill at or better than your price (optimistic) | Upper bound estimate |
| `worse` | Fill only if trade went strictly through your price (conservative) | Lower bound |
| `none` | No passive fills | Pure taker strategies |

**Critical warning**: `queue` mode gives 5–10× higher PnL than `realistic` for strategies that quote at the best price. Never compare absolute numbers across modes. Tibo uses `--match-trades realistic` for all serious backtests.

**Reading output**: per-product stats include PnL, trade count, max position, passive vs aggressive fill split, fill efficiency (filled/submitted), avg inventory ratio.

### 5. Grid search

```bash
python -m prosperity.tooling.grid_search \
  --strategy tibo_mm_first --round 1 --days -2 -1 \
  --param "ASH_COATED_OSMIUM.gap_trigger_min=8,10,12,14" \
  --param "ASH_COATED_OSMIUM.band_rank=5,10,15,20" \
  --execution-rule realistic \
  --top 15 --rank-by pnl
```

Param spec format: `PRODUCT.param_name=val1,val2,val3`. Always specify the product symbol prefix. Always use `--execution-rule realistic` when searching for Tibo's strategies.

### 6. Exporting for IMC

```bash
# Full config (all products)
python scripts/export_submission.py --member tibo_mm_first --round 1

# Single product only
python scripts/export_submission.py --member tibo_mm_first --round 1 --product ASH_COATED_OSMIUM
```

The exporter:
1. Reads the config for the member
2. Inlines `market.py`, `persistence.py`, `base.py`, and any needed strategy files
3. Strips prosperity-internal imports (they're now inlined)
4. Embeds the config as a plain `PRODUCTS` dict
5. Validates: syntax, banned imports, instantiation, one-tick run, 200-tick latency benchmark
6. Writes `artifacts/submissions/{member}_round{round}_submission.py` for upload
7. Also writes `submissions/{member}.py` wrapper for local backtesting

**Banned imports** (IMC sandbox): os, sys, subprocess, socket, pathlib, shutil, importlib, ctypes, multiprocessing, threading. The `os.environ.get("INTERNAL_BACKTEST")` pattern in base.py is automatically replaced with `False` during export.

---

## Current Strategies in Use

### Tibo — `tibo_mm_first` (primary, Round 1)

**File**: `prosperity/strategies/mm_first.py`

**Concept**: Penny-improve market maker with inventory-adaptive stepping and aggressive features.

**Flow each tick**:
1. Compute `mid_smooth` (EWMA of mid price)
2. Choose quote level: L1 (penny-improve) by default, L2 (join best) when `|pos| >= inv_step_threshold * limit`
3. Fire taker orders when `ask <= mid_smooth - take_edge` or `bid >= mid_smooth + take_edge`, or when absolute thresholds (`taker_buy_threshold`, `taker_sell_threshold`) are hit
4. Re-anchor passive prices after taker fires (use first book level NOT swept as new reference)
5. Gap exploit: if L1 is thin (`vol <= gap_trigger_max_vol_pct * limit`) and gap to L2 is large (`>= gap_trigger_min`), sweep L1 aggressively and re-anchor passive to L2 ± 1
6. Post passive bid/ask orders

**Key params** (ASH_COATED_OSMIUM):
```python
inv_step_threshold=0.9       # step to L2 at 90% of limit
take_edge=1                  # take when edge >= 1 tick vs mid_smooth
maker_size_base_pct=0.75     # base size = 75% of limit
pct_kept_for_takers=0.1      # hard stop: reserve 10% capacity for takers
mid_smooth_window=50         # EWMA window
mid_smooth_half_life=10      # EWMA half-life
taker_buy_threshold=9990     # absolute buy signal
taker_sell_threshold=10025   # absolute sell signal
gap_trigger_min=10           # min gap L1→L2 to fire gap exploit
gap_trigger_max_vol_pct=0.2  # L1 "thin" = ≤ 20% of position limit
gap_trigger_confirm_ticks=1  # require 1 consecutive tick before firing
```

**Important bug already fixed**: After a taker order sweeps L1, the passive price is re-anchored to `new_best ± 1` (not stale `old_best ± 1`). This prevents posting a passive sell below the price we just bought at.

### Tibo — `tibo_mean_rev` (experimental, Round 1)

**File**: `prosperity/strategies/mean_reversion.py`

**Concept**: Rolling-quantile bands for mean reversion on mid price. Taker-only.

**Flow each tick**:
1. Compute `mid_smooth` (EWMA)
2. Maintain rolling buffer of M mid prices → `pS` = N-th largest, `pL` = N-th smallest
3. `band_mid = pL + exit_band_pct * (pS - pL)` (default: midpoint)
4. **Exit first (priority)**:
   - Short position + `mid_smooth <= band_mid` → buy to close
   - Long position + `mid_smooth >= band_mid` → sell to close
5. **Entry** (only if no exit):
   - `mid_smooth > pS` → sell (in top-N tail, expect reversion down)
   - `mid_smooth < pL` → buy (in bottom-N tail, expect reversion up)

**Key params** (defaults):
```python
band_window=200          # rolling window size M
band_rank=10             # N for N-th largest/smallest
exit_band_pct=0.5        # exit at midpoint of bands
min_band_width=0         # no minimum band width filter
maker_size_base_pct=0.5  # base size = 50% of limit
```

### Leo — multiple naive_tight_mm variants

Leo iterates through `naive_tight_mm_v1` to `v24` and regression-based strategies. Key configs: `leo_round1_naive_v7`, `leo_round1_naive_v8`, `leo_reg_lin_round1` through `leo_reg_lin_round1_v5`.

### Theo — round 1 variants

Multiple `theo_round1_v10` through `theo_round1_v14d` entries. Uses `naive_tight_mm_v9/v10/v14` and regression strategies.

---

## Data Format

### Price CSV (`data/round_1/prices_round_1_day_{DAY}.csv`)
```
day, timestamp, product, bid_price_1, bid_volume_1, bid_price_2, bid_volume_2, bid_price_3, bid_volume_3,
ask_price_1, ask_volume_1, ask_price_2, ask_volume_2, ask_price_3, ask_volume_3, mid_price, profit_and_loss
```
- `timestamp` increments by 100 each tick
- Round 1 day 0: timestamps 0–99900 (1000 ticks); days -2, -1: timestamps 0–999900 (10000 ticks)
- `profit_and_loss` is IMC's own P&L — not used for backtesting

### Trade CSV (`data/round_1/trades_round_1_day_{DAY}.csv`)
```
timestamp, buyer, seller, symbol, currency, price, quantity
```
- These are OTHER participants' trades (market trades), not our own
- `buyer`/`seller` are participant IDs (e.g., "Valentina", "Caesar", "Penelope") or blank
- Used by `_simulate_fills()` for passive fill matching

### Key timestamps
- `ts_increment=100` — tick size (100ms per tick)
- `last_ts_value=99900` — last timestamp for round 1 day 0 (days -2/-1 use 999900)
- `log_flush_ts=1000` — quote trace flush interval

---

## BookSnapshot Fields

```python
book.best_bid        # int or None
book.best_ask        # int or None
book.best_bid_volume # int
book.best_ask_volume # int
book.mid_price       # float or None (simple (bid+ask)/2)
book.microprice      # float or None (volume-weighted top-of-book only)
book.spread          # int or None
book.imbalance       # float or None (bid_vol - ask_vol) / total
book.bid_levels      # List[Tuple[int, int]] — [(price, vol), ...] descending
book.ask_levels      # List[Tuple[int, int]] — [(price, vol), ...] ascending
```

`book.microprice` uses top-of-book volumes only. For the full book microprice use `self._microprice(book)`.

---

## OrderDepth Conventions

```python
order_depth.buy_orders   # Dict[price, volume]  — volume is POSITIVE
order_depth.sell_orders  # Dict[price, volume]  — volume is NEGATIVE
```

So `-order_depth.sell_orders[ask_p]` gives the positive available quantity at `ask_p`.

---

## Order Conventions

```python
Order(self.product, price, quantity)
# quantity > 0 = BUY
# quantity < 0 = SELL
```

Aggressive buy (taker): use `ask_p` from `sell_orders`, quantity > 0.
Aggressive sell (taker): use `bid_p` from `buy_orders`, quantity < 0.

---

## Logging and Tracing

Strategies emit two types of structured traces for the dashboard:

1. **Quote trace** via `log_quote_snapshot()` — called every tick, flushed at `log_flush_ts` checkpoints
   ```python
   self.log_quote_snapshot(
       state=state, memory=memory,
       bid_price=bid_price, ask_price=ask_price,
       extras={"position": position, "mid_smooth": ..., "level": "L1"},
   )
   ```
   Schema from `extras` is stable across ticks (same keys every call). The dashboard renders per-tick bid/ask overlaid on market data.

2. **Taker fill trace** via `log_taker_fill()` — called when a taker order is detected as filled
   ```python
   self.log_taker_fill(state=state, memory=memory, side="BUY", price=trade.price, quantity=trade.quantity)
   ```

Both are controlled by `runtime_trace_enabled()` (disabled during internal backtest via `INTERNAL_BACKTEST` env var, or explicit `runtime_trace_enabled` param).

---

## Key Design Decisions (Already Made — Don't Re-litigate)

1. **`realistic` fill mode**: Tibo uses `--match-trades realistic` for all serious backtests. `queue` mode inflates PnL by 5–10×. Never compare absolute numbers across modes.

2. **EWMA mid smoother over microprice**: Tibo switched from microprice to EWMA-smoothed mid and it performed better. Keep using `_smooth_mid()` in `mm_first.py`.

3. **Taker re-anchoring**: After a taker sweeps L1, the passive price must be re-anchored to `new_best_ask - 1` (not stale `best_ask - 1`). The fix is already in `mm_first.py` lines 139–155.

4. **Gap exploit 1-level case removed**: Adding single-level aggressive clearing (when there's no L2 to measure a gap against) destroyed PnL. The gap exploit only fires when `len(bids) >= 2`.

5. **`gap_trigger_confirm_ticks=1`**: Require 1 consecutive tick before firing gap exploit to filter transient thin levels. Stored as `_gap_bid_streak`/`_gap_ask_streak` in memory.

6. **`pct_kept_for_takers`**: Hard stop — when `|pos| >= limit * (1 - pct_kept_for_takers)`, stop posting passive orders on the inventory-increasing side to reserve capacity for takers.

---

## Common Tasks (How To)

### Add a new strategy
1. Create `prosperity/strategies/my_strategy.py` inheriting `BaseStrategy`, implement `compute_orders()`
2. Register in `prosperity/strategies/__init__.py` (`_load_registry` function + `_REGISTRY` dict)
3. Register in `scripts/export_submission.py` `STRATEGY_REGISTRY` dict
4. Add a `MEMBER_OVERRIDES` entry in `prosperity/config.py`
5. Test: `python backtest.py --strategy my_member --round 1 --match-trades realistic --days -2`

### Tune parameters for an existing strategy
```bash
python -m prosperity.tooling.grid_search \
  --strategy tibo_mm_first --round 1 --days -2 -1 \
  --param "ASH_COATED_OSMIUM.param_name=v1,v2,v3,v4" \
  --execution-rule realistic --top 10 --rank-by pnl
```
Then update the config in `prosperity/config.py`.

### Export for upload
```bash
python scripts/export_submission.py --member tibo_mm_first --round 1
# Output: artifacts/submissions/tibo_mm_first_round1_submission.py
```

### Run a single-product backtest
```bash
python backtest.py --strategy tibo_mm_first --round 1 --match-trades realistic --days -2 --product ASH_COATED_OSMIUM
```

### Analyze official logs
```bash
python -m prosperity.tooling.logs --log logs/my_submission.json --symbol ASH_COATED_OSMIUM
```

### Compare strategies
```bash
python -m prosperity.tooling.compare --strategies tibo_mm_first tibo_mean_rev leo_round1_naive_v8 --round 1 --days -2 -1 --execution-rule realistic
```

---

## Collaboration Model

- **Branch per member**: `tibo`, `leo`, `theo` — each member works on their branch and opens PRs to `main`
- **Config is the source of truth**: different strategies differ only by their `MEMBER_OVERRIDES` entry. No member should modify another member's config entries.
- **`champion` member**: the current best-performing config, updated before official submissions
- **Shared framework**: changes to `base.py`, `backtest.py`, `export_submission.py`, `market.py` affect everyone — communicate before modifying

---

## Known Issues and Limitations

1. **Backtest fill model**: Queue mode is optimistic for strategies posting at the best price. The `realistic` mode is better but still not exact FIFO. True queue simulation would require full order book reconstruction.

2. **Passive fill for join strategies**: When a strategy joins the best (posts at `best_bid` rather than `best_bid + 1`), the backtest fills it as if it has top queue priority. In reality, existing orders at that level have priority. This inflates PnL for join strategies.

3. **traderData size limit**: IMC imposes a limit on the JSON-serialized `traderData` string. Strategies with large rolling buffers (`band_window=500`, etc.) may hit this. Keep buffers reasonable.

4. **Round 1 day-0 data**: Only 1000 ticks (vs 10000 for training days). Some strategies need enough warm-up ticks before their signals activate. Check `band_rank * 2` or `sigma_window` vs available ticks.

5. **`last_ts_value` must match data**: For day 0 it's `99900`, for days -2/-1 it's `999900`. Log flush and PnL logging depend on this. Always set correctly in config.

---

## Where To Find Things

| What | Where |
|---|---|
| Strategy params and member configs | `prosperity/config.py` |
| Base strategy helpers | `prosperity/strategies/base.py` |
| Tibo's main strategy | `prosperity/strategies/mm_first.py` |
| Tibo's mean-rev strategy | `prosperity/strategies/mean_reversion.py` |
| Leo's latest variant | `prosperity/strategies/naive_tight_mm_v24.py` |
| Regression strategies | `prosperity/strategies/round_1/regression_mm_v5.py` |
| Backtest engine + fill modes | `prosperity/tooling/backtest.py` |
| Grid search | `prosperity/tooling/grid_search.py` |
| Export script | `scripts/export_submission.py` |
| Round 1 data | `data/round_1/` |
| Official logs | `logs/` |
| Generated submissions | `artifacts/submissions/` |
| Team operating guide | `team/shared/competition_playbook.md` |
| Historical decisions and session notes | `agent_handoff.md` |
| Outstanding work items | `TODO.md` |
| Recent changes and status | `NOTE.md` |
