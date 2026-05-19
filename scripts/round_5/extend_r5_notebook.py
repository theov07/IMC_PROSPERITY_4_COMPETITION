"""Extend research/analysis-round5.ipynb with means/variance/PCA/clustering analysis."""
import json

with open('research/analysis-round5.ipynb') as f:
    nb = json.load(f)

# Define new cells
new_cells = []

# Markdown header
new_cells.append({
    "cell_type": "markdown",
    "metadata": {},
    "source": [
        "# Round 5 -- Variance, Clustering, PCA Analysis\n",
        "\n",
        "Approfondissement post-correlations:\n",
        "- Moyennes par groupe (lineaires vs oscillantes)\n",
        "- Variance intra vs inter groupe\n",
        "- PCA per group + inter-group eigen-portfolios\n",
        "- Hierarchical clustering of products\n",
        "- Tail dependence (copules) per group"
    ]
})

# Cell: linearity stats
new_cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "# Group means: identify FLAT vs DRIFTING\n",
        "from scipy import stats\n",
        "\n",
        "group_mean_stats = {}\n",
        "for gname, gmean in group_mean_df.items():\n",
        "    s = gmean.dropna()\n",
        "    if len(s) < 100: continue\n",
        "    x = np.arange(len(s))\n",
        "    slope, intercept, r, p, se = stats.linregress(x, s.values)\n",
        "    group_mean_stats[gname] = {\n",
        "        'mean': float(s.mean()), 'std': float(s.std()),\n",
        "        'slope': float(slope), 'R2': float(r**2),\n",
        "    }\n",
        "stats_df = pd.DataFrame(group_mean_stats).T.sort_values('R2', ascending=False)\n",
        "print('=== Group means: linearity (R^2) ===')\n",
        "print('R^2 close to 1 = LINEAR drift; close to 0 = FLAT/oscillating')\n",
        "print(stats_df.round(4))"
    ]
})

# Cell: plot all group means
new_cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "# Plot all 10 group means on one chart\n",
        "fig = go.Figure()\n",
        "for gname, gmean in group_mean_df.items():\n",
        "    fig.add_trace(go.Scatter(x=gmean.index, y=gmean.values, mode='lines', name=gname))\n",
        "for b in day_boundaries[:-1]:\n",
        "    fig.add_vline(x=b, line_dash='dash', line_color='grey')\n",
        "fig.update_layout(title='Group means over 3 days (1 line = 1 group, 5 products averaged)',\n",
        "                  height=500, xaxis_title='Time', yaxis_title='Mean mid-price')\n",
        "fig.show()"
    ]
})

# Cell: variance decomposition
new_cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "# Variance decomposition: intra-group vs factor variance\n",
        "rets_wide = mid_wide.pct_change().dropna(how='all')\n",
        "\n",
        "var_decomp = []\n",
        "for gname, prods in groups.items():\n",
        "    members = [p for p in prods if p in rets_wide.columns]\n",
        "    if len(members) < 2: continue\n",
        "    sub = rets_wide[members]\n",
        "    intra = sub.var().mean()\n",
        "    factor_ret = sub.mean(axis=1)\n",
        "    factor_var = factor_ret.var()\n",
        "    corr_m = sub.corr().values\n",
        "    n = len(members)\n",
        "    mask = np.triu(np.ones(n), k=1).astype(bool)\n",
        "    cohesion = corr_m[mask].mean()\n",
        "    ratio = intra / max(factor_var, 1e-12) / n\n",
        "    var_decomp.append({\n",
        "        'group': gname, 'n': n,\n",
        "        'intra_var': intra, 'factor_var': factor_var,\n",
        "        'intra_to_factor': ratio, 'cohesion': cohesion,\n",
        "    })\n",
        "var_df = pd.DataFrame(var_decomp).sort_values('intra_to_factor', ascending=False)\n",
        "print('=== Variance decomposition (returns) ===')\n",
        "print('intra_to_factor: high = members independent; ~1.0 = move together')\n",
        "print(var_df.round(4))"
    ]
})

