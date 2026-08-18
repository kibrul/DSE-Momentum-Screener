"""
Live layer for DSE. Unlike the US version, this does NOT need per-ticker
polling — bdshare's get_current_trade_data() returns EVERY currently traded
symbol's latest price in a single call, so refreshing the whole market's
live view every 1-5 minutes is cheap and doesn't risk rate-limiting.

DSE trading hours are Sunday-Thursday (Bangladesh's work week), NOT the
Mon-Fri US convention — so we use bdshare's own get_market_status(), which
reads DSE's site directly, instead of hardcoding a weekday/time window.
"""
import pandas as pd
from bdshare import get_current_trade_data, get_market_status, BDShareError


def is_market_open() -> bool:
    """True if DSE's own site reports the market status as 'Open'."""
    try:
        status = get_market_status()
        return "open" in status.strip().lower()
    except BDShareError:
        return False


def get_market_status_text() -> str:
    try:
        return get_market_status()
    except BDShareError:
        return "Unknown (could not reach dsebd.org)"


def fetch_live_snapshot(avg_volume_by_symbol: dict[str, float] | None = None) -> pd.DataFrame:
    """
    Pulls the current live price table for the WHOLE DSE market in one call.
    If avg_volume_by_symbol is provided (e.g. computed from recent history),
    adds an RVOL column comparing today's volume to that average.
    """
    try:
        df = get_current_trade_data()
    except BDShareError:
        return pd.DataFrame()

    if df.empty:
        return df

    df = df.copy()
    # ycp = "yesterday's closing price" (DSE's own prior-close field)
    df["pct_change"] = ((df["ltp"] / df["ycp"]) - 1) * 100
    df["pct_from_high"] = ((df["ltp"] / df["high"]) - 1) * 100
    df["at_day_high"] = df["ltp"] >= df["high"] * 0.999

    if avg_volume_by_symbol:
        df["avg_volume"] = df["symbol"].map(avg_volume_by_symbol)
        df["rvol"] = df.apply(
            lambda r: (r["volume"] / r["avg_volume"]) if r.get("avg_volume") else float("nan"),
            axis=1,
        )
    else:
        df["rvol"] = float("nan")

    df["breakout_now"] = df["at_day_high"] & (df["rvol"] >= 1.5)
    df["intraday_ep"] = (df["pct_change"] >= 10) & (df["rvol"] >= 2.0)

    out = df.rename(columns={
        "symbol": "Symbol", "ltp": "Last Price", "high": "Day High", "low": "Day Low",
        "close": "Close", "ycp": "Prev Close", "change": "Change", "trade": "Trades",
        "value": "Value (mn)", "volume": "Volume",
        "pct_change": "% Change", "pct_from_high": "% From Day High",
        "at_day_high": "At Day High", "rvol": "RVOL", "breakout_now": "Breakout Now",
        "intraday_ep": "Intraday EP",
    })
    cols = ["Symbol", "Last Price", "% Change", "Day High", "Day Low", "Prev Close",
            "Volume", "RVOL", "% From Day High", "At Day High", "Breakout Now",
            "Intraday EP", "Trades", "Value (mn)"]
    return out[[c for c in cols if c in out.columns]]


def compute_avg_volume(price_data: dict[str, pd.DataFrame], window: int = 10) -> dict[str, float]:
    """Average daily volume per symbol over the trailing `window` sessions, from historical data."""
    result = {}
    for symbol, df in price_data.items():
        if len(df) >= 5 and "Volume" in df.columns:
            result[symbol] = df["Volume"].tail(window).mean()
    return result


def compute_live_breadth(snapshot: pd.DataFrame) -> dict:
    if snapshot.empty:
        return {"up_4pct": 0, "down_4pct": 0, "advancers": 0, "decliners": 0, "count": 0}

    up_4 = (snapshot["% Change"] >= 4).sum()
    down_4 = (snapshot["% Change"] <= -4).sum()
    advancers = (snapshot["% Change"] > 0).sum()
    decliners = (snapshot["% Change"] < 0).sum()

    return {
        "up_4pct": int(up_4),
        "down_4pct": int(down_4),
        "advancers": int(advancers),
        "decliners": int(decliners),
        "count": len(snapshot),
    }
