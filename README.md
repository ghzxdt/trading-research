# Index research: stage 1

## Intraday Today workspace

The existing research app now opens on **Today** at http://localhost:8766/today.html. It adds a shared
sixteen-instrument universe, intraday charts and levels, options information, source health, historical
scenario research and a separate observation journal. Existing daily studies and paper records remain intact.

Use the existing desktop control panel. **Collect intraday** explicitly refreshes the selected instrument;
check **Include options snapshot** for free indicative chains. **Run baseline research** is a historical
scenario, and archive timing must be explicitly selected. Neither function certifies a profitable strategy.

Full capabilities, import formats and commands: [Intraday terminal guide](docs/INTRADAY_TERMINAL.md). Read the [complete upgrade and audit breakdown](docs/UPGRADE_AUDIT_2026-11-07.md) and [app walkthrough](docs/UI_WALKTHROUGH.md).

A program that downloads about 16 years of free market history for the big index ETFs and writes a
report on how they **normally** behave. It doesn't predict tomorrow or suggest trades. It sets the
"normal" that any future trading idea has to beat.

## Run it

One-time setup (in this folder):

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

Then, any time you want fresh numbers:

```bash
.venv/Scripts/python run_stage1.py --open
```

That downloads the latest data, rebuilds everything, and opens the report in your browser.
Add `--offline` to reuse the last download instead of fetching again. On Mac/Linux, use
`.venv/bin/python` instead of `.venv/Scripts/python`.

To check the build itself:

```bash
.venv/Scripts/python run_stage1.py --check
```

This rebuilds the table from data cut off at several past dates and confirms that no column used
information from after its own day. It also runs a few arithmetic and labeling checks. It prints
PASS or FAIL for each check and doesn't write a report.

`requirements.txt` pins the exact package versions this was checked with. If you upgrade a
package, run `--check` again and compare the report before trusting the new numbers. If Yahoo
downloads fail on Windows with a `curl_cffi` "DLL load failed" error, run
`.venv/Scripts/python -m pip uninstall curl_cffi`; yfinance falls back to plain requests.

## What you get (in `output/`)