# Cell: PCA per group
new_cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "# PCA per group: identify factors and orthogonal contrasts\n",
        "from numpy.linalg import eigh\n",
        "\n",
        "def pca_decompose(returns_df):\n",
        "    X = returns_df.dropna().values\n",
        "    Xc = X - X.mean(axis=0)\n",
        "    C = np.cov(Xc.T)\n",
        "    evals, evecs = eigh(C)\n",
        "    idx = np.argsort(evals)[::-1]\n",
        "    return evals[idx], evecs[:, idx], (evals[idx] / evals.sum())\n",
        "\n",
        "for gname, prods in groups.items():\n",
        "    members = [p for p in prods if p in rets_wide.columns]\n",
        "    if len(members) < 2: continue\n",
        "    evals, evecs, expvar = pca_decompose(rets_wide[members])\n",
        "    print(f'\\n=== PCA: {gname} ===')\n",
        "    pcs_str = ' '.join([f'PC{i+1}={expvar[i]*100:.1f}%' for i in range(min(5, len(expvar)))])\n",
        "    print(f'  Var: {pcs_str}')\n",
        "    print(f'  PC1 loadings:')\n",
        "    for m, w in zip(members, evecs[:, 0]):\n",
        "        print(f'    {m:<35} {w:+.3f}')\n",
        "    print(f'  PC2 loadings:')\n",
        "    for m, w in zip(members, evecs[:, 1]):\n",
        "        print(f'    {m:<35} {w:+.3f}')"
    ]
})

# Cell: Inter-group PCA
new_cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "# Inter-group PCA: build group indices, run PCA on those\n",
        "group_ret_df = pd.DataFrame()\n",
        "for gname, prods in groups.items():\n",
        "    members = [p for p in prods if p in rets_wide.columns]\n",
        "    if not members: continue\n",
        "    group_ret_df[gname] = rets_wide[members].mean(axis=1)\n",
        "group_ret_df = group_ret_df.dropna()\n",
        "evals, evecs, expvar = pca_decompose(group_ret_df)\n",
        "\n",
        "print(f'=== INTER-GROUP PCA (10 groups) ===')\n",
        "print(f'Variance explained per PC:')\n",
        "for i in range(min(5, len(expvar))):\n",
        "    print(f'  PC{i+1}: {expvar[i]*100:.1f}%')\n",
        "loadings_df = pd.DataFrame(\n",
        "    evecs[:, :3], index=group_ret_df.columns, columns=['PC1', 'PC2', 'PC3']\n",
        ").round(3)\n",
        "print(f'\\nLoadings:')\n",
        "print(loadings_df)\n",
        "pc1_dom = loadings_df['PC1'].abs().idxmax()\n",
        "print(f'\\n-> PC1 dominated by: {pc1_dom}')"
    ]
})

# Cell: Hierarchical clustering
new_cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "# Hierarchical clustering of products via returns correlation\n",
        "from scipy.cluster.hierarchy import linkage, dendrogram, fcluster\n",
        "from scipy.spatial.distance import squareform\n",
        "\n",
        "rets_clean = rets_wide.dropna(axis=1, thresh=int(0.95 * len(rets_wide)))\n",
        "corr_m = rets_clean.corr().fillna(0)\n",
        "dist_m = 1 - corr_m.abs()\n",
        "np.fill_diagonal(dist_m.values, 0)\n",
        "condensed = squareform(dist_m.values, checks=False)\n",
        "Z = linkage(condensed, method='average')\n",
        "\n",
        "fig, ax = plt.subplots(figsize=(15, 12))\n",
        "dendrogram(Z, labels=corr_m.columns.tolist(), orientation='left', leaf_font_size=8, ax=ax)\n",
        "ax.set_title('Hierarchical clustering of R5 products (1 - |corr|, avg linkage)')\n",
        "plt.tight_layout()\n",
        "plt.show()"
    ]
})

