# Project summary: index ETF research app (as of Nov 6, 2026)

> **Review request:** Please review this project as a skeptical quant reviewer before we build stage 2. Look for:
> - methodology problems: look-ahead, overfitting, multiple testing, overlapping windows
> - anything that looks wrong or too good to be true
> - weak assumptions, especially the Kalshi liquidation model
> - what's missing
>
> Tell me what you agree with, what you'd change, and what you'd test first. The questions at the end are a starting point. I'm also attaching a PDF breakdown of every piece and where it lives.

*Market data runs through the Nov 5, 2026 close. This is research, not financial advice, and nothing below is a tested trading strategy yet.*

## Who it's for and what it's for
- **The user:** a small-account retail trader. Trades the big index ETFs (SPY, QQQ) and their 3× versions (TQQQ, SQQQ, UPRO, SPXU), and uses **Kalshi's perpetual futures ("perps")** for leverage.
- **The goal:** build a daily **up / down / no-edge thesis** for index perps on Kalshi from real market data. Kalshi's own prices aren't used as signals.
- **Stages:**
  - **Stage 1 (done):** history and base rates, plus supporting tabs.
  - **Stage 2 (next):** the daily thesis and position sizing.

## What's built
A local Python app (pandas, yfinance, requests). It writes static HTML pages to one **hub** in the browser, with **four tabs** that are kept separate. Data flows one way:
- The Tickers and Leverage tabs read the Indexes tab's data.
- The GEX/DIX tab reads Indexes and Leverage.
- Nothing reads GEX/DIX.

How it runs:
- `run_all.py` refreshes everything.
- `hub_server.py` serves the hub at localhost:8765 and handles one button.
- `run_stage1.py --check` runs a self-check.

| Tab | What it does |
|---|---|
| **Indexes** | Base rates and luck-tested findings for the index ETFs (mainly SPY), 2010 to now. Risk numbers go back to 1993. |
| **Tickers** | One page per ETF (SPY, QQQ, IWM, DIA, RSP, TQQQ, SQQQ, UPRO, SPXU): stats, charts, daily order-flow stand-ins, headlines. Descriptive, not luck-tested. |
| **Leverage (perps)** | Every Kalshi perp (88 listed, 86 active) in a sortable table, plus studies on the index perps: liquidation odds, funding, tracking, overnight moves |
| **GEX / DIX** | SqueezeMetrics dealer-positioning (GEX) and dark-pool (DIX) data. Updated only by hand, with a Cold/Warm/Hot "worth refreshing?" indicator. |

## Data and timing rules
**Sources:**
- Yahoo Finance via yfinance: adjusted daily OHLCV for 9 ETFs since 2010, plus SPY since 1993 and QQQ since 1999. Free but unofficial.
- Cboe: VIX, VIX9D, VIX3M, VVIX.
- FRED: 2-year and 10-year yields, shifted a day because they're published late.
- Event dates: jobs, CPI and Fed through Dec 2027, typed in from BLS and Fed calendars.
- Kalshi's public perps API.
- SqueezeMetrics' GEX/DIX CSV, downloaded manually because their terms bar automated retrieval.
- Yahoo headlines and the Fed's press-release RSS.

**Timing rules:**
- **Point in time:** every column is tagged with when it was knowable. The self-check rebuilds the table from data cut off at 6 past dates and confirms no column changes (no look-ahead).
- **Expected move** = yesterday's VIX ÷ √252 (the "VIX/16" rule).
- **Day types** = SPY's move ÷ expected move: big drop (< −1), normal drop, quiet (±0.3), normal rise, big rise (> +1).
- **GEX/DIX** are published after the close, so they're treated as known only before the *next* open.

**Data cleaning:**
- Opens that exactly equal the prior close are treated as unconfirmed and left out of the overnight/daytime split.
- A single bad SPXU price was removed.
- A pre-2010 data note is flagged.

## Method
**Luck test.** The mean (or move size) on signal days is compared with 4,000 random same-size draws of days. Borderline results (2–10%) get 40,000 draws. Draws are seeded per test, so results don't depend on test order. 5-day results use a circular-shift test, which slides the signal dates along the calendar, because their windows overlap.

**Verdicts:**
- **Possible edge:** p < 5%, the same direction in at least 3 of 4 periods (2010-14, 2015-19, 2020-22, 2023-now), and at least 30 cases.
- **Weak hint:** p < 20%.
- **No edge:** everything else.
- **Fact:** descriptive, not tested.
- p between 4% and 6% is flagged as borderline.

**Comparisons and multiple testing:**
- Events that mostly fall on one weekday are compared with that weekday (expiration and jobs days vs. Fridays, Fed days vs. Wednesdays).
- "Size tests" compare move size (RMS in expected moves) instead of direction.
- The report counts its tests: **30 tests on the Indexes tab, so about 1.5 would pass by chance alone.**

## Key results (Indexes tab)

| Finding | Result | Luck (p) | Periods |
|---|---|---|---|
| **Direction:** after a big SPY rise, next day | −0.12% (vs +0.06% normal); much of it from 14 days in early 2020 | 0.9% | 4/4 |
| **Direction:** after a big rise with VIX ≥ 20, next day | −0.32% (112 cases), almost all of it overnight (−0.28%). Split chosen after seeing the result. | 3.5% | 3/4 |
| **Direction:** after a normal drop, next 5 days | +0.51% (vs +0.28% for any 5 days) | 1.2% | 4/4 |
| **Direction:** after a big rise, next 5 days | −0.02% (vs +0.28%) | 3.0% | 4/4 |
| **Size:** jobs-report mornings, overnight gap | 1.19× ordinary | 3.1% | 3/4 |
| **Size:** Fed afternoons, daytime move | 1.29× ordinary | 0.4% | 4/4 |
| **Size:** weekend gaps (Fri close → Mon open), since 1993 | 1.14× weeknights | < 0.1% | 3/4 |
| **Size:** holiday / long-weekend gaps | 1.50× weeknights | < 0.1% | 4/4 |