| File | What it is |
|---|---|
| `report.html` | The report. Open it in any browser; no internet needed. Ends with a **data check** listing what looked wrong in the free data and what was done; any warning also shows at the top. |
| `daily_table.csv` | One row per trading day since 2010: prices, overnight/daytime returns, VIX family, yields, event flags, and a data note per ETF (`spy_flag` etc.) marking unconfirmed opens and removed bad prices. |
| `data_dictionary.csv` | What every column in the table means and **when you could have known it** (previous close, the open, the close, or scheduled in advance). |
| `long_history.csv` | SPY since 1993 and QQQ since 1999, with the VIX. Used only for risk numbers (study 7 and the Leverage tab's liquidation odds), so crashes like 2000-02 and 2008 count. |

## The seven questions the report answers

1. **Overnight vs. daytime:** which part of the day made the money?
2. **The fear gauge:** how well does VIX / 16 predict tomorrow's move size, and is anything better?
3. **The day after:** after big or quiet days, does the market keep going or bounce? It covers the next day (split into overnight and daytime) and the next 5 days.
4. **Moving together:** how tightly do SPY, QQQ, IWM, DIA, RSP and VIX move, and what happens when one breaks away?
5. **Event days:** how much bigger are moves on jobs, inflation, Fed, options-expiration and month-end days?
6. **3x ETFs:** do TQQQ/SQQQ (and UPRO/SPXU) really deliver 3x over a day, week, month?
7. **How far it can go against you:** how big bad days get at each VIX level, how often noise reaches a stop, and how big weekend and holiday gaps are. Uses history back to 1993.

GEX and DIX now have their own tab (see below).

Every finding carries a label: **Fact**, **Possible edge**, **Weak hint** or **No edge**. A
"possible edge" has to beat a luck test (random days picked thousands of times) *and* point the
same way in at least 3 of 4 time periods (2010-14, 2015-19, 2020-22, 2023-now). The report also
says how many tests it ran, because the more you test, the more things pass by chance.

A few more rules keep the tests fair:

- **Like with like.** An event that falls on one weekday at least 80% of the time is compared with
  that weekday. For example, options-expiration days are compared with other Fridays.
- **Size tests.** "Are moves bigger on jobs-report days?" uses the same luck test on move size.
  These results say how big moves get, which matters for sizing and stops, not which way to bet.
- **Borderline results.** Anything with luck between 2% and 10% gets 10x as many random picks.
  Anything between 4% and 6% also carries a note that its label could go either way.
- **Multi-day results** (the next 5 days) use a different luck test. Back-to-back 5-day windows overlap,
  so instead of random days, the signal days are slid along the calendar by a random amount. That
  keeps their spacing and clustering.

## Where the data comes from (all free, no sign-up)

- **ETF prices:** Yahoo Finance through the `yfinance` package, adjusted for splits and dividends.
- **VIX, VIX9D, VIX3M, VVIX:** Cboe's public daily history files.
- **2-year and 10-year Treasury yields:** FRED. These are published a day late, so the table shifts them to the day you'd actually see them.
- **Long history:** SPY from Feb 1993 and QQQ from Mar 1999 (Yahoo), plus Cboe's VIX back to 1990. Used only for risk numbers.
- **Event dates:** `data/events/events.csv`. Jobs and CPI dates come from the BLS release archives, Fed decision dates from federalreserve.gov. Reports released while the stock market was closed (e.g. Good Friday) count on the next trading day.

### Keeping event dates current

BLS blocks automated downloads, so jobs and CPI dates are added by hand. Jobs, CPI and Fed dates
**through December 2027** are already in the file. Jobs and CPI dates come from the BLS calendar as
of Nov 5, 2026.

BLS sometimes moves a release (the late-2025 shutdown delayed several). If that happens, fix that
line in `data/events/events.csv`. When the 2028 schedules come out, add lines in this format:

```
YYYY-MM-DD,jobs_report,08:30,BLS Employment Situation
YYYY-MM-DD,cpi,08:30,BLS Consumer Price Index
```

The report's data check warns you when the file has no upcoming jobs or CPI date.

## Limits

- No trading costs, spreads or slippage anywhere. Real results would be lower.
- Daily data only. Nothing looks inside the day (VWAP, opening range, first 30 minutes); that needs minute data.
- Most studies start in 2010. Only the risk numbers use the history back to 1993.
- Yahoo is free but unofficial. Old opening prices can have small errors.
- Past patterns fade, especially once many people trade them.
- Research only, not financial advice.

## The hub: four tabs

**[APP_GUIDE.md](APP_GUIDE.md) is the full guide:** what every tab does, how to run it, and exactly what makes the GEX / DIX tab Cold, Warm or Hot.

| Tab | Page | Built by | What it shows |
|---|---|---|---|
| **Indexes** | `output/report.html` | `run_stage1.py` | Everything above: how the index ETFs behave |
| **Tickers** | `output/tickers.html` + `ticker_<TICKER>.html` | `run_tickers.py` | One page per ETF: stats, charts, order-flow stand-ins, news |
| **Leverage (perps)** | `output/leverage.html` | `run_leverage.py` | Perpetual futures by market: leverage, cost and risk |
| **GEX / DIX** | `output/gex.html` | `run_gex.py` | Dealer positioning from a SqueezeMetrics file you download; a Cold/Warm/Hot refresh bar and an Update button |

To look at the hub, start the helper and open http://localhost:8765. The helper serves the pages and runs the GEX / DIX Update button. It only listens on this computer.

```bash
.venv/Scripts/python hub_server.py
```

**GEX / DIX and SqueezeMetrics' terms:** their terms bar systematically retrieving their data, so the app never downloads it. To update:
1. Click **Get the file** on the tab.
2. Click **CSV** on their page.
3. Click **Update**. The app copies the newest `DIX*.csv` from your Downloads folder into `data/manual/DIX.csv`.

Without the helper, run `.venv/Scripts/python run_gex.py --import` instead. Nothing else in the app depends on this tab.

## The Leverage tab (Kalshi perps)

`output/index.html` opens the hub. To refresh both tabs at once:

```bash
.venv/Scripts/python run_all.py --open
```

The Leverage tab has:

- **A sortable table of every perp** on Kalshi (88 listed on Nov 5, 2026), highest leverage first.
  - Columns: platform, type, what it tracks, max leverage, move to liquidation, funding per $10k a day and per year, days longs paid, number of funding payments, spread, volume, open interest, hours, and launch date.
  - Click a column to sort. Tick types (Index, ETF, Stock, Metal, Energy, Crypto) to filter.
  - Indexes, ETFs and stocks show by default.
- **Four studies on the index perps** (US500, US Tech 100, SPY, QQQ):
  - How far a move wipes you out, with the odds taken from SPY and QQQ history.
  - What funding costs.
  - How closely each perp follows its index.
  - What the perp does overnight versus the ETF's open.
- **A data check** for the Kalshi data.

Where the data comes from: Kalshi's public market-data API. No account or key is needed. Raw
downloads are saved in `data/raw/kalshi/`. Each run also adds the market list to
`data/kalshi/snapshots.csv`, because Kalshi doesn't serve past spreads or open interest, so run it
daily to build that history. Also saved: `output/leverage_markets.csv`, the table as a spreadsheet.

Limits:
- Leverage is Kalshi's estimate for a small position.
- Move-to-liquidation figures are calculated from Kalshi's risk settings: liquidation happens when
  equity falls to the initial margin ÷ 1.3. Kalshi doesn't publish them, so confirm on Kalshi
  before trading.
- Most perps are days or weeks old, so their own numbers are first looks.

The table is built to hold more than one platform. Another platform needs its own downloader
that produces the same row columns (see `leverage/build.py`).

## Stage 2 (planned)

- **"Where today fits":** a short box at the top showing where the latest day sits against this
  history (e.g. "VIX is higher than on 70% of days since 2010", "today was a big-drop day").
- **Evening and morning thesis card:** lean, confirms-if, cancels-if, no-trade-if, entry/stop and
  size, filled in from the numbers stage 1 produces, plus a log of every thesis to score later.
- **Intraday data** (free Alpaca minute bars) to test entry rules: opening range, VWAP, gap fills.
- **Proper tests of stage 1's leads**, with trading costs, on SPY/QQQ shares first, then TQQQ/SQQQ.
