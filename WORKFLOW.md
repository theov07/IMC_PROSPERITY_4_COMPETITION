# IMC Prosperity 4 — Complete Strategy Development Workflow

**Last Updated:** April 6, 2026

---

## Quick Reference: Command Cheat Sheet

### Exploration
```bash
# Launch interactive data explorer (before you start coding)
python research/visualizer/main.py
# → Opens http://localhost:8050
```

### Backtesting
```bash
# Test a single strategy variant on historical data
python backtest.py --strategy champion --round 0 --days -2 -1

# Verbose output for debugging
python backtest.py --strategy champion --round 0 --days -2 -1 --verbose
```

### Comparison & Ranking
```bash
# Compare multiple variants side-by-side
python -m prosperity.tooling.compare \
  --strategies champion leo theo \
  --round 0 --days -2 -1
```

### Parameter Optimization
```bash
# Grid search: test all combinations of parameter ranges
python -m prosperity.tooling.grid_search \
  --strategy champion --round 0 --days -2 -1 \
  --param "EMERALDS.ema_alpha=0.05,0.10,0.15,0.20" \
  --param "EMERALDS.quote_half_spread=1,2,3" \
  --param "TOMATOES.ema_alpha=0.16,0.18,0.20"
```

### Testing
```bash
# Run unit and smoke tests on the framework
python -m unittest tests/ -v

# Test specific test file
python -m unittest tests.test_strategies -v
```

### Export for IMC
```bash
# Generate single-file submission
python scripts/export_submission.py \
  --member champion --round 0 \
  --output artifacts/submissions/champion_submission.py

# Compile-check the exported file
python -m py_compile artifacts/submissions/champion_submission.py
```

### Post-Submission Analysis
```bash
# Review official log with interactive dashboard
python -m prosperity.tooling.dashboard --log examples/official_logs/16248.log

# Export static HTML (no Dash server needed)
python -m prosperity.tooling.dashboard --log examples/official_logs/16248.log --static \
  --output artifacts/analysis/my_submission.html
```

---

## Complete Strategy Development Workflow

### Phase 1: Data Exploration (First Few Hours of Round)

When a new round opens, **before you write any strategy code**, explore the data to understand market structure.

```bash
python research/visualizer/main.py
```

**What this tool does:**
- Loads CSV price and trade data from `/data/`
- Provides interactive playback with play/pause controls
- Shows multiple market analytics per product

**In the dashboard, for each product, look for:**

1. **Trend vs Mean-Reversion**: Is price drifting up/down or bouncing around?
   - Trending products → favor trend-following or signal_trader
   - Mean-reverting → favor market_maker or stat_arb

2. **Bid-Ask Spreads**: How tight is the market?
   - Tight spreads (1-2 ticks) → tight market, low edge available
   - Wide spreads (3-5+ ticks) → good edge for market making

3. **Order Book Imbalance**: Are there more buyers or sellers?
   - Positive imbalance → more buy demand (price may rise)
   - Negative imbalance → more sell pressure (price may fall)

4. **Volume Patterns**: Is trading volume smooth or spiky?
   - Smooth volume → suitable for grid-based market making
   - Spiky/adversarial volume → need defensive strategies

5. **Price Volatility**: How much does price move?
   - Low volatility → market_maker (wider inventory comfort)
   - High volatility → avellaneda_stoikov (inventory-sensitive quoting)

**Key metrics in the dashboard:**
- **VWAP** (Volume Weighted Avg Price) — consensus price
- **VPIN** (Volume Pin) — proxy for informed trading
- **Depth curves** — how much size at each price level
- **Imbalance** — buy volume vs sell volume at top of book

**Duration:** 30-60 minutes per new round. Take screenshots or notes.

---

### Phase 2: Strategy Selection & Parameter Tuning

Based on your exploration, decide which strategy to use per product, then tune parameters.

#### Step 2.0: If you need to create a new strategy:

- Create prosperity/strategies/my_strategy.py — the canonical source
  - First, look at base.py to see what you need to implement
- Register in `prosperity/strategies/__init__.py`
- Add one line to STRATEGY_REGISTRY in `scripts/export_submission.py` (name → file + class name)
- Add to Configuration: edit `config.py`
- Add Unit Tests (Recommended): Create/update `test_strategies.py`




