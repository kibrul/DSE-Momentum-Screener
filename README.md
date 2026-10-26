# DSE Momentum & Breadth Screener

Stockbee-style market breadth monitor + Qullamaggie-style momentum/breakout screener for the **Dhaka Stock Exchange (DSE)**, built on the free `bdshare` package (no API key needed).

## Setup

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## How this differs from the US (NASDAQ/NYSE) version

DSE has no official free API. Data here comes from **`bdshare`**, a PyPI package that crawls DSE's own site, [dsebd.org](https://dsebd.org). The good news: DSE only lists ~650 instruments total (vs. thousands on NASDAQ+NYSE), and `bdshare` can return the **entire market's** history or live prices in a **single request** — no per-ticker chunked downloading, no rate-limit dance. That makes this version simpler and faster than the US one.

- **Historical screen**: one call to `get_historical_data(start, end, code="All Instrument")` pulls OHLCV for every listed symbol over your chosen date range at once.
- **Live tab**: one call to `get_current_trade_data()` pulls every symbol's latest price at once — so unlike the US app, there's no need to scope this to a small watchlist.
- **Market hours**: DSE trades **Sunday–Thursday**, ~10:00 AM–2:30 PM Bangladesh Time (BDT) — the opposite weekend convention from US markets. Rather than hardcoding this, the Live tab calls `bdshare`'s `get_market_status()`, which reads DSE's site directly for the actual current status.

## Volume Spike tab

Flags stocks where at least **one individual day** within a lookback window (default 9 trading days) hit a share-volume threshold — checked day by day, not as an average. A stock with one huge day buried among otherwise-quiet days still gets caught, even though its average over the same window looks unremarkable.

**Starting default: 2,000,000 shares in a single day.** An informed estimate from public reporting, not a precise statistical study of DSE's full archive (`dsebd.org` wasn't reachable from the sandbox this was built in) — grounded in reporting showing a highly liquid higher-priced stock (Square Pharma) traded only ~1.15 million shares even on a big-turnover day, while low-priced, high-float names (Beximco) routinely trade 10-30+ million shares on active days.

**For a real, data-driven threshold** instead of this estimate, use the "Compute empirical percentiles from loaded data" button in the tab's expander — it calculates actual percentiles (p90/p95/p99) from whatever history you loaded via the sidebar. Since your machine can reach `dsebd.org` directly (unlike the sandbox this was built in), this is the more trustworthy number for your own use.

Note: `utils/volume_spike.py` still supports a Taka-turnover metric internally (used by the earlier design), but the UI now only exposes Share Volume, per preference.

## Narrow Range Volume Spike tab

Same pattern as the USA app's Narrow Range Volume Spike tab: flags a high-volume day where price barely moved — a possible quiet accumulation/distribution signal, as opposed to a spike that comes with a big directional move (already covered by the regular Volume Spike Scan tab).

Uses **Share Volume** only (default threshold: 2,000,000 shares), same as the Volume Spike Scan tab.

"Narrow range" means the day's **Open-to-Close** % change stayed within a tight band (default ±1.9%) — not the High-Low range (covered by the Momentum tab's Tight Base / ADR% instead).

Two selectable modes:
- **Spike day itself was narrow-range**: the day with the volume spike is also the day that didn't move much.
- **Spike happened recently, most recent day is narrow-range now**: a spike occurred somewhere in the lookback window, and the most recent day is currently sitting in a tight range — spike day and quiet day can differ.

All parameters (mode, lookback window, volume threshold, narrow-range band) are adjustable in the tab.

## Tendon Pattern tab

Identical logic to the USA app's Tendon tab — this is a pure price-shape pattern (based on the 9-day SMA of Close), so it's currency-agnostic and needed no DSE-specific changes. Looks for: rise → peak → rounded V/U trough → recovery to a new high → flat sideways tail, within a rolling window (default ~63 trading days ≈ 3 months).

All five parameters (window, min decline %, min recovery %, consolidation tail length, max consolidation range %) are adjustable in the tab, with a "Visual confirmation" chart of the matched symbol's MA9 line.

