"""
DSE Momentum & Breadth Screener
Stockbee-style market breadth monitor + Qullamaggie-style momentum/breakout
screener for the Dhaka Stock Exchange. Free data via the `bdshare` package
(scrapes dsebd.org — DSE has no official free API).
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from utils.data import get_all_trading_codes, filter_equity_codes, fetch_full_market_history
from utils.breadth import compute_breadth_stats, breadth_regime_label
from utils.momentum import build_momentum_screen
from utils.live import (
    is_market_open, get_market_status_text, fetch_live_snapshot,
    compute_avg_volume, compute_live_breadth,
)

st.set_page_config(page_title="DSE Momentum & Breadth Screener", layout="wide")

st.title("📈 DSE Momentum & Breadth Screener")
st.caption(
    "Stockbee-style breadth monitor + Qullamaggie-style momentum/breakout screener for the "
    "Dhaka Stock Exchange — free data via bdshare (dsebd.org)."
)

# ---------------- Sidebar controls ----------------
with st.sidebar:
    st.header("Universe & History")
    equities_only = st.checkbox("Equities only (exclude mutual funds/bonds — heuristic)", value=True)

    lookback_days = st.selectbox(
        "History lookback",
        options=[90, 180, 365],
        format_func=lambda d: f"{d} days (~{d // 30} months)",
        index=1,
    )
    min_price = st.number_input("Min last close (BDT)", min_value=0.0, value=0.0, step=1.0)
    max_price = st.number_input("Max last close (BDT)", min_value=0.0, value=0.0, step=1.0,
                                 help="Leave at 0 for no upper limit.")

    st.header("Momentum Screen Settings")
    min_rs_rank = st.slider("Minimum RS Rank (percentile)", 50, 99, 80)

    run_button = st.button("Run Screen", type="primary", use_container_width=True)

# ---------------- Data fetch ----------------
if run_button:
    status = st.empty()
    status.info("Step 1/2 — Fetching DSE trading codes...")
    all_codes = get_all_trading_codes()
    codes_to_keep = filter_equity_codes(all_codes) if equities_only else all_codes
    status.info(f"Step 1/2 done — {len(all_codes)} total listed symbols, {len(codes_to_keep)} kept.")

    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)
    status.info(
        f"Step 2/2 — Downloading full-market history "
        f"({start_date.isoformat()} to {end_date.isoformat()}) in a single request..."
    )
    price_data = fetch_full_market_history(start_date.isoformat(), end_date.isoformat())

    if equities_only:
        price_data = {k: v for k, v in price_data.items() if k in set(codes_to_keep)}

    if min_price > 0 or max_price > 0:
        def _in_price_range(df):
            last_close = df["Close"].iloc[-1]
            if min_price > 0 and last_close < min_price:
                return False
            if max_price > 0 and last_close > max_price:
                return False
            return True
        price_data = {k: v for k, v in price_data.items() if _in_price_range(v)}

    status.success(f"Done — {len(price_data)} symbols loaded and ready to screen.")
    st.session_state["price_data"] = price_data
    st.session_state["fetched"] = True

if st.session_state.get("fetched"):
    price_data = st.session_state["price_data"]

    if not price_data:
        st.error(
            "No price data returned. This can mean dsebd.org is temporarily unreachable, "
            "or your filters excluded everything — try widening the price range or the lookback window."
        )
        st.stop()

    st.success(f"Screening {len(price_data)} DSE symbols.")

    tab_breadth, tab_momentum, tab_live = st.tabs(
        ["📊 Market Breadth (Stockbee)", "🚀 Momentum Screener (Qullamaggie)", "🔴 Live"]
    )

    # ---------------- Breadth tab ----------------
    with tab_breadth:
        stats = compute_breadth_stats(price_data)
        regime = breadth_regime_label(stats)

        st.subheader("Market Monitor")
        st.info(f"**Read:** {regime}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("% Up 4%+ Today", f"{stats['pct_up_4pct_today']}%")
        c2.metric("% Down 4%+ Today", f"{stats['pct_down_4pct_today']}%")
        c3.metric("Momentum Ratio (Up4/Down4)", stats["momentum_ratio"])
        c4.metric("Universe Size", stats["universe_size"])

        c5, c6, c7 = st.columns(3)
        c5.metric("% Up 25%+ (1 day)", f"{stats['pct_up_25pct_1d']}%")
        c6.metric("% Up 25%+ (4 days)", f"{stats['pct_up_25pct_4d']}%")
        c7.metric("% Up 25%+ (10 days)", f"{stats['pct_up_25pct_10d']}%")

        c8, c9 = st.columns(2)
        c8.metric("% Up 25%+ (Quarter)", f"{stats['pct_up_25pct_quarter']}%")
        c9.metric("% Up 50%+ (Quarter)", f"{stats['pct_up_50pct_quarter']}%")

        st.caption(
            "These mirror Stockbee's Market Monitor ratios, applied to the DSE. Note DSE's much smaller "
            "universe (~650 listed vs. thousands on NASDAQ+NYSE) means these percentages are noisier — "
            "a handful of stocks moving can swing the ratio more than in a bigger market."
        )

    # ---------------- Momentum tab ----------------
    with tab_momentum:
        st.subheader("Momentum Candidates")
        screen_df = build_momentum_screen(price_data, min_rs_rank=min_rs_rank)
        st.session_state["last_screen_df"] = screen_df

        if screen_df.empty:
            st.warning("No symbols met the RS Rank threshold. Try lowering it in the sidebar.")
        else:
            st.caption(
                f"{len(screen_df)} symbols with RS Rank ≥ {min_rs_rank}. "
                "Tight Base / Breakout Today / Episodic Pivot flag Qullamaggie-style setups. "
                "Prices are in BDT (৳)."
            )

            def highlight_flags(row):
                if row.get("Breakout Today"):
                    return ["background-color: #d4f4dd"] * len(row)
                if row.get("Episodic Pivot"):
                    return ["background-color: #fde9c8"] * len(row)
                return [""] * len(row)

            st.dataframe(
                screen_df.style.apply(highlight_flags, axis=1),
                use_container_width=True,
                height=500,
            )
            st.markdown("**Flag legend:** 🟩 Breakout today · 🟧 Episodic pivot (gap + volume surge)")

            st.divider()
            st.subheader("Setup filters")
            f1, f2 = st.columns(2)
            with f1:
                if st.checkbox("Show only Breakout Today"):
                    st.dataframe(screen_df[screen_df["Breakout Today"]], use_container_width=True)
            with f2:
                if st.checkbox("Show only Episodic Pivots"):
                    st.dataframe(screen_df[screen_df["Episodic Pivot"]], use_container_width=True)

    # ---------------- Live tab ----------------
    with tab_live:
        st.subheader("Live Market Snapshot")
        st.caption(
            "Unlike the US version, DSE's bulk endpoint returns every symbol's live price in one call, "
            "so this shows the whole market — no watchlist needed."
        )

        market_status = get_market_status_text()
        if is_market_open():
            st.success(f"🟢 DSE market status: {market_status}")
        else:
            st.warning(
                f"🔴 DSE market status: {market_status} — DSE trades Sunday-Thursday, ~10:00 AM-2:30 PM BDT. "
                "Data below is from the last session."
            )

        auto_refresh_on = st.checkbox("Auto-refresh", value=True, key="live_auto_refresh")
        refresh_minutes = st.select_slider("Auto-refresh interval", options=[1, 2, 3, 5], value=2)

        if auto_refresh_on and is_market_open():
            st_autorefresh(interval=refresh_minutes * 60 * 1000, key="live_autorefresh_timer")
        elif auto_refresh_on:
            st.caption("Auto-refresh paused — market is closed.")

        avg_vol = compute_avg_volume(price_data, window=10)
        with st.spinner("Fetching live snapshot for the full DSE market..."):
            snapshot = fetch_live_snapshot(avg_vol)

        if snapshot.empty:
            st.error("No live data returned — dsebd.org may be temporarily unreachable.")
        else:
            if equities_only:
                snapshot = snapshot[snapshot["Symbol"].isin(price_data.keys())]

            live_stats = compute_live_breadth(snapshot)
            lc1, lc2, lc3, lc4 = st.columns(4)
            lc1.metric("Symbols", live_stats["count"])
            lc2.metric("Advancers", live_stats["advancers"])
            lc3.metric("Decliners", live_stats["decliners"])
            lc4.metric("Up 4%+ / Down 4%+", f"{live_stats['up_4pct']} / {live_stats['down_4pct']}")

            snapshot_sorted = snapshot.sort_values("% Change", ascending=False).reset_index(drop=True)

            def highlight_live(row):
                if row.get("Breakout Now"):
                    return ["background-color: #d4f4dd"] * len(row)
                if row.get("Intraday EP"):
                    return ["background-color: #fde9c8"] * len(row)
                return [""] * len(row)

            st.dataframe(
                snapshot_sorted.style.apply(highlight_live, axis=1),
                use_container_width=True,
                height=500,
            )
            st.caption(
                "🟩 Breakout Now: at/near the day's high with RVOL ≥ 1.5x its 10-session average. "
                "🟧 Intraday EP: up 10%+ today with RVOL ≥ 2x. RVOL is computed from the historical "
                "data loaded in the sidebar (10-session average volume), so run the main screen first "
                "for RVOL to populate."
            )
            st.caption(f"Last updated: {pd.Timestamp.now(tz='Asia/Dhaka').strftime('%Y-%m-%d %H:%M:%S %Z')}")
else:
    st.info("Set your filters in the sidebar, then click **Run Screen**.")
