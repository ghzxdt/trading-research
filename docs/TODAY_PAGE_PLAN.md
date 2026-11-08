# Today page: daily thesis and intraday, side by side (proposed 2026-11-08, awaiting the user's OK)

The user asked to build both directions side by side, prioritizing one first if needed. The Today page gets two
tabs that share one header (as-of times, data health):

- **Daily thesis** (build first): the original plan. Evening (after 4:30 PM ET) and morning (before 9:30 AM ET)
  view of the S&P 500, Nasdaq-100 and Russell 2000, expressed through the ETFs, the 3x ETFs and the Kalshi perps.
- **Intraday** (exists, from the Codex release): 16 instruments, minute charts, levels, options context,
  observation journal. Its data collects automatically; research unlocks when the liquidity history allows.

## Why daily first
- 30+ years of daily history (SPY since 1993) versus two days of minute bars.
- Everything the backtester has found so far is daily (the oversold signals).
- The Kalshi perps, the main instruments, are traded around the 4 PM close and held overnight.
- Intraday needs no attention to keep progressing: collection, liquidity samples and backups run on schedule, and
  the snapshot liquidity policy can start qualifying sessions around Dec 8, 2026.

## Daily thesis tab, v1 contents

1. **Regime**: trend (SPY/QQQ/IWM vs 50- and 200-day averages); volatility (VIX level and 10-year percentile,
   VIX/VIX3M term structure, implied daily move); credit (Moody's Baa-10y back to 1986; ICE BofA HY/CCC for the
   last 3 years; level and 1-month change; new FRED fetch); breadth (RSP vs SPY over 20 days); and upcoming events
   (CPI, jobs, Fed from the calendar; mega-cap earnings once added).
2. **Today's signals and what happened after similar setups**: which registered signals fired at today's close,
   with the backtester's evidence (signal count, excess return, hit rate, the 1993-2009 holdout result, after-cost
   verdict, trade-simulation result). Read from an evidence file the backtester exports. If the file is missing,
   the section says "unavailable"; the research app never needs the backtester to run.
3. **Overnight and expectations** (morning mode): futures and perps change since 4 PM; Kalshi CPI/Fed odds next to
   the Cleveland Fed nowcast.
4. **Expressions and risk at several leverage levels** (the user set no fixed limit): for each underlying, the ETF,
   the 3x ETF and the Kalshi perp, with current spread, fees (maker/taker), and funding per day. For 1x, 2x, 3x, 5x
   and 10x: distance to liquidation, today's implied 1-day move as % of equity, and the historical worst day and
   week at similar VIX levels as % of equity. No recommended size (sizing stays blocked).
5. **What would change the call**: automatic invalidations (e.g. a close back above the signal level, VIX above a
   threshold, an event inside the holding window) plus the user's own.
6. **Thesis log**: the user records a long/short/flat call with instrument, horizon, invalidation and reason.
   Append-only and hash-chained, kept separate from the frozen rules' paper log. Scored automatically when the
   horizon ends (return, and versus buy-and-hold over the same days), with a running scoreboard.

## Build order
1. Backtester: the trade simulator (designed in its LOG.md), then an evidence export (JSON) that section 2 reads.
2. Research app: Daily thesis tab with Regime and Expressions/risk (sections 1 and 4). Data is mostly in hand; add
   the FRED credit-spread fetch.
3. Wire in the evidence (section 2) and morning mode (section 3).
4. Thesis log and automatic scoring (section 6), then the invalidation list (section 5).
5. Earnings calendar for the Nasdaq-100 heavyweights (Yahoo dates, Nasdaq calendar, SEC filing times).

Intraday in parallel, with no extra build needed until its data is ready:
- Collection, liquidity samples, OCC volume and backups run every weekday.
- Around Dec 8, 2026: first sessions can qualify under the snapshot liquidity policy, so the registered
  opening-range baseline can run (labeled with that policy).
- After about 3 months of minute bars: backtester intraday studies (VWAP, opening range, relative volume by time of
  day), shown on the intraday tab the same way section 2 shows daily evidence.
- Later: add the Kalshi perps to the intraday tab's instrument list.
