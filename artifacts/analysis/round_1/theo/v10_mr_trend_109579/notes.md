# V10 Notes - Run 109579

Main observation on `INTARIAN_PEPPER_ROOT`:

- early accumulation works, but it is expensive
- all official buys are aggressive ask takes
- the strategy later sells some inventory passively, then often buys it back almost immediately
- paired sell -> rebuy churn costs roughly `156` XIRECs on this run

Representative churn sequences:

- `65700`: sell `8 @ 12061`, then `65800`: buy `8 @ 12068`
- `47700`: sell `4 @ 12043`, then `47800`: buy `4 @ 12054`
- `49800`: sell `3 @ 12045`, then `49900`: buy `3 @ 12056`

Why V11 targets passive asks first:

- the strategy already finishes `+80` in IPR
- removing churn is safer than weakening the initial long bias
- ASH is left untouched to keep attribution clean
