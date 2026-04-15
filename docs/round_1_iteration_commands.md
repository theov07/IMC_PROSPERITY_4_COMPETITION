# Round 1 Iteration Commands

## 0. Variables

```bash
export PREV=34 NEXT=35
```

## 1. Nouvelle Logique

Important:

```text
Avant l'export, la nouvelle version doit exister dans prosperity/config.py
sous la clé "theo_round1_vNEXT".
Sinon --member theo_round1_vNEXT ne marchera pas.
```

```bash
cp prosperity/strategies/naive_tight_mm_v${PREV}.py prosperity/strategies/naive_tight_mm_v${NEXT}.py
cp submissions/theo_round1_v${PREV}.py submissions/theo_round1_v${NEXT}.py
```

```bash
python -m py_compile prosperity/strategies/naive_tight_mm_v${NEXT}.py submissions/theo_round1_v${NEXT}.py
```

```bash
python - <<PY
from prosperity.config import get_round_config
cfg = get_round_config(1, "theo_round1_v${NEXT}")
print(sorted(cfg.keys()))
PY
```

```bash
python -m prosperity.tooling.backtest \
  --strategy submissions.theo_round1_v${NEXT} \
  --round 1 \
  --days 0 \
  --data-dir data/round_1 \
  --execution-rule realistic \
  --json-out artifacts/backtest_results/round_1/theo_round1_v${NEXT}_day0_realistic.json
```

```bash
python -m prosperity.tooling.backtest \
  --strategy submissions.theo_round1_v${NEXT} \
  --round 1 \
  --days -1 \
  --data-dir data/round_1 \
  --execution-rule realistic \
  --json-out artifacts/backtest_results/round_1/theo_round1_v${NEXT}_day-1_realistic.json
```

```bash
python - <<'PY'
import json
import os
from pathlib import Path
next_version = os.environ["NEXT"]
for file in [
    f"artifacts/backtest_results/round_1/theo_round1_v{next_version}_day0_realistic.json",
    f"artifacts/backtest_results/round_1/theo_round1_v{next_version}_day-1_realistic.json",
]:
    data = json.loads(Path(file).read_text())["days"][0]
    ps = data["product_summaries"]["INTARIAN_PEPPER_ROOT"]
    fills = [f for f in data["fills"] if f["symbol"] == "INTARIAN_PEPPER_ROOT"]
    buy_qty = sum(f["quantity"] for f in fills if f["side"] == "BUY")
    sell_qty = sum(f["quantity"] for f in fills if f["side"] == "SELL")
    print(file, ps["pnl"], ps["trades"], buy_qty, sell_qty, ps["ending_position"])
PY
```

```bash
python scripts/export_submission.py \
  --member theo_round1_v${NEXT} \
  --round 1 \
  --output artifacts/submissions/theo_round1_v${NEXT}_round1_submission.py
```

## 2. Params Seulement

Important:

```text
Même si tu ne changes que les params, il faut quand même créer
"theo_round1_vNEXT" dans prosperity/config.py.
Sinon l'export échoue.
```

```bash
cp submissions/theo_round1_v${PREV}.py submissions/theo_round1_v${NEXT}.py
```

```bash
python -m py_compile submissions/theo_round1_v${NEXT}.py
```

```bash
python - <<PY
from prosperity.config import get_round_config
cfg = get_round_config(1, "theo_round1_v${NEXT}")
print(sorted(cfg.keys()))
PY
```

```bash
python -m prosperity.tooling.backtest \
  --strategy submissions.theo_round1_v${NEXT} \
  --round 1 \
  --days 0 \
  --data-dir data/round_1 \
  --execution-rule realistic \
  --json-out artifacts/backtest_results/round_1/theo_round1_v${NEXT}_day0_realistic.json
```

```bash
python -m prosperity.tooling.backtest \
  --strategy submissions.theo_round1_v${NEXT} \
  --round 1 \
  --days -1 \
  --data-dir data/round_1 \
  --execution-rule realistic \
  --json-out artifacts/backtest_results/round_1/theo_round1_v${NEXT}_day-1_realistic.json
```

```bash
python - <<'PY'
import json
import os
from pathlib import Path
next_version = os.environ["NEXT"]
for file in [
    f"artifacts/backtest_results/round_1/theo_round1_v{next_version}_day0_realistic.json",
    f"artifacts/backtest_results/round_1/theo_round1_v{next_version}_day-1_realistic.json",
]:
    data = json.loads(Path(file).read_text())["days"][0]
    ps = data["product_summaries"]["INTARIAN_PEPPER_ROOT"]
    fills = [f for f in data["fills"] if f["symbol"] == "INTARIAN_PEPPER_ROOT"]
    buy_qty = sum(f["quantity"] for f in fills if f["side"] == "BUY")
    sell_qty = sum(f["quantity"] for f in fills if f["side"] == "SELL")
    print(file, ps["pnl"], ps["trades"], buy_qty, sell_qty, ps["ending_position"])
PY
```

```bash
python scripts/export_submission.py \
  --member theo_round1_v${NEXT} \
  --round 1 \
  --output artifacts/submissions/theo_round1_v${NEXT}_round1_submission.py
```

## 3. Analyse Log IMC

```bash
python -m prosperity.tooling.logs \
  --log logs/round_1/theo/131059.log \
  --symbol INTARIAN_PEPPER_ROOT \
  --outdir artifacts/analysis/round_1
```

```bash
cp artifacts/analysis/round_1/theo/<submission_id>_INTARIAN_PEPPER_ROOT_review.png artifacts/analysis/round_1/theo/${NEXT}.png
```

## 4. Fichiers A Modifier

```text
prosperity/strategies/naive_tight_mm_vNEXT.py
prosperity/strategies/__init__.py
scripts/export_submission.py
prosperity/config.py
submissions/theo_round1_vNEXT.py
```

## 5. IPR Only

```python
"ASH_COATED_OSMIUM": None,
```



# html

```html
open artifacts/analysis/round_1/theo/d93a7668-3cd3-4285-a4a3-01815879d005_INTARIAN_PEPPER_ROOT_review.html
```

```python
python scripts/analyze_log.py --log logs/round_1/theo/133069.json --outdir artifacts/analysis/round_1 --plotly
```