# Round 2 Wiki — Archived

Source : Prosperity 4 wiki R2 ("Growing Your Outpost"), extracted 2026-04-19.

## Key MAF rules

- Can bid for **+25% more quotes** in the order book.
  New quotes fit perfectly in the distribution of existing quotes.
- Bid via `def bid(self): return X` method inside `class Trader`.
- **One-time fee at start of R2, paid ONLY if bid accepted.**
- **Top 50% of bids accepted** (strict: bids > median).
- Accepted bid = subtracted from final R2 PnL.
- **Blind auction**: bids only compared at start of final R2 simulation.
- Bid ignored during testing — only counts at the real final run.

## Edge cases

- No `bid()` method → counted as 0 in median denominator
- Negative bid → treated as 0
- No trader.py submission → **excluded** from median denominator entirely

## Testing vs live

> "During testing of round 2, the default set of quotes you interact with is 80%
> of all quotes we generated (i.e., no extra market access). This 80% has been
> slightly randomized for every submission to reflect real-world conditions."

**→ CONFIRMS our 80% subsampling methodology for V measurement.**
**→ Justifies the variance we observed across live runs (stochastic sampling).**

## Wiki examples (IMPORTANT — creates anchors for adversary model)

### Code example (primary anchor)
```python
class Trader:
    def bid(self):
        return 15     ← ⚠ 15 is the wiki-example bid number

    def run(self, state: TradingState):
        (Implementation)
```

### Bidding mechanism example
```
Bids:           [10,   20,  15,   19,   21,   34]
Accepted:  [No, Yes, No, No, Yes, Yes]
Median: 19.5
```
Secondary anchors: 10, 19, 20, 21, 34 (and 15 appears again here).

### Order book example (not bid-related, just book enrichment)
```
Without MAF:                With MAF:
  ask 10@$9                   ask 10@$9
  ask 10@$7                   ask 5@$8   ← extra flow
                              ask 10@$7
  bid 10@$5                   bid 10@$5
  bid 5@$4                    bid 5@$4
```

## Game theory note from wiki

> "To get extra market access, you just need to be in the top 50% of bidders,
> not necessarily the highest bidder. Placing an extremely high bid will almost
> certainly yield full market access, but perhaps you could save (a lot of)
> XIRECs by bidding less while staying in the top 50% of bidders."

→ IMC explicitly hints at shading the bid. Sophisticated teams will shade.
