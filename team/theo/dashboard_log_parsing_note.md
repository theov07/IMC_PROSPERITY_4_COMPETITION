# Dashboard Log Parsing Note

## Summary

We found and fixed a bug in the `Prosperity Trading Dashboard` when reviewing IMC logs for `leo_naive_v2`.

This was **not a strategy bug** and **not an IMC platform formatting bug**.
It was a **dashboard-side log parsing bug** affecting how runtime quotes from `lambdaLog` were reconstructed and displayed.

## Symptom

In the dashboard, the `MM Ask (log)` trace sometimes showed values like:

- `1`
- `2`
- `3`
- `4`

for products such as `TOMATOES` and `EMERALDS`.

These values were obviously impossible as real ask prices and made the quote overlay look broken.

## Root Cause

The issue comes from the fact that IMC stores our `lambdaLog` output, but the internal structure of that payload is defined by our own strategy code.

So:

- IMC log container format is stable
- but the inner `lambdaLog` JSON schema is **repo-defined**, not IMC-enforced

We currently have multiple logging conventions across strategies:

- `naive_tight_mm`: `[timestamp, bid_price, ask_price]`
- `avellaneda_stoikov`: `[timestamp, reservation, bid_price, ask_price]`
- `naive_tight_mm_v2`: `[timestamp, bid_price, ask_price, tighten, skew]`

The old parser in `prosperity/tooling/logs.py` used this rule:

- length `== 3` -> interpret as `[ts, bid, ask]`
- length `>= 4` -> interpret as `[ts, reservation, bid, ask]`

That assumption was wrong for `leo_naive_v2`.

Example:

```json
[0, 5000, 5012, 1, 0]
```

Real meaning:

- `timestamp = 0`
- `bid_price = 5000`
- `ask_price = 5012`
- `tighten = 1`
- `skew = 0`

Old parser meaning:

- `timestamp = 0`
- `reservation = 5000`
- `bid_price = 5012`
- `ask_price = 1`

This is why the dashboard displayed `MM Ask (log)` around `1..4`.

## Scope

Affected:

- `Prosperity Trading Dashboard`
- log-based quote overlays using `_parse_lambda_logs(...)`
- `scripts/shared/analyze_log.py` indirectly, since it uses the same log tooling

Not affected:

- actual IMC execution
- actual submitted quotes
- backtest matching logic
- strategy order generation
- official profit numbers

So the bug was in **review tooling**, not in live trading logic.

## Fix Implemented

The parser in `prosperity/tooling/logs.py` was updated to support multiple tick formats:

- `[ts, bid, ask]`
- `[ts, reservation, bid, ask]`
- `[ts, bid, ask, extra_1, extra_2, ...]`

The fix is generic and does **not** special-case `leo_naive_v2` by name.

Instead, it detects whether the payload is:

- `reservation-first`
- or `quote-first + extra fields`

This makes the solution reusable for future strategies with extra diagnostics appended after bid/ask.

## Validation

Validated on the real IMC run:

- `logs/leo_round0_naive_v2/78241.json`

Before fix:

- `TOMATOES ask_min = 1`, `ask_max = 4`
- `EMERALDS ask_min = 1`, `ask_max = 4`

After fix:

- `TOMATOES ask_min = 4976`, `ask_max = 5015`
- `EMERALDS ask_min = 9997`, `ask_max = 10007`

Unit tests were added/updated and pass successfully.

## Recommendation

The current fix is good and modular, but the long-term improvement would be to standardize runtime log schemas explicitly.

Example:

```json
{
  "product": "TOMATOES",
  "log_format": "quote_first",
  "log": [...]
}
```

That would remove the need for parser heuristics entirely and make dashboard/log tooling more robust across strategies.

## Bottom Line

- This was a real bug
- but it was a **dashboard/log parsing bug**
- not a strategy bug
- not an IMC bug
- and not a wrong PnL calculation

The main consequence was misleading quote visualization in the dashboard.
