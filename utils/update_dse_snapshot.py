"""
update_dse_snapshot.py - save the DSE market history to data/dse_history.csv.gz.

WHY: dse.com.bd / dsebd.org refuse requests from many cloud datacenter IPs (including Streamlit Community Cloud),
so the deployed app can't download DSE data itself. Run this script on a machine that CAN reach DSE (for example
your own desktop), commit the file it writes, and the deployed app falls back to it automatically.

USAGE (from the project folder):
    python update_dse_snapshot.py              # last 400 days, merged into any existing snapshot
    python update_dse_snapshot.py --days 800   # keep a longer history

THEN publish it:
    git add data/dse_history.csv.gz
    git commit -m "Update DSE snapshot"
    git push

Run it again after each trading day (DSE publishes day-end data after the close) to keep the snapshot fresh. New
days are merged into the existing file, so the history only grows up to --days.
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

import pandas as pd

from utils import data as D  # also gives bdshare's session the browser-like headers / optional proxy


def main() -> int:
    parser = argparse.ArgumentParser(description="Save DSE market history to data/dse_history.csv.gz")
    parser.add_argument("--days", type=int, default=400, help="how many calendar days of history to keep (default 400)")
    args = parser.parse_args()

    end = date.today()
    start = end - timedelta(days=args.days)
    print(f"Fetching DSE full-market history {start.isoformat()} to {end.isoformat()} (one request, may take a minute)...")

    try:
        raw = D.get_historical_data(start=start.isoformat(), end=end.isoformat(), code="All Instrument")
    except Exception as e:
        print(f"\nFAILED to fetch from DSE: {e}\n"
              "This machine can't reach DSE either, so nothing was written. Existing snapshot left untouched.")
        return 1
    if raw is None or raw.empty:
        print("\nDSE returned no rows. Existing snapshot left untouched.")
        return 1

    fresh = D._normalize_raw(raw)
    print(f"Downloaded {len(fresh):,} rows for {fresh['symbol'].nunique()} symbols, "
          f"{fresh['date'].min().date()} to {fresh['date'].max().date()}.")

    path = D.SNAPSHOT_PATH
    if path.exists():
        try:
            old = pd.read_csv(path, parse_dates=["date"])
            fresh = pd.concat([old, fresh], ignore_index=True)
            print(f"Merged with the existing snapshot ({len(old):,} rows).")
        except Exception as e:
            print(f"Existing snapshot unreadable ({e}); replacing it.")

    fresh = fresh.drop_duplicates(subset=["date", "symbol"], keep="last")        # newest download wins
    cutoff = fresh["date"].max() - pd.Timedelta(days=args.days)
    fresh = fresh[fresh["date"] >= cutoff].sort_values(["symbol", "date"]).reset_index(drop=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    fresh.to_csv(path, index=False, compression="gzip", float_format="%.4f", date_format="%Y-%m-%d")

    newest = fresh["date"].max().date()
    print(f"\nSaved {len(fresh):,} rows, {fresh['symbol'].nunique()} symbols, "
          f"{fresh['date'].min().date()} to {newest}  ->  {path}  ({path.stat().st_size / 1e6:.1f} MB)")
    if (date.today() - newest).days > 5:
        print(f"WARNING: the newest day in the data is {newest}, more than 5 days ago. Check DSE is publishing "
              "day-end data, or that this wasn't a holiday stretch.")
    print("\nNext, publish it so the deployed app can use it:\n"
          "    git add data/dse_history.csv.gz\n"
          '    git commit -m "Update DSE snapshot"\n'
          "    git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
