# Trading research: thesis terminal for a few index tickers

## Intraday terminal extension (user, 2026-11-07)
The current request extends this existing app locally, then publishes the code to GitHub. The new
Today workspace is the landing page; the old research tabs remain available. See
`docs/INTRADAY_TERMINAL.md` for capabilities, commands and limits.

- Shared intraday universe: SPY, QQQ, IWM, TQQQ, SQQQ, SOXL, TNA, LABD, KORU, BITX, ERY, FNGU,
  UPRO, SPXL, NVDL and TSLL. The user confirmed these eleven additions to the original five.
  `terminal_config.json` is the shared source of scope; inclusion never establishes execution eligibility.
- Use existing free feeds. Explicit collection retains minute-bar receipt times and indicative current
  chains. Yahoo's last-trade time is not a verified quote time. Contract-level execution requires verified
  timestamped imports. No paid subscription or broker integration has been added.
- The new `intraday/`, `options_research/`, `today/`, versioned state API and news first-seen archive are
  separate from the frozen daily experiment. Never relabel archive scenarios as forward evidence.
- Paper buttons record research observations/abstentions. Automatic forward trade-outcome resolution is
  not implemented. Current evidence and risk limits do not approve personalized sizing.
- Intraday data lives in separately ignored local folders. Existing scheduled jobs are unchanged;
  collection is manual. Offline builds and GET/replay requests do not collect data or create paper events.
- For any future change to registered strategy behavior, create a new study/experiment version.
- `liquidity_screen.py` gates new research using 20 prior verified sessions and 80% window eligibility;
  failing sessions are excluded individually. Free current chains cannot certify that history. Initial
  thresholds in `terminal_config.json` are research assumptions, not measured execution capacity.
- NVDL/TSLL retain charts/data but cannot use index candidates, index research, or the index journal.
  Their separately registered event study remains unavailable.

## Start of every session
1. Read this file and `LOG.md` (open items are at the top).
2. Give a short status: what's in progress, what's waiting on the user.
3. Wait for the user's request.

## What we're building (user, 2026-11-07)
A terminal the user checks to build a thesis for profitable trades on a small set of tickers. It gathers the
relevant news, data and events, compares them with history ("what happened after similar situations"), and
gives a long / short / flat thesis with the evidence and what would invalidate it. The user then charts and
places trades themselves. The app never trades.

Every evening (after 4:30 PM ET) and morning (before 9:30 AM ET), one page shows:
- the market regime
- the evidence for long, short or flat, with historical base rates and sample sizes
- the size the risk rules allow (as % of account and distance to liquidation, not dollars)
- what would change the call

Each call is logged and later scored. Charts and news feed this page; they are not the product.
Success is measured in % return per unit of risk, not dollars.

## Universe (user, 2026-11-07)
Organized by underlying; within each, the instruments are ways to express the same view.
- **S&P 500:** SPY; Kalshi `KXUS500PERP` (US500), `KXSPYPERP` (SPY perp)
- **Nasdaq-100:** QQQ, TQQQ (3x), SQQQ (-3x); Kalshi `KXUSTECH100PERP` (US Tech 100), `KXQQQPERP` (QQQ perp)
- **Russell 2000:** IWM; Kalshi `KXUS2000PERP` (inactive as of 2026-11-07)

DIA, RSP, UPRO and SPXU stay in the research tabs only (RSP vs SPY is useful breadth context).
Single-stock and crypto perps are out of scope. Higher volatility (TQQQ/SQQQ) scales wins and losses equally;
it is a leverage choice on the Nasdaq-100 view, not a separate idea.

## Roadmap (user priorities, 2026-11-07)
1. **Operations:** scheduled evening refresh so the paper log never misses a day (done 2026-11-07); market
   snapshots at ~9:00 AM and 4:05 PM ET: Kalshi perps and CPI/Fed/payrolls markets, S&P/Nasdaq futures and the
   Cleveland Fed inflation nowcast (done 2026-11-07; the user agreed a full every-15-minutes collector isn't worth
   it unless a strategy needs intraday entries or limit-order fills); Leverage tab ignores closed-market quotes
   when showing spreads (done 2026-11-07).
