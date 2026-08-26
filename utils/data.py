"""
Data layer for the Dhaka Stock Exchange (DSE), built on the `bdshare` package
(https://pypi.org/project/bdshare/), which crawls DSE's official site
(dsebd.org). DSE has no official free API, so this is the closest free
equivalent to yfinance for this market.

Key difference from the US version: DSE only has ~650 listed instruments
total, and bdshare's get_historical_data() can return the FULL market's
OHLCV history for a date range in a single call (code="All Instrument") —
no per-ticker chunked downloading needed like the NASDAQ/NYSE version.
"""
import pandas as pd
import streamlit as st

# Defensive import: newer bdshare (>=1.0) exposes get_historical_data() and
# BDShareError directly; older cached installs (<1.0) only had the legacy
# get_hist_data() alias and no BDShareError class. This works either way.
try:
    from bdshare import get_historical_data, get_current_trading_code, BDShareError
except ImportError:
    from bdshare import get_hist_data as get_historical_data, get_current_trading_code

    class BDShareError(Exception):
        """Fallback stand-in — your installed bdshare predates this class."""
        pass

# Heuristic keyword/pattern filter for excluding non-common-equity instruments.
# DSE does not expose a clean "instrument type" field via bdshare, so this is
# a best-effort filter based on common DSE trading-code conventions:
#   - Mutual funds commonly contain "MF" in the trading code (e.g. "1JANATAMF")
#   - Bonds/debentures/Sukuk commonly contain these substrings
# This is NOT guaranteed accurate — spot-check results if precision matters.
_NON_EQUITY_CODE_SUBSTRINGS = ["MF", "BOND", "DEB", "SUKUK", "PREF"]


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def get_all_trading_codes() -> list[str]:
    """All currently traded DSE symbols."""
    try:
        df = get_current_trading_code()
        return sorted(df["symbol"].dropna().unique().tolist())
    except BDShareError as e:
        st.warning(f"Could not fetch DSE trading codes: {e}")
        return []


def filter_equity_codes(symbols: list[str]) -> list[str]:
    """
    Heuristically filters out mutual funds, bonds, debentures, Sukuk, and
    preference shares based on trading-code naming conventions. Imperfect —
    DSE doesn't expose an instrument-type field through this data source.
    """
    return [
        s for s in symbols
        if not any(sub in s.upper() for sub in _NON_EQUITY_CODE_SUBSTRINGS)
    ]


@st.cache_data(ttl=60 * 30, show_spinner=False)
def fetch_full_market_history(start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    """
    Fetches OHLCV history for the ENTIRE DSE market in a single call
    (code="All Instrument"), then reshapes it into {symbol: DataFrame}
    with columns Open, High, Low, Close, Volume — the same schema the
    breadth.py / momentum.py modules expect, so they work unchanged.
    """
    try:
        raw = get_historical_data(start=start_date, end=end_date, code="All Instrument")
    except BDShareError as e:
        st.error(f"Could not fetch DSE market history: {e}")
        return {}

    if raw.empty:
        return {}

    raw = raw.reset_index()  # 'date' becomes a column again
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw = raw.dropna(subset=["date"])

    result: dict[str, pd.DataFrame] = {}
    for symbol, group in raw.groupby("symbol"):
        df = group.sort_values("date").set_index("date")
        df = df.rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume", "value": "Value",
        })
        # "Value" = daily turnover as scraped from DSE's day-end archive table,
        # in millions of Taka (DSE's own site convention for this table).
        # Not independently verified against a live fetch from this environment —
        # sanity-check a known day's figure against dsebd.org after your first run.
        keep_cols = [c for c in ["Open", "High", "Low", "Close", "Volume", "Value"] if c in df.columns]
        df = df[keep_cols].dropna(subset=["Open", "High", "Low", "Close", "Volume"])
        if len(df) >= 15:  # need enough bars for MAs / RS lookback to be meaningful
            result[symbol] = df

    return result