**Note on match count**: DSE's much smaller universe (~650 stocks vs. thousands on NASDAQ+NYSE) means you should expect far fewer matches even when the pattern is genuinely present in the market — don't read a low count as the scanner being broken.

## Bullish Pin Bar tab

Identical logic to the USA app's Bullish Pin Bar tab — pure candle geometry (Open/High/Low/Close), so it's currency-agnostic and needed no DSE-specific changes. Scans the last few trading days (default 3) for a bullish pin bar / hammer candle on any single day within that window:
- **Small real body near the top** of the day's range (max upper wick 10% of range by default).
- **Long lower wick** — at least two-thirds (66.67%) of the day's total range by default.
- **Volume confirmation** — that day's volume ≥ the prior day's (toggle-able).
- **Green body** (Close > Open) required by default, can be unchecked.

All thresholds are adjustable in the tab. Tested at DSE-scale (Taka) prices with the extra `Value` (turnover) column present — unaffected, since the pattern only reads Open/High/Low/Close/Volume.

## Pullback Pattern tab

Finds the "3-9 day straight up, then pullback to the 9 or 18 MA" setup. Two conditions:

1. **Run**: bullish candles going almost straight up for 3-9 days (adjustable). *Strict* mode (default) needs every run candle to be green with a higher high and a higher low than the candle before it; unchecking it relaxes that to "closes above the prior close", which allows an occasional red-bodied candle. The run is the unbroken streak ending at the peak bar, and the candle right after the peak must not continue it (so an 11-day run can't pass as a 9-day one).
2. **Pullback**: after the peak, price comes down (the pullback's lowest low drops below the peak candle's low) and a candle reaches the **9-period or 18-period simple moving average of Close**. A "touch" means the candle's low came down to the MA (within a tolerance, default 0.5%) and, by default, the candle still closed at/above it, so a decisive break below the MA doesn't count.

Settings in the tab: run length range, max days between peak and touch (default 5), how many of the latest bars may hold the touch (default 1 = the latest bar only), touch tolerance, which MA (either / 9MA only / 18MA only), strict run, close-holds-the-MA, and an optional **Require 9MA above 18MA** (uptrend context as in the reference chart; off by default so the scan follows the two conditions exactly). A "Visual confirmation" chart plots Close with MA9 and MA18 for any matched symbol.

If the match list is too long, tighten it with a higher minimum run length, the 9MA > 18MA option, or a smaller touch tolerance.

Tested against constructed cases for every rule (match, run too short/long, pullback stopping short of the MA, closing through the MA, red candle inside the run, touch too old, touch too many days after the peak, shallow dip that never pulls back, zero-price bad data, a downtrend bounce with and without the 9MA > 18MA option) and by running both real apps headlessly with injected data. Not yet checked against live market data, since the sandbox it was built in can't reach Yahoo Finance or dsebd.org. The logic is pure OHLC/moving-average geometry, so it is identical to the USA app's and needs no BDT-specific changes.

## Anticipation tab

Finds the "3-9 day straight up, then narrow-range sideways" coil, still in progress on the latest bar. Two conditions:

1. **Run**: bullish candles going almost straight up for 3-9 days (adjustable). *Strict* mode (default) needs every run candle to be green with a higher high and a higher low than the one before; unchecking it relaxes that to "closes above the prior close", which allows an occasional red-bodied candle. The run must end at the peak bar.
2. **Consolidation**: the most recent 3-9 candles after the peak move sideways in a very narrow box. The box is the whole range, highest High vs lowest Low, and must be within **2.5%** by default. A second check, **max give-back from the peak close** (default 3%), keeps the base up near the highs so "run, crash, then go flat" doesn't match.

The consolidation must run right up to the latest bar, so a base that has already broken out is not listed. Bases containing zero-volume (no-trade) days or zero-price rows are skipped, since a frozen price isn't a real base. The table is sorted tightest base first and includes the box high/low and "To Breakout %" (distance from the last close to the box high, the trigger level). A "Visual confirmation" chart draws Close with the box high/low over the base.

Tested against constructed cases for every rule (match, base too short/long, box too wide, run too short/long, base sitting well below the peak, zero-volume day, zero-price data, red candle in the run, a first base candle that ticks up and extends the run, a breakout candle on the latest bar, too little history, no Volume column) and by running the real app headlessly with injected data. Not yet checked against live market data, since the sandbox it was built in can't reach Yahoo Finance or dsebd.org. The logic is pure OHLC geometry, so it is identical to the USA app's with no BDT-specific changes; the zero-volume guard matters most here, because thinly traded DSE stocks can have frozen-price days.

## Gap-Up Scan tab

Finds symbols that **gapped up ≥ 9% in a single day on big volume**, on any day in the last month, or in the latest session only.

- **Gap** = the day's **Open** versus DSE's **YCP**, the exchange-adjusted previous close, which already reflects dividends and bonus shares. Measuring against the raw previous close would miss real gaps on those dates (for example a 1:1 bonus halves the price, so the raw comparison reads about -50%). If YCP is missing the previous close is used. Default minimum 9%.
- **Big volume** = that day's share volume is at least **RVOL** times its average over the 20 *traded* days before it (default 2.0x), plus an optional minimum share count (default off). Zero-volume "no-trade" days are left out of that average, so a thinly traded stock can't look like it has a volume spike just because it often doesn't trade. A stock needs at least 10 traded days in the prior 20 to get an RVOL, and the gap day itself must have traded.
- **Scope**: "Any day in the last N trading days" (default 21, about one month) or "Current day only (latest session)".
- **One row per symbol**, showing its most recent qualifying day, newest first, with the gap %, open-to-close change on the gap day, volume, RVOL, **Since Gap %** (follow-through) and the number of qualifying days in range. A chart shows Close with the reference close as a flat line, so you can see whether the gap is holding.

**"Current day" on DSE:** this scan reads DSE's day-end archive, which is published after the close, and DSE's live feed (`get_current_trade_data`) has **no opening price**, so a gap can't be measured while the session is running. "Current day" means the latest completed session in the loaded data. The tab says so while the market is open; for intraday movers use the Live tab (its "Intraday EP" flag).

**Price limits:** DSE caps how far a stock can move in a day, and that limit has changed over time, so a 9% opening gap may be unreachable when a tighter limit is in force. When a scan comes back empty, the tab shows the **largest opening gap-up actually found** in the range (ignoring volume), so you can lower "Min gap up" to a level that exists.

`utils/data.py` now keeps the `YCP` column (the earlier version dropped it). Update both files together for the exact YCP-based gap; with an older `data.py` the scan still runs but falls back to the previous close.

Tested against constructed cases for every rule (gap too small, volume too light, below an absolute minimum, gap older than the window, latest-session mode, two gap days, zero/NaN open data, a gap that sells off, too little volume history, a bonus-share YCP adjustment, a thinly traded stock, a zero-volume gap day, the largest-gap helper) and by running the real app headlessly with planted data. Not yet checked against live dsebd.org data, since the sandbox it was built in can't reach it.

## Running on Streamlit Community Cloud (DSE refuses cloud servers)

If the deployed app shows *"Could not fetch DSE market history ... Failed to GET after 3 retries ... Last error: None"* but it works on your own computer, DSE's servers are answering every request with a non-200 HTTP status (that is what `Last error: None` means: no network error, just a refusal). They are blocking the cloud host's IP address, so no code change can make the deployed app download directly. The fix is a **saved snapshot** that you create where DSE works and commit to the repo:

1. **On your desktop** (where the app already works), from the project folder:
   ```bash
   python update_dse_snapshot.py
   ```
   This downloads the whole market's history and writes `data/dse_history.csv.gz` (roughly 5-10 MB for the default 400 days; `--days 800` keeps longer). It merges into any existing snapshot, so history only grows, and it never overwrites the file if the download fails.
2. **Commit and push it** (make sure `data/` and `*.gz` aren't in your `.gitignore`):
   ```bash
   git add data/dse_history.csv.gz
   git commit -m "Update DSE snapshot"
   git push
   ```
3. Streamlit Cloud redeploys, and whenever live DSE data can't be fetched the app **falls back to the snapshot automatically**, with a warning that states the snapshot's last date and how old it is.
4. **Repeat after each trading day** you want fresh data (DSE publishes day-end data after the close). The screens only know what is in the snapshot, so they are as current as your last update.

What to expect on the cloud: every screen (Breadth, Momentum, Volume Spike, Narrow Range, Tendon, Pin Bar, Pullback, Anticipation, Gap-Up) works from the snapshot. The **Live tab** needs live DSE data, so it stays empty there unless you use a proxy (below); running the app on your own computer keeps it fully live.

Also in this version:
- bdshare's HTTP session now sends ordinary **browser headers** (it used to identify itself as `bdshare/2.0`, which web firewalls often refuse). This is best effort: it can help if DSE filters by user agent, but it can't beat an IP-address block.
- **Optional proxy:** set a `DSE_PROXY_URL` secret (Streamlit Cloud: App settings, then Secrets, e.g. `DSE_PROXY_URL = "http://user:pass@host:port"`) or environment variable to route DSE requests through a proxy that DSE doesn't block, ideally one located in Bangladesh. Free proxies are unreliable, so treat this as a last resort.
- A failed download is **no longer cached** (it used to be remembered for 12 hours for the trading codes and 30 minutes for history), so the app retries on the next run.
- If DSE's trading-code list can't be fetched, the app uses the symbols found in the price history for the "Equities only" filter. Previously an unreachable code list made that filter drop every symbol.

Tested by simulating the blocked response (including the exact `Last error: None` message) against the real app, with and without a snapshot, plus recovery once DSE is reachable again, and the snapshot script's create, merge, trim and failure paths. Not tested against the real dse.com.bd or Streamlit Cloud, which the sandbox it was built in can't reach.

## What it does

**Market Breadth tab** — same Stockbee-style ratios as the US version (% up/down 4%+ today, momentum-burst windows, quarterly participation), computed across your filtered DSE universe. Note: with only a few hundred stocks, these percentages are noisier than in a bigger market — a handful of names moving can swing the ratio more.

**Momentum Screener tab** — same Qullamaggie-style logic as the US version: RS Rank (percentile return rank within the DSE universe), ADR%, returns over 1D/5D/1M/3M, % from 52-week high, and Tight Base / Breakout Today / Episodic Pivot flags. Prices display in BDT (৳).

**Live tab** — live snapshot of the whole (filtered) DSE market, refreshed on a timer during market hours. Shows % change, RVOL (today's volume vs. a 10-session average pulled from the historical data), and Breakout Now / Intraday EP flags.

## Known limitations

- **"Equities only" filter is a heuristic, not a real instrument-type classification.** `bdshare` doesn't expose a clean instrument-type field, so the filter excludes trading codes containing `MF`, `BOND`, `DEB`, `SUKUK`, or `PREF` (common DSE naming conventions for mutual funds, bonds/debentures, Sukuk, and preference shares). This can both over- and under-exclude — spot-check results if precision matters. Turn it off in the sidebar to see the unfiltered universe.
- **`bdshare` is an unofficial scraper of dsebd.org.** If DSE changes its website's HTML structure, `bdshare`'s parsing can break until the package is updated. If you hit errors, check the [bdshare PyPI page](https://pypi.org/project/bdshare/) for a newer version.
- **RVOL in the Live tab depends on having run the main screen first** (it needs the historical data loaded there to compute each symbol's 10-session average volume). If you go straight to the Live tab without running the main screen, RVOL will be blank.
- **Data freshness**: `bdshare` scrapes DSE's public pages rather than using a dedicated real-time feed — treat live data as "near real-time, good enough for monitoring," not for order execution.
- **The market-status check depends on dsebd.org being reachable.** If it's down, the Live tab will show "Unknown" and pause auto-refresh conservatively.

## Extending

- `utils/data.py` — the DSE-specific data layer and equity-filter heuristic
- `utils/live.py` — live snapshot + market-status logic
- `utils/breadth.py` and `utils/momentum.py` — identical, unmodified copies of the US app's screening logic (they only need standard OHLCV columns, so they work as-is on DSE data)