#### Step 2a: Understand Available Strategies

Check what's already configured in [prosperity/config.py](prosperity/config.py):

```bash
cat prosperity/config.py
```

Available strategies:
- `market_maker` — Classic market making with fair value + inventory skew (**most used for round 0**)
- `avellaneda_stoikov` — Inventory-aware quoting model (more sophisticated MM)
- `stat_arb` — Statistical arbitrage on baskets
- `black_scholes` — Options/voucher pricing
- `conversion_arb` — Arbitrage on conversions
- `signal_trader` — Directional strategy following signals

#### Step 2b: Create Your Config Variant

Edit [prosperity/config.py](prosperity/config.py) and add a new member variant under `MEMBER_OVERRIDES`:

```python
MEMBER_OVERRIDES: Dict[str, Dict[int, Dict[str, ProductConfig]]] = {
    "champion": {},  # uses base configs as-is
    "leo": { ... },
    # ADD YOUR VARIANT HERE:
    "my_attempt_v1": {
        0: {
            "EMERALDS": _override(
                ROUND_0["EMERALDS"],
                ema_alpha=0.12,           # Experiment: faster EMA response
                quote_half_spread=1,      # Tighter quotes
                maker_size=18,            # Larger quote size
                inventory_aversion=1.0,   # Less inventory skew
            ),
            "TOMATOES": ROUND_0["TOMATOES"],  # Keep tomatoes unchanged
        },
    },
}
```

**Parameters to tune per product:**
- `ema_alpha` — How responsive fair value estimate is to market changes (0.01-0.3)
- `quote_half_spread` — How wide to quote around fair value (1-5 ticks)
- `maker_size` — How much size to quote per level (5-20)
- `inventory_aversion` — How aggressively to skew for inventory (0.5-2.0)
- `take_edge` — When to aggressively take liquidity (0.5-2.0)

#### Step 2c: Run Initial Backtest

```bash
python backtest.py --strategy my_attempt_v1 --round 0 --days -2 -1
```

**Output interpretation:**
```
EMERALDS:  PnL=1,234  Trades=15  Position=+3  Turnover=50,000
TOMATOES:  PnL=567    Trades=22  Position=-2  Turnover=38,000
----
Total:     PnL=1,801  Timestamp=49,900
```

- **PnL** — Profit/loss in game currency
- **Trades** — Number of filled orders
- **Position** — Current inventory (positive=long, negative=short)
- **Turnover** — Total traded volume × price

**Red flags:**
- PnL < 0 → strategy is losing money, needs rework
- Position constantly at position_limit → not managing inventory well
- Very few trades → quotes not aggressive enough or spread too tight

---

### Phase 3: Comparison & Ranking

Now compare your variant against existing ones to see who wins.

```bash
python -m prosperity.tooling.compare \
  --strategies champion leo theo my_attempt_v1 \
  --round 0 --days -2 -1
```

**Output:** Ranked table showing which variant made the most money

```
Rank  Strategy       Total PnL  Avg Daily  Trades  Max Drawdown
1     leo            5,234      2,617     412     -150
2     my_attempt_v1  4,891      2,445     398     -180
3     champion       4,100      2,050     385     -200
4     theo           3,900      1,950     320     -220
```

**Interpretation:**
- If your variant ranks #1 or #2, you're on the right track
- If it ranks last, parameters need adjustment
- If P&L is close to champion, consider: did I make meaningful improvement?

**Next step:** If ranking is good, move to Phase 4. If not, adjust parameters in [config.py](prosperity/config.py) and re-test.

---

### Phase 4: Parameter Optimization (Grid Search)

Once you're in the ballpark, systematically find optimal parameters.

```bash
python -m prosperity.tooling.grid_search \
  --strategy my_attempt_v1 --round 0 --days -2 -1 \
  --param "EMERALDS.ema_alpha=0.08,0.10,0.12,0.14,0.16" \
  --param "EMERALDS.quote_half_spread=1,2,3,4" \
  --param "TOMATOES.ema_alpha=0.16,0.18,0.20,0.22"
```

**How it works:**
- Tests all combinations: 5 × 4 × 4 = **80 backtests** automatically
- Ranks by total P&L
- Returns best-performing parameter combination

**Output:** Ranked list with best params highlighted

