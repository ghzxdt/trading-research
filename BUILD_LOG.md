# Build log: index research tool

Last updated: Nov 5, 2026, late evening (after the close)

## Where things stand

| | Status |
|---|---|
| Stage 1: history report ("what's normal") | **Built, updated, checked.** Data through the Nov 5, 2026 close. |
| Stage 1 updates (section 9) | **All 9 done**, plus 4 more fixes found along the way |
| Tickers tab: a page per ETF (section 15) | **Built, checked.** |
| GEX / DIX tab, helper, Cold/Warm/Hot (section 14) | **Built, tested end to end.** |
| Stage 1 tweaks A-G (section 13) | **All done.** 33 tests, 9 possible edges. |
| Leverage tab: Kalshi perps (section 12) | **Built, checked.** Kalshi data as of Nov 5, 2026, 11:20 pm ET. |
| Stage 2: "where today fits", thesis card, minute data, cost tests | Planned, **not started** |
| Anything tested with trading costs | **Nothing yet** |

This is research only, not trade advice. Nothing in it is a buy or sell signal yet.

---

## 1. Reviewed the ChatGPT selloff-screener chat

I read it as a quant developer would. Three rules carried into the build:

- **Point in time.** Every number is tagged with *when you could have known it*, so no test can use tomorrow's information by accident.
- **Luck test before trust.** A pattern only counts if random days rarely look as good *and* it shows up in most time periods.
- **Index first.** SPY/QQQ come first. TQQQ/SQQQ are studied as SPY/QQQ times 3, with the extra risks spelled out.

## 2. Checked for helpful ChatGPT plugins

Three worth knowing about: **Alpaca** (free minute data and paper trading), **Interactive Brokers**, and **Financial Datasets**. Alpaca's free minute bars are planned for stage 2. Stage 1 doesn't need any of them.

## 3. Planned the work in stages

- **Stage 1:** a history report of how the index ETFs normally behave.
- **Stage 2:** the daily "where today fits" box, evening and morning thesis cards, minute data, and cost-tested versions of stage 1's leads.
- **Later:** SPY options, once the account allows it.

Decision: **"where today fits" goes in stage 2**, not stage 1 (your call).

## 4. Built stage 1

### Files

| File | What it does |
|---|---|
| [run_stage1.py](run_stage1.py) | The one command you run. `--open` opens the report, `--offline` reuses the last download, `--check` runs the self-check. |
| [stage1/sources.py](stage1/sources.py) | Downloads the data (retries 3 times), saves a copy in `data/raw/`, and records whether each source came down fresh or fell back to the saved copy. |
| [stage1/dataset.py](stage1/dataset.py) | Builds the daily table: one row per trading day, every column tagged with when it was knowable. Also flags unconfirmed opens and removes bad prices. |
| [stage1/studies.py](stage1/studies.py) | The six studies, the luck test, and the verdict rules. |
| [stage1/health.py](stage1/health.py) | **New.** The data check that appears in the report (freshness, odd prices, missing values, event calendar). |
| [stage1/selfcheck.py](stage1/selfcheck.py) | **New.** The `--check` command: proves no column peeks at the future, plus arithmetic and label checks. |
| [stage1/report.py](stage1/report.py) + [stage1/report_template.html](stage1/report_template.html) | Turns everything into one self-contained HTML page with charts. It works offline. |
| [data/events/events.csv](data/events/events.csv) | Event dates: 215 jobs reports, 215 CPI reports, 145 Fed decisions (2010 through Dec 2027). |
| [requirements.txt](requirements.txt) | Exact package versions (pandas 3.1.1, numpy 2.5.4, yfinance 1.8.0, requests 2.34.2). |
| [README.md](README.md) | Plain-English setup, run steps, rules, sources, limits. |
| `.claude/launch.json` | Starts a local viewer for the report (port 8765). |

About 1,730 lines of Python and 440 of HTML/JS.

### Data (all free, no sign-up)

