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
from utils.volume_spike import (
    build_spike_screen, suggest_threshold_from_history,
    DEFAULT_TURNOVER_THRESHOLD_MN_TAKA, DEFAULT_VOLUME_THRESHOLD_SHARES,
    mn_taka_to_crore, crore_to_mn_taka,
)
from utils.live import (
    is_market_open, get_market_status_text, fetch_live_snapshot,
    compute_avg_volume, compute_live_breadth,
)
from utils.tendon_pattern import build_tendon_screen, DEFAULT_WINDOW as TENDON_DEFAULT_WINDOW

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
    min_price = st.number_input("Min last close (BDT)", min_value=6.0, value=6.0, step=1.0)
    max_price = st.number_input("Max last close (BDT)", min_value=9000.0, value=9000.0, step=1.0,
                                 help="Leave at 0 for no upper limit.")

    st.header("Momentum Screen Settings")
    min_rs_rank = st.slider("Minimum RS Rank (percentile)", 50, 99, 60)

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

    tab_breadth, tab_momentum, tab_vol_spike, tab_tendon, tab_live = st.tabs(
        ["📊 Market Breadth (Stockbee)", "🚀 Momentum Screener (Qullamaggie)",
         "📈 Volume/Turnover Spike Scan", "🪢 Tendon Pattern", "🔴 Live"]
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

    # ---------------- Volume/Turnover Spike tab ----------------
    with tab_vol_spike:
        st.subheader("Single-Day Volume/Turnover Spike Scan")
        st.caption(
            "Flags stocks where at least ONE individual day within the lookback window hit the "
            "threshold — checked day by day, not as an average. A stock with one huge day and "
            "otherwise quiet activity still qualifies, even though its average over the window is low."
        )

        metric_choice = st.radio(
            "Metric",
            ["Turnover (Taka) — recommended", "Share Volume"],
            index=0,
            help="Turnover is denominated in Taka and is directly comparable across differently "
                 "priced stocks. Share volume is raw share count, which favors low-priced stocks.",
        )
        column = "Value" if metric_choice.startswith("Turnover") else "Volume"

        sv1, sv2 = st.columns(2)
        with sv1:
            spike_window = st.number_input("Lookback window (trading days)", min_value=2, max_value=60, value=9)
        with sv2:
            if column == "Value":
                threshold_crore = st.number_input(
                    "Turnover threshold (single day, Tk crore)", min_value=0.0,
                    value=mn_taka_to_crore(DEFAULT_TURNOVER_THRESHOLD_MN_TAKA), step=1.0,
                )
                threshold = crore_to_mn_taka(threshold_crore)
            else:
                threshold = st.number_input(
                    "Volume threshold (single day, shares)", min_value=0,
                    value=DEFAULT_VOLUME_THRESHOLD_SHARES, step=100_000, format="%d",
                )

        with st.expander("Where do these defaults come from? / Get a data-driven threshold instead"):
            st.markdown(
                "**Starting defaults** (Tk 10 crore turnover / 2,000,000 shares) come from recent public "
                "DSE reporting, not a precise statistical study of the full archive:\n"
                "- Recent DSE weekly recaps show even the **top 3 most actively traded stocks** on DSE "
                "averaging only ~Tk 25-37 crore/day turnover.\n"
                "- DSE's average daily **market-wide** turnover (all ~650 stocks combined) has ranged "
                "roughly Tk 472-997 crore across 2023-2026 (source: DSE annual/FY recaps via The "
                "Business Standard, BSS).\n"
                "- Tk 10 crore for a single stock in a single day sits comfortably above typical daily "
                "turnover for most DSE names, while remaining reachable during a genuine spike.\n\n"
                "**For a real, data-driven number instead of these estimates**, click below to compute "
                "actual percentiles from the history you just loaded (up to the lookback window you "
                "picked in the sidebar, e.g. 1 year) — this reflects DSE's real numbers, not public "
                "news snippets."
            )
            if st.button("Compute empirical percentiles from loaded data"):
                suggestion = suggest_threshold_from_history(price_data, column=column)
                if not suggestion:
                    st.warning("No data available to compute percentiles from.")
                else:
                    st.json(suggestion)
                    if column == "Value":
                        st.caption(
                            f"Based on {suggestion['sample_size']} stock-days loaded. "
                            f"p95 ≈ Tk {suggestion.get('p95_crore')} crore, "
                            f"p99 ≈ Tk {suggestion.get('p99_crore')} crore — consider setting your "
                            f"threshold near the p95-p99 range to flag genuinely unusual days rather "
                            f"than routine activity from the most liquid names."
                        )

        spike_df = build_spike_screen(price_data, column=column, window=int(spike_window), threshold=threshold)

        if spike_df.empty:
            label = f"Tk {mn_taka_to_crore(threshold):,.1f} crore" if column == "Value" else f"{threshold:,.0f} shares"
            st.warning(f"No symbols had a single day with {metric_choice.split(' —')[0].lower()} ≥ {label} within the last {spike_window} trading days.")
        else:
            st.success(f"{len(spike_df)} symbols had at least one qualifying spike day within the last {spike_window} trading days.")
            st.dataframe(spike_df, use_container_width=True, height=500)
            st.caption(
                "'Days Ago' counts back from the most recent bar in the window (0 = most recent day). "
                "'Spike Count' is how many separate days in the window individually cleared the threshold "
                "— a high count often just means the stock is inherently very liquid (e.g. Beximco), not "
                "that something unusual happened."
            )

    # ---------------- Tendon Pattern tab ----------------
    with tab_tendon:
        st.subheader("Tendon Pattern Scan")
        st.caption(
            "Looks for a V/U-shaped decline-then-recovery in the 9-day SMA of Close within a rolling "
            "window, followed AFTER the recovery by a flat, sideways consolidation — the shape: "
            "rise → peak → rounded trough → recovery to a new high → flat tail. Same logic as the "
            "USA app's Tendon tab — this is a price-shape pattern, currency-agnostic."
        )

        tc1, tc2 = st.columns(2)
        with tc1:
            tendon_window = st.number_input(
                "Rolling window (trading days, ~3 months ≈ 63)", min_value=20, max_value=252,
                value=TENDON_DEFAULT_WINDOW, key="tendon_window",
            )
            tendon_min_decline = st.number_input(
                "Minimum decline into trough (%)", min_value=1.0, max_value=80.0, value=8.0, step=1.0,
                key="tendon_min_decline",
            )
            tendon_min_recovery = st.number_input(
                "Minimum recovery out of trough (%)", min_value=1.0, max_value=200.0, value=8.0, step=1.0,
                key="tendon_min_recovery",
            )
        with tc2:
            tendon_consolidation_window = st.number_input(
                "Consolidation tail length (trading days)", min_value=3, max_value=60, value=12,
                key="tendon_consolidation_window",
            )
            tendon_max_range = st.number_input(
                "Max consolidation range (%, tighter = flatter)", min_value=0.5, max_value=30.0,
                value=5.0, step=0.5, key="tendon_max_range",
            )

        tendon_df, tendon_matches = build_tendon_screen(
            price_data, window=int(tendon_window), min_decline_pct=tendon_min_decline,
            min_recovery_pct=tendon_min_recovery, consolidation_window=int(tendon_consolidation_window),
            max_consolidation_range_pct=tendon_max_range,
        )

        if tendon_df.empty:
            st.warning(
                "No symbols matched this pattern. Try loosening the decline/recovery minimums or "
                "widening the consolidation range. Note: DSE's smaller universe (~650 stocks vs. "
                "thousands on NASDAQ+NYSE) means fewer matches are expected even when the pattern "
                "is genuinely present in the market."
            )
        else:
            st.success(f"{len(tendon_df)} symbols matched the Tendon pattern.")
            st.dataframe(tendon_df, use_container_width=True, height=400)
            st.caption(
                "'Consolidation Range %' is how tight the flat tail is (lower = flatter). "
                "'Days Since Peak' is how many trading days ago the recovery peak occurred. "
                "Prices are in BDT (৳)."
            )

            st.divider()
            st.subheader("Visual confirmation")
            chosen_symbol = st.selectbox("Preview MA9 for a matched symbol", tendon_df["Ticker"].tolist())
            if chosen_symbol:
                match = tendon_matches[chosen_symbol]
                ma_series = match["ma9_series"]
                chart_df = pd.DataFrame({"MA9": ma_series})
                st.line_chart(chart_df, height=300)
                st.caption(
                    f"Trough: {match['trough_date'].strftime('%Y-%m-%d') if hasattr(match['trough_date'], 'strftime') else match['trough_date']} · "
                    f"Recovery peak: {match['post_peak_date'].strftime('%Y-%m-%d') if hasattr(match['post_peak_date'], 'strftime') else match['post_peak_date']} · "
                    f"Decline {match['decline_pct']}% · Recovery {match['recovery_pct']}% · "
                    f"Consolidation range {match['consolidation_range_pct']}%"
                )

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
