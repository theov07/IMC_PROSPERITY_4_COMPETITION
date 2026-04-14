# Run 118950 - V19 book-following trend

- run id: `118950`
- submission id: `8ef05877-f534-43af-878e-06adbe561b88`
- review chart: [118950_ipr_review.png](/Users/theoverdelhan/Documents/TRADING/IMC_PROSPERITY_4_COMPETITION/artifacts/analysis/round_1/theo/v19_book_follow_118950/118950_ipr_review.png)

What the official run shows:

- the directional thesis is good:
  - buys are mostly early / lower in the trend
  - sells land on local highs
- the issue is not sell quality, it is sell frequency
  - official IPR trades: `34`
  - buy qty: `120`
  - sell qty: `40`

Sell-opportunity reconstruction from the official log:

- total sell-opportunity ticks: `13`
- sell-opportunity ticks while position was already `>= 60`: `8`
- several of those windows were not monetized

Takeaway:

- do not rewrite the whole strategy
- do not force broad inventory rotation
- only add tiny trims on rare rich-bid windows when already very long

Follow-up branch result:

- `V20`: too aggressive, rejected
- `V21`: right idea, initial params slightly too eager
- `V22`: tuned version of the same branch
  - day 0 realistic IPR: `78817.0` vs `78553.0` for V19
  - day -1 realistic IPR: `79369.0` vs `79290.0` for V19
