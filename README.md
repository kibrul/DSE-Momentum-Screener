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

## Volume/Turnover Spike tab

Flags stocks where at least **one individual day** within a lookback window (default 9 trading days) hit a volume or turnover threshold — checked day by day, not as an average. A stock with one huge day buried among otherwise-quiet days still gets caught, even though its average over the same window looks unremarkable.

Two metrics, selectable in the tab:
- **Turnover (Taka)** — recommended default, since DSE's currency is Taka and turnover is directly comparable across differently priced stocks (a Tk10 share and a Tk800 share need very different share counts to represent the same money).
- **Share Volume** — raw share count, favors low-priced/high-float names.

**Starting defaults and their sources** (these are informed estimates from public reporting, not a precise statistical study of DSE's full archive — `dsebd.org` wasn't reachable from the sandbox this was built in, so no live 3-year archive could be pulled directly):
- **Turnover default: Tk 10 crore (100 million Taka) in a single day.** Recent DSE weekly recaps show even the top 3 most actively traded stocks on DSE averaging only ~Tk 25-37 crore/day turnover; DSE's average daily *market-wide* turnover (all ~650 stocks combined) has ranged roughly Tk 472-997 crore across 2023-2026 (sources: The Business Standard's DSE annual/FY recaps, BSS/DSE FY26 report). Tk 10 crore for a *single stock* on a *single day* sits comfortably above typical daily turnover for most DSE names while remaining achievable during a genuine spike.
- **Share volume default: 2,000,000 shares in a single day.** Grounded in reporting showing a highly liquid higher-priced stock (Square Pharma) traded only ~1.15 million shares even on a big-turnover day, while low-priced, high-float names (Beximco) routinely trade 10-30+ million shares on active days.

**For a real, data-driven threshold** instead of these estimates, use the "Compute empirical percentiles from loaded data" button in the tab's expander — it calculates actual percentiles (p90/p95/p99) from whatever history you loaded via the sidebar, which reflects DSE's real recent numbers rather than a handful of news snippets. Since your machine can reach `dsebd.org` directly (unlike the sandbox this was built in), this is the more trustworthy number for your own use.

**Caveat on units**: the turnover ("Value") field is scraped directly from DSE's day-end archive table and assumed to be in millions of Taka, per DSE's own site convention — this wasn't independently verified against a live fetch. Sanity-check a known day's turnover figure against dsebd.org after your first run; if the units are off, the "Compute empirical percentiles" button will make it obvious (the numbers will look implausibly large or small).

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
