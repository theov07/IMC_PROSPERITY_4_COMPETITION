# Competition Playbook

## Before a round opens

- copy the new CSV files into `data/round_<n>/`
- identify products, limits, conversions, and any special constraints
- run the baseline backtests for `champion`, `leo`, `theo`, and `pietro`
- produce a quick table with pnl, volume, max inventory, and strong or weak products
- open at least one official log for review with `scripts/shared/analyze_log.py`

## During the working window

- always keep one stable variant alive
- test only one main idea per strategy branch
- document results immediately in the member folder or in `shared/`
- review official logs as soon as a run is available

## Before final submission

- export the single-file submission with `scripts/shared/export_submission.py`
- compile-check the exported file
- note the UUID or submission id
- save the exact profile and parameters used

## After submission

- fetch the official log
- review executions by product
- inspect quote placement, inventory, missed opportunities, and fair-value drift
- decide whether the next iteration should focus on pricing, sizing, inventory skew, aggressive taking, or regime filters
