"""Parse IMC R2 live logs → per-run per-product final PnL, with stats.

Each .log file in IMC's format is a JSON with:
  - submissionId
  - activitiesLog (semicolon-CSV of book snapshots with IMC's own profit_and_loss col)
  - logs
  - tradeHistory

The last row per product gives the final live PnL for that run.

Usage:
    python research/round_2/round_2_MAF/07_parse_live_logs.py \\
        --logs "C:/Users/.../Downloads/log_2_champion_combine/308318.log" \\
               "C:/Users/.../Downloads/log_champion_combine/308278.log"

    # Or a directory containing several *.log files:
    python research/round_2/round_2_MAF/07_parse_live_logs.py --dir "C:/Users/.../Downloads"

    # Filter by keyword (useful when scanning Downloads):
    python research/round_2/round_2_MAF/07_parse_live_logs.py --dir "C:/Users/.../Downloads" \\
        --keyword champion_combine

Produces:
    - stdout report (per-run PnL + mean/std per product)
    - optional --save-json out.json for pipeline re-use
"""
from __future__ import annotations
import argparse
import json
import statistics
import sys
from pathlib import Path

PRODUCTS = ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT")


def parse_log(path: Path) -> dict:
    """Return {'submissionId': ..., 'ASH_COATED_OSMIUM': final_pnl, 'INTARIAN_PEPPER_ROOT': final_pnl, 'TOTAL': ...}."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"error": f"read fail: {e}", "path": str(path)}

    csv = data.get("activitiesLog", "")
    if not csv:
        return {"error": "no activitiesLog", "path": str(path)}

    lines = csv.strip().split("\n")
    if len(lines) < 2:
        return {"error": "empty csv", "path": str(path)}

    header = lines[0].split(";")
    try:
        pnl_idx = header.index("profit_and_loss")
        prod_idx = header.index("product")
        ts_idx = header.index("timestamp")
    except ValueError:
        return {"error": f"missing cols: {header}", "path": str(path)}

    # Group rows by product, get row with max timestamp
    last_per_prod: dict = {}
    for line in lines[1:]:
        cols = line.split(";")
        if len(cols) <= max(pnl_idx, prod_idx, ts_idx):
            continue
        prod = cols[prod_idx]
        try:
            ts = int(cols[ts_idx])
            pnl = float(cols[pnl_idx]) if cols[pnl_idx] else 0.0
        except ValueError:
            continue
        if prod not in last_per_prod or ts > last_per_prod[prod][0]:
            last_per_prod[prod] = (ts, pnl)

    out = {"submissionId": data.get("submissionId", ""), "path": str(path)}
    total = 0.0
    for p in PRODUCTS:
        v = last_per_prod.get(p, (None, 0.0))[1]
        out[p] = v
        total += v
    out["TOTAL"] = total
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", nargs="*", default=[], help="Explicit log file paths")
    ap.add_argument("--dir", type=str, default=None, help="Directory to scan recursively for *.log")
    ap.add_argument("--keyword", type=str, default=None, help="Keep logs whose path contains this keyword")
    ap.add_argument("--save-json", type=str, default=None, help="Write results to JSON file")
    args = ap.parse_args()

    paths = [Path(p) for p in args.logs]
    if args.dir:
        for p in Path(args.dir).rglob("*.log"):
            paths.append(p)
    if args.keyword:
        paths = [p for p in paths if args.keyword in str(p)]
    paths = sorted(set(paths))

    if not paths:
        print("No logs matched. Nothing to do.")
        sys.exit(1)

    print(f"\nParsing {len(paths)} log(s)...\n")
    results = []
    for p in paths:
        r = parse_log(p)
        results.append(r)

    # Print per-run
    good = [r for r in results if "error" not in r]
    bad = [r for r in results if "error" in r]

    print("═" * 90)
    print(f"{'File':<55} {'OSM':>10} {'IPR':>10} {'TOTAL':>10}")
    print("═" * 90)
    for r in good:
        name = Path(r["path"]).parent.name + "/" + Path(r["path"]).name
        if len(name) > 53:
            name = "..." + name[-50:]
        print(f"{name:<55} {r['ASH_COATED_OSMIUM']:>10,.0f} {r['INTARIAN_PEPPER_ROOT']:>10,.0f} {r['TOTAL']:>10,.0f}")
    print("═" * 90)

    if len(good) >= 1:
        osm = [r["ASH_COATED_OSMIUM"] for r in good]
        ipr = [r["INTARIAN_PEPPER_ROOT"] for r in good]
        tot = [r["TOTAL"] for r in good]
        def ms(xs): return (statistics.mean(xs), statistics.stdev(xs) if len(xs) > 1 else 0.0,
                            min(xs), max(xs))
        mo, so, lo_o, hi_o = ms(osm)
        mi, si, lo_i, hi_i = ms(ipr)
        mt, st, lo_t, hi_t = ms(tot)
        print(f"\n{'STATS':<15} {'mean':>10} {'std':>10} {'min':>10} {'max':>10}  (n={len(good)})")
        print("-" * 90)
        print(f"{'OSM':<15} {mo:>10,.0f} {so:>10,.0f} {lo_o:>10,.0f} {hi_o:>10,.0f}")
        print(f"{'IPR':<15} {mi:>10,.0f} {si:>10,.0f} {lo_i:>10,.0f} {hi_i:>10,.0f}")
        print(f"{'TOTAL':<15} {mt:>10,.0f} {st:>10,.0f} {lo_t:>10,.0f} {hi_t:>10,.0f}")

    if bad:
        print(f"\n⚠ {len(bad)} log(s) failed to parse:")
        for r in bad:
            print(f"  {r.get('path')}: {r.get('error')}")

    if args.save_json:
        with open(args.save_json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved to {args.save_json}")


if __name__ == "__main__":
    main()
