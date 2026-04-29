# 🏆 R5 FINAL CHAMPION — best_v1611_drop_mint

## Performance

| Metric | Backtest 3-day | Live (1 day) |
|---|---:|---:|
| **PnL Total** | **880,725** | **30,144** |
| Max DD | 28,361 (9.7%) | 8,235 (27% intraday, recovered) |
| Win rate | 0.542 | -- |
| Volume | 47,781 passive trades | -- |

### vs Tibo's v10 baseline (847,680)
- **+33,045 PnL backtest** (+3.9%)
- **-4,385 DD backtest** (-13% drawdown)

### vs v2 baseline live (24,609)
- **+5,535 PnL live** (+22.5%)
- **-1,588 DD live**

## Composition (47 active products)

### Tibo's specialized alphas
- **pebbles_arb_v1** sur PEBBLES_XL → +89k (conservation 50000 - sum others)
- **ar1_mean_rev_v1** sur ROBOT_DISHES → +140k (z-score taker thresh=20)
- **trend_follow_v2** sur 11 produits → +97k (EMA vs session start)
- **coint_mm_v1** sur ROBOT_LAUNDRY/VAC + MICROCHIP_RECTANGLE → +35k (cointegration)

### Mes overlays
- **inventory_carry_mm** sur 4 produits flipped (PANEL_4X4, GRAPHITE_MIST, SOLAR_FLAMES, PEBBLES_L) → +4,650
  - LIVE confirmé : PANEL_4X4 +5,163, GRAPHITE_MIST +3,848
- **pair_skip_mm** thresh=1.25 sur 3 paires → +24,360
  - PEBBLES_S↔PEBBLES_XL → +22,995 (synergie avec pebbles_arb)
  - SNACKPACK_VANILLA↔CHOCOLATE → +1,279
  - SNACKPACK_RASPBERRY↔STRAWBERRY → +85

### Drops (perpetual losers)
- TRANSLATOR_SPACE_GRAY → None (Tibo)
- PEBBLES_M → None (Tibo)
- SLEEP_POD_LAMB_WOOL → None (Tibo)
- UV_VISOR_MAGENTA → None (mon ajout v1610, +3,479)
- OXYGEN_SHAKE_MINT → None (mon ajout v1611, +558 bt, +2,119 live!)

## Tests effectués (40+ variants)

### ✅ Ce qui MARCHE
- naive_tight_mm (penny improve, baseline)
- inventory_carry_mm (carry-aware overlay) — +4.6k bt
- pair_skip_mm (passive skip-side) — +24k bt
- Drop perpetual losers — +4k bt cumul

### ❌ Ce qui N'AIDE PAS
- adaptive_regime_mm (PnL throttle) → -8k
- real_mm (inventory skew + adaptive size) → -95k (trop coûteux en spread)
- top_down_filter (group-level throttle) → -77k
- multi_pair_skip basket → -10k à -18k
- vol_adjusted size → -1k à -8k
- cross-asset hedge SLEEP_POD↔ROBOT/MICROCHIP → -3k à -20k
- pca_residual_mr → -10k (signal trop faible)
- impulse_pause SNACKPACK leader → -1k
- carry sur tous les naive → -86k (trop large)
- carry sur 32 audit-recommended → -36k
- zscore_mr_adaptive (UV_VISOR_AMBER) → -5k
- pair_skip sur PEBBLES_XS (replace trend_v2) → -23k
- Drop based on live extrap (v200) → fragile, overfit

## Pourquoi MM sophistiqué (R3/R4) ne marche pas en R5

1. **pos_limit=10** (vs 200-300 R3/R4) : inventory skew n'a pas d'effet matériel
2. **Trader IDs anonymisés** : pas de toxic flow detection possible
3. **Spread = 8-15 ticks** : déjà capturé par penny-improve simple
4. **Skew price-based coûte 1 tick par fill** : net negative sur la plupart des produits

## DD Live profile

- ts=0 → 0 (start)
- ts=25k → +3k (build-up)
- ts=50k → +12k (peak)
- ts=75k → +7.5k (mid-day drawdown -4.5k)
- ts=100k → +30k (recovered, final)

DD intraday important (27% peak-to-trough) mais récupère. Pattern stable observable.

## Ce qui reste à explorer (pour le futur)

Aucun gain attendu — tous les variants testés sont moins bons. Mais idées non-testées :
- Reinforcement learning sur la sélection de stratégie par produit
- Détection régime change online (changepoint detection)
- Multi-timeframe MM (rapid + slow EMAs combinés)

Tous nécessiteraient infrastructure significative pour un gain marginal.
