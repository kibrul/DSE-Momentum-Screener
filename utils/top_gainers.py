"""
Top gainers: ranks ordinary shares by price gain between two dates chosen inside the loaded history, and
reports the same table for specific symbols you pick (build_symbol_report).

Output columns
    Rank | Symbol | First_Day | Last_Day | % Gain | % ADR | % GAP | RVOL | % RS | Big_Volume_Day

Definitions (all measured inside [start, end]; "traded day" = a day with Volume > 0, because DSE keeps a
row, with a carried-forward price, for days a stock never traded)

  First_Day / Last_Day : the CLOSE on the stock's first / last available day in the range (prices, not dates).
  % Gain   : (Last_Day / First_Day - 1) * 100. Rank 1 = the biggest gain.
  % ADR    : average daily range = mean of (High / Low - 1) * 100 over the traded days.
  % GAP    : the largest opening gap-up in the range = max of (Open / reference close - 1) * 100 over traded
             days, where the reference close is DSE's YCP (the exchange-adjusted previous close) when the data
             has it, else the previous Close. Left blank when no day gapped up.
  RVOL     : relative volume. Two bases are offered because "within the range" can mean either:
               "last_vs_range"    (default) the Last_Day volume / the average volume of the other traded days in the range
               "range_vs_history" the average traded-day volume in the range / the average over the whole loaded history
  % RS     : relative strength = the percentile (0-100) of the stock's % Gain among ALL ordinary shares ranked
             for the same range (not just the top ones), so the leaders sit near 100.
  Big_Volume_Day : the traded day with the largest volume in the range, as "YYYY-MM-DD (volume)".

A stock needs at least two days with a close in the range to have a gain. A stock that only started trading
inside the range is measured from its first available close. Pure price/volume geometry, so there is nothing
DSE-specific except the optional YCP column.
"""
import numpy as np
import pandas as pd

TOP_N = 18
COLUMNS = ["Rank", "Symbol", "First_Day", "Last_Day", "% Gain", "% ADR", "% GAP", "RVOL", "% RS", "Big_Volume_Day"]

RVOL_LAST_VS_RANGE = "last_vs_range"
RVOL_RANGE_VS_HISTORY = "range_vs_history"


def _range_stats(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, rvol_mode: str):
    """All per-stock numbers for [start, end], or None if there aren't two days with a close in the range."""
    if any(col not in df.columns for col in ("Open", "High", "Low", "Close", "Volume")) or df.empty:
        return None
    df = df.sort_index()
    lo = df.index.searchsorted(start, side="left")                       # first row on/after start
    hi = df.index.searchsorted(end + pd.Timedelta(days=1), side="left")  # one past the last row on/before end
    if hi - lo < 2:
        return None

    o, h, l, c, v = (df[col].to_numpy(dtype=float) for col in ("Open", "High", "Low", "Close", "Volume"))
    ycp = df["YCP"].to_numpy(dtype=float) if "YCP" in df.columns else None

    rng = np.arange(lo, hi)
    has_close = rng[np.isfinite(c[lo:hi]) & (c[lo:hi] > 0)]
    if has_close.size < 2:
        return None
    first_i, last_i = has_close[0], has_close[-1]

    gain = (c[last_i] / c[first_i] - 1) * 100
    traded = rng[np.isfinite(v[lo:hi]) & (v[lo:hi] > 0)]

    # ---- ADR: mean daily (High/Low - 1) over traded days ----
    adr = float("nan")
    ok = traded[(h[traded] > 0) & (l[traded] > 0)]
    if ok.size:
        adr = float(np.mean((h[ok] / l[ok] - 1) * 100))

    # ---- GAP: largest opening gap-up vs the reference (previous) close ----
    best_gap = float("nan")
    for i in traded:
        if not (o[i] > 0):
            continue
        if ycp is not None and ycp[i] > 0:
            ref = ycp[i]
        elif i > 0 and c[i - 1] > 0:
            ref = c[i - 1]
        else:
            continue
        g = (o[i] / ref - 1) * 100
        if g > 0 and (np.isnan(best_gap) or g > best_gap):
            best_gap = g

    # ---- RVOL ----
    rvol = float("nan")
    if rvol_mode == RVOL_RANGE_VS_HISTORY:
        hist = v[np.isfinite(v) & (v > 0)]
        if traded.size and hist.size and hist.mean() > 0:
            rvol = float(v[traded].mean() / hist.mean())
    else:
        last_vol = v[last_i] if np.isfinite(v[last_i]) else 0.0
        others = traded[traded != last_i]
        if others.size and v[others].mean() > 0:
            rvol = float(last_vol / v[others].mean())

    # ---- biggest volume day ----
    big_day = ""
    if traded.size:
        j = traded[np.argmax(v[traded])]
        big_day = f"{df.index[j]:%Y-%m-%d} ({v[j]:,.0f})"

    return {"first_close": c[first_i], "last_close": c[last_i], "gain": gain, "adr": adr, "gap": best_gap,
            "rvol": rvol, "big_day": big_day, "first_date": df.index[first_i], "last_date": df.index[last_i]}


