"""
Narrow-range volume/turnover spike screen for DSE: flags a stock that had a
single-day volume OR turnover spike within a recent window, WHERE the price
barely moved that day — a possible "quiet accumulation/distribution" signal
(size traded without pushing price around), as opposed to a spike that
comes with a big directional move.

Same two metrics as utils/volume_spike.py, for the same reason (DSE's
currency is Taka, so turnover is the more directly comparable measure
across differently priced stocks than raw share count):
  - "Value":  turnover in Taka (millions, DSE day-end archive convention) — recommended default
  - "Volume": raw share count

"Narrow range" means the day's Open-to-Close % change stayed within a tight
band (default ±1.9%) — NOT the High-Low range (that's covered by
utils/momentum.py's Tight Base / ADR% instead).

Two modes, same as the USA app's narrow_range_spike.py:
  - "spike_day": the day with the volume/turnover spike is ALSO the
    narrow-range day (high volume/turnover, but that day didn't move much).
  - "most_recent_day": a spike happened somewhere in the window, and
    separately, the MOST RECENT day is currently narrow-range — the spike
    day and the quiet day can be different days.
"""
import pandas as pd

from utils.volume_spike import (
    DEFAULT_TURNOVER_THRESHOLD_MN_TAKA, DEFAULT_VOLUME_THRESHOLD_SHARES,
    mn_taka_to_crore,
)

DEFAULT_WINDOW = 9
DEFAULT_MAX_ABS_PCT = 1.9  # narrow-range band: Open-to-Close % change within [-1.9%, +1.9%]


def _default_threshold(column: str) -> float:
    return DEFAULT_TURNOVER_THRESHOLD_MN_TAKA if column == "Value" else DEFAULT_VOLUME_THRESHOLD_SHARES


def open_to_close_pct(df: pd.DataFrame, idx: int) -> float:
    """Open-to-Close % change for the row at integer position `idx` in df."""
    row = df.iloc[idx]
    if row["Open"] == 0 or pd.isna(row["Open"]) or pd.isna(row["Close"]):
        return float("nan")
    return (row["Close"] / row["Open"] - 1) * 100


def is_narrow_range_day(df: pd.DataFrame, idx: int, max_abs_pct: float = DEFAULT_MAX_ABS_PCT) -> bool:
    """True if the day at position `idx` had an Open-to-Close % change within [-max_abs_pct, +max_abs_pct]."""
    pct = open_to_close_pct(df, idx)
    if pd.isna(pct):
        return False
    return abs(pct) <= max_abs_pct


def find_spike_day_narrow_range(df: pd.DataFrame, column: str = "Value", window: int = DEFAULT_WINDOW,
                                 threshold: float = None, max_abs_pct: float = DEFAULT_MAX_ABS_PCT) -> dict | None:
    """
    Mode "spike_day": scans the last `window` days for a day that BOTH had
    `column` >= threshold AND was itself a narrow-range day. Returns the
    most recent such day, or None if no day qualifies.
    """
    if threshold is None:
        threshold = _default_threshold(column)
    if len(df) < 1 or column not in df.columns:
        return None

    recent = df.tail(window)
    for pos in range(len(recent) - 1, -1, -1):  # most recent first
        row = recent.iloc[pos]
        if row[column] >= threshold:
            global_idx = len(df) - len(recent) + pos
            pct = open_to_close_pct(df, global_idx)
            if pd.notna(pct) and abs(pct) <= max_abs_pct:
                return {
                    "date": recent.index[pos],
                    "value": row[column],
                    "open_to_close_pct": round(pct, 2),
                    "days_ago": len(recent) - pos - 1,
                }
    return None


def find_recent_spike_then_quiet(df: pd.DataFrame, column: str = "Value", window: int = DEFAULT_WINDOW,
                                  threshold: float = None, max_abs_pct: float = DEFAULT_MAX_ABS_PCT) -> dict | None:
    """
    Mode "most_recent_day": checks whether (a) ANY day in the last `window`
    days had `column` >= threshold, AND (b) the MOST RECENT day is itself a
    narrow-range day. The spike day and the narrow-range day can differ.
    """
    if threshold is None:
        threshold = _default_threshold(column)
    if len(df) < 2 or column not in df.columns:
        return None

    recent = df.tail(window)
    spike_mask = recent[column] >= threshold
    if not spike_mask.any():
        return None

    last_idx = len(df) - 1
    last_pct = open_to_close_pct(df, last_idx)
    if pd.isna(last_pct) or abs(last_pct) > max_abs_pct:
        return None

    spike_rows = recent[spike_mask]
    most_recent_spike_date = spike_rows.index[-1]
    most_recent_spike_value = spike_rows[column].iloc[-1]
    days_since_spike = list(recent.index).index(df.index[last_idx]) - list(recent.index).index(most_recent_spike_date)

    return {
        "date": df.index[last_idx],
        "last_day_open_to_close_pct": round(last_pct, 2),
        "spike_date": most_recent_spike_date,
        "spike_value": most_recent_spike_value,
        "days_since_spike": days_since_spike,
    }


def build_narrow_range_spike_screen(price_data: dict[str, pd.DataFrame], mode: str = "spike_day",
                                     column: str = "Value", window: int = DEFAULT_WINDOW,
                                     threshold: float = None, max_abs_pct: float = DEFAULT_MAX_ABS_PCT) -> pd.DataFrame:
    """
    Scans the full universe for the narrow-range volume/turnover spike pattern.
    mode: "spike_day" or "most_recent_day". column: "Value" (turnover, Taka) or "Volume" (shares).
    """
    if threshold is None:
        threshold = _default_threshold(column)
    finder = find_spike_day_narrow_range if mode == "spike_day" else find_recent_spike_then_quiet

    rows = []
    for symbol, df in price_data.items():
        if column not in df.columns:
            continue
        result = finder(df, column=column, window=window, threshold=threshold, max_abs_pct=max_abs_pct)
        if result is None:
            continue

        if mode == "spike_day":
            row = {
                "Symbol": symbol,
                "Spike Date": result["date"].strftime("%Y-%m-%d") if hasattr(result["date"], "strftime") else str(result["date"]),
                "Days Ago": result["days_ago"],
                f"{column} on Spike Day": round(float(result["value"]), 2),
                "Open→Close % (Spike Day)": result["open_to_close_pct"],
                "Last Close (BDT)": round(df["Close"].iloc[-1], 2),
            }
            if column == "Value":
                row["Turnover on Spike Day (crore)"] = round(mn_taka_to_crore(float(result["value"])), 2)
        else:
            row = {
                "Symbol": symbol,
                "Most Recent Date": result["date"].strftime("%Y-%m-%d") if hasattr(result["date"], "strftime") else str(result["date"]),
                "Open→Close % (Most Recent Day)": result["last_day_open_to_close_pct"],
                "Spike Date": result["spike_date"].strftime("%Y-%m-%d") if hasattr(result["spike_date"], "strftime") else str(result["spike_date"]),
                f"Spike {column}": round(float(result["spike_value"]), 2),
                "Days Since Spike": result["days_since_spike"],
                "Last Close (BDT)": round(df["Close"].iloc[-1], 2),
            }
            if column == "Value":
                row["Spike Turnover (crore)"] = round(mn_taka_to_crore(float(result["spike_value"])), 2)
        rows.append(row)

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    sort_col = f"{column} on Spike Day" if mode == "spike_day" else f"Spike {column}"
    return out.sort_values(sort_col, ascending=False).reset_index(drop=True)
