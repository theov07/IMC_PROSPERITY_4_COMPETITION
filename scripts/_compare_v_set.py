"""Compare velvet+options variants 3-day + LW."""
import json
LW_TS = 99900

variants = [
  ('naive_mm baseline',                             'analysis/round_3/velvet_opt_naive_mm_3days.json'),
  ('v4_high_k',                                     'analysis/round_3/velvet_opt_v4_high_k_3days.json'),
  ('gamma_unhedged',                                'backtest_results/round_3/options_research/r3_velvet_options_gamma_unhedged_3d.json'),
  ('max3d_blend (winner so far)',                   'backtest_results/round_3/options_research/r3_velvet_options_max3d_blend_3d.json'),
  ('max3d_v2 (gamma 5400/5500 + qty 100)',          'analysis/round_3/r3_velvet_options_max3d_v2_3d.json'),
  ('max3d_v3 (skew tilt 5300/5400)',                'analysis/round_3/r3_velvet_options_max3d_v3_3d.json'),
  ('max3d_v4 (combined)',                           'analysis/round_3/r3_velvet_options_max3d_v4_3d.json'),
]

def lw(ec):
    last = 0.0
    for ts, p in ec:
        if ts > LW_TS: break
        last = p
    return last

print(f'{"Variant":<45} {"3-day":>9} {"D0":>8} {"D1":>8} {"D2":>8} {"D2 LW":>8}')
print('-' * 95)
for label, fname in variants:
    p = f'artifacts/{fname}'
    try:
        with open(p) as fh: d = json.load(fh)
        total = d['summary']['total_pnl']
        days = d['days']
        d0 = days[0]['pnl'] if len(days)>0 else 0
        d1 = days[1]['pnl'] if len(days)>1 else 0
        d2 = days[2]['pnl'] if len(days)>2 else 0
        d2_lw = lw(days[2].get('equity_curve', [])) if len(days)>2 else 0
        print(f'{label:<45} {total:>9,.0f} {d0:>8,.0f} {d1:>8,.0f} {d2:>8,.0f} {d2_lw:>8,.0f}')
    except FileNotFoundError:
        print(f'{label:<45} (not yet)')
    except Exception as e:
        print(f'{label:<45} ERR {e}')

print()
print('=== Per-product (new variants only) ===')
for label, fname in variants[-3:]:
    p = f'artifacts/{fname}'
    try:
        with open(p) as fh: d = json.load(fh)
    except FileNotFoundError:
        print(f'\n{label}: (not yet)')
        continue
    summ = d['summary']
    print(f'\n{label}: total={summ["total_pnl"]:,.0f}')
    for sym, pnl in sorted(summ['per_product_pnl'].items(), key=lambda x: -x[1]):
        if pnl == 0: continue
        trades = summ['per_product_trades'].get(sym, 0)
        maxpos = summ['per_product_max_pos'].get(sym, 0)
        print(f'  {sym:>22}  pnl={pnl:>10,.0f}  trades={trades:>5}  max_pos={maxpos:>4}')
