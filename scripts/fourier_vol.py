"""Fourier + volatility regime analysis on OSMIUM."""
import pandas as pd
import numpy as np

days = [-2, -1, 0]
frames = []
for d in days:
    df = pd.read_csv(f"data/round_1/prices_round_1_day_{d}.csv", sep=";")
    df = df[df["product"] == "ASH_COATED_OSMIUM"].copy()
    df["day"] = d
    frames.append(df)
df = pd.concat(frames).sort_values(["day", "timestamp"]).reset_index(drop=True)
df["mid"] = (df["bid_price_1"] + df["ask_price_1"]) / 2
df["ret"] = df["mid"].diff()

print("=== FFT on OSMIUM mid price (day -2) ===")
day = df[df["day"] == -2]["mid"].dropna().values
centered = day - day.mean()
fft = np.fft.rfft(centered)
freqs = np.fft.rfftfreq(len(centered), d=1)  # freq in 1/tick
power = np.abs(fft) ** 2
# Drop DC component
idx_sorted = np.argsort(power[1:])[::-1][:10] + 1
print("Top 10 frequency components (period in ticks, power):")
for i in idx_sorted:
    period = 1 / freqs[i] if freqs[i] > 0 else float("inf")
    print(f"  period={period:>10.1f} ticks  power={power[i]:.2e}  amplitude={np.sqrt(power[i]*2/len(day)):.2f}")

print("\n=== Is there a dominant cycle? ===")
total_power = power[1:].sum()
top5_power = sum(power[idx_sorted[:5]])
print(f"  Top-5 freq / total variance: {top5_power / total_power * 100:.1f}%")
print(f"  Top-10 freq / total variance: {sum(power[idx_sorted]) / total_power * 100:.1f}%")

# --- GARCH-lite: rolling realized vol and regime detection ---
print("\n=== Rolling vol (window=100) ===")
df["vol_100"] = df.groupby("day")["ret"].rolling(100, min_periods=20).std().reset_index(level=0, drop=True)

# Persistence: does vol cluster?
print(f"  mean vol: {df['vol_100'].mean():.3f}")
print(f"  std  vol: {df['vol_100'].std():.3f}")
print(f"  min/max: {df['vol_100'].min():.3f} / {df['vol_100'].max():.3f}")
auto = df.groupby("day")["vol_100"].apply(lambda s: s.autocorr(lag=1)).mean()
print(f"  autocorr(vol, lag=1, mean across days): {auto:.3f}")

# Does high-vol regime mean anything for fwd returns?
df["vol_bucket"] = pd.qcut(df["vol_100"], 4, labels=["low", "lo-mid", "hi-mid", "high"])
df["fwd_20"] = df.groupby("day")["mid"].shift(-20) - df["mid"]
df["abs_fwd_20"] = df["fwd_20"].abs()
print("\n  |fwd_20| by vol bucket:")
print(df.groupby("vol_bucket", observed=True)["abs_fwd_20"].mean().to_string())

# Does a simple vol-adaptive spread help? Check if high-vol periods
# show higher adverse selection (post-fill markout)
print("\n=== Does high vol correlate with adverse moves in dev direction? ===")
df["dev"] = df["mid"] - 10000
df["rev_100"] = -np.sign(df["dev"]) * (df.groupby("day")["mid"].shift(-100) - df["mid"])
print(df.groupby("vol_bucket", observed=True)["rev_100"].agg(["mean", "count"]).to_string())