2. **Jobs / macro data fix** (see below).
3. **Thesis terminal "Today" page** for the universe: regime, relevant news and events with historical
   comparisons, evidence, invalidation, risk numbers, logged calls. Design approved 2026-11-08: two tabs side by
   side, Daily thesis (built first) and Intraday; see `docs/TODAY_PAGE_PLAN.md` for contents and build order.
   Historical comparisons must show base rates, sample sizes and holdout results so the page can't manufacture
   confidence. Interactive candlestick charts with news pinned to the time it hit (TradingView Lightweight
   Charts is the candidate library).
4. **Back burner (user, 2026-11-07): backtesting to develop our own edge.** Perp-native backtester (perp entry
   times, discrete 4 PM funding, measured spreads, real fees, exposure-matched benchmark and the 1993-2009 holdout
   in every result), normal-drop exposure overlay, risk engine and sizing.

## Jobs / macro data fix
- Today: BLS web page and calendar requests return HTTP 403, so no release numbers. Static calendar dates are
  correct (checked in the 2026-11-06 audit).
- Plan: BLS Public Data API (v1 needs no key; v2 key is free) for payrolls `CES0000000001`, unemployment
  `LNS14000000`, average hourly earnings `CES0500000003`; ALFRED (FRED's vintage archive; free FRED API key the
  user must register) for first-release values so history has no revision look-ahead; FRED release-dates API
  for the official schedule; weekly jobless claims (FRED `ICSA`). Consensus: check whether Kalshi's own jobs/CPI
  markets give a timestamped market expectation; otherwise manual entry.
- Use: mainly event risk. Jobs-morning overnight gaps run about 1.2x normal; the jobs direction test is null
  (p = 0.69). Surprise data feeds the thesis as context, not a standalone trade signal.

## Rules
- Work directly in `C:\Users\gzdt\trading-research`, not in a git worktree. The runtime (`.venv`) and the data
  aren't tracked by git, so a worktree can't run the app or its tests. If a session starts under
  `.claude\worktrees`, move the session to this folder before doing anything else.
