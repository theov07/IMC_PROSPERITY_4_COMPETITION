# Round 3 — Velvet+Options Final Strategies Recap

Document destiné à l'équipe (Tibo / Theo / Leo) pour décision finale d'upload.

## CV% — qu'est-ce que c'est ?

**Coefficient of Variation** = `stdev(daily_pnls) / mean(daily_pnl) × 100`

Mesure la dispersion relative du PnL jour par jour :
- **CV bas (<25%)** → PnL stable jour par jour, généralise bien en live
- **CV haut (>35%)** → PnL inégal, possible overfit à un jour spécifique

## Recap Pareto frontier — 5 candidats finals

| Tier | Variant | PnL (3d) | DD | Ratio | CV% | Profil |
|---|---|---:|---:|---:|---:|---|
| TOP0 | v52_theo_minimal | 147,679 | 59,356 | 2.488 | 38.1% | Lowest DD point |
| **TOP1** ★ | **v57_v7_passive_unwind** | **156,010** | **59,720** | **2.612** | **38.1%** | **DEFAULT — best ratio** |
| TOP2 | v58_v7_with_5300 | 158,696 | 62,165 | 2.553 | 38.1% | + VEV_5300 strike |
| TOP3 | v61_tibo_far_otm | 160,766 | 68,228 | 2.356 | 39.1% | + Tibo MM on 5300/5400 |
| TOP4 | v62_tibo_5200_5400 | 165,476 | 76,360 | 2.167 | 41.9% | + Tibo MM on 5200 too |

**Pattern PnL par jour** : tous ~28k D0 (warm-up gamma) / 65k D1 / 65k D2.
CV ~38-42% est élevé mais **structurel** (warm-up jour 0).

## Inventaire — équilibre par produit (v62 = TOP4 max stretch)

| Product | PnL | avg_pos% | near_lim% | flips | trades | Inventory |
|---|---:|---:|---:|---:|---:|---|
| VELVETFRUIT_EXTRACT | 82,502 | 81% | 73% | **21** | 3,082 | ✅ **BALANCED** (rotates long↔short) |
| VEV_4000 | 23,384 | 52% | 26% | 0 | 302 | ⚠️ ONE-WAY LONG |
| VEV_4500 | 16,062 | 38% | 1% | 0 | 180 | ⚠️ ONE-WAY LONG (light) |
| VEV_5000 | 7,326 | 20% | 0% | 0 | 90 | ⚠️ ONE-WAY LONG (very light) |
| VEV_5100 | 19,564 | 41% | 32% | 0 | 115 | ⚠️ ONE-WAY LONG |
| VEV_5200 | 11,882 | 61% | 40% | 0 | 236 | ⚠️ ONE-WAY LONG (Tibo MM) |
| **VEV_5300** | 4,426 | **84%** | **74%** | 0 | 145 | ⚠️⚠️ **STUCK NEAR LIMIT** |
| VEV_5400 | 330 | 12% | 0% | 0 | 62 | ⚠️ ONE-WAY LONG (light, prevent_crossing) |

