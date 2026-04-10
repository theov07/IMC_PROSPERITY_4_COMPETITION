# Commandes Framework Prosperity

Ce fichier est le guide pratique pour utiliser le framework dans le bon ordre.
Il complete `README.md` et remplace utilement les essais disperses dans le repo.

## 1. Installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest tests/ -v
```

## 2. Comprendre le flux du framework

Flux principal:

```text
main.py
  -> submissions/champion.py
    -> prosperity/strategies/trader.py
      -> prosperity/config.py
        -> strategies par produit dans prosperity/strategies/
```

En pratique:

- `main.py` sert de point d'entree local par defaut.
- `backtest.py` sert de point d'entree CLI simple pour le backtest.
- la logique metier est surtout dans `prosperity/`.

## 3. Visualiser les donnees brutes de `data/`

### Visualisateur de recherche interactif

```powershell
python research\visualizer\dashboard.py
```

### Generer des graphes dans `artifacts/visualizer_output/`

```powershell
python research\visualizer\main.py
```

### Analyse texte + JSON d'un jour

```powershell
python research\analysis.py --data-dir data --round 0 --day -2
```

Utilise cette phase avant de coder pour voir:

- tendance ou mean reversion
- spread
- volatilite
- imbalance
- bots actifs

## 4. Creer une nouvelle strategie

Ordre recommande:

1. Creer le fichier dans `prosperity/strategies/`, par exemple `my_strategy.py`
2. Enregistrer la classe dans `prosperity/strategies/__init__.py`
3. Ajouter le nom de strategie dans `scripts/export_submission.py`
4. Ajouter une variante dans `prosperity/config.py`
5. Creer un wrapper dans `submissions/mon_variant.py`
6. Backtester

### Fichier strategie

Exemple de chemin:

```text
prosperity/strategies/my_strategy.py
```

La classe doit heriter de `BaseStrategy`.

### Enregistrement

Le registre de strategies est ici:

```text
prosperity/strategies/__init__.py
```

L'exporteur a aussi son propre registre:

```text
scripts/export_submission.py
```

### Configuration

Les variantes se definissent ici:

```text
prosperity/config.py
```

Si tu veux backtester `mon_variant`, il faut une entree dans `MEMBER_OVERRIDES`.

### Wrapper de soumission / backtest

Creer un fichier de ce style:

```text
submissions/mon_variant.py
```

Le plus simple est de copier `submissions/leo.py` ou `submissions/theo.py` et remplacer le membre.

## 5. Backtester une strategie

### Backtest simple

```powershell
python backtest.py --strategy champion --round 0 --days -2 -1
```

### Backtest avec sortie JSON pour le dashboard

```powershell
python backtest.py --strategy champion --round 0 --days -2 -1 --json-out artifacts\backtest_results\champion.json
```

### Backtest plus conservateur sur les fills passifs

```powershell
python backtest.py --strategy champion --round 0 --days -2 -1 --match-trades worse
```

Modes disponibles pour `--match-trades`:

- `all`: optimiste
- `worse`: plus conservateur
- `none`: pas de fills passifs

Important:

- `backtest.py` a la racine est juste un wrapper
- le vrai moteur est `prosperity/tooling/backtest.py`

## 6. Visualiser un backtest

Apres avoir genere un JSON de backtest:

```powershell
python -m prosperity.tooling.dashboard --backtest-json artifacts\backtest_results\champion.json --data-dir data
```

Tu verras selon les variantes:

- prix du marche
- fills
- quotes
- PnL
- position
- features comme la reservation price si la strategie les expose

## 7. Comparer plusieurs variantes

```powershell
python -m prosperity.tooling.compare --strategies champion leo leo_naive theo pietro tibo_AvSt --round 0 --days -2 -1
```

Utilise ca apres un backtest unitaire pour savoir si ta variante vaut le coup.

## 8. Faire une grid search

```powershell
python -m prosperity.tooling.grid_search --strategy champion --round 0 --days -2 -1 --param "EMERALDS.ema_alpha=0.05,0.10,0.15" --param "TOMATOES.quote_half_spread=1,2,3"
```

Utilise cette etape apres avoir une strategie deja fonctionnelle.

Ordre conseille:

1. premiere version qui tourne
2. backtest simple
3. compare
4. grid search
5. backtest final

## 9. Visualiser un log officiel IMC

### Dashboard interactif

```powershell
python -m prosperity.tooling.dashboard --log logs\official_logs\16248.log
```

### Analyse statique avec sorties PNG

```powershell
python scripts\analyze_log.py --log logs\official_logs\16248.log --outdir artifacts\analysis
```

Tu peux remplacer `16248.log` par n'importe quel log dans `logs/`.

## 10. Exporter la strategie pour IMC

```powershell
python scripts\export_submission.py --member champion --round 0 --output artifacts\submissions\champion_submission.py
python -m py_compile artifacts\submissions\champion_submission.py
```

L'exporteur:

- genere le fichier monolithique pour IMC dans `artifacts/submissions/`
- peut aussi ecrire ou mettre a jour le wrapper `submissions/<member>.py`

## 11. Ordre recommande de travail

Ordre simple et sain:

1. visualiser les CSV de `data/`
2. decider de l'idee de strategie
3. creer la strategie dans `prosperity/strategies/`
4. l'enregistrer dans le registre
5. l'ajouter dans `config.py`
6. creer le wrapper dans `submissions/`
7. lancer un backtest
8. visualiser le backtest dans le dashboard
9. comparer avec les autres variantes
10. faire une grid search si la base est prometteuse
11. exporter pour IMC
12. recuperer le log officiel
13. analyser le log officiel
14. iterer

Version courte:

```text
data -> strategy -> config -> submissions -> backtest -> dashboard -> compare -> export -> official log -> review
```

## 12. Fichiers racine: a quoi ils servent

### `main.py`

Contenu actuel:

```python
from submissions.champion import Trader
```

Role:

- point d'entree local par defaut
- permet a des tests ou scripts de faire `import main` puis `main.Trader`
- pointe aujourd'hui vers la variante `champion`

### `backtest.py`

Contenu actuel:

```python
from prosperity.tooling.backtest import run_cli

