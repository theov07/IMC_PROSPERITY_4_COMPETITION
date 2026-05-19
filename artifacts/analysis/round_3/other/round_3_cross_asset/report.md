# Round 3 Cross-Asset Pattern Report

Signals are measured on normalized HYDROGEL/VELVET paths, matching the dashboard's Cross-Asset Evolution view.

## Regime Counts
| Regime | Samples |
| --- | --- |
| DECOUPLED | 586 |
| MIXED | 1168 |
| NEG_COUPLED | 177 |
| NODE | 653 |
| POS_COUPLED | 356 |
| WARMUP | 60 |

## VELVET Forward Markout +1000
| Regime | Samples | Mean bps | Median bps | Hit | Avg t | Abs spread |
| --- | --- | --- | --- | --- | --- | --- |
| NEG_COUPLED | 177 | 0.28 | 0.95 | 0.520 | 0.67 | 0.477 |
| MIXED | 1168 | 0.07 | 0.00 | 0.471 | 0.42 | 0.415 |
| NODE | 653 | 0.04 | 0.00 | 0.449 | 0.18 | 0.051 |
| POS_COUPLED | 356 | -0.00 | 0.00 | 0.461 | -0.01 | 0.410 |
| DECOUPLED | 586 | -0.03 | 0.00 | 0.445 | -0.13 | 0.426 |
| WARMUP | 60 | -0.84 | 0.00 | 0.433 | -1.16 | 0.158 |

## VELVET Forward Markout +5000
| Regime | Samples | Mean bps | Median bps | Hit | Avg t | Abs spread |
| --- | --- | --- | --- | --- | --- | --- |
| NEG_COUPLED | 177 | 0.70 | 1.91 | 0.514 | 0.66 | 0.477 |
| POS_COUPLED | 356 | 0.68 | 0.00 | 0.494 | 0.86 | 0.410 |
| MIXED | 1168 | 0.32 | 0.00 | 0.477 | 0.88 | 0.415 |
| NODE | 653 | 0.20 | 0.00 | 0.473 | 0.44 | 0.051 |
| DECOUPLED | 586 | -0.29 | 0.00 | 0.478 | -0.54 | 0.426 |
| WARMUP | 60 | -4.84 | -6.20 | 0.317 | -2.97 | 0.158 |

## VELVET Forward Markout +10000
| Regime | Samples | Mean bps | Median bps | Hit | Avg t | Abs spread |
| --- | --- | --- | --- | --- | --- | --- |
| MIXED | 1168 | 1.08 | 0.00 | 0.500 | 2.12 | 0.415 |
| POS_COUPLED | 356 | 0.57 | 0.00 | 0.497 | 0.57 | 0.410 |
| NODE | 653 | 0.25 | -0.95 | 0.471 | 0.40 | 0.051 |
| NEG_COUPLED | 177 | -0.23 | 0.00 | 0.492 | -0.15 | 0.477 |
| DECOUPLED | 586 | -0.52 | 0.00 | 0.484 | -0.69 | 0.426 |
| WARMUP | 60 | -8.89 | -8.06 | 0.283 | -4.63 | 0.158 |

## VELVET Forward Markout +50000
| Regime | Samples | Mean bps | Median bps | Hit | Avg t | Abs spread |
| --- | --- | --- | --- | --- | --- | --- |
| NEG_COUPLED | 177 | 4.99 | 14.33 | 0.633 | 1.91 | 0.477 |
| MIXED | 1168 | 4.71 | 6.65 | 0.579 | 4.36 | 0.415 |
| DECOUPLED | 586 | 1.36 | 0.00 | 0.489 | 0.88 | 0.426 |
| NODE | 653 | -1.10 | 0.00 | 0.494 | -0.90 | 0.051 |
| POS_COUPLED | 356 | -5.52 | -5.71 | 0.421 | -3.55 | 0.410 |
| WARMUP | 60 | -8.78 | -9.05 | 0.383 | -3.36 | 0.158 |

## Longest Nodes
| Day | Start | End | Ticks | Mean abs spread |
| --- | --- | --- | --- | --- |
| 2 | 365000 | 381000 | 17 | 0.049 |
| 0 | 280000 | 292000 | 13 | 0.048 |
| 2 | 159000 | 171000 | 13 | 0.047 |
| 0 | 753000 | 764000 | 12 | 0.041 |
| 0 | 582000 | 592000 | 11 | 0.057 |
| 1 | 360000 | 370000 | 11 | 0.051 |
| 1 | 350000 | 358000 | 9 | 0.040 |
| 2 | 180000 | 188000 | 9 | 0.042 |
| 0 | 53000 | 60000 | 8 | 0.045 |
| 0 | 110000 | 117000 | 8 | 0.038 |
| 0 | 195000 | 202000 | 8 | 0.053 |
| 0 | 299000 | 306000 | 8 | 0.042 |

## Parameters
```json
{
  "data_dir": "data\\round_3",
  "days": [
    0,
    1,
    2
  ],
  "window": 1000,
  "return_step": 100,
  "sample_every": 10,
  "node_threshold": 0.1,
  "pos_threshold": 0.55,
  "neg_threshold": 0.55,
  "decorr_threshold": 0.15,
  "horizons": [
    1000,
    5000,
    10000,
    50000
  ],
  "targets": [
    "VELVETFRUIT_EXTRACT",
    "HYDROGEL_PACK",
    "VEV_5000",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500"
  ],
  "pooled_regime_counts": {
    "DECOUPLED": 586,
    "MIXED": 1168,
    "NEG_COUPLED": 177,
    "NODE": 653,
    "POS_COUPLED": 356,
    "WARMUP": 60
  }
}
```