_EMPTY_META = {"universe": 0, "first_date": None, "last_date": None}


def _rank_universe(price_data: dict, start_date, end_date, rvol_mode: str) -> pd.DataFrame:
    """
    Per-share stats for EVERY share with a gain in [start, end], indexed by symbol, best gain first, with
    `rank` (1 = biggest gain; tied gains are ordered alphabetically) and `rs` (the gain percentile, 0-100).
    Empty DataFrame when the range is invalid or nothing qualifies.
    """
    start, end = pd.Timestamp(start_date).normalize(), pd.Timestamp(end_date).normalize()
    if end <= start:
        return pd.DataFrame()
    rows = {}
    for symbol in sorted(price_data):
        stats = _range_stats(price_data[symbol], start, end, rvol_mode)
        if stats is not None:
            rows[symbol] = stats
    if not rows:
        return pd.DataFrame()
    stats = pd.DataFrame.from_dict(rows, orient="index")
    stats["rs"] = stats["gain"].rank(pct=True) * 100          # percentile among every ranked share
    stats = stats.sort_values("gain", ascending=False, kind="mergesort")
    stats["rank"] = np.arange(1, len(stats) + 1)
    return stats


def _to_table(stats: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Rank": stats["rank"].to_numpy(),
        "Symbol": stats.index,
        "First_Day": stats["first_close"].round(2).to_numpy(),
        "Last_Day": stats["last_close"].round(2).to_numpy(),
        "% Gain": stats["gain"].round(2).to_numpy(),
        "% ADR": stats["adr"].round(2).to_numpy(),
        "% GAP": stats["gap"].round(2).to_numpy(),
        "RVOL": stats["rvol"].round(2).to_numpy(),
        "% RS": stats["rs"].round(2).to_numpy(),
        "Big_Volume_Day": stats["big_day"].to_numpy(),
    })[COLUMNS]


def _meta(stats: pd.DataFrame) -> dict:
    return {"universe": len(stats), "first_date": stats["first_date"].min(), "last_date": stats["last_date"].max()}


def build_top_gainers(price_data: dict, start_date, end_date, top_n: int = TOP_N,
                      rvol_mode: str = RVOL_LAST_VS_RANGE):
    """
    Returns (table, meta). `table` has COLUMNS (empty if nothing qualifies); `meta` has the number of shares ranked
    (the % RS universe) and the earliest first / latest last trading date seen in the range.
    """
    stats = _rank_universe(price_data, start_date, end_date, rvol_mode)
    if stats.empty:
        return pd.DataFrame(columns=COLUMNS), dict(_EMPTY_META)
    return _to_table(stats.head(top_n)), _meta(stats)


def build_symbol_report(price_data: dict, symbols, start_date, end_date, rvol_mode: str = RVOL_LAST_VS_RANGE):
    """
    The same table for the symbols you pick, instead of the top 18. Every number is exactly what that symbol would
    show in the full ranking, so `Rank` is its REAL position by % Gain among all shares in `price_data` ranked for
    the range (not 1..n) and `% RS` its percentile among them. Rows come back best rank first.

    Returns (table, meta, skipped): `skipped` lists picked symbols that can't be ranked (unknown, or fewer than two
    days with a close in the range).
    """
    wanted = list(dict.fromkeys(symbols))                       # drop duplicates, keep order
    stats = _rank_universe(price_data, start_date, end_date, rvol_mode)
    if stats.empty:
        return pd.DataFrame(columns=COLUMNS), dict(_EMPTY_META), wanted
    chosen = [s for s in wanted if s in stats.index]
    skipped = [s for s in wanted if s not in stats.index]
    if not chosen:
        return pd.DataFrame(columns=COLUMNS), _meta(stats), skipped
    return _to_table(stats.loc[chosen].sort_values("rank")), _meta(stats), skipped