if __name__ == "__main__":
    raise SystemExit(run_cli())
```

Role:

- raccourci CLI
- permet d'ecrire `python backtest.py ...`
- le vrai moteur est dans `prosperity/tooling/backtest.py`

### `datamodel.py`

Role:

- compatibilite avec le format Prosperity
- definit `TradingState`, `Order`, `OrderDepth`, `Trade`

## 13. Commandes utiles du quotidien

```powershell
python -m pytest tests/ -v
python backtest.py --strategy champion --round 0 --days -2 -1
python backtest.py --strategy champion --round 0 --days -2 -1 --json-out artifacts\backtest_results\champion.json
python -m prosperity.tooling.dashboard --backtest-json artifacts\backtest_results\champion.json --data-dir data
python -m prosperity.tooling.compare --strategies champion leo leo_naive theo pietro tibo_AvSt --round 0 --days -2 -1
python -m prosperity.tooling.grid_search --strategy champion --round 0 --days -2 -1 --param "EMERALDS.ema_alpha=0.05,0.10,0.15"
python -m prosperity.tooling.dashboard --log logs\official_logs\16248.log
python scripts\analyze_log.py --log logs\official_logs\16248.log --outdir artifacts\analysis
python scripts\export_submission.py --member champion --round 0 --output artifacts\submissions\champion_submission.py
```

## 14. Notes importantes

- `WORKFLOW.md` contient des bonnes idees, mais certaines commandes sont plus anciennes que le code actuel.
- Si une strategie n'apparait pas au backtest, verifier:
  - `prosperity/config.py`
  - `submissions/<member>.py`
  - `prosperity/strategies/__init__.py`
  - `scripts/export_submission.py`
- `artifacts/` et `logs/` sont surtout des sorties generees, pas la source metier.
