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
import os
from pathlib import Path

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

# ---------------------------------------------------------------------------
# Request hygiene for bdshare's shared HTTP session
# ---------------------------------------------------------------------------
# bdshare identifies itself as "bdshare/2.0 (...)", which web-application firewalls like to refuse, and DSE
# answers many datacenter IPs (Streamlit Community Cloud runs in a US datacenter) with a non-200 status.
# Sending ordinary browser headers helps with the first problem. It cannot fix an IP-address block: for that,
# use a saved snapshot (see SNAPSHOT_PATH below) or an optional proxy (DSE_PROXY_URL).
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/130.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _secret_or_env(name: str):
    """Value of a Streamlit secret or environment variable, or None. Never raises."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def _configure_bdshare_session() -> None:
    """Browser-like headers on bdshare's shared session, plus an optional proxy from DSE_PROXY_URL."""
    try:
        from bdshare.util.helper import _session
    except Exception:
        return  # a bdshare version without the shared session: nothing to configure
    _session.headers.update(BROWSER_HEADERS)
    proxy = _secret_or_env("DSE_PROXY_URL")
    if proxy:
        try:
            from bdshare.util.proxy import configure_proxy
            configure_proxy(str(proxy))
        except Exception:
            pass


_configure_bdshare_session()

# Heuristic keyword/pattern filter for excluding non-common-equity instruments.
# DSE does not expose a clean "instrument type" field via bdshare, so this is
# a best-effort filter based on common DSE trading-code conventions:
#   - Mutual funds commonly contain "MF" in the trading code (e.g. "1JANATAMF")
#   - Bonds/debentures/Sukuk commonly contain these substrings
# This is NOT guaranteed accurate — spot-check results if precision matters.
_NON_EQUITY_CODE_SUBSTRINGS = ["MF", "BOND", "DEB", "SUKUK", "PREF"]


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def _load_trading_codes() -> list[str]:
    """Raises on failure, so Streamlit never caches a failed fetch (it would be remembered for 12 hours)."""
    df = get_current_trading_code()
    codes = sorted(df["symbol"].dropna().unique().tolist())
    if not codes:
        raise RuntimeError("DSE returned an empty list of trading codes")
    return codes


def get_all_trading_codes() -> list[str]:
    """
    All currently traded DSE symbols, or [] if DSE can't be reached from this host. Callers should then fall back
    to the symbols found in the price history instead of treating [] as "no equities".
    """
    try:
        return _load_trading_codes()
    except Exception:
        st.info("DSE's trading-code list could not be fetched from this host, so the symbols found in the "
                "price history are used instead.")
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


# A saved copy of the market history, committed to the repo, used when DSE can't be reached from this host.
# Create / refresh it from a machine that CAN reach DSE with:  python update_dse_snapshot.py
SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "dse_history.csv.gz"
SNAPSHOT_COLUMNS = ["date", "symbol", "Open", "High", "Low", "Close", "Volume", "Value", "YCP"]


def _normalize_raw(raw: pd.DataFrame) -> pd.DataFrame:
    """bdshare's output (date index, lower-case columns) -> a tidy long frame with exactly SNAPSHOT_COLUMNS."""
    df = raw.reset_index()
    if "date" not in df.columns and "index" in df.columns:
        df = df.rename(columns={"index": "date"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close",
        "volume": "Volume", "value": "Value", "ycp": "YCP",
    })
    for col in SNAPSHOT_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")
    return df[SNAPSHOT_COLUMNS]


