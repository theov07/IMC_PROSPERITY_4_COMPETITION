# RELATIVISTIC QUANTS

<p align="center"><strong>IMC Prosperity 4 - Team Trading Research Repository</strong></p>

<table align="center">
  <tr>
    <td align="center" width="220">
      <a href="https://fr.linkedin.com/in/theoverdelhan">
        <img src="https://github.com/theov07.png?size=200" width="96" alt="Théo Verdelhan">
      </a>
      <br>
      <strong>Théo Verdelhan</strong>
      <br>
      <a href="https://fr.linkedin.com/in/theoverdelhan">LinkedIn</a>
      <br>
      <a href="https://github.com/theov07">GitHub</a>
    </td>
    <td align="center" width="220">
      <a href="https://fr.linkedin.com/in/leorenault">
        <img src="https://github.com/Leho777.png?size=200" width="96" alt="Léo Renault">
      </a>
      <br>
      <strong>Léo Renault</strong>
      <br>
      <a href="https://fr.linkedin.com/in/leorenault">LinkedIn</a>
      <br>
      <a href="https://github.com/Leho777">GitHub</a>
    </td>
    <td align="center" width="220">
      <a href="https://www.linkedin.com/in/thibautdesauty">
        <img src="https://github.com/thibaut-dst.png?size=200" width="96" alt="Thibaut Desauty">
      </a>
      <br>
      <strong>Thibaut Desauty</strong>
      <br>
      <a href="https://www.linkedin.com/in/thibautdesauty">LinkedIn</a>
      <br>
      <a href="https://github.com/thibaut-dst">GitHub</a>
    </td>
  </tr>
</table>

<p align="center">
  <em>A six-round quantitative trading project built around research discipline, fast iteration, and collaborative execution.</em>
</p>

---

## Overview

This repository is the public showcase of **RELATIVISTIC QUANTS**, our team entry for the **IMC Prosperity 4** trading competition.

Rather than presenting a single polished strategy in isolation, this repo shows what the full project actually looked like:

- understanding each new round from scratch
- building and improving a shared trading framework under time pressure
- testing teammate ideas in parallel
- reviewing official logs after every important submission
- solving manual trading and market design side-challenges
- merging the best components into stronger final candidates

It should be read primarily as a working record of how we approached the competition:

- a **research archive** of what we studied round by round
- a **team workflow system** for building, comparing, and shipping strategies
- a **record of decisions** showing how we moved from baseline ideas to integrated champion variants

## Team

**RELATIVISTIC QUANTS** was built around a three-person collaboration:

All three of us contributed across the full lifecycle of the project:

- market exploration when new rounds opened
- alpha research and strategy iteration
- backtesting, diagnostics, and official-log review
- manual challenge modeling and decision-making
- final submission selection and integration

So while some branches naturally reflect who pushed a specific idea the hardest at a given moment, the project was never split into rigid roles. The strongest results in this repo came from **overlapping contributions**, fast idea exchange, and repeated hybridization between our research directions.

More broadly, this repository reflects a shared trajectory: all three of us want to build toward **quantitative research**, and this project became a practical training ground for modeling, experimentation, and collaborative problem-solving under pressure.

## What This Repo Contains

This is the actual working archive of a team that competed across six rounds. It includes:

- shared framework code that stayed usable throughout the competition
- round-by-round research notes and strategy variants
- manual challenge modeling and decision tools
- final candidate summaries and post-submission reviews
- preserved results that are representative of our progress, even if we were not one of the top-ranked teams overall

## At a Glance

| Topic | Snapshot |
|---|---|
| Duration | 6 rounds of iterative development |
| Team name | **RELATIVISTIC QUANTS** |
| Working style | shared framework + parallel teammate branches + champion merge path |
| Manual trading | covered across multiple rounds with dedicated research and optimization |
| Final scale | up to **50 products** in the last round |
| Best archived leaderboard placement | **Round 1 algorithmic: rank 77 worldwide, rank 1 in France** |
| Largest archived final candidate | **1,038,132** 3-day backtest PnL in Round 5 |
| Representative live result in repo | **+64,195** live PnL on a fresh Round 3 session |
| Framework status | tested, executable, and organized for public review |