Other facts:
- **Overnight vs. daytime:** 68% of SPY's growth since 2010 came overnight (QQQ 69%). That's about +0.036% a night before costs.
- **VIX vs. real moves:** VIX overstated real moves by about 15%, and 81% of days stayed within one expected move. Above VIX 30 it understated them. VIX9D was the best next-day move-size predictor (rank correlation 0.43).
- **Clustering:** calm follows calm (next day 0.89× normal size) and big days follow big days (1.26×). Nothing usable for direction after big drops.
- **Correlation:** SPY, QQQ, DIA and RSP move together at 0.93–0.95. QQQ moves about 1.13× SPY (1.28× since 2023).
- **No scheduled event predicts direction.** Options-expiration days are only a weak hint (−0.06% vs +0.07% on other Fridays).
- **3× ETFs:** in choppy months, TQQQ and SQQQ each come out about 1.2% short of exact 3×, and both lose in 21% of them.
- **How big bad days get (since 1993):** a 1-in-100 day ranges from 1.4% (VIX < 13) to 8.9% (VIX 30+).
- **Stops:** a stop 2 expected moves below yesterday's close gets hit by noise on 2.5% of days (about 1 in 40).
- **Crash years:** 2000-09 had 23 days where SPY traded 5%+ below the prior close, vs 13 since 2010. QQQ's worst intraday point was −17.2% (Aug 24, 2015 flash crash).

## Leverage tab (Kalshi perps)

| Index perp | Max leverage (Kalshi's estimate) | Move to liquidation at max (calculated) | Long liquidated within 1 day (ETF history) | Within 1 week |
|---|---|---|---|---|
| US500 | 12.2× | 1.9% | 8.2% of days (SPY since 1993) | 31.1% |
| US Tech 100 | 10.6× | 2.2% | 13.4% (QQQ since 1999) | 38.8% |
| SPY perp | 5.0× | 4.6% | 0.6% | 6.7% |
| QQQ perp | 5.0× | 4.6% | 2.3% | 14.7% |

- **Liquidation model:** liquidation happens when equity falls to the initial margin ÷ 1.3 (Kalshi's published initial-margin multiplier). This matches the 15.5% minimum margin in Kalshi's filing, but it's labeled an estimate.
- **Funding** is charged daily on index and stock perps. US500 longs paid about $1.36 per $10k a day, roughly 5% a year on the position, or about 61% a year of posted cash at max leverage.
- **Tracking and overnight:** US500's 4 pm moves matched SPY's at 1.00 correlation (average gap 0.04%/day over 22 days). Its 4 pm → 9 am move matched the direction of SPY's opening gap on 95% of 22 nights.
- **History is short:** US500 since Oct 2026, the SPY and QQQ perps since Nov 5, 2026.

## GEX / DIX tab
- **GEX:** when GEX closed below zero, the next day session was 1.31× bigger even after adjusting for VIX (possible edge, size; p < 0.1%, 4/4 periods). That's useful for sizing, not direction.
- **DIX:** no edge either way over 5 sessions.
- **Cold/Warm/Hot indicator** (a reminder of when to refresh, not a market call):
  - **Hot** if any of: VIX ≥ 20; the last GEX reading below zero or under $1B; SPY's latest day a big move; the fear curve inverted (VIX > VIX3M).
  - **Warm** if VIX is 16–20.
  - **Cold** otherwise.
  - History behind it: GEX was below zero on 0.06% of days with VIX < 16, 3.9% at 16–20, 17% at 20–25, 39% at 25–30, and 46% at 30+.

## Bugs found and fixed along the way
- **Options-expiration mislabel:** the newest row was mislabeled as an expiration day, so the −4.4% crash on Nov 5 was counted as one and inflated an "edge." Fixed, and the self-check now guards against it.
- **Yields:** blank after bond holidays.
- **Test-order dependence:** luck-test results changed depending on the order tests ran in.
- **Up-volume:** miscounted on the Tickers pages.
- **Liquidation odds:** QQQ's pre-1999 days were counted as "not hit."

## Limits
- **No trading costs anywhere yet** (spreads, slippage, fees, funding). Every lead must survive them.
- **Daily data only.** "Order flow" is daily stand-ins: relative volume, close location, up-day volume share, and the A/D line. True trade-by-trade flow and order books aren't free for these ETFs.
- **Not luck-tested:** per-ticker numbers.
- **Unchecked inputs:** Yahoo data is unofficial, and SqueezeMetrics' method isn't public.

## Stage 2 plan
1. **A daily call** (up / down / no edge) for 1-day and 1-week holds, built from the leads above, with confirm and cancel conditions.
2. **Translation into a Kalshi position:**
   - which perp
   - a stop from the stop table, well inside liquidation
   - a size that survives a 1-in-100 day
   - extra caution before weekends, holidays, jobs and Fed days, and when GEX < 0
3. **Cost-tested versions of the leads,** plus minute data for entry timing.
4. **A log of every call,** so they can be scored.

**Open decisions:**
- the holding period (overnight, intraday, or about a week)
- the maximum leverage to allow
- which perps to cover first (US500 only, or also US Tech 100 and the SPY/QQQ perps)

## Useful things to ask a reviewer
- Are the luck-test and period-consistency rules strict enough, given 30+ tests and overlapping signals?
- How should trading costs and Kalshi funding be modeled to test the 4 direction leads?
- What's a sound way to combine the leads and size effects into one daily call without overfitting?
- Is the liquidation-cushion model right for Kalshi perps?
