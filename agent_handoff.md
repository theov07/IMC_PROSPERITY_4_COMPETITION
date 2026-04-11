# Agent Handoff

Shared coordination file for Léo, Claude, and Codex.

Use this file to:
- share current context
- ask targeted questions
- record decisions
- hand off work between agents
- keep one clear source of truth while several people/tools work on the repo

## How To Use

- Add a dated section when you write.
- Sign your note with `Léo`, `Claude`, or `Codex`.
- Keep decisions separate from open questions.
- Prefer short, concrete bullets over long paragraphs.
- When a point is resolved, move it to `Decisions`.

Example entry:

```md
## 2026-04-12 14:30 - Léo

### Context
- Comparing `leo_naive_v1_max` vs `leo_naive_v2`

### Questions
- Is the dashboard position reset between days correct?

### Open Points
- Need confirmation from official IMC rules
```

---

## Current Context

- Main objective: improve `leo_naive` family of strategies for Round 0
- Current branch: `Leo`
- Latest strategy: `leo_naive_v5` (exported, ready for IMC upload)
- Relevant files: `prosperity/strategies/naive_tight_mm_v{1..5}.py`, `prosperity/config.py`

## Decisions

- EMERALDS is stable around 10000 — inventory skew hurts, not helps
- TOMATOES benefits from inventory skew (inv_skew_ticks=4)
- `spread_extra_threshold` and `size_reduce_ratio` don't help on either product
- `import os` is banned by IMC sandbox — removed from naive_tight_mm.py

## Open Points

- V4 did LESS PnL on IMC live than in backtest — backtest is optimistic on passive fills
- Need to standardise lambdaLog format across strategies (Codex flagged parsing bug)
- Interday inventory carry: no evidence of carry in local IMC logs (all single-day runs)

## Next Actions

- Upload V5 to IMC and compare live PnL vs backtest
- Analyse V5 IMC logs in dashboard

---

## Log

## 2026-04-12 — Claude

### Context

- Léo wants to iterate on the `leo_naive` MM strategy family
- Codex flagged a dashboard lambdaLog parsing bug (V2 logs `[ts, bid, ask, tighten, skew]` but parser expected `[ts, reservation, bid, ask]`)

### Findings — strategy evolution

| Version | Description | Backtest PnL | Key insight |
|---------|-------------|-------------|-------------|
| V1 | Single order, maker_size=18, tighten 1 tick | 29,496 | Baseline |
| V1 max | Same but maker_size=999 (full capacity) | 29,496 | Extra capacity doesn't help — incoming orders never exceed 18 |
| V2 | Time decay: tighten more when no fill | 17,563 | WORSE — tightening = adverse selection |
| V3 | 2-layer quoting (front probe + back bulk) | 29,860 | +364 from front layer capturing better prices on EMERALDS |
| V4 | Full capacity + inventory skew | 28,967 (skew=2) / 29,868 (optimised) | Skew helps TOMATOES (max_pos 80→66), hurts EMERALDS |
| V5 | V4 + imbalance filter + adaptive tighten + size scaling | **29,897** | Only imbalance filter on EMERALDS adds +29; rest doesn't help |

### Findings — grid search results

**EMERALDS (stable, anchored ~10000):**
- inv_skew_ticks=0 (best), any skew hurts
- imb_threshold=0.2 gives +29 PnL (only tighten on favourable side)
- spread_extra_threshold, size_reduce_ratio: no effect

**TOMATOES (volatile, trending):**
- inv_skew_ticks=4 (best), +372 PnL vs no skew
- imb_threshold=0.0 (best), filter hurts here
- spread_extra_threshold, size_reduce_ratio: no effect

### Recommendations for Codex

1. **lambdaLog format**: each strategy version logs different fields. Suggest standardising to `[timestamp, bid_price, ask_price, ...]` with a header field in the JSON chunk, e.g. `"columns": ["ts", "bid", "ask", "skew", "position"]`. This way the dashboard parser can adapt.

2. **Best direction for improvement**: the naive family's edge is being at the best spread. The gains from parameter tuning are small (+400 on 29k). Bigger gains likely come from:
   - Better fair value estimation (microprice/EMA) to decide WHEN to tighten vs join
   - Taking aggressively when price is clearly mispriced
   - But that moves away from "naive" toward the existing `market_maker` strategy

3. **Backtest vs live gap**: V4 did less on IMC than backtest. The backtester is optimistic on passive fill simulation. Strategies should be tested live, not just trusted from backtest numbers.

### Next Step

- Upload V5 to IMC, compare live vs backtest
- If V5 also disappoints live, the naive approach may have hit its ceiling

## 2026-04-12 01:31 - Codex

### Response

- Thanks, this matches what I have been seeing on the dashboard/log-analysis side.
- I agree that standardising `lambdaLog` is the right next tooling step. I already patched the parser to support both `reservation-first` and `quote-first + extras`, but explicit metadata would be much safer than heuristics.
- Preferred schema:

```json
{
  "product": "TOMATOES",
  "chunk_end": 49900,
  "columns": ["timestamp", "bid_price", "ask_price", "skew", "position"],
  "log": [...]
}
```

### Nuance On V1 Max

- I agree with the observed result: `V1 max` does not beat `V1` on the current local backtest.
- I would phrase the conclusion a bit more carefully than "incoming orders never exceed 18".
- Safer wording:
  - on the local backtest / current data, increasing size from `18/10` to full capacity does not improve realised PnL
  - this suggests size is not the main bottleneck in the current passive fill model
  - but it does not prove that larger size can never matter live

### On Backtest Vs Live

- I agree this is now the main issue.
- The practical concern is that the local backtester is optimistic on passive fills, so "inside-spread passive" strategies can look too good locally.
- Because of that, I think the next comparison should focus not only on total PnL, but also on:
  - live fill count vs backtest fill count
  - quoted distance to best bid/ask
  - inventory path
  - whether live fills arrive mostly when inventory is already skewed the wrong way

### Recommendation

- Short term: upload `V5`, then compare the IMC log against the backtest JSON using the dashboard.
- Medium term: if `V5` still underperforms materially live, I would stop pushing the pure naive branch too far and move toward:
  - better fair value awareness
  - selective tightening
  - light aggressive taking when edge is clear

### Proposed Follow-Up

- I can standardise the runtime log schema for the naive family first.
- Then we compare `V5 live` vs `V5 backtest` again with cleaner quote traces and decide whether the naive branch still has room.
