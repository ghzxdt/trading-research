# Trading research: thesis terminal for a few index tickers

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
1. **Operations:** scheduled evening refresh so the paper log never misses a day; Kalshi quote collector for
   the universe perps every ~15 minutes (bid/ask, sizes, mark, funding, open flag; order-book depth if the API
   has it); Leverage tab must ignore closed-market quotes when showing spreads.
2. **Jobs / macro data fix** (see below).
3. **Thesis terminal "Today" page** for the universe: regime, relevant news and events with historical
   comparisons, evidence, invalidation, risk numbers, logged calls. Design it with the user before building.
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
- No order placement or broker integration. Never use Kalshi's trading endpoints.
- Never fabricate data or consensus values. Unknown stays unknown (the app's existing principle).
- Sizing stays blocked until margin/liquidation is calibrated and a strategy has forward evidence.
- Never edit `data/monitor/paper_events.jsonl` by hand (append-only, hash-chained). Never change a frozen
  experiment (`data/monitor/experiment_lock.json`); a new experiment gets a new version.
- After every change: run the tests, then commit with a clear message. Don't commit `data/raw/`, `output/`,
  `backups/`, `work/` or `.venv/` (already in `.gitignore`).
- The computer's clock is US Central; market times are Eastern (Central = Eastern minus 1 hour).

## How to run
- Desktop shortcut **Trading Research Control Panel** opens `desktop_app.pyw` from this folder.
- Dashboard: http://localhost:8766/monitor.html (server binds to 127.0.0.1 only).
- Tests: `.venv\Scripts\python -B -m unittest discover -s tests` (59 tests).
- Offline rebuild: `.venv\Scripts\python -B run_all.py --offline` (about 70 seconds).
- Online refresh: the control panel's **Run / Refresh data**, or `run_all.py` without `--offline`.
- Review checks: `.venv\Scripts\python -B research\holdout_checks.py` and `research\review_checks.py`.

## History
- 2026-11-05/06: original 4-tab app built in a Claude session (scratch workspace; original copy preserved in
  `backups/original_20261106T064353Z.zip`).
- 2026-11-06/07: audited and repaired in Codex at
  `C:\Users\gzdt\Documents\Codex\2026-11-06\x20-au\outputs\trading_research` (5 evaluation tabs, control panel).
  Portable archives (`trading_research_desktop_2026-11-07.zip` etc.) remain in that `outputs` folder.
- 2026-11-07: moved here, git initialized, quant review in `docs/QUANT_REVIEW_2026-11-07.md`.

## Key facts from the review (details in docs/QUANT_REVIEW_2026-11-07.md)
- Only normal-drop long 5 survives the untouched SPY 1993-2009 holdout; the three rally shorts don't.
- Normal-drop long 5 is mostly beta: +0.34%/trade gross vs +0.25% for random entries in the same windows.
- Kalshi index perps trade Sun 6 PM to Fri ~5 PM ET, so 4:00 PM signals are tradeable at ~4:05 PM.
- Kalshi funding is one payment per day at 4:00 PM ET.
- Open-session index perp half-spreads were ~0.2-0.7 bp; fees unknown; SPY/QQQ perps are thin.

## Open decisions (user)
- Max drawdown (%) and max leverage they're willing to use. Dollar account size isn't needed.
- GitHub private repo for off-machine backup (git commit identity is a local placeholder until then).
