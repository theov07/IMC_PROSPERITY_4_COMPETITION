"""3D grid search around v5 winning weights (M49=-0.8, M14=-0.5, M01=-0.2).

Tests every combination of:
  M49 ∈ {-0.7, -0.8, -0.9}
  M14 ∈ {-0.4, -0.5, -0.6}
  M01 ∈ {-0.15, -0.20, -0.25}
= 27 backtests.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[2]

M49_VALUES = [-0.7, -0.8, -0.9]
M14_VALUES = [-0.4, -0.5, -0.6]
M01_VALUES = [-0.15, -0.20, -0.25]


def add_member_config(weights):
    """Generate code to add a member override to config.py."""
    name = f"_grid_M49_{abs(weights['Mark 49']):.2f}_M14_{abs(weights['Mark 14']):.2f}_M01_{abs(weights['Mark 01']):.2f}".replace(".", "")
    return name, weights


def write_grid_configs():
    """Append all grid configs to config.py temporarily."""
    config_path = ROOT / "prosperity" / "config.py"
    src = config_path.read_text(encoding="utf-8")
    if "# === CP_BIAS_3D_GRID_START ===" in src:
        # Already added; remove old block first
        before, _, after_start = src.partition("# === CP_BIAS_3D_GRID_START ===")
        _, _, after = after_start.partition("# === CP_BIAS_3D_GRID_END ===")
        src = before + after.lstrip()

    # Build new block
    block = "\n# === CP_BIAS_3D_GRID_START ===\n"
    names = []
    for m49 in M49_VALUES:
        for m14 in M14_VALUES:
            for m01 in M01_VALUES:
                name = f"r4_grid_M49_{abs(m49)*100:.0f}_M14_{abs(m14)*100:.0f}_M01_{abs(m01)*100:.0f}"
                names.append(name)
                block += f"""MEMBER_OVERRIDES["{name}"] = _v4_with_extras({{"Mark 49": {m49}, "Mark 14": {m14}, "Mark 01": {m01}}})
"""
    block += "# === CP_BIAS_3D_GRID_END ===\n"

    config_path.write_text(src + block, encoding="utf-8")
    return names


def make_submission_wrapper(name):
    """Create a tiny dispatch wrapper in submissions/."""
    sub = ROOT / "submissions" / f"{name}.py"
    template = ROOT / "submissions" / "r4_velvet_options_only.py"
    content = template.read_text(encoding="utf-8")
    content = content.replace("r4_velvet_options_only", name)
    sub.write_text(content, encoding="utf-8")


def run_backtest(name):
    """Run 3-day backtest, return (name, pnl, dd, ratio)."""
    json_path = ROOT / "artifacts" / "analysis" / "round_4" / f"{name}_3d.json"
    cmd = [
        sys.executable, "backtest.py",
        "--strategy", name,
        "--round", "4",
        "--days", "1", "2", "3",
        "--match-trades", "realistic",
        "--json", str(json_path),
    ]
    env = {"PYTHONIOENCODING": "utf-8"}
    import os
    env.update(os.environ)
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, env=env, text=False)
    if result.returncode != 0:
        return (name, None, None, None)
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            d = json.load(f)
        pnl = d["summary"]["total_pnl"]
        dd = d["summary"]["robustness"]["max_drawdown"]
        ratio = pnl / dd if dd else 0
        return (name, pnl, dd, ratio)
    except Exception as e:
        return (name, str(e), None, None)


def main():
    print("Setting up 27 grid configs...")
    names = write_grid_configs()
    print(f"Created {len(names)} configs")

    print("Creating submission wrappers...")
    for n in names:
        make_submission_wrapper(n)

    print("Running 27 backtests in parallel (4 at a time)...")
    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, result in enumerate(ex.map(run_backtest, names)):
            results.append(result)
            print(f"  [{i+1}/{len(names)}] {result[0]}: {result[1]}")

    # Sort by PnL descending
    valid = [r for r in results if isinstance(r[1], (int, float))]
    valid.sort(key=lambda r: -r[1])

    print("\n" + "=" * 100)
    print("3D GRID SEARCH RESULTS (27 combos around v5)")
    print("=" * 100)
    print(f"{'Variant':>50s}  {'PnL_3d':>10s}  {'DD':>10s}  {'Ratio':>6s}")
    print("-" * 100)
    for n, pnl, dd, r in valid:
        flag = " <-- v5 (M49=-0.8 M14=-0.5 M01=-0.20)" if "M49_80_M14_50_M01_20" in n else ""
        print(f"{n:>50s}  {pnl:>+10,.0f}  {dd:>10,.0f}  {r:>6.2f}{flag}")

    # Best
    if valid:
        best = valid[0]
        print(f"\nBEST: {best[0]} = PnL {best[1]:,.0f} / DD {best[2]:,.0f} / Ratio {best[3]:.2f}")
        v5_baseline = 174751
        delta = best[1] - v5_baseline
        print(f"vs v5 ({v5_baseline:,}): {delta:+,.0f}")


if __name__ == "__main__":
    main()
