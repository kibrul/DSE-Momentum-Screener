"""
Single-day volume/turnover spike screen for DSE: flags a stock if ANY single
day within a recent window individually cleared a threshold — checked day by
day, not as an average. Catches a one-day spike (news, block deal, retail
rush) that would get diluted away by a rolling average over the same window.

Two metrics are supported, since DSE stocks vary hugely in typical share
volume (a Tk10 share and a Tk800 share need very different share counts to
represent the same money):

  - "Volume": raw share count for the day.
  - "Value":  turnover in Taka for the day (as scraped from DSE's day-end
              archive, in millions of Taka per DSE's own site convention).
              Since DSE currency is Taka, this is the metric most directly
              comparable across differently priced stocks.

Sensible starting defaults (see README for full reasoning + sources):
  - Turnover: Tk 10 crore (100 million Taka) in a single day. Grounded in
    recent DSE reporting: even the top 3 most actively traded stocks on DSE
    recently averaged only ~Tk 25-37 crore/day turnover, and DSE's average
    daily MARKET-WIDE turnover (all ~650 stocks combined) has ranged
    roughly Tk 472-997 crore across 2023-2026. Tk 10 crore for a SINGLE
    stock in a SINGLE day is comfortably above typical daily turnover for
    most DSE-listed names, while still achievable during a genuine spike.
  - Share volume: 2,000,000 shares in a single day. Grounded in reporting
    showing a highly liquid higher-priced stock (e.g. Square Pharma) traded
    only ~1.15 million shares even on a big-turnover day, while low-priced,
    high-float names (e.g. Beximco) routinely trade 10-30+ million shares
    on active days — 2M sits above "normal" for most mid/higher-priced
    names while remaining reachable for a genuine spike in others.

These are informed STARTING POINTS from public reporting, not a precise
percentile computed from DSE's full 3-year archive (dsebd.org isn't
reachable from the environment this was built in). Use
`suggest_threshold_from_history()` below to compute a real, data-driven
threshold from whatever history your own run actually loads.
"""
import pandas as pd

TAKA_PER_CRORE = 10_000_000       # 1 crore = 10 million Taka
DEFAULT_TURNOVER_THRESHOLD_MN_TAKA = 100.0   # Tk 10 crore, expressed in millions (DSE's "Value" units)
DEFAULT_VOLUME_THRESHOLD_SHARES = 2_000_000


def crore_to_mn_taka(crore: float) -> float:
    """DSE's 'Value' field is in millions of Taka; 1 crore = 10 million Taka."""
    return crore * 10.0


def mn_taka_to_crore(mn_taka: float) -> float:
    return mn_taka / 10.0


def any_day_spike(df: pd.DataFrame, column: str = "Value", window: int = 9, threshold: float = None) -> bool:
    """
    True if any single day's value in `column` within the last `window`
    bars is >= `threshold`. Checks each day individually (not an average).
    """
    if threshold is None:
        threshold = DEFAULT_TURNOVER_THRESHOLD_MN_TAKA if column == "Value" else DEFAULT_VOLUME_THRESHOLD_SHARES
    if len(df) == 0 or column not in df.columns:
        return False
    recent = df[column].tail(window)
    return bool((recent >= threshold).any())


def days_with_spike(df: pd.DataFrame, column: str = "Value", window: int = 9, threshold: float = None) -> pd.Series:
    """Returns the individual days within the window whose value met/exceeded the threshold."""
    if threshold is None:
        threshold = DEFAULT_TURNOVER_THRESHOLD_MN_TAKA if column == "Value" else DEFAULT_VOLUME_THRESHOLD_SHARES
    if len(df) == 0 or column not in df.columns:
        return pd.Series(dtype=float)
    recent = df[column].tail(window)
    return recent[recent >= threshold]


def build_spike_screen(price_data: dict[str, pd.DataFrame], column: str = "Value",
                        window: int = 9, threshold: float = None) -> pd.DataFrame:
    """
    Scans the full universe and returns a table of symbols with at least
    one single-day spike within the lookback window.
    """
    if threshold is None:
        threshold = DEFAULT_TURNOVER_THRESHOLD_MN_TAKA if column == "Value" else DEFAULT_VOLUME_THRESHOLD_SHARES

    rows = []
    for symbol, df in price_data.items():
        if column not in df.columns:
            continue
        spikes = days_with_spike(df, column=column, window=window, threshold=threshold)
        if spikes.empty:
            continue

        recent_window = df.tail(window)
        most_recent_date = spikes.index[-1]
        days_ago = len(recent_window) - list(recent_window.index).index(most_recent_date) - 1

        row = {
            "Symbol": symbol,
            "Spike Count (in window)": len(spikes),
            f"Max {column} in Window": round(float(spikes.max()), 2),
            "Most Recent Spike Date": most_recent_date.strftime("%Y-%m-%d")
            if hasattr(most_recent_date, "strftime") else str(most_recent_date),
            "Days Ago": days_ago,
            "Last Close (BDT)": round(df["Close"].iloc[-1], 2) if len(df) else None,
        }
        if column == "Value":
            row["Max Turnover (crore)"] = round(mn_taka_to_crore(float(spikes.max())), 2)
        rows.append(row)

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    sort_col = f"Max {column} in Window"
    return out.sort_values(sort_col, ascending=False).reset_index(drop=True)


def suggest_threshold_from_history(price_data: dict[str, pd.DataFrame], column: str = "Value",
                                    percentiles: tuple = (90, 95, 99, 99.5)) -> dict:
    """
    Computes REAL empirical percentiles of daily per-stock values (Volume or
    Value/turnover) across the loaded universe and history — a data-driven
    alternative to the hardcoded defaults above, based on whatever you
    actually pulled from dsebd.org rather than public news snippets.
    """
    all_values = []
    for symbol, df in price_data.items():
        if column in df.columns:
            all_values.extend(df[column].dropna().tolist())

    if not all_values:
        return {}

    series = pd.Series(all_values)
    result = {f"p{p}": round(float(series.quantile(p / 100)), 2) for p in percentiles}
    result["max"] = round(float(series.max()), 2)
    result["median"] = round(float(series.median()), 2)
    result["sample_size"] = len(series)
    if column == "Value":
        result_crore = {f"{k}_crore": round(mn_taka_to_crore(v), 2) for k, v in result.items()
                         if k not in ("sample_size",)}
        result.update(result_crore)
    return result