# Cell: cluster assignments
new_cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "# Auto cluster into 6 clusters\n",
        "k = 6\n",
        "clusters = fcluster(Z, t=k, criterion='maxclust')\n",
        "cluster_df = pd.DataFrame({'product': corr_m.columns, 'cluster': clusters})\n",
        "print(f'=== {k} clusters identified ===')\n",
        "for c in sorted(cluster_df['cluster'].unique()):\n",
        "    members = cluster_df[cluster_df['cluster']==c]['product'].tolist()\n",
        "    print(f'\\nCluster {c} ({len(members)} products):')\n",
        "    for m in members:\n",
        "        print(f'  - {m}')"
    ]
})

# Cell: tail dependence
new_cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "# Tail dependence within each group (lambda_L, lambda_U)\n",
        "def tail_dep(x, y, q=0.05, side='lower'):\n",
        "    common = pd.concat([x, y], axis=1).dropna()\n",
        "    if len(common) < 200: return float('nan')\n",
        "    a = common.iloc[:,0]; b = common.iloc[:,1]\n",
        "    if side == 'lower':\n",
        "        thr_a = a.quantile(q); thr_b = b.quantile(q)\n",
        "        cond = a <= thr_a\n",
        "    else:\n",
        "        thr_a = a.quantile(1-q); thr_b = b.quantile(1-q)\n",
        "        cond = a >= thr_a\n",
        "    if cond.sum() < 5: return float('nan')\n",
        "    return float((b[cond] <= thr_b if side=='lower' else b[cond] >= thr_b).mean())\n",
        "\n",
        "for gname, prods in groups.items():\n",
        "    members = [p for p in prods if p in rets_wide.columns]\n",
        "    if len(members) < 2: continue\n",
        "    print(f'\\n=== Tail dep (q=0.05): {gname} ===')\n",
        "    for i, a in enumerate(members):\n",
        "        for b in members[i+1:]:\n",
        "            common = pd.concat([rets_wide[a], rets_wide[b]], axis=1).dropna()\n",
        "            if len(common) < 200: continue\n",
        "            r = float(common.corr().iloc[0,1])\n",
        "            ll = tail_dep(rets_wide[a], rets_wide[b], 0.05, 'lower')\n",
        "            lu = tail_dep(rets_wide[a], rets_wide[b], 0.05, 'upper')\n",
        "            print(f'  {a:<25} <-> {b:<25} corr={r:+.3f} L={ll:.3f} U={lu:.3f}')"
    ]
})

# Cell: PCA residual mean reversion
new_cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "# PCA-residual AR1: who has mean-reverting residuals?\n",
        "X_all = rets_clean.fillna(0).values\n",
        "Xc = X_all - X_all.mean(axis=0)\n",
        "evals_g, evecs_g, expvar_g = pca_decompose(rets_clean)\n",
        "pc1_factor = Xc @ evecs_g[:, 0:1]\n",
        "\n",
        "ar1_resids = []\n",
        "for i, prod in enumerate(rets_clean.columns):\n",
        "    beta = evecs_g[i, 0]\n",
        "    resid = rets_clean[prod].values - beta * pc1_factor[:, 0]\n",
        "    s = resid[~np.isnan(resid)]\n",
        "    if len(s) < 100: continue\n",
        "    if s[:-1].std() < 1e-9: continue\n",
        "    ar = float(np.corrcoef(s[:-1], s[1:])[0,1])\n",
        "    ar1_resids.append((prod, ar))\n",
        "\n",
        "ar1_df = pd.DataFrame(ar1_resids, columns=['product', 'ar1_resid']).sort_values('ar1_resid')\n",
        "print('Mean-reverting PC1-residuals (negative AR1 = candidate for MR strategy):')\n",
        "print(ar1_df.head(15).round(4).to_string(index=False))"
    ]
})

# Replace cell 13 (empty) with first new cell, append rest
if len(nb['cells']) >= 14:
    nb['cells'][13] = new_cells[0]
    nb['cells'].extend(new_cells[1:])
else:
    nb['cells'].extend(new_cells)

with open('research/analysis-round5.ipynb', 'w') as f:
    json.dump(nb, f, indent=1)

print(f"Notebook now has {len(nb['cells'])} cells")
print(f"Added {len(new_cells)} new cells (variance/PCA/clustering/tail-dep/MR)")