| What | Where from | Notes |
|---|---|---|
| SPY, QQQ, IWM, DIA, RSP, TQQQ, SQQQ, UPRO, SPXU | Yahoo Finance (`yfinance`) | Adjusted for splits and dividends. Unofficial source. |
| VIX, VIX9D, VIX3M, VVIX | Cboe public history files | VIX9D only goes back to Jan 2011. |
| 2-year and 10-year Treasury yields | FRED | Shifted one day, because FRED publishes them a day late. |
| Jobs, CPI, Fed dates | BLS and Fed sites, typed in by hand | BLS blocks scripts. Late-2025 shutdown delays use the actual dates. Future dates come from the BLS calendar as of Nov 5, 2026. |

### Outputs (in `output/`)

- `report.html`: the report (6 studies, 8 charts, each with a "show the numbers" table), ending with the data check.
- `daily_table.csv`: 4,236 trading days by 110 columns, including a data note per ETF (`spy_flag` etc.).
- `data_dictionary.csv`: what each column means and when you could have known it.

### Rules the report follows

- **Day types** compare SPY's move with the move VIX expected (VIX ÷ 16 for one day): big drop (below −1), normal drop, quiet (between −0.3 and +0.3), normal rise, big rise (above +1).
- **Luck test:** draw 4,000 random sets of the same number of days and count how often they look at least as different. Each test has its own fixed random draws, so adding a test never changes another one. Borderline results (2-10%) get 40,000 draws.
- **Like with like:** an event that falls on one weekday at least 80% of the time is compared with that weekday. Expiration and jobs days are compared with Fridays, Fed days with Wednesdays.
- **Size tests:** "are moves bigger on these days?" uses the same luck test on move size. These results say how big moves get, not which way.
- **Verdicts:**
  - **Possible edge:** beats luck (under 5%), points the same way in at least 3 of 4 periods (2010-14, 2015-19, 2020-22, 2023-now), and has 30 or more cases.
  - **Weak hint:** beats luck but isn't consistent across periods, or comes close (under 20%).
  - **No edge:** everything else.
  - **Fact:** a description, not a test.
  - Anything between 4% and 6% says its label could go either way.
- **Honesty check:** the report counts its tests and says how many would pass by chance alone.

## 5. Problems hit while building, and the fixes

| Problem | Fix |
|---|---|
| A comma inside a note broke the events file | Rewrote the note without a comma |
| `curl_cffi` (pulled in by yfinance) failed to load on Windows ("filename too long") | Uninstalled it. yfinance falls back to plain requests. |
| Date-formatting crash on weekly chart dates | Converted the dates to a pandas date index first |
| Event counts came up short (e.g. jobs reports on Good Friday, when stocks are closed) | Reports on market holidays now count on the next trading day |
| Chart axes showed stray ticks below 0 and past ±1 | Fixed a rounding error in the tick math |
| Bar labels overlapped on grouped bars | Labels only on single-series bar charts, and only when there's room |
| "+" signs on sizes, which can't be negative, and ugly "−0.00%" | Added an "unsigned" format and a zero check |

## 6. How it was checked

- `--check` passes:
  - **No look-ahead:** the table was rebuilt from data cut off at 6 dates (2013 to yesterday), and the rows came out the same.
  - Overnight × daytime = full day for every ETF.
  - Day types match their thresholds.
  - Every column has a "known at" label.
  - There's one expiration day per month.
- The look-ahead check is proven to work: with the old expiration-day bug put back on purpose, it fails on 3 of the 6 cuts.
- All 8 charts render with no browser errors. Tooltips, dark mode and light mode all work.
- The biggest overnight moves (March 2020, Aug 2015) were spot-checked against history and are real.
- A row for today is dropped if the run happens before 4:30 pm ET, so a half-finished day never gets in.

## 7. Results (Nov 5, 2026, after the updates)

| Question | Answer |
|---|---|
| Overnight vs. daytime | 68% of SPY's growth since 2010 came overnight (QQQ: 69%). If the 36 unconfirmed-open days are counted, it's 66%. About +0.04% a night, before costs. |
| VIX ÷ 16 | It overstated real moves by about 15%. 81% of days stayed within one expected move. VIX9D predicted tomorrow's move size best. |
| The day after | Calm follows calm (0.89× normal size) and storms follow storms (1.26×). Nothing usable after big drops. |
| Indexes together | QQQ moves about 1.13× SPY, with a correlation of 0.93, so they're basically one bet. VIX vs SPY: −0.75. |
| Event days | Jobs-report nights gap 1.19× bigger and Fed days swing 1.29× bigger. **Both now pass a size test.** CPI nights (1.13×) are a weak hint. Expiration and month-end days aren't bigger. |
| 3x ETFs | Close to 3× over one day. In choppy months TQQQ and SQQQ both came out about 1.2% worse than exactly 3×, and both lost money in 21% of those months. |
| Nov 5, 2026 | SPY −4.41%: the open was only −0.17%, and the remaining −4.24% came after the open. |

