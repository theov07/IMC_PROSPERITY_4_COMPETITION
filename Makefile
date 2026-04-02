.PHONY: help setup test backtest compare grid-search analyze dashboard benchmark export clean

PYTHON = python
STRATEGY ?= champion
ROUND ?= 0
DAYS ?=
MEMBER ?= champion

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup:  ## Create venv and install dependencies
	$(PYTHON) -m venv .venv
	.venv/Scripts/pip install -r requirements.txt
	@echo "Activate with: source .venv/Scripts/activate"

test:  ## Run all unit tests
	$(PYTHON) -m pytest tests/ -v

backtest:  ## Run backtest (STRATEGY=champion ROUND=0)
	$(PYTHON) backtest.py --strategy $(STRATEGY) --round $(ROUND) $(if $(DAYS),--days $(DAYS),)

compare:  ## Compare all strategies (ROUND=0)
	$(PYTHON) -m prosperity.tooling.compare --strategies champion leo theo pietro --round $(ROUND)

grid-search:  ## Run grid search (needs --param flags, see docs)
	@echo "Usage: make grid-search ARGS='--param EMERALDS.ema_alpha=0.05,0.10,0.15 --strategy champion'"
	$(PYTHON) -m prosperity.tooling.grid_search --strategy $(STRATEGY) --round $(ROUND) $(ARGS)

analyze:  ## Analyze round data (ROUND=0 DAY=-2)
	$(PYTHON) research/analysis.py --round $(ROUND) --day $(or $(DAY),-2)

dashboard:  ## Launch interactive dashboard (LOG=path/to/log.json)
	$(PYTHON) -m prosperity.tooling.dashboard --log $(LOG)

dashboard-static:  ## Export static HTML charts (LOG=path/to/log.json)
	$(PYTHON) -m prosperity.tooling.dashboard --log $(LOG) --static

benchmark:  ## Benchmark strategy latency (STRATEGY=champion)
	$(PYTHON) scripts/benchmark_strategy.py --strategy $(STRATEGY)

export:  ## Export single-file submission (MEMBER=champion)
	$(PYTHON) scripts/export_submission.py --member $(MEMBER)

clean:  ## Remove generated artifacts
	rm -rf artifacts/ __pycache__/ .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