## Selected Results

While this repository covers the full six-round project, the most relevant result to highlight from a pure algorithmic trading standpoint is our **Round 1** finish.

- **Round 1 algorithmic leaderboard:** **rank 77 worldwide**
- **Round 1 algorithmic leaderboard in France:** **rank 1**
- **Archived Round 1 final PnL:** **107,674 XIRECs**

That result matters to us because it came early in the competition and validated the framework and research process we had put in place. It gave us a base to keep building on in later rounds involving manual trading, market design, options, counterparties, and larger multi-product systems.

## The Project Story, Round by Round

### Round 0 - Building the base layer

Round 0 was where we created the foundation that the rest of the project depended on.

At that stage, the important thing was not sophistication. It was speed, clarity, and having a common environment that all three of us could trust. We put in place the first shared backtesting workflow, the core strategy configuration pattern, baseline market-making logic, and the first version of the "champion" integration path.

This round matters in the repo because it established the discipline used later:

- one place to define active products and limits
- one common backtester
- one way to compare variants
- one export path for competition submissions

Without that structure, the later hybrid work would have been much messier.

### Round 1 - From baseline quoting to signal-aware trading

Round 1 was the first real jump in sophistication. The team moved beyond simple spread capture and began working on more signal-aware quoting behavior, especially around inventory and short-term directional structure.

This is where the repo starts to show differentiated thinking:

- teammate-specific variants appeared more clearly
- regression-style and trend-sensitive logic began to replace purely mechanical baselines
- the framework started to support richer experimentation without breaking the shared workflow

Archived leaderboard analysis preserved in this repo places the team at:

- **107,674 final PnL**
- **rank 77 globally**
- **rank 1 in France**

That result became more than a score. It also became data for later rounds: we reused the leaderboard distributions when we modeled field behavior and manual challenge dynamics in Round 2.

### Round 2 - Market design, manual optimization, and strategy synthesis

Round 2 is where the project became much more than "just trading code".

We had two distinct layers of work:

1. **Algorithmic strategy development**
2. **Manual and market design analysis**

On the algorithmic side, the repo shows how teammate ideas started to combine more directly. Round 2 contains several places where one person's structure became the base for another person's improvement, especially around quoting logic, gap behavior, and order-book exploitation.

On the manual side, we treated the competition problems as quantitative decision problems:

- value estimation for the **Market Access Fee** auction
- break-even analysis
- scenario modeling for adversary behavior
- tournament-regret adjustments
- data-driven optimization for the **"Invest and Expand"** challenge

The final archived recommendation for the Round 2 manual allocation problem was:

- **Research = 12%**
- **Scale = 35%**
- **Speed = 53%**

What makes Round 2 especially interesting for a public reader is that it shows our range:

- trading strategy work
- statistical modeling
- game theory reasoning
- practical decision-making under uncertainty

### Round 3 - Options, volatility structure, and live probing

Round 3 was a major step up in complexity.

The competition introduced a structure with an underlying plus a full option chain, and the repo reflects that shift very clearly. This is where our project started to look much more like a small quant research lab:

- implied volatility smile analysis
- Greeks and portfolio exposure analysis
- option-chain diagnostics
- live probes to test behavior under competition conditions
- hybrid strategies mixing passive market making, directional filters, and option overlays

This round also made collaboration more valuable than ever. No single person had to own every subproblem. The repo shows different teammates pushing:

- option-specific logic
- underlying behavior analysis
- volatility and smile diagnostics
- live-safe execution adjustments

The archived Round 3 submissions record a final uploaded candidate at:

- **240,918 backtest PnL**
- **56,858 drawdown**
- **4.237 PnL/DD ratio**

And the round summary archived in the repo also highlights a strong live outcome:

- **+64,195 PnL on a fresh full live session**

Round 3 is probably the clearest example in the repo of our shift from simple strategy iteration toward broader quantitative research.

### Round 4 - Counterparty-aware alpha and robustness filtering

Round 4 introduced a different kind of challenge: information about who was trading.