**Leads worth testing in stage 2 (direction):**
1. After a big rise, SPY's next day averaged −0.12% (vs +0.06% normally). Luck: 0.8%. 4 of 4 periods. But 14 days in early 2020 carry much of it; without them it's −0.04%.
2. After a big rise **with VIX at 20 or higher**, the next day averaged −0.32% (112 times). Luck: 3.6%. This split was chosen after seeing the result, so it deserves extra caution.

**Size effects (for sizing and stops):** jobs-report nights 1.19× (luck 3.0%) and Fed days 1.29× (luck 0.5%).

**Honesty check:** 23 tests in total, so about 1.2 would pass by chance alone. 4 passed.

## 8. Review and updates (Nov 5, 2026)

### What changed in the results

| Finding | Before | After | Why |
|---|---|---|---|
| Options-expiration days | **Possible edge** (−0.09%) | **Weak hint** (−0.06% vs +0.07% on other Fridays, luck 11%) | Today's −4.4% crash had been counted as an expiration day (bug below), and the fair comparison is other Fridays |
| Big rise → next day | Possible edge | Possible edge, with the 2020 caveat attached | Much of it comes from 14 days in early 2020 |
| Big rise, VIX 20+ | — | **Possible edge** (new) | Where the effect lives; picked after looking |
| Big rise, VIX under 20 | — | Weak hint (new, right at the line) | |
| Jobs-night and Fed-day sizes | "Fact", untested | **Pass the size test** | Now tested |
| CPI-night size | "Fact", untested | Weak hint | Now tested |
| Overnight share (SPY) | 66% | 68% | Unconfirmed opens left out |
| "QQQ much weaker than SPY" | Flipped between weak hint and possible edge while I was making changes | Weak hint (5.1%), marked as right at the line | It sits on the 5% line. Fixed random draws per test stop it flipping when other tests change. |

### Bugs found and fixed

| Bug | Effect | Fix |
|---|---|---|
| **Expiration-day mislabel:** before a month's 3rd Friday, the newest row was flagged as that month's expiration day | Nov 5, 2026 (−4.4%) counted as an expiration day, which inflated that lead. It would also have mislabeled "today" in stage 2. | A month only counts once its 3rd Friday has arrived. The self-check now guards against this. |
| Treasury yields blank on the day after Columbus Day and Veterans Day | 31 blank days. No study used yields. | Fill FRED's blank holiday rows first. Now 0 missing. |
| Luck-test results depended on the order tests ran in | A borderline result could flip just by adding a test elsewhere | Each test's random draws are tied to its own data, and borderline cases get 10× more draws |
| A pandas setting about to change its default (concat sorting) | None yet. A future pandas would have changed it silently. | Set explicitly. Versions are now pinned. |
| 3x finding said "fell −1.2% short" and "SQQQ more" when both were equal | Confusing wording | Wording now follows the numbers |

### Data health (now shown in the report)

| Issue | Size | What's done |
|---|---|---|
| Opening price exactly equals the prior close | SPY 36 (mostly 2016-17), RSP 78, SPXU 78, others 20-59 | Left out of the overnight/daytime split. Flagged in the table. |
| SPXU Oct 18, 2010 bad price | 1 day | Removed (it moved the wrong way vs SPY, then snapped back) |
| 3x funds far off 3× on Mar 16-18, 2020 and Apr 9-10, 2025 | 7 fund-days | Kept: real extreme days |
| SQQQ zero volume for its first 2 months (2010) | 29 days | Noted. Volume isn't used. |
| VIX9D starts Jan 2011; VVIX missing 2 days | — | Those days are skipped where needed |
| Download fell back to a saved copy | — | Warning banner at the top of the report |
| No upcoming jobs/CPI dates in the file | — | Fixed now (through Dec 2027). A warning appears if it runs out. |

## 9. The 9 suggested updates

