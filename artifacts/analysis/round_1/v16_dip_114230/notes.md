# Run 114230 - V16 dip/anti-chase

## Official result

- run id: `114230`
- submission id: `c5d5a978-4244-4e54-bbee-85520f64d7fb`
- strategy: `theo_round1_v16`
- official final PnL: `9540.5`

## Comparison vs prior official runs

- V11 `110477`: `9542.5`
- V13 `111852`: `9511.5`
- V16 `114230`: `9540.5`

Interpretation:

- V16 recovers almost all of the loss from V13.
- V16 is effectively tied with V11 on total official PnL.
- ASH is unchanged across all three runs: official PnL stays `2529.5`.
- The whole comparison is therefore about IPR execution quality.

## IPR read

- official IPR PnL:
  - V11 `110477`: `7013.0`
  - V13 `111852`: `6982.0`
  - V16 `114230`: `7011.0`
- final position: still `+80`
- official IPR flow:
  - `15` buys
  - `0` sells
  - total buy quantity: `80`

Weighted official buy markouts:

- V11:
  - `markout_5 = -5.6625`
  - `markout_10 = -5.04375`
- V13:
  - `markout_5 = -8.3625`
  - `markout_10 = -7.69375`
- V16:
  - `markout_5 = -4.6875`
  - `markout_10 = -4.525`

Interpretation:

- V16 clearly improves average buy quality versus both V11 and V13.
- The `buy dips / don't chase` idea did change live behavior in the intended direction.

## What actually happened

V16 split the IPR accumulation into many smaller clips:

- early cluster, same region as V11:
  - `4100`: buy `6 @ 12011`
  - `5000` to `6100`: several buys of `3-6 @ 12012-12013`
- one good passive-style reload:
  - `6400`: buy `4 @ 12001`
- then a late second cluster:
  - `7100` to `7800`: several buys `@ 12014`

Interpretation:

- The positive:
  - V16 avoided the V13 mistake of slamming the whole position too early.
  - The passive-ish fill at `12001` is exactly the kind of improvement we wanted.
- The negative:
  - after the first accumulation block, V16 still resumed buying late at `12014`.
  - that late chase likely gave back most of the edge gained from the better early entries.

## Main takeaway for V17

The useful lesson is not "V16 failed". The useful lesson is:

- early entry timing improved
- late re-acceleration buys were still too permissive

Best next step:

- keep the smaller early taker clips
- keep the ability to reload on real dips
- once position is already substantially long, block or heavily reduce further
  aggressive buys unless the market gives a clear pullback again
