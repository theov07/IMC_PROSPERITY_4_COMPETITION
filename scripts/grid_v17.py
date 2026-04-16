"""Manual grid search for v17 vol-adaptive AR gain."""
import subprocess
import re
import itertools

# Parameter grid
ar_gain_lo_vals = [0.3, 0.5, 0.7, 1.0]
ar_gain_hi_vals = [1.0, 1.5, 2.0]
vol_threshold_vals = [2.0, 3.0, 5.0]

combos = list(itertools.product(ar_gain_lo_vals, ar_gain_hi_vals, vol_threshold_vals))
print(f"Testing {len(combos)} combos on day 0...")

results = []
for i, (lo, hi, thr) in enumerate(combos):
    if lo >= hi:  # skip nonsensical combos
        continue
    # Use grid_search with single-value params to avoid the subprocess config issue
    cmd = [
        "python", "-m", "prosperity.tooling.grid_search",
        "--strategy", "leo_osmium_v17",
        "--round", "1", "--days", "0",
        "--param", f"ASH_COATED_OSMIUM.ar_gain_lo={lo}",
        "--param", f"ASH_COATED_OSMIUM.ar_gain_hi={hi}",
        "--param", f"ASH_COATED_OSMIUM.vol_threshold={thr}",
        "--execution-rule", "realistic",
        "--top", "1", "--rank-by", "pnl",
    ]
    print(f"\n[{i+1}/{len(combos)}] lo={lo} hi={hi} thr={thr} ...", flush=True)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        out = r.stdout + r.stderr
        # Extract PnL from output
        pnl_match = re.search(r"total_pnl[=:\s]+([-\d.]+)", out)
        if not pnl_match:
            # Try another pattern
            pnl_match = re.search(r"PnL[=:\s]+([-\d,.]+)", out)
        if pnl_match:
            pnl = float(pnl_match.group(1).replace(",", ""))
            results.append((lo, hi, thr, pnl))
            print(f"  -> PnL = {pnl:.0f}", flush=True)
        else:
            # Print last 10 lines for debugging
            lines = out.strip().split("\n")
            for l in lines[-10:]:
                print(f"  {l}", flush=True)
    except subprocess.TimeoutExpired:
        print("  -> TIMEOUT", flush=True)

print("\n" + "="*60)
print("RESULTS (sorted by PnL):")
print("="*60)
results.sort(key=lambda x: -x[3])
for lo, hi, thr, pnl in results:
    print(f"  lo={lo:.1f}  hi={hi:.1f}  thr={thr:.1f}  PnL={pnl:.0f}")