| # | Change | Status |
|---|---|---|
| 1 | Compare expiration days with other Fridays | **Done.** Extended to any event that mostly falls on one weekday. |
| 2 | VIX split and 2020 check for the big-rise lead | **Done** |
| 3 | Luck tests on the event-size numbers | **Done** |
| 4 | Fix the yields bug | **Done** |
| 5 | Data-health box in the report, skip suspicious opens | **Done** |
| 6 | "Stale data" banner | **Done.** Also warns if VIX lags prices or prices lag today. |
| 7 | Pin package versions | **Done** |
| 8 | BLS schedule from Nov 2026 on | **Done.** Through Dec 2027. |
| 9 | Self-check (`--check`) | **Done** |

## 10. Known limits

- No trading costs, bid-ask spreads or slippage anywhere yet.
- Daily data only, so nothing inside the day (VWAP, opening range).
- Yahoo is unofficial, and some opening prices can't be confirmed (section 8).
- The expiration-day rule doesn't know exchange holidays ahead of time. On the Thursday before a Good Friday that is also the 3rd Friday, that Thursday only gets flagged once the next trading day's data arrives. That happens about once every few years.
- Past patterns fade, especially once many people trade them.

## 11. Stage 2 (planned)

1. **"Where today fits"** box at the top of the report (e.g. "VIX is higher than on 70% of days since 2010", "today was a big-drop day", "tomorrow is a jobs report").
2. **Evening and morning thesis card:** which way you lean, what would confirm it, what would cancel it, when not to trade, entry/stop/size. Filled from stage 1 numbers, with a log of every thesis so it can be scored later.
3. **Minute data** (free from Alpaca) to test entry rules: opening range, VWAP, gap fills.
4. **Cost-tested versions of the leads:** SPY/QQQ shares first, then TQQQ/SQQQ.

## 12. Leverage tab: Kalshi perps (Nov 5, 2026)

You asked for Kalshi's perpetual futures as their own part of the app, kept apart from the index
history, with markets sorted by leverage, platform and the rest.

### How the information was found, and how far to trust it

