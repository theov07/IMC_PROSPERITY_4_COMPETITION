# A3 Merge Report — best_v19 vs best_v2640_carry_morning

Recommended live-tilted final: `best_v2810_v2640_plus_v19_laundry_A3`

Backtest-max alternative: `best_v2800_v2640_plus_v19_A3`

## Portfolio Summary

| Variant | D2 | D3 | D4 | Total | Max DD | D4@99900 |
|---|---:|---:|---:|---:|---:|---:|
| best_v19 | 288,154.0 | 263,651.0 | 378,061.0 | 929,866.0 | 25,773.0 | 31,730.5 |
| best_v2640_carry_morning | 242,737.5 | 300,639.0 | 423,937.5 | 967,314.0 | 24,361.0 | 30,465.5 |
| best_v2800_v2640_plus_v19_A3 | 286,071.0 | 319,347.0 | 435,935.5 | 1,041,353.5 | 22,042.5 | 37,028.0 |
| best_v2810_v2640_plus_v19_laundry_A3 | 290,997.0 | 319,843.0 | 427,734.5 | 1,038,574.5 | 21,327.5 | 38,301.0 |

## Product-by-Product Decisions

Only products where `v19` and `v2640` differ are listed below. All other products are unchanged between the two parents.

| Product | v19 strategy | v19 BT D2/D3/D4 | v19 BT total | v19 live | v2640 strategy | v2640 BT D2/D3/D4 | v2640 BT total | v2640 live | Kept in v2810 | Why |
|---|---|---:|---:|---:|---|---:|---:|---:|---|---|
| GALAXY_SOUNDS_BLACK_HOLES | cross_group_trend_A2 | +16,614.0 / +15,825.0 / +9,269.0 | +41,708.0 | +2,314.0 | pair_skip_mm | +1,187.5 / +4,889.0 / +9,547.5 | +15,624.0 | +2,120.0 | v19 | v19 wins 2/3 BT days, +26.1k total BT, slightly better live. |
| GALAXY_SOUNDS_DARK_MATTER | cross_group_trend_A2 | +6,239.0 / +8,545.0 / +2,120.0 | +16,904.0 | -421.0 | pair_skip_mm | +1,978.0 / +2,766.0 / +5,922.5 | +10,666.5 | -3,689.0 | v19 | v19 wins 2/3 BT days and loses far less live. |
| GALAXY_SOUNDS_PLANETARY_RINGS | naive_tight_mm | +22,611.0 / +779.0 / -4,786.5 | +18,603.5 | -7,334.5 | inventory_carry_mm | +18,972.0 / +2,319.0 / +634.0 | +21,925.0 | -3,607.0 | v2640 | v2640 carry fixes the live bleed and wins 2/3 BT days. |
| GALAXY_SOUNDS_SOLAR_FLAMES | naive_tight_mm | -7,356.5 / +5,637.0 / +1,102.0 | -617.5 | +1,294.0 | inventory_carry_mm | -5,440.0 / +7,043.0 / -1,536.0 | +67.0 | +1,341.0 | v2640 | v2640 carry is only slightly better; kept for consistency with live-positive carry basket. |
| GALAXY_SOUNDS_SOLAR_WINDS | naive_tight_mm | -9,713.0 / +8,045.0 / +8,791.5 | +7,123.5 | +452.0 | naive_tight_mm | -9,377.0 / +8,446.0 / +9,650.5 | +8,719.5 | +270.0 | v2640 | same naive core, but size=5 wins all 3 BT days; live edge for v19 too small. |
| MICROCHIP_CIRCLE | naive_tight_mm | +222.0 / -1,208.0 / +11,367.0 | +10,381.0 | +1,228.0 | pair_skip_mm | +1,329.0 / +2,530.0 / +15,018.5 | +18,877.5 | -1,000.0 | v2640 | pair_skip wins all 3 BT days; live miss was not enough to overturn the BT gap. |
| MICROCHIP_OVAL | naive_tight_mm | +4,638.0 / +5,001.0 / +1,036.0 | +10,675.0 | +2,621.0 | pair_skip_mm | +8,054.0 / +3,638.5 / +179.0 | +11,871.5 | +2,730.5 | v2640 | pair_skip total slightly better and live slightly better. |
| MICROCHIP_RECTANGLE | coint_mm_v1 | +9,419.5 / +6,271.0 / -4,994.0 | +10,696.5 | -564.0 | pair_skip_mm | +13,923.5 / +13,649.0 / -1,253.0 | +26,319.5 | -1,189.5 | v2640 | pair_skip wins all 3 BT days by a lot; live loss smaller than the BT edge. |
| OXYGEN_SHAKE_GARLIC | trend_follow_v2 | +19,315.0 / -1,855.0 / +19,260.0 | +36,720.0 | +2,460.0 | trend_follow_v2 | +9,535.0 / +0.0 / +9,910.0 | +19,445.0 | +0.0 | v19 | v19 advisor-informed trend fix is massively better in BT and live. |
| OXYGEN_SHAKE_MINT | naive_tight_mm | -1,524.0 / -1,332.0 / +2,820.0 | -36.0 | -2,183.5 | DROP | +0.0 / +0.0 / +0.0 | +0.0 | +0.0 | v2640 | v2640 drop avoids a negative/flat product. |
| OXYGEN_SHAKE_MORNING_BREATH | naive_tight_mm | +3,677.0 / +2,159.0 / +7,874.5 | +13,710.5 | -3,369.0 | inventory_carry_mm | +8,161.0 / +1,908.0 / +3,840.0 | +13,909.0 | -1,758.0 | v2640 | carry wins total and live; difference is small but in the right direction. |
| PANEL_2X2 | naive_tight_mm | +7,217.0 / +331.0 / +805.0 | +8,353.0 | -2,754.0 | inventory_carry_mm | +6,949.5 / +6,002.0 / +1,792.0 | +14,743.5 | -2,308.0 | v2640 | carry is better in BT and less bad live. |
| PANEL_4X4 | naive_tight_mm | -4,698.5 / -1,746.5 / +2,755.5 | -3,689.5 | +3,227.0 | inventory_carry_mm | -4,987.5 / -1,602.5 / +6,830.0 | +240.0 | +4,551.0 | v2640 | carry rescues a losing naive product and is better live too. |
| PEBBLES_L | naive_tight_mm | +1,040.0 / +7,488.0 / -7,211.0 | +1,317.0 | -400.0 | inventory_carry_mm | -713.0 / +12,337.0 / -10,493.0 | +1,131.0 | -98.0 | v2640 | carry has slightly lower BT but much better live; kept for robustness. |
| PEBBLES_S | naive_tight_mm | +17,789.0 / +4,963.0 / +15,920.0 | +38,672.0 | +80.0 | pair_skip_mm | +21,769.0 / +10,850.0 / +29,048.0 | +61,667.0 | +669.0 | v2640 | pair_skip dominates all 3 BT days and live. |
| PEBBLES_XS | trend_follow_v2 | +17,425.0 / +9,425.0 / +5,310.0 | +32,160.0 | +0.0 | trend_follow_v2 | +15,885.0 / +7,765.0 / +1,800.0 | +25,450.0 | +0.0 | v19 | v19 wins all 3 BT days; live is neutral for both. |
| ROBOT_IRONING | trend_follow_v2 | +880.0 / +16,136.0 / +2,270.0 | +19,286.0 | +4,070.0 | trend_follow_v2 | +2,560.0 / +13,830.0 / +1,070.0 | +17,460.0 | +0.0 | v19 | v19 wins 2/3 BT days and was the only one that actually monetized live. |
| ROBOT_LAUNDRY | coint_mm_v1 | +8,850.0 / +4,100.5 / +1,607.5 | +14,558.0 | -389.5 | pair_skip_mm | +3,924.0 / +3,604.5 / +9,808.5 | +17,337.0 | -2,302.5 | v19 | mixed case: v2640 wins full-day BT thanks to late D4, but v19 is much safer live and improves D4@99900 in the merged portfolio. |
| SLEEP_POD_COTTON | trend_follow_v2 | +8,220.0 / +509.0 / -4,318.0 | +4,411.0 | +432.0 | pair_skip_mm | -663.0 / +5,374.0 / +14,954.0 | +19,665.0 | -1,456.0 | v2640 | v2640 pair-skip wins total BT despite ugly live; no validated hybrid kept yet. |
| SLEEP_POD_SUEDE | naive_tight_mm | +13,834.0 / +3,597.0 / -4,196.5 | +13,234.5 | +1,178.5 | pair_skip_mm | +12,656.0 / +7,092.0 / -654.0 | +19,094.0 | -736.5 | v2640 | v2640 pair-skip wins total BT; same note as COTTON. |
| SNACKPACK_RASPBERRY | naive_tight_mm | +4,162.0 / +5,574.5 / +5,660.5 | +15,397.0 | -869.5 | pair_skip_mm | +4,375.5 / +5,802.5 / +5,304.0 | +15,482.0 | -786.5 | v2640 | almost tie; v2640 slightly better on both BT and live. |
| SNACKPACK_VANILLA | snackpack_cross_mm_v1_A1 | +5,129.0 / +5,956.0 / +8,430.0 | +19,515.0 | +358.5 | pair_skip_mm | +1,195.5 / +605.5 / +2,250.0 | +4,051.0 | +430.5 | v19 | v19 cross-mm wins all 3 BT days with similar live. |
| TRANSLATOR_ASTRO_BLACK | naive_tight_mm | +802.0 / -1,255.0 / +5,974.5 | +5,521.5 | +2,757.0 | naive_tight_mm | +394.0 / +220.0 / +7,679.5 | +8,293.5 | +2,869.0 | v2640 | v2640 size=5 is slightly better in BT and live. |
| TRANSLATOR_ECLIPSE_CHARCOAL | naive_tight_mm | +12,708.0 / -6,889.0 / +6,943.5 | +12,762.5 | +3,981.5 | pair_skip_mm | +2,635.5 / -1,420.5 / +11,104.5 | +12,319.5 | +3,562.0 | v19 | v19 wins total BT and live, despite v2640 winning 2/3 individual days. |
| TRANSLATOR_GRAPHITE_MIST | naive_tight_mm | -521.5 / +2,224.0 / +4,873.5 | +6,576.0 | +2,690.0 | inventory_carry_mm | -4,500.5 / +4,285.0 / +7,014.0 | +6,798.5 | +3,440.0 | v2640 | v2640 carry slightly better in BT and live. |
| UV_VISOR_MAGENTA | naive_tight_mm | +2,656.5 / -1,489.5 / -4,645.5 | -3,478.5 | +508.0 | DROP | +0.0 / +0.0 / +0.0 | +0.0 | +0.0 | v2640 | drop is cleaner than keeping a negative BT product. |
| UV_VISOR_ORANGE | naive_tight_mm | +3,877.0 / +1,925.5 / +9,194.5 | +14,997.0 | +4,125.0 | pair_skip_mm | +8,824.0 / +5,927.5 / +6,739.5 | +21,491.0 | +3,602.0 | v2640 | pair_skip much stronger in BT; live giveback not large enough to revert. |
| UV_VISOR_RED | naive_tight_mm | +1,233.0 / +8,456.0 / +109.5 | +9,798.5 | +3,821.5 | pair_skip_mm | +701.0 / +16,300.0 / +3,059.0 | +20,060.0 | +2,208.5 | v2640 | pair_skip much stronger in BT; live giveback not large enough to revert. |

## Notes on the Mixed Case

- `ROBOT_LAUNDRY` is the only product where I kept the live-oriented source (`v19`) in the recommended final `v2810`, even though `v2640` wins on full 3-day BT. The reason is that `v2640` makes its edge late on D4, while `v19` is much less toxic on the actual live slice and improves the merged portfolio at `D4@99900` from `37,028.0` to `38,301.0`.
- I did not keep a new within-product conditional hybrid for `SLEEP_POD_COTTON`, `SLEEP_POD_SUEDE`, or `MICROCHIP_CIRCLE` yet. Those are the next obvious candidates for a delayed-switch / warmup-gated pair-skip idea, but I did not validate such a strategy enough to recommend it now.