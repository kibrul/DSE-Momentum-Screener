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
from utils.volume_spike import build_spike_screen, suggest_threshold_from_history, DEFAULT_VOLUME_THRESHOLD_SHARES
from utils.live import (
    is_market_open, get_market_status_text, fetch_live_snapshot,
    compute_avg_volume, compute_live_breadth,
)
from utils.tendon_pattern import build_tendon_screen, DEFAULT_WINDOW as TENDON_DEFAULT_WINDOW
from utils.narrow_range_spike import build_narrow_range_spike_screen, DEFAULT_MAX_ABS_PCT as NR_DEFAULT_MAX_ABS_PCT
from utils.bullish_pin_bar import build_bullish_pin_bar_screen, DEFAULT_WINDOW as PIN_BAR_DEFAULT_WINDOW
from utils.pullback_pattern import (
    build_pullback_screen, pullback_chart_data,
    DEFAULT_MIN_RUN_DAYS as PB_DEFAULT_MIN_RUN, DEFAULT_MAX_RUN_DAYS as PB_DEFAULT_MAX_RUN,
    DEFAULT_MAX_PULLBACK_DAYS as PB_DEFAULT_MAX_PULLBACK, DEFAULT_TOUCH_WINDOW as PB_DEFAULT_TOUCH_WINDOW,
    DEFAULT_TOUCH_TOLERANCE_PCT as PB_DEFAULT_TOLERANCE,
)
from utils.anticipation_pattern import (
    build_anticipation_screen, anticipation_chart_data,
    DEFAULT_MIN_RUN_DAYS as AN_MIN_RUN, DEFAULT_MAX_RUN_DAYS as AN_MAX_RUN,
    DEFAULT_MIN_CONSOLIDATION_DAYS as AN_MIN_CONS, DEFAULT_MAX_CONSOLIDATION_DAYS as AN_MAX_CONS,
    DEFAULT_MAX_RANGE_PCT as AN_MAX_RANGE, DEFAULT_MAX_DROP_FROM_PEAK_PCT as AN_MAX_DROP,
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

    tab_breadth, tab_momentum, tab_vol_spike, tab_narrow_range, tab_tendon, tab_pin_bar, tab_pullback, tab_anticipation, tab_live = st.tabs(
        ["📊 Market Breadth (Stockbee)", "🚀 Momentum Screener (Qullamaggie)",
         "📈 Volume Spike Scan", "🔍 Narrow Range Volume Spike", "🪢 Tendon Pattern",
         "🔨 Bullish Pin Bar", "🎯 Pullback Pattern", "🔮 Anticipation", "🔴 Live"]
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
        st.subheader("Single-Day Volume Spike Scan")
        st.caption(
            "Flags stocks where at least ONE individual day within the lookback window hit the "
            "volume threshold — checked day by day, not as an average. A stock with one huge day and "
            "otherwise quiet activity still qualifies, even though its average over the window is low."
        )

        column = "Volume"

        sv1, sv2 = st.columns(2)
        with sv1:
            spike_window = st.number_input("Lookback window (trading days)", min_value=2, max_value=60, value=9)
        with sv2:
            threshold = st.number_input(
                "Volume threshold (single day, shares)", min_value=0,
                value=DEFAULT_VOLUME_THRESHOLD_SHARES, step=100_000, format="%d",
            )

        with st.expander("Where does this default come from? / Get a data-driven threshold instead"):
            st.markdown(
                "**Starting default** (2,000,000 shares) is an informed estimate from public DSE "
                "reporting, not a precise statistical study of the full archive — a highly liquid "
                "higher-priced stock (e.g. Square Pharma) has traded as few as ~1.15 million shares "
                "even on a big-turnover day, while low-priced, high-float names (e.g. Beximco) "
                "routinely trade 10-30+ million shares on active days.\n\n"
                "**For a real, data-driven number instead**, click below to compute actual percentiles "
                "from the history you just loaded — this reflects DSE's real numbers, not public "
                "news snippets."
            )
            if st.button("Compute empirical percentiles from loaded data"):
                suggestion = suggest_threshold_from_history(price_data, column=column)
                if not suggestion:
                    st.warning("No data available to compute percentiles from.")
                else:
                    st.json(suggestion)

        spike_df = build_spike_screen(price_data, column=column, window=int(spike_window), threshold=threshold)

        if spike_df.empty:
            st.warning(f"No symbols had a single day with volume ≥ {threshold:,.0f} shares within the last {spike_window} trading days.")
        else:
            st.success(f"{len(spike_df)} symbols had at least one qualifying spike day within the last {spike_window} trading days.")
            st.dataframe(spike_df, use_container_width=True, height=500)
            st.caption(
                "'Days Ago' counts back from the most recent bar in the window (0 = most recent day). "
                "'Spike Count' is how many separate days in the window individually cleared the threshold "
                "— a high count often just means the stock is inherently very liquid (e.g. Beximco), not "
                "that something unusual happened."
            )

    # ---------------- Narrow Range Volume Spike tab ----------------
    with tab_narrow_range:
        st.subheader("Narrow Range Volume Spike Scan")
        st.caption(
            "Flags a high-volume day where price barely moved — a possible quiet accumulation/"
            "distribution signal (size traded without pushing price around), as opposed to a spike that "
            "comes with a big directional move."
        )

        nr_column = "Volume"

        nr_mode_label = st.radio(
            "Pattern to look for",
            [
                "Spike day itself was narrow-range (high volume, that day didn't move much)",
                "Spike happened recently, and the most recent day is narrow-range now (quiet after the spike)",
            ],
            index=0,
            key="nr_mode_label",
        )
        nr_mode = "spike_day" if nr_mode_label.startswith("Spike day itself") else "most_recent_day"

        nr1, nr2 = st.columns(2)
        with nr1:
            nr_window = st.number_input("Lookback window (trading days)", min_value=2, max_value=60, value=9, key="nr_window")
            nr_max_pct = st.number_input(
                "Narrow-range band (± %, Open→Close)", min_value=0.1, max_value=20.0,
                value=NR_DEFAULT_MAX_ABS_PCT, step=0.1, key="nr_max_pct",
            )
        with nr2:
            nr_threshold = st.number_input(
                "Volume threshold (single day, shares)", min_value=0,
                value=DEFAULT_VOLUME_THRESHOLD_SHARES, step=100_000, format="%d", key="nr_threshold_vol",
            )

        st.caption(
            f"\"Narrow range\" means the day's Open→Close % change stayed within ±{nr_max_pct}% — "
            f"this is the day's own move, not the High-Low range (that's covered by the Momentum "
            f"tab's Tight Base / ADR% instead)."
        )

        nr_df = build_narrow_range_spike_screen(
            price_data, mode=nr_mode, column=nr_column, window=int(nr_window),
            threshold=nr_threshold, max_abs_pct=nr_max_pct,
        )

        if nr_df.empty:
            st.warning(
                f"No symbols matched this pattern within the last {nr_window} trading days. "
                f"Try widening the narrow-range band or lowering the threshold."
            )
        else:
            st.success(f"{len(nr_df)} symbols matched this pattern.")
            st.dataframe(nr_df, use_container_width=True, height=500)
            if nr_mode == "spike_day":
                st.caption(
                    "Shows the most recent day (within the window) that had BOTH a volume "
                    "spike AND a narrow Open→Close range on that same day. Prices are in BDT (৳)."
                )
            else:
                st.caption(
                    "Shows symbols where a spike occurred at some point in the window, and the "
                    "MOST RECENT day is now sitting in a narrow range — the spike and the quiet day "
                    "can be different days. Prices are in BDT (৳)."
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

    # ---------------- Bullish Pin Bar tab ----------------
    with tab_pin_bar:
        st.subheader("Bullish Pin Bar Scan")
        st.caption(
            "Looks for a bullish pin bar / hammer candle on any single day within the last few "
            "trading days: a small real body sitting near the top of the day's range, a long lower "
            "wick (rejection of the low), and volume confirming (that day's volume ≥ the prior day's). "
            "Same logic as the USA app's Bullish Pin Bar tab — pure candle geometry, currency-agnostic."
        )

        pb1, pb2 = st.columns(2)
        with pb1:
            pin_window = st.number_input(
                "Lookback window (trading days)", min_value=1, max_value=20,
                value=PIN_BAR_DEFAULT_WINDOW, key="pin_window",
            )
            pin_min_lower_wick = st.number_input(
                "Minimum lower wick (% of day's range)", min_value=20.0, max_value=95.0,
                value=66.67, step=1.0, key="pin_min_lower_wick",
            )
        with pb2:
            pin_max_upper_wick = st.number_input(
                "Maximum upper wick (% of day's range, keeps body near the top)", min_value=1.0,
                max_value=40.0, value=10.0, step=1.0, key="pin_max_upper_wick",
            )
            pin_max_body = st.number_input(
                "Maximum body size (% of day's range)", min_value=5.0, max_value=50.0,
                value=33.0, step=1.0, key="pin_max_body",
            )

        pb3, pb4 = st.columns(2)
        with pb3:
            pin_require_green = st.checkbox(
                "Require green body (Close > Open)", value=True, key="pin_require_green",
                help="Uncheck to also allow a red body, as long as the wick/body shape still qualifies.",
            )
        with pb4:
            pin_require_volume = st.checkbox(
                "Require volume ≥ prior day", value=True, key="pin_require_volume",
            )

        pin_df = build_bullish_pin_bar_screen(
            price_data, window=int(pin_window), min_lower_wick_pct=pin_min_lower_wick,
            max_upper_wick_pct=pin_max_upper_wick, max_body_pct=pin_max_body,
            require_green_body=pin_require_green, require_volume_confirmation=pin_require_volume,
        )

        if pin_df.empty:
            st.warning(
                "No symbols matched this pattern within the lookback window. Try loosening the "
                "wick/body thresholds or unchecking the volume/green-body requirements."
            )
        else:
            st.success(f"{len(pin_df)} symbols had a qualifying bullish pin bar within the last {pin_window} trading days.")
            st.dataframe(pin_df, use_container_width=True, height=500)
            st.caption(
                "'Days Ago' counts back from the most recent bar (0 = most recent day). "
                "'Lower Wick %' / 'Upper Wick %' / 'Body %' are each as a share of that day's total "
                "High-Low range, and sum to 100%. Prices are in BDT (৳)."
            )

    # ---------------- Pullback Pattern tab ----------------
    with tab_pullback:
        st.subheader("Pullback Pattern Scan")
        st.caption(
            "Condition 1: a strong, almost straight-up run of bullish candles (3-9 days by default). "
            "Condition 2: a pullback that then comes down and touches the 9-day or 18-day simple moving "
            "average of Close. Same logic as the USA app's Pullback tab; it is pure price geometry, so it is currency-agnostic."
        )

        pb_ma_options = {"Either 9MA or 18MA": "either", "9MA only": "9ma", "18MA only": "18ma"}

        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            pb_min_run = st.number_input("Min run length (days)", min_value=2, max_value=30,
                                         value=PB_DEFAULT_MIN_RUN, key="pb_min_run")
            pb_touch_window = st.number_input(
                "Touch must be within the last N bars", min_value=1, max_value=10,
                value=PB_DEFAULT_TOUCH_WINDOW, key="pb_touch_window",
                help="1 = the most recent bar only. Raise it to also catch touches from the last few days.",
            )
        with pc2:
            pb_max_run = st.number_input("Max run length (days)", min_value=2, max_value=30,
                                         value=PB_DEFAULT_MAX_RUN, key="pb_max_run")
            pb_tolerance = st.number_input(
                "Touch tolerance (% from the MA)", min_value=0.0, max_value=5.0,
                value=PB_DEFAULT_TOLERANCE, step=0.1, key="pb_tolerance",
                help="How close the candle's low must get to the MA to count as a touch.",
            )
        with pc3:
            pb_max_pullback = st.number_input(
                "Max pullback length (days after the peak)", min_value=1, max_value=15,
                value=PB_DEFAULT_MAX_PULLBACK, key="pb_max_pullback",
            )
            pb_ma_label = st.radio("Pullback must touch", list(pb_ma_options), key="pb_ma_choice")

        pk1, pk2, pk3 = st.columns(3)
        with pk1:
            pb_strict = st.checkbox(
                "Strict run: green candles, higher highs & higher lows", value=True, key="pb_strict",
                help="Uncheck to only require each candle to close above the prior close "
                     "(allows an occasional red-bodied candle in the run).",
            )
        with pk2:
            pb_hold = st.checkbox(
                "Touch candle must close at/above the MA", value=True, key="pb_hold",
                help="Uncheck to also allow a candle that wicks to the MA but closes below it.",
            )
        with pk3:
            pb_uptrend = st.checkbox(
                "Require 9MA above 18MA", value=False, key="pb_uptrend",
                help="Uptrend context, as in the reference chart. Off by default so the scan follows "
                     "the two conditions exactly.",
            )

        if pb_min_run > pb_max_run:
            st.error("Min run length can't be greater than max run length.")
        else:
            pb_df = build_pullback_screen(
                price_data, min_run_days=int(pb_min_run), max_run_days=int(pb_max_run),
                max_pullback_days=int(pb_max_pullback), touch_window=int(pb_touch_window),
                touch_tolerance_pct=pb_tolerance, ma_choice=pb_ma_options[pb_ma_label],
                strict_run=pb_strict, require_close_holds_ma=pb_hold, require_ma_uptrend=pb_uptrend,
            )

            if pb_df.empty:
                st.warning(
                    "No symbols matched. Try raising 'Touch must be within the last N bars', widening the "
                    "touch tolerance, or unchecking the strict-run / close-holds-the-MA options."
                )
            else:
                st.success(f"{len(pb_df)} symbols matched the pullback pattern.")
                st.dataframe(pb_df, use_container_width=True, height=450)
                st.caption(
                    "'Days Ago' = how many bars ago the MA touch happened (0 = latest bar). 'Run Gain %' is the "
                    "close-to-close gain over the straight-up run; 'Pullback Depth %' is the drop from the peak "
                    "bar's high to the pullback's lowest low. Prices are in BDT (৳)."
                )

                st.divider()
                st.subheader("Visual confirmation")
                pb_choice = st.selectbox("Preview Close with 9MA / 18MA for a matched symbol",
                                         pb_df["Ticker"].tolist(), key="pb_preview_ticker")
                if pb_choice:
                    st.line_chart(pullback_chart_data(price_data[pb_choice], bars=45), height=300)

    # ---------------- Anticipation tab ----------------
    with tab_anticipation:
        st.subheader("Anticipation Pattern Scan")
        st.caption(
            "Condition 1: price goes almost straight up for 3-9 days. Condition 2: it then moves sideways in a "
            "very narrow range for 3-9 days, still in progress on the latest bar. The tight base near the highs "
            "is the coil that anticipates the next move. Bases containing zero-volume (no-trade) days are "
            "skipped. Same logic as the USA app's Anticipation tab; it is pure price geometry, so it is currency-agnostic."
        )

        an1, an2, an3 = st.columns(3)
        with an1:
            an_min_run = st.number_input("Min run length (days)", min_value=2, max_value=30,
                                         value=AN_MIN_RUN, key="an_min_run")
            an_max_run = st.number_input("Max run length (days)", min_value=2, max_value=30,
                                         value=AN_MAX_RUN, key="an_max_run")
        with an2:
            an_min_cons = st.number_input("Min consolidation (days)", min_value=2, max_value=30,
                                          value=AN_MIN_CONS, key="an_min_cons")
            an_max_cons = st.number_input("Max consolidation (days)", min_value=2, max_value=30,
                                          value=AN_MAX_CONS, key="an_max_cons")
        with an3:
            an_max_range = st.number_input(
                "Max box range (%, tighter = narrower)", min_value=0.2, max_value=15.0,
                value=AN_MAX_RANGE, step=0.1, key="an_max_range",
                help="Whole consolidation box: highest High vs lowest Low.",
            )
            an_max_drop = st.number_input(
                "Max give-back from peak close (%)", min_value=0.0, max_value=15.0,
                value=AN_MAX_DROP, step=0.5, key="an_max_drop",
                help="Keeps the base up near the highs, so 'run, crash, then flat' doesn't match.",
            )

        an_strict = st.checkbox(
            "Strict run: green candles, higher highs & higher lows", value=True, key="an_strict",
            help="Uncheck to only require each candle to close above the prior close "
                 "(allows an occasional red-bodied candle in the run).",
        )

        if an_min_run > an_max_run or an_min_cons > an_max_cons:
            st.error("A minimum can't be greater than its maximum.")
        else:
            an_df = build_anticipation_screen(
                price_data, min_run_days=int(an_min_run), max_run_days=int(an_max_run),
                min_consolidation_days=int(an_min_cons), max_consolidation_days=int(an_max_cons),
                max_range_pct=an_max_range, max_drop_from_peak_pct=an_max_drop, strict_run=an_strict,
            )

            if an_df.empty:
                st.warning(
                    "No symbols matched. Try widening the box range, allowing a bigger give-back from the "
                    "peak, or unchecking the strict-run option."
                )
            else:
                st.success(f"{len(an_df)} symbols matched the anticipation pattern.")
                st.dataframe(an_df, use_container_width=True, height=450)
                st.caption(
                    "Sorted tightest base first. 'Consolidation Range %' is the whole box (highest High vs lowest "
                    "Low); 'Drop From Peak %' is how far the base's low sits below the peak close; 'To Breakout %' "
                    "is the distance from the last close up to the box high (the trigger level). Prices are in BDT (৳)."
                )

                st.divider()
                st.subheader("Visual confirmation")
                an_choice = st.selectbox("Preview Close with the consolidation box for a matched symbol",
                                         an_df["Ticker"].tolist(), key="an_preview_ticker")
                if an_choice:
                    row = an_df[an_df["Ticker"] == an_choice].iloc[0]
                    st.line_chart(
                        anticipation_chart_data(price_data[an_choice], int(row["Consolidation Days"]),
                                                float(row["Consolidation High"]), float(row["Consolidation Low"]),
                                                bars=40),
                        height=300,
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