def _reshape_history(long_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    Tidy long frame -> {symbol: DataFrame} with columns Open, High, Low, Close, Volume (+ Value, YCP when present),
    the same schema breadth.py / momentum.py / the pattern modules expect.
      "Value" = daily turnover as scraped from DSE's day-end archive, in millions of Taka (DSE's own convention;
                not independently verified against a live fetch from this environment).
      "YCP"   = DSE's own adjusted previous close (already reflects dividends / bonus shares); the Gap-Up Scan
                measures gaps against it and falls back to the previous Close if it is absent.
    """
    result: dict[str, pd.DataFrame] = {}
    for symbol, group in long_df.groupby("symbol"):
        df = group.sort_values("date").set_index("date")
        keep = [c for c in ["Open", "High", "Low", "Close", "Volume", "Value", "YCP"]
                if c in df.columns and (c in ("Open", "High", "Low", "Close", "Volume") or df[c].notna().any())]
        df = df[keep].dropna(subset=["Open", "High", "Low", "Close", "Volume"])
        if len(df) >= 15:  # need enough bars for MAs / RS lookback to be meaningful
            result[symbol] = df
    return result


@st.cache_data(ttl=60 * 30, show_spinner=False)
def _load_history_live(start_date: str, end_date: str) -> pd.DataFrame:
    """The whole market's history in ONE call. Raises on failure/empty, so a failure is never cached."""
    raw = get_historical_data(start=start_date, end=end_date, code="All Instrument")
    if raw is None or raw.empty:
        raise RuntimeError("DSE returned no rows for this date range")
    return _normalize_raw(raw)


@st.cache_data(show_spinner=False)
def _read_snapshot(path_str: str, mtime: float) -> pd.DataFrame:
    """Reads the snapshot file; `mtime` is only part of the cache key, so a replaced file is re-read."""
    return pd.read_csv(path_str, parse_dates=["date"])


def _load_snapshot():
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        return _read_snapshot(str(SNAPSHOT_PATH), SNAPSHOT_PATH.stat().st_mtime)
    except Exception as e:
        st.warning(f"The saved DSE snapshot ({SNAPSHOT_PATH.name}) could not be read: {e}")
        return None


def _explain_failure(err: Exception) -> str:
    text = str(err)
    if "Last error: None" in text:
        return ("DSE's servers answered but refused the request (a non-200 HTTP status, no network error), which "
                "almost always means they block this host's IP address; cloud hosts such as Streamlit Community "
                "Cloud are commonly blocked")
    if any(k in text for k in ("Name or service", "Max retries", "Timeout", "timed out", "Connection")):
        return "DSE could not be reached from this host (network error)"
    return text[:200]


def fetch_full_market_history(start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    """
    OHLCV history for the ENTIRE DSE market ({symbol: DataFrame}). Tries DSE live first; if that fails (e.g. DSE
    blocks this host), falls back to the saved snapshot in data/dse_history.csv.gz and says so. Returns {} only
    when neither works.
    """
    try:
        return _reshape_history(_load_history_live(start_date, end_date))
    except Exception as live_error:
        reason = _explain_failure(live_error)

    snap = _load_snapshot()
    if snap is not None and not snap.empty:
        sliced = snap[(snap["date"] >= pd.Timestamp(start_date)) & (snap["date"] <= pd.Timestamp(end_date))]
        if not sliced.empty:
            last = sliced["date"].max()
            age = (pd.Timestamp(end_date).normalize() - last.normalize()).days
            st.warning(
                f"Live DSE data could not be fetched: {reason}. Using the saved snapshot "
                f"(data/{SNAPSHOT_PATH.name}), which runs through {last.date()} ({age} day(s) before {end_date}). "
                "Refresh it by running update_dse_snapshot.py on a machine that can reach DSE, then commit the file."
            )
            return _reshape_history(sliced)

    st.error(
        f"Could not fetch DSE market history: {reason}. There is also no saved snapshot to fall back on. "
        "Fix: on a machine that can reach DSE (e.g. your desktop) run `python update_dse_snapshot.py`, commit "
        f"`data/{SNAPSHOT_PATH.name}` to your repo, and redeploy. (Optional: set a DSE_PROXY_URL secret for a "
        "proxy that DSE doesn't block.)"
    )
    return {}