That changed the style of research. The repo shows a clear move toward:

- participant-aware log review
- trader-specific flow analysis
- fading specific counterparties
- order-book imbalance adjustments
- selective disabling of components that became toxic in new conditions

This round is also a good example of the team being disciplined rather than dogmatic. We did not insist on keeping every product live just because it had worked before. In the archived notes and final candidates, some products were deliberately disabled or downweighted when the evidence pointed that way.

The best archived Round 4 champion candidate in the repo is:

- **174,751 PnL**
- **67,465 drawdown**
- **2.59 PnL/DD ratio**

Round 4 demonstrates something important for a reviewer: we were not only generating ideas, but also **filtering**, **rejecting**, and **de-risking** them when the market structure changed.

### Round 5 - Scaling to 50 products and merging specialized alpha

Round 5 was the large-scale systems round.

The problem became much less about a few hand-tuned products and much more about managing a broad universe intelligently. The repository shows the team responding by moving toward:

- structure analysis across product groups
- pair relationships and anti-correlation overlays
- carry-aware behavior
- selective product dropping
- specialist per-product strategies
- hybrid assembly of multiple teammate alpha sources

Round 5 is where the collaborative nature of the repo becomes impossible to miss. One of the strongest archived outcomes is an explicit **hybrid merge** between:

- a Leo-led framework emphasizing pair and carry overlays
- a Tibo-led framework emphasizing stronger directional and cross-group alpha

The final archived hybrid candidate reaches:

- **1,038,132** 3-day backtest PnL

That number matters, but the more interesting point is *how* it was achieved:

- by comparing product-level behavior
- by not forcing one global style on every asset
- by combining distinct teammate strengths into one integrated system

Round 5 is the clearest expression of the collaborative style behind this repo.

## Manual Trading and Market Design Challenges

One of the strongest things about this repository is that it does not stop at the algorithmic side.

We also tackled the manual and market-structure parts of the competition as serious quantitative problems.

### Round 2 - "Invest and Expand"

For the manual challenge, we did not just eyeball an allocation. We reconstructed the payoff landscape and modeled the problem as a field-dependent tournament:

- exhaustive and semi-exhaustive scans
- best-response reasoning
- focal-point analysis
- level-k style modeling
- data-driven field assumptions using preserved leaderboard information

That work is one of the best examples in the repo of turning a vague competition prompt into a proper optimization pipeline.

### Round 2 - Market Access Fee auction

We also built a full process to reason about the value of extra market access:

- estimate the incremental value of the fee
- use official logs to calibrate realistic impact
- compute break-even levels
- move from naive expected value to tournament-aware bidding

This is exactly the kind of side-problem that often gets treated casually in competitions. In our case, it became a documented research stream of its own.

### Round 3 and Round 4 - Manual trading remained part of the workflow

Even when the headline technical difficulty moved toward options and counterparties, the manual side was still present in our decision process. The repo keeps the context, the research notes, and the logic used to think about those rounds as complete projects rather than isolated scripts.

### Round 5 - Fee-aware allocation tool

For the final manual challenge, we built a compact optimizer that converts alpha views into allocations under quadratic fees. It is small in code, but very representative in spirit:

- state the economics clearly
- write down the optimization
- make assumptions explicit
- build a reusable decision tool

## How We Worked Together

This repository is as much about **process** as it is about results.

Our practical team workflow looked like this:

1. **Open the new round and map the products**
2. **Keep one stable baseline alive**
3. **Split research directions across teammates**
4. **Backtest and compare variants in a shared framework**
5. **Review official logs as soon as fresh evidence arrived**
6. **Promote only the strongest ideas into a champion branch**

That workflow is visible throughout the repo:

- teammate workspaces
- champion and hybrid variants
- archived final recommendations
- notes comparing one teammate's mechanism to another's
- scripts dedicated to reviewing live versus backtest behavior

In other words, this was not a repo where three people worked separately and only merged at the end. It was a repo built to make **joint iteration** possible.

## What the Framework Enabled

Even though this README is intentionally project-oriented rather than code-oriented, the framework work matters because it is what made the team effective.

At a high level, the shared infrastructure gave us:

