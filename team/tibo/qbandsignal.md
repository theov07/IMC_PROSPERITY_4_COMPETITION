Yes — the quantile-band signal is basically:

1. **Demean the series** so you work on deviations from a local equilibrium.  
2. **Look back over a rolling window of length \(M\)**.  
3. **Compute the lower and upper empirical thresholds** from that window:  
   - \(P_L\) = \(L\)-th smallest value,  
   - \(P_S\) = \(S\)-th largest value.  
4. **Trade only when the current demeaned spread is beyond one of those bands**. 

## Signal construction

If \(x_t\) is your spread, the usual first step is:
\[
r_t = x_t - \text{rolling mean}(x_t)
\]
so you are trading the residual, not the raw level. 

Then, over the last \(M\) observations of \(r_t\), you sort the window and pick tail values:
- lower band = the \(L\)-th smallest value,
- upper band = the \(S\)-th largest value. 

That gives you dynamic bands that adapt to the recent distribution instead of assuming a fixed standard deviation or a normal shape.

## How the trade decision works

A simple rule is:

- **Go long** when \(r_t \le P_L\).  
- **Go short** when \(r_t \ge P_S\).  
- **Do nothing** when \(P_L < r_t < P_S\). 

If you want a more robust version, you often add persistence:
- enter only if the signal stays beyond the band for \(k\) bars,
- exit when it reverts back inside the bands,
- or require an additional confirmation indicator.

## What \(L\), \(S\), and \(M\) mean

- \(M\): lookback window length. Larger \(M\) gives more stable but slower bands. 
- \(L\): lower-tail rank. Smaller \(L\) means a more extreme lower threshold.  
- \(S\): upper-tail rank. Smaller distance from the top means a more extreme upper threshold.

So if \(M=3600\) and you choose something like the 100th smallest / 100th largest, you are saying: “only trade when the residual is in the far tails of the last hour.” 

## Practical interpretation

This is different from a z-score signal because it does **not** care about standard deviation units; it cares about empirical rarity in the recent window. That makes it more robust if the spread is skewed, heavy-tailed, or regime-changing. 

A clean trading logic is:

- **Long entry**: residual is below \(P_L\).  
- **Short entry**: residual is above \(P_S\).  
- **Exit**: residual crosses back inside the bands or hits the rolling mean.