- **Source: Kalshi's own public API**, the data behind its site, with no login needed. It lists 88 perps, 86 active: 58 stocks and ETFs, 19 crypto, 6 metals, 2 indexes, 1 oil.
- News articles only told me the products existed. Where one disagreed (it said SPY and QQQ weren't approved yet), I went with Kalshi's API, which shows both trading.
- **Straight from Kalshi:** the market list, prices, bid/ask, volume, open interest, trading hours, and every funding payment since launch.
- **Kalshi's estimate:** max leverage, for a small position. Bigger positions get less.
- **My calculation:** move to liquidation. It assumes liquidation happens when equity falls to the initial margin ÷ 1.3, Kalshi's published "initial margin multiplier". That matches the 15.5% minimum margin in the single-stock filing (1 ÷ 4.96 ÷ 1.3 = 15.5%), but Kalshi doesn't state the formula in one place. The page labels it an estimate.

### What was built

| File | What it does |
|---|---|
| [leverage/kalshi.py](leverage/kalshi.py) | Downloads the market list, risk settings, all funding history (one call), and hourly prices for the index perps. Saves a snapshot of the market list each run. |
| [leverage/build.py](leverage/build.py) | One comparable row per market (built to take more platforms later), the four index-perp studies, and the data check |
| [leverage/report.py](leverage/report.py) | The Leverage page: the sortable, filterable table, then the studies |
| [run_leverage.py](run_leverage.py) | Builds the Leverage tab (`--offline`, `--open`) |
| [run_all.py](run_all.py) | Refreshes both tabs |
| `stage1/report.py`, template | Hub tabs on both pages, `output/index.html`, a daily mode for line charts |

### First results (Nov 5, 2026)

| | US500 | US Tech 100 | SPY perp | QQQ perp |
|---|---|---|---|---|
| Max leverage | 12.2x | 10.6x | 5.0x | 5.0x |
| Move to liquidation at max (est.) | 1.9% | 2.2% | 4.6% | 4.6% |
| Long hit within 1 day, since 2010 (ETF history) | 6.7% of days | 8.1% | 0.4% | 0.8% |
| Long hit within 1 week | 27.7% | 31.8% | 5.5% | 9.1% |
| Funding, longs paid per $10k a day | $1.36 (31 payments) | $1.21 (23) | too new | too new |
| Funding per year on your cash at max leverage | ~61% | ~47% | too new | too new |
| 4 pm moves vs. the ETF | lined up 1.00, gap 0.04%/day (22 days) | 1.00, gap 0.19% (16 days) | too new | too new |
| Overnight move (4 pm to 9 am) same direction as ETF's open | 95% of 22 nights | 100% of 16 nights | too new | too new |

- **Biggest takeaway:** at max leverage, the cushion is smaller than an ordinary bad day. The leverage you choose matters far more than the maximum. At 3x on US500, the cushion is about 27%, versus SPY's worst single day since 2010 of −11.9%.
- **Funding** has averaged about a quarter of SPY's typical daily gain. It's charged on the whole position, so leverage multiplies it too.
- **The index perps' overnight moves matched where SPY and QQQ opened.** That's useful for the morning check in stage 2. It's only 16 to 22 nights so far.

### Checks

- The page opens and the tabs switch both ways.
- The table sorts by every column, the type filters work, and Indexes, ETFs and stocks show by default (60 of 88).
- Both charts render in light and dark mode, with no browser errors.
- Brand-new markets show "–" for "days longs paid" until they have 5 payments, and a column shows how many funding payments each has had.
- Stage 1's `--check` still passes after the shared template changes.

### Not done

- Nothing is tested with trading costs.
- No other platforms yet.
- Snapshots of spreads and open interest start today, so that history builds only as you keep running it.

## 13. Stage 1 tweaks A-G (Nov 5, 2026, late)

You asked for all seven tweaks before stage 2. The current state of every result is in [STAGE1_REVIEW.md](STAGE1_REVIEW.md).

| # | What was added | Where |
|---|---|---|
| A | How big bad days get (1 in 10/20/100) by VIX level, worst point during the day, and a stop table in expected moves | New study 7 |
| B | Each day type's next day split into overnight and daytime | Study 3 |
| C | Weekend and holiday gaps vs. weeknights (2 size tests) | Study 7 |
| D | Next 5 trading days after each day type (5 tests, using a luck test built for overlapping windows) | Study 3 |
| E | SPY from 1993 and QQQ from 1999 for risk numbers (`output/long_history.csv`); the Leverage tab's liquidation odds now use it | Study 7, Leverage tab |
| F | "After a normal drop" shown as its own finding | Study 3 |
| G | SqueezeMetrics GEX (size test) and DIX (2 direction tests over 5 days) | New study 8 |

**Data decision for G:** SqueezeMetrics' CSV is free, but their terms bar "systematically retrieving data... to create a database" without permission. So the app never fetches it. It reads `data/manual/DIX.csv`, which you refresh by clicking CSV on squeezemetrics.com/monitor/dix. I seeded it with the one copy I downloaded to check the data. Delete it to switch study 8 off. The data check warns when it's more than 2 trading days old.

**New results:** tests went from 23 to 33, and possible edges from 4 to 9.
- **Direction:** normal drop → next 5 days +0.51% (luck 1.2%, 4 of 4 periods). Big rise → next 5 days −0.02% (luck 3.0%, 4 of 4).
- **Size:** weekend gaps 1.14×, holiday gaps 1.50×, and GEX below zero 1.31× bigger moves beyond VIX.
- **Split (B):** after a big rise with VIX ≥ 20, the next-day dip is almost all overnight (−0.28%).
- **Long history (E):** QQQ's worst point in a day was −17.2% (Aug 24, 2015 flash crash), and 73 of its 113 days at 5%+ down were in 2000-02.
- **Leverage tab:** liquidation odds at max leverage rose from 6.7% to 8.2% of days (US500) and from 8.1% to 13.4% (US Tech 100).
- **DIX:** no edge.

**Fixes along the way:** a misplaced decorator in the new luck test, and the Leverage tab's liquidation odds now only count days the ETF existed (QQQ before 1999 would otherwise have been counted as "not hit").

**Checks:**
- `--check` passes, including look-ahead on the GEX/DIX columns and the long-history table.
- The report renders 12 charts with no browser errors.
- The Leverage tab rebuilds with no errors.

## 14. GEX / DIX tab, the helper, and the Cold/Warm/Hot indicator (Nov 6, 2026)

You asked for GEX/DIX as its own tab that sits quietly until you choose to update it. When you do, it syncs with the other tabs, and it shows an indicator for when an update is worth it. **[APP_GUIDE.md](APP_GUIDE.md) is now the full guide to the whole app.**

| Piece | What it does |
|---|---|
| `gex/` + `run_gex.py` | The tab, with four parts: the refresh bar and buttons; today's reading (latest GEX/DIX plus the Indexes tab's VIX and the Leverage tab's cushions); the last 6 months; and history (3 tests, moved here from the Indexes tab). Plus a data check. |
| `gex/importer.py` | Copies the newest `DIX*.csv` from Downloads. It checks the columns, only replaces your copy with something newer, and keeps the old copy. |
| `hub_server.py` | Replaces the plain viewer. It serves the hub at localhost:8765 and runs the Update button. It only listens on this computer and refuses requests from other sites. |
| Cold / Warm / Hot | **Hot** if any of: VIX ≥ 20; your last GEX below zero or under $1B; SPY's latest day a big drop or big rise; the fear curve inverted. **Warm** if VIX is 16-20. **Cold** otherwise. A ✓ is added when your copy is current. Shown on the tab and as a badge on the tab name on every page. |

**Changes to the Indexes tab:**
- Study 8 and the GEX/DIX columns moved out of it, so it no longer depends on the manual file at all.
- It now runs 30 tests with 8 possible edges.
- `run_stage1.py` still refreshes the Cold/Warm/Hot level, because it has the new VIX.

**Tests:**
- **Update flow, end to end in the browser.** I used a copy made 2 days stale and a test file in a scratch folder, not your Downloads. The bar read Hot (refresh recommended) → clicked Update → imported and reloaded → "Hot: your copy is up to date", badge "Hot ✓".
- **Clicking again** correctly said nothing newer.
- **Requests without the hub's header or host** were refused.
- **Your real GEX file** was restored exactly (all 3,903 rows match), and the test leftovers were deleted.
- **The Indexes self-check** still passes, and all three pages load with no browser errors.

## 15. Tickers tab: a page per ETF (Nov 6, 2026)

You asked to keep the Indexes tab as the summary and add the same stats per ticker, each on its own page with charts, news and order flow.

| Piece | What it does |
|---|---|
| `tickers/news.py` | Yahoo headlines per ticker (via yfinance, the same unofficial source as the prices), the Fed's official press-release RSS, and an upcoming-events calendar. Headlines and links only; only http/https links are kept. Saved in `data/raw/news/`. |
| `tickers/build.py` | For each of the 9 ETFs: snapshot, order-flow stand-ins, overnight vs daytime, after each SPY day type, event days, risk, and 3× tracking. Descriptive only (no luck tests). |
| `tickers/report.py` + `run_tickers.py` | The overview (`tickers.html`, with a side-by-side table) and 9 ticker pages with a ticker-button row |
| Hub | A "Tickers" tab added after Indexes; `run_all.py` runs it |

**Order flow:** true trade-by-trade flow isn't free for these ETFs, so the pages show daily stand-ins and label them that way:
- volume vs. its 20-day average, with how rare that is
- where the day closed in its range
- share of volume on up days
- the accumulation/distribution line
- Kalshi perp readings for the related markets, and DIX/GEX on the SPY page

**Bugs caught while checking:**
- Up-day volume was counting the last 20 up days, not up days within the last 20 days. SPY showed 91% during a selloff; it's now 40%.
- "Higher than 100% of days" was rounding; it's now a rank, for example "the 14th heaviest of 4,216 days."
- The inverse funds' drawdown showed −100.0%; it now shows −99.9995%. SQQQ really has lost that much since its 2010 peak.
- The stats tables were hidden behind "More numbers"; on these pages they now show directly.

**Checks:**
- All 10 pages load with no browser errors, in dark and light mode.
- 75 headlines and 12 Fed releases loaded.
- `run_all.py` rebuilds all four tabs.

## How to re-run

```bash
.venv/Scripts/python run_all.py
```

```bash
.venv/Scripts/python hub_server.py
```

```bash
.venv/Scripts/python run_stage1.py --open
```

```bash
.venv/Scripts/python run_leverage.py --open
```

```bash
.venv/Scripts/python run_stage1.py --check
```