```
Rank  EMERALDS.ema_alpha  EMERALDS.quote_half_spread  TOMATOES.ema_alpha  Total PnL
1     0.12                2                           0.18                5,412
2     0.14                2                           0.18                5,380
3     0.12                1                           0.20                5,245
...
```

**Workflow:**
1. Identify top-3 parameter combinations
2. For each, manually validate with a full backtest
3. Pick the one that feels most robust (not just lucky)

**Pro tip:** Grid search finds local optima. Don't over-optimize on 2-day data or you'll overfit.

---

### Phase 5: Backtesting & Visual Inspection

Once you've found good parameters, run a final backtest and visually inspect the trades.

```bash
python backtest.py --strategy my_attempt_v1 --round 0 --days -2 -1 --verbose
```

The `--verbose` flag outputs detailed trade-by-trade information.

**[OPTIONAL] Visual Deep Dive:**

If you want to see actual trades overlaid on price charts, the backtest currently outputs JSON. You can manually load it into the dashboard (this requires a small enhancement to `prosperity/tooling/dashboard.py` if not already present).

**Sanity checks:**
- Do I see fills when I expect to? (around the mid price)
- Am I getting hit on bad fills? (check worst-execution fills)
- Is my inventory growing uncontrollably? (should fluctuate, not trend)
- Are spreads reasonable? (compare to market spreads in visualizer)

---

### Phase 6: Unit Tests (For New Strategies Only)

If you implemented a **new strategy class** (not just parameter tweaking), test it.

```bash
python -m unittest tests.test_strategies -v
```

**What gets tested:**
- Strategy doesn't crash on empty order books
- Orders respect position limits
- Conversions are valid
- Memory state persists correctly

**Write a simple test if needed:**

```python
# In tests/test_strategies.py
def test_my_new_strategy(self):
    from prosperity.strategies.my_strategy import MyStrategy
    strat = MyStrategy("TEST", params={...})
    orders, convs = strat.compute_orders(state, book, order_depth, position=0, memory={})
    self.assertIsInstance(orders, list)
    self.assertGreaterEqual(convs, 0)
```

**Run full test suite:**
```bash
python -m unittest tests/ -v
```

---

### Phase 7: Final Export & Submission

Lock in your best config and prepare for IMC.

#### Step 7a: Update trader.py

Edit [prosperity/strategies/trader.py](prosperity/strategies/trader.py):

```python
# ── Change these two constants before each round submission ──────────
CURRENT_ROUND = 0
CURRENT_MEMBER = "my_attempt_v1"  # ← Change this to your best variant
```

#### Step 7b: Generate Single-File Submission

```bash
python scripts/export_submission.py \
  --member my_attempt_v1 --round 0 \
  --output artifacts/submissions/my_submission.py
```

This bundles your entire strategy (including all dependencies) into **one .py file** ready for IMC.

#### Step 7c: Compile-Check

Verify the exported file has no syntax errors:

```bash
python -m py_compile artifacts/submissions/my_submission.py
# Should complete silently if OK
```

#### Step 7d: Upload to IMC

1. Go to IMC Prosperity website
2. Upload `artifacts/submissions/my_submission.py`
3. Wait for it to finish compiling and running
4. Get the **submission ID** (e.g., "16248")
5. Save the **official log** file

---

### Phase 8: Post-Submission Review

After your submission runs on IMC servers, download the official log and compare it to your local backtest.

#### Step 8a: Save Official Log

Download from IMC dashboard:
- Right-click → Save as → `examples/official_logs/16248.log`

#### Step 8b: Analyze with Dashboard

```bash
python -m prosperity.tooling.dashboard --log examples/official_logs/16248.log
```

This opens an interactive Plotly dashboard showing:
- **Price chart** with bid/ask/fair price overlay
- **Trade markers** — your buy/sell fills with size color-coded
- **Order book depth** — market depth at each timestamp
- **PnL equity curve** — your cumulative profit over time
- **Position tracking** — your inventory over time
- **Spread & imbalance** — market conditions

#### Step 8c: Compare to Backtest

**Key questions:**
- Did actual fills match backtest fills? (quality of passive fill simulation)
- Did PnL match backtest? (calibration check)
- Were there any bad fills I didn't expect? (model mismatch)
- Did my position management work as expected?