- No order placement or broker integration. Never use Kalshi's trading endpoints.
- Never fabricate data or consensus values. Unknown stays unknown (the app's existing principle).
- Use the best free sources, and don't let any number depend on one provider when a free independent check
  exists (user, 2026-11-07: "I don't want it to only come from Kalshi"). Prefer official sources (Cboe, FRED,
  BLS, the Fed); Kalshi is the only source only for its own perps' quotes, depth and funding.
- Sizing stays blocked until margin/liquidation is calibrated and a strategy has forward evidence.
- Never edit `data/monitor/paper_events.jsonl` by hand (append-only, hash-chained). Never change a frozen
  experiment (`data/monitor/experiment_lock.json`); a new experiment gets a new version.
- After every change: run the tests, commit with a clear message, then push `main` (`git push`) to the private
  GitHub repo https://github.com/ghzxdt/trading-research. Don't commit `data/raw/`, `output/`, `backups/`,
  `work/` or `.venv/` (already in `.gitignore`).
- The computer's clock is US Central; market times are Eastern (Central = Eastern minus 1 hour).

## How to run
- Desktop shortcut **Trading Research Control Panel** opens `desktop_app.pyw` from this folder.
- Dashboard: http://localhost:8766/today.html (server binds to 127.0.0.1 only).
- Tests: `.venv\Scripts\python -B -m unittest discover -s tests` (216 tests).
- Scheduled task **Trading Research Intraday Collection** (Mon-Fri 9:30, 11:30 AM, 1:30, 2:50 and 7:10 PM Central)
  runs `scheduled_collect.py`: liquidity snapshots at 10:30, 12:30 and 2:30 PM ET (`liquidity_free.sample`); at
  3:50 PM ET minute bars, option chains and a fourth snapshot; at 8:10 PM ET minute bars, then OCC options
  volume and the day's record in the **snapshot** liquidity journal (`liquidity_free.update`), then the backup.
  The snapshot journal is a declared weaker policy (spreads from 4 snapshots, not session medians). It is shown
  separately on Today and used only with `run_intraday.py research --liquidity-journal snapshot`; the strict
  `verified` journal stays the default. Yahoo keeps only ~5 days of minute bars, so this is what builds intraday history. It waits for
  builds and for a Today-page collection. Log: `work\intraday_collect.log`. The evening run then backs up all
  of `data/` except `data/raw/` (`data_backup.py`) to `backups/data/` and to the first cloud folder in
  `backup_targets.json` that exists (Google Drive for desktop or iCloud for Windows). It keeps 3 days plus one
  per week for 4 weeks.
- Companion app: **trading-backtester** (`C:\Users\gzdt\trading-backtester`, private repo
  https://github.com/ghzxdt/trading-backtester) reads this app's data read-only and tests indicator rules. Never
  make this app depend on it.
- Scheduled task **Trading Research Market Snapshots** (Mon-Fri 8:00 AM and 3:05 PM Central) runs
  `market_snapshot.py --scheduled`, which appends Kalshi perps and macro markets (`data/kalshi/perp_quotes.csv`,
  `event_quotes.csv`), S&P/Nasdaq futures from Yahoo (`data/futures/futures_quotes.csv`) and, at 4:05 PM, the
  Cleveland Fed inflation nowcast (`data/macro/inflation_nowcast.csv`). Log: `work\market_snapshot.log`. A start
  outside 8:00-9:30 AM or 4:00-4:45 PM ET records nothing.
- The Data quality tab checks Yahoo's SPY/QQQ daily returns against FRED's S&P 500 and Nasdaq-100 closes
  (`crosscheck.py`; online refreshes cache the FRED series in `data/raw/crosscheck/`).
- Scheduled task **Trading Research Evening Refresh** (Mon-Fri 3:45 PM Central) runs `scheduled_refresh.py`:
  waits for the day's VIX close, runs the app's refresh, then `git_backup.py` commits the data files and pushes
  `main`. Log: `work\scheduled_refresh.log`. Turn it off in Task Scheduler.
- Offline rebuild: `.venv\Scripts\python -B run_all.py --offline` (about 70 seconds).
- Online refresh: the control panel's **Run / Refresh data**, or `run_all.py` without `--offline`. Both refuse,
  with the reason, while the latest session's paper decisions aren't logged and Cboe hasn't posted its VIX close
  (`refresh_guard.py`); `run_all.py --skip-vix-guard` overrides it, which logs that day as data-blocked.
- Review checks: `.venv\Scripts\python -B research\holdout_checks.py` and `research\review_checks.py`.

## History
- 2026-11-05/06: original 4-tab app built in a Claude session (scratch workspace; original copy preserved in
  `backups/original_20261106T064353Z.zip`).
- 2026-11-06/07: audited and repaired in Codex at
  `C:\Users\gzdt\Documents\Codex\2026-11-06\x20-au\outputs\trading_research` (5 evaluation tabs, control panel).
  Portable archives (`trading_research_desktop_2026-11-07.zip` etc.) remain in that `outputs` folder.
- 2026-11-07: moved here, git initialized, quant review in `docs/QUANT_REVIEW_2026-11-07.md`. Evening refresh task
  set up; private GitHub repo https://github.com/ghzxdt/trading-research created, and the evening task pushes
  `main` to it.

## Key facts from the review (details in docs/QUANT_REVIEW_2026-11-07.md)
- Only normal-drop long 5 survives the untouched SPY 1993-2009 holdout; the three rally shorts don't.
- Normal-drop long 5 is mostly beta: +0.34%/trade gross vs +0.25% for random entries in the same windows.
- Kalshi index perps trade Sun 6 PM to Fri ~5 PM ET, so 4:00 PM signals are tradeable at ~4:05 PM.
- Kalshi funding is one payment per day at 4:00 PM ET: the time-weighted premium of the perp over its index;
  positive means longs pay shorts.
- Open-session index perp half-spreads were ~0.2-0.7 bp; SPY/QQQ perps are thin.
- Kalshi perps fees (checked 2026-11-07): 0.12% taker / 0.02% maker per side at the base tier, on notional.
- Cboe posts the VIX close well after 4:30 PM ET, so evening jobs must wait for it (see LOG.md).

## Open decisions (user)
- Risk limits: the user has set no max drawdown or max leverage (2026-11-07); the goal is good trades and large
  gains. Show outcomes at several leverage levels instead of one allowed size. Sizing stays blocked.
- Git commit identity is still the local placeholder `trading-research (local)`, so commits on GitHub don't link
  to the user's account (ghzxdt). Change it only if the user wants that.
