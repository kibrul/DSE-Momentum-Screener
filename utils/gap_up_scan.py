"""
Gap-up screen: finds stocks that gapped up by at least `min_gap_pct` (default 9%) in a single day on big
volume, on ANY day in the last `window` trading days (default 21, about one month), or on the latest bar only
(the "current day" check).

Definitions
  gap %   = (Open / reference close - 1) * 100            (the opening gap, not the whole-day move)
            reference close = the "YCP" column when the data has one and it is > 0 (DSE's exchange-adjusted
            previous close, which already accounts for dividends / bonus shares), otherwise the previous Close.
  RVOL    = that day's Volume / average Volume of the (up to) 20 TRADED days before it
            (zero-volume "no-trade" days are left out of the average, so thinly traded stocks aren't flattered)
  "big high volume" = RVOL >= min_rvol (default 2.0x)  AND  Volume >= min_volume shares (default 0 = off)

A day needs at least 10 traded days of prior volume to get an RVOL; days without it are skipped.

Current day: while a market is open, today's bar can be unfinished, so its volume is only the volume so far
(RVOL reads low until the close). `partial_bar_date` lets the caller skip the volume tests for that one
unfinished bar, so a stock that gapped at the open still shows up; its gap % is already final at the open.

Pure price/volume geometry, so nothing here is market-specific; used by both the USA and DSE apps.
"""
import numpy as np
import pandas as pd

DEFAULT_WINDOW = 21            # trading days, about one month
DEFAULT_MIN_GAP_PCT = 9.0
DEFAULT_MIN_RVOL = 2.0
DEFAULT_MIN_VOLUME = 0         # shares; 0 = no absolute minimum
AVG_VOLUME_DAYS = 20
MIN_BASELINE_DAYS = 10


def _reference_close(c, ycp, t):
    """Previous-close reference for bar t: YCP when available and > 0, else the prior bar's Close."""
    if ycp is not None and ycp[t] > 0:
        return ycp[t]
    return c[t - 1]


def find_gap_ups(df: pd.DataFrame,
                 window: int = DEFAULT_WINDOW,
                 min_gap_pct: float = DEFAULT_MIN_GAP_PCT,
                 min_rvol: float = DEFAULT_MIN_RVOL,
                 min_volume: float = DEFAULT_MIN_VOLUME,
                 latest_only: bool = False,
                 partial_bar_date=None) -> list:
    """All qualifying gap days in the scan range, oldest first (each a dict). Empty list if none."""
    if any(col not in df.columns for col in ("Open", "Close", "Volume")) or len(df) < 2:
        return []

    o = df["Open"].to_numpy(dtype=float)
    c = df["Close"].to_numpy(dtype=float)
    v = df["Volume"].to_numpy(dtype=float)
    ycp = df["YCP"].to_numpy(dtype=float) if "YCP" in df.columns else None
    n = len(df)
    start = n - 1 if latest_only else max(1, n - window)
    partial_date = pd.Timestamp(partial_bar_date).date() if partial_bar_date is not None else None

    found = []
    for t in range(start, n):
        ref, day_open = _reference_close(c, ycp, t), o[t]
        if not (ref > 0) or not (day_open > 0) or np.isnan(c[t]):
            continue  # bad / missing data
        gap_pct = (day_open / ref - 1) * 100
        if gap_pct < min_gap_pct:
            continue

        baseline = v[max(0, t - AVG_VOLUME_DAYS):t]
        baseline = baseline[np.isfinite(baseline) & (baseline > 0)]   # traded days only
        avg_vol = baseline.mean() if baseline.size >= MIN_BASELINE_DAYS else float("nan")
        day_vol = v[t]
        rvol = day_vol / avg_vol if (avg_vol > 0 and not np.isnan(day_vol)) else float("nan")

        is_partial = partial_date is not None and pd.Timestamp(df.index[t]).date() == partial_date
        if not is_partial:
            if np.isnan(day_vol) or day_vol <= 0:
                continue  # a day with no trades is not a gap, whatever the minimum RVOL is set to
            if np.isnan(rvol) or rvol < min_rvol:
                continue
            if day_vol < min_volume:
                continue
        elif np.isnan(avg_vol):
            continue  # nothing to compare against even for the unfinished bar

        found.append({
            "date": df.index[t],
            "days_ago": n - 1 - t,
            "gap_pct": round(gap_pct, 2),
            "open": round(day_open, 2),
            "prev_close": round(ref, 2),
            "close": round(c[t], 2),
            "day_change_pct": round((c[t] / day_open - 1) * 100, 2),
            "volume": day_vol,
            "avg_volume": avg_vol,
            "rvol": round(rvol, 2) if not np.isnan(rvol) else float("nan"),
            "unfinished_bar": is_partial,
        })
    return found


def build_gap_up_screen(price_data: dict, **params) -> pd.DataFrame:
    """One row per ticker (its most recent qualifying gap day); `params` go straight to find_gap_ups()."""
    rows = []
    for ticker, df in price_data.items():
        hits = find_gap_ups(df, **params)
        if not hits:
            continue
        g = hits[-1]  # most recent qualifying day
        last_close = float(df["Close"].iloc[-1])
        d = g["date"]
        rows.append({
            "Ticker": ticker,
            "Gap Date": d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d),
            "Days Ago": g["days_ago"],
            "Gap %": g["gap_pct"],
            "Day Change % (Open→Close)": g["day_change_pct"],
            "Volume": int(g["volume"]) if not np.isnan(g["volume"]) else None,
            "Avg Vol (20d)": int(g["avg_volume"]) if not np.isnan(g["avg_volume"]) else None,
            "RVOL": g["rvol"],
            "Prev Close": g["prev_close"],
            "Gap-Day Open": g["open"],
            "Gap-Day Close": g["close"],
            "Since Gap %": round((last_close / g["close"] - 1) * 100, 2) if g["close"] > 0 else float("nan"),
            "Gap Days (in range)": len(hits),
            "Last Close": round(last_close, 2),
            "Unfinished Bar": g["unfinished_bar"],
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["Days Ago", "Gap %"], ascending=[True, False]).reset_index(drop=True)


def largest_gap_up(price_data: dict, window: int = DEFAULT_WINDOW, latest_only: bool = False):
    """
    The biggest opening gap-up in the scan range, ignoring volume: (ticker, gap_pct, date) or None.
    Useful when a scan comes back empty, e.g. to see whether the gap threshold is even reachable on a market
    whose daily price limit caps how far a stock can open.
    """
    best = None
    for ticker, df in price_data.items():
        if any(col not in df.columns for col in ("Open", "Close")) or len(df) < 2:
            continue
        o = df["Open"].to_numpy(dtype=float)
        c = df["Close"].to_numpy(dtype=float)
        ycp = df["YCP"].to_numpy(dtype=float) if "YCP" in df.columns else None
        n = len(df)
        for t in range(n - 1 if latest_only else max(1, n - window), n):
            ref = _reference_close(c, ycp, t)
            if ref > 0 and o[t] > 0:
                g = (o[t] / ref - 1) * 100
                if best is None or g > best[1]:
                    best = (ticker, round(g, 2), df.index[t])
    return best


def gap_chart_data(df: pd.DataFrame, gap_date, prev_close: float, bars: int = 60) -> pd.DataFrame:
    """Close for the last `bars` bars plus a flat 'Pre-gap close' line from the gap day on (does price hold the gap?)."""
    out = pd.DataFrame({"Close": df["Close"]}).tail(bars)
    out["Pre-gap Close"] = np.where(out.index >= pd.Timestamp(gap_date), prev_close, np.nan)
    return out