**Read** :
- **VELVET = market maker équilibré** (R3GuardedAnchor + toxic flow + passive unwind tournent l'inventory). 21 sign flips → vraie rotation directionnelle. C'est sain.
- **Options = gamma scalp UNHEDGED** par design (target_qty long). 0 flips partout. **Risque asymétrique** : on gagne si VELVET monte, on perd si VELVET descend.
- **VEV_5300 = risque principal de v62** : 84% near_limit → si VELVET tombe on ne peut pas s'échapper.

## Decision tree pour upload

| Si tu veux... | Pick |
|---|---|
| **Plus safe pour live** | TOP1 v57 (best ratio, lowest CV gardable) |
| Lower DD si live ressemble pas au backtest | TOP0 v52 (no toxic, no unwind) |
| Balance moyen | TOP2 v58 |
| Max PnL avec ratio > 2.3 | TOP3 v61 |
| Max PnL absolu (et DD plus haut) | TOP4 v62 |

## Live alpha findings (Codex 17 probes + core_v1 analysis)

### ⚠️ HYDROGEL turned TOXIC when traded aggressively in live

- Probes 00A/00B/00C (20 HYDRO trades each, tiny passive) → **+5.78 avg signed_mtm** ✅
- core_v1 (188 HYDRO trades, full anchor MM) → **-5.94 avg signed_mtm**, **85.6% adverse** ❌

**Insight critique** : HYDROGEL est profitable en passif TINY-size mais TOXIC en aggressive trading.
Notre v7b fait 3000+ HYDRO trades en backtest → **risque de -16k PnL en live au lieu de +100k backtest**.

### Clean signal live (Codex's analysis sur 17 probes)

| Product | Live markout_5 | adverse% | Live verdict |
|---|---:|---:|---|
| HYDRO clean (passive) | +6.16 | 5.7% | ✅ ALPHA REAL (small size) |
| VELVET passive | +1.25 | 19.8% | ✅ OK |
| VELVET flow-follow | -1.8 | 75%+ | ❌ TOXIC |
| **VEV_4000 tiny passive** | **+10.4** | 0% | ✅✅ **goldmine, mais petit** |
| VEV_4000 aggressive/gap | -9.5 | 95%+ | ❌❌ TOXIC |
| **VEV_4500 dynamic** | **+2.0** | 15% | ✅ best new option leg |
| VEV_5000-5200 | +1-2 | mid | OK conservateur seulement |
| VEV_5400+ | negative | high | ❌ couper en live |

### Implications pour notre lineup velvet+options

✅ **Notre v57 est probablement BIEN** :
- VEV_4500 = 16k PnL, 38% loaded, 180 trades = "light" → marche en live
- VELVET R3GuardedAnchor = balanced, 21 flips = pas overtrading
- Pas de VEV_5400 (drag confirmé)

⚠️ **Risk live de v62 (max stretch)** :
- VEV_5200 à 61% loaded en aggressive 2-sided MM → adverse selection probable
- VEV_5300 à 84% near limit → catastrophe possible si VELVET tombe

⚠️ **Risk transversal — VEV_4000 dans tous nos variants** :
- En backtest 23k PnL avec 302 trades, 52% loaded
- En live 188 trades aggressive = -9.5 markout (TOXIC)
- En live 8 trades tiny passive = +10.4 markout (GOLDMINE)
- **Notre 302 trades est entre les deux** — risque incertain

## Recommandation finale équipe

1. **Default upload velvet+options seul** : `TOP1 v57_v7_passive_unwind` (156k / 60k / 2.61, CV 38%)
   - Conservative, prouvé, pas de stretch dangereux
   - Si live behave like backtest → 156k easy
   - Si live diffère → DD < 60k stable

2. **Si on veut aussi HYDROGEL** : ⚠️ **CHOIX RISQUÉ** suite aux findings live
   - Le backtest dit `v7b_guarded_loose = 99k` mais
   - Live dit "HYDROGEL aggressive = toxic"
   - **Mitigation possible** : v7b avec maker_size réduit (30→15) pour être plus passive
   - **Ou** : `02_HYDRO_RISK_ADJUSTED hydrogel_smart` (29k PnL but DD only 2.6k, plus passif)

3. **Surtout PAS** : `TOP4 v62` + HYDRO aggressive simultanément. Trop d'exposure asymétrique.

## Probes already uploaded (live results known)

| Probe | Live PnL | Read |
|---|---:|---|
| 00A baseline | +760 | passive partout, baseline OK |
| 00B gap+flow follow | -3,275 | flow follow toxic |
| 00C option flow fade | -587 | fade légèrement moins toxic |
| 03/04/05 dynamic skew | +1,134 | confirme dynamic skew package |
| 14 IV momentum | +1,023 | OK mais bouge VEV_5400 mal |
| core_v1 (Codex) | -2,761 | HYDRO aggressive = toxic |

**Estimation live PnL pour TOP1 v57 (velvet+options seul)** : difficile à projeter car le backtest dit 156k mais le live n'a pas encore vu cette combinaison. Probabilité forte de **+5k à +20k** sur une session 1000-tick (5-10x le PnL des probes baseline).

## Files locked et synced dans 3 folders

```
artifacts/submissions/round_3/_final/velvet_options/00_FINAL_CANDIDATES/
artifacts/submissions/round_3/a_tester_sur_imc_live/velvet_et_options/
artifacts/submissions/round_3/locked/velvet_options/
```

Tous les variants TOP0-TOP4 disponibles dans chaque folder.