- a common backtesting layer
- round-aware configuration
- side-by-side strategy comparison
- robustness diagnostics beyond raw PnL
- official-log parsing and replay tooling
- a path from modular research code to single-file competition submissions
- a lightweight testing layer to keep the framework trustworthy

That infrastructure reduced friction between research and execution. It let us spend more time deciding *what* to test, and less time rebuilding the same workflow every time a new round opened.

## Representative Artifacts

### Round 1 - Archived leaderboard positioning

<p align="center">
  <img src="docs/assets/readme/r1_rank_vs_pnl.png" alt="Round 1 leaderboard position" width="900">
</p>

<p align="center">
  <em>Archived leaderboard analysis preserved in the repo and later reused as part of field modeling work.</em>
</p>

### Round 2 - Manual challenge landscape

<p align="center">
  <img src="docs/assets/readme/r2_manual_speed_landscape.png" alt="Round 2 manual speed landscape" width="900">
</p>

<p align="center">
  <em>Round 2 manual work was treated as a quantitative optimization problem, not a gut-feel decision.</em>
</p>

### Round 3 - Volatility research and strategy comparison

<p align="center">
  <img src="docs/assets/readme/r3_volatility_smile.png" alt="Round 3 volatility smile" width="48%">
  <img src="docs/assets/readme/r3_strategy_comparison.png" alt="Round 3 strategy comparison" width="48%">
</p>

<p align="center">
  <em>Round 3 combined options diagnostics, volatility structure work, and direct comparison between strategy families.</em>
</p>

### Round 4 - Backtest dashboard for the final champion candidate

<p align="center">
  <img src="docs/assets/readme/r4_backtest_dashboard.png" alt="Round 4 backtest dashboard" width="900">
</p>

<p align="center">
  <em>The Round 4 dashboard made the final candidate legible at a glance: total PnL, drawdown, per-day contribution, and where the edge came from across the underlying and option strikes.</em>
</p>

### Round 5 - Structural analysis behind pair and carry overlays

<p align="center">
  <img src="docs/assets/readme/r5_group_structure.png" alt="Round 5 group structure analysis" width="900">
</p>

<p align="center">
  <em>Round 5 was not only about scaling up. It was also about understanding which product families moved together, which ones diverged, and where pair structure was strong enough to justify specialized overlays.</em>
</p>

## Repository Guide

This repository is large, so here is the best way to navigate it:

- `prosperity/`
  - the shared trading framework
  - configuration, backtesting, diagnostics, and strategy modules
- `research/`
  - round-specific studies, notebooks, manual challenge work, and structural analysis
- `scripts/`
  - operational tools for analysis, dashboards, exports, and validation
- `artifacts/submissions/`
  - archived final candidates, selection notes, and round summaries
- `artifacts/analysis/`
  - generated research visuals and review outputs
- `team/`
  - teammate notes, playbooks, and coordination material
- `docs/`
  - guides, preserved references, and presentation assets

## Good Places to Start Reading

If you only have a few minutes and want the most representative pieces:

- this `README.md`
- `research/round_2/manual_round_2/FINDINGS.md`
- `research/round_2/round_2_MAF/FINDINGS.md`
- `artifacts/submissions/round_3/README.md`
- `artifacts/submissions/round_4/_BASELINE/README.md`
- `artifacts/submissions/round_5/FINAL_v3000_HYBRID.md`

Those files give a strong picture of the team’s style: strategy development, quantitative reasoning, manual challenge modeling, and final integration work.

## Minimal Quick Start

For anyone who wants to run the repository locally:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m pytest tests -q
python3 backtest.py --strategy champion --round 0 --days -2 --execution-rule queue
```

## Why This Repo Matters

The point of this repository is not that it presents a perfect competition outcome.

What it does show is a way of working that is useful far beyond a trading competition:

- turning messy problems into structured experiments
- combining quantitative reasoning with practical engineering
- collaborating under deadline pressure without losing rigor
- using post-trade review as a real source of research feedback
- integrating multiple people’s strengths into stronger final systems

That is what **RELATIVISTIC QUANTS** really built here.