**If there are big differences:**
- Passive fill simulation may be too optimistic
- You might have latency issues (orders arrive late)
- Market conditions shifted (volatility, liquidity)

#### Step 8d: [OPTIONAL] Static Export

If you don't have Dash installed or want a shareable report:

```bash
python -m prosperity.tooling.dashboard --log examples/official_logs/16248.log --static \
  --output artifacts/analysis/submission_16248_report.html
```

This generates a static HTML file with all charts.

---

## Decision Tree: What to Do Next?

```
Backtest PnL > Champion PnL?
├─ YES → Proceed to Phase 3 (Comparison)
│   └─ Ranked #1 or #2?
│       ├─ YES → Proceed to Phase 4 (Grid Search)
│       │   └─ Found better params?
│       │       ├─ YES → Proceed to Phase 7 (Export)
│       │       └─ NO → Adjust & retry Phase 2
│       └─ NO → Adjust parameters & retry Phase 2
└─ NO → Needs rework
    ├─ Check visualizer: is strategy right for this product?
    ├─ Adjust parameters (Phase 2b)
    └─ Re-run backtest (Phase 2c)
```

---

## Common Issues & Troubleshooting

### Issue: Very few trades (0-5 per day)

**Likely cause:** Quotes are too tight or too wide

```python
# If quotes too tight (no fills):
_override(ROUND_0["EMERALDS"], quote_half_spread=3, make_size=20)

# If quotes too wide (being picked off):
_override(ROUND_0["EMERALDS"], quote_half_spread=1, maker_size=10)
```

### Issue: Position keeps hitting the limit

**Likely cause:** Inventory management broken

```python
# Increase inventory aversion
_override(ROUND_0["EMERALDS"], inventory_aversion=2.0)

# Or reduce maker_size
_override(ROUND_0["EMERALDS"], maker_size=10)
```

### Issue: Backtest shows profit but official log shows loss

**Likely causes:**
1. Passive fill simulation too optimistic (set `--verbose` to see fills)
2. Latency issues (orders arrive after best prices)
3. Market conditions shifted between backtest days and submission day

**Fix:** Increase conservatism in [config.py](prosperity/config.py):
- Smaller `maker_size`
- Larger `quote_half_spread`
- Higher `inventory_aversion`

### Issue: Grid search takes forever

**Likely cause:** Too many parameter combinations

```bash
# Instead of: 5 × 5 × 5 = 125 tests
python -m prosperity.tooling.grid_search \
  --param "EMERALDS.ema_alpha=0.08,0.10,0.12,0.14,0.16" \
  --param "EMERALDS.quote_half_spread=1,2,3,4,5"

# Use fewer values:
python -m prosperity.tooling.grid_search \
  --param "EMERALDS.ema_alpha=0.08,0.12,0.16" \
  --param "EMERALDS.quote_half_spread=1,3,5"
# → 3 × 3 = 9 tests
```

---

## Summary: The Cycle

1. **Explore** — Use visualizer to understand market structure (30 min)
2. **Strategize** — Pick strategy type and rough parameters (30 min)
3. **Backtest** — Validate on historical data (1 min)
4. **Compare** — Rank against team variants (2 min)
5. **Optimize** — Grid search for best params (5-15 min depending on grid size)
6. **Inspect** — Spot-check for sanity (5 min)
7. **Export** — Create submission file (1 min)
8. **Submit** — Upload to IMC (instant, then wait for results)
9. **Review** — Analyze official log vs backtest (10 min)
10. **Iterate** — Learn, adjust, repeat

**Typical cycle time:** 1-2 hours from idea to submission.

---

## Makefile Shortcuts

For convenience, use the [Makefile](Makefile) shortcuts:

```bash
make setup                          # Install dependencies
make test                           # Run unit tests
make backtest STRATEGY=champion     # Backtest
make compare ROUND=0                # Compare all variants
make grid-search STRATEGY=champion  # Grid search
make dashboard LOG=path/to/log.log  # Launch dashboard
make export MEMBER=champion         # Export submission
```

Example:
```bash
make backtest STRATEGY=leo ROUND=0
make compare ROUND=0
make grid-search STRATEGY=leo ROUND=0 ARGS="--param EMERALDS.ema_alpha=0.05,0.10,0.15"
```
