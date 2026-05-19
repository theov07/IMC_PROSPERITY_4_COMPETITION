"""Compare OSMIUM-only PnL across baseline strategies (tibo + leo)."""

from __future__ import annotations

from pathlib import Path

from prosperity.tooling.backtest import BacktestEngine, TradeMatchingMode

MEMBERS = [
    "leo_osmium_only",
    "tibo_mm",
    "tibo_mm_first",
    "tibo_naive_mm",
]
DAYS = ["-2", "-1", "0"]


def run(member: str) -> tuple[float, float]:
    engine = BacktestEngine(Path("data"), f"submissions.{member}", round_num=1)
    total, osm = 0.0, 0.0
    for d in DAYS:
        s = engine.run_day(d, mode=TradeMatchingMode.realistic)
        total += float(s.pnl)
        ps = s.product_summaries.get("ASH_COATED_OSMIUM")
        if ps:
            osm += float(ps.pnl)
    return total, osm


def main() -> None:
    results = []
    for m in MEMBERS:
        try:
            t, o = run(m)
            results.append((m, t, o))
            print(f"{m:22s}  osm={o:8.0f}  total={t:8.0f}")
        except Exception as e:
            print(f"{m:22s}  FAIL: {e}")
    results.sort(key=lambda r: -r[2])
    print("\nRanking by OSMIUM PnL:")
    for m, t, o in results:
        print(f"  {m:22s}  osm={o:8.0f}")


if __name__ == "__main__":
    main()
