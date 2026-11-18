# Trading research: thesis terminal for a few index tickers

## Intraday terminal extension (user, 2026-11-07)
The current request extends this existing app locally, then publishes the code to GitHub. Its intraday
workspace is now the **Intraday** tab (`today.html`); since 2026-11-08 the landing page is the **Daily thesis**
tab (`thesis.html`). The old research tabs remain available. See `docs/INTRADAY_TERMINAL.md` for capabilities,
commands and limits.

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

**Thesis instruments (user, 2026-11-08):** the morning/evening thesis shows ETFs only (SPY, UPRO, SPXU; QQQ,
TQQQ, SQQQ; IWM). Don't add Kalshi to the thesis; the scheduled snapshots keep collecting Kalshi data for later use.

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
   **Daily thesis tab built 2026-11-08** (`thesis/`, `run_thesis.py`): regime, registered signals with the
   backtester's evidence, fixed stance rules (never short; **v2 since 2026-11-13**, shared by the page and the
   stance log in `thesis/eligibility.py`: long only when a rule fired whose *next-open* pricing is a Lead; a rule
   that is a Lead only at the close is "fired, but not a setup now"; "No call" when the evidence is missing,
   damaged, mismatched, unchecked or over 45 days old, with a caution after 10 days), events and
   mega-cap earnings, ETF loss scenarios at 1x-10x, morning futures/nowcast, and the user's call log
   (`data/thesis/calls.jsonl`, scored automatically). The page's own stance is logged forward by online builds
   (`data/thesis/stance_log.jsonl`, SPY/QQQ long or flat, only before the next open) and scored the same way
   (user asked 2026-11-08). Intraday research needs 20 complete sampled days; none existed on 2026-11-13, so
   mid-December at the earliest. **Added 2026-11-13 (user: "lets do all of those"):** a System status card
   (`thesis/ops.py`: last result of each job, missed paper-decision days); the **Journal** (`thesis/journal.py`,
   notes with a snapshot of the page and a 5/20-session look-back); the **Idea ledger** (`thesis/ledger.py`, each
   idea from "idea" to "kept" or "dropped", counting everything tested); optional "leans on" tags on calls.
   The playbook `docs/THESIS_PLAYBOOK.pdf` lists the 15 information gaps in priority order; gaps 1-4 are fixed.
   **Also added 2026-11-13 (user: "build everything"; details in `docs/CHANGES_2026-11-12_13.md`):**
   the **Paper ticket and paper book** (`thesis/paper_book.py`: each logged long followed to its rule's own exit,
   with the backtest beside it; a view, not a new log); the **Pre-close check** (`thesis/preclose.py`,
   `data/thesis/preclose.jsonl`: at about 3:50 PM ET, which rules would fire at the current price, compared later
   with the real close, plus paper trades bought at that close); **same-day option snapshots** (`zero_dte.py`,
   Cboe's free delayed feed, SPY/QQQ/IWM, `data/zero_dte/`, research data only, never a signal); a **News since
   the last close** card (`thesis/news.py`); a futures line among a long call's cautions; a bad-print filter for
   extended-hours levels (`intraday/features.py`, `BAD_PRINT`). `/api/v1/thesis/live` refreshes the ticket,
   pre-close and 0DTE cards without a rebuild. **Added the evening of 2026-11-13 (user: "finish please"):** a
   rolling two-week **earnings calendar** (`thesis/earnings_calendar.py`, Nasdaq.com's daily calendar, companies
   of $25B or more; the ten mega-caps stay cross-checked with Yahoo); **large moves in the ten biggest holdings**
   (`thesis/movers.py`, flagged at 4%, also listed among the cautions); **latest release values**
   (`thesis/releases.py`: payrolls, unemployment, hourly earnings, CPI and core CPI from the BLS API v1, jobless
   claims from FRED; published values with revisions, no expectation, so no surprise). All three download in
   online builds to `data/raw/` and keep the last good copy on failure. **2026-11-14: the backtester's export
   moved to Lead v2** (same schema; `verdict_version`, `verdict_definition`, per-row `verdict_v1`, `q`, `v2` p-values
   and the `risk_matched` benchmark). The page shows v2's statistics and definition and uses `risk_matched` in the
   drawdown caution. Under v2 only QQQ has next-open Leads (Bollinger and RSI(14), both with the 5-day-average
   exit); no SPY rule is a Lead, so SPY logs flat. Stance records logged before 2026-11-13 follow v1's exits in the
   paper book (`verdict_v1`), so their trades don't vanish when a later verdict differs.
   **2026-11-18: the export moved to Lead v3** (same schema; development window fixed at 2010-01-01 to
   2026-11-13, later trades are the backtester's forward record; a Lead whose forward record falls below its band
   becomes "Forward below band"). The page keeps the provisional-Lead caution for v3 (`build.verdict_caution`),
   and a rule rated "Forward below band" is never silent: if it fires the stance is flat with status
   `forward_below_band` and the stance record lists it in `forward_below_rules`; otherwise it is a caution.
   The same two QQQ next-open Leads remain.
   **Also 2026-11-18 (backtester hand-off; user: "Build all three"):** a **daily archive** of the page's key values
   (`thesis/archive.py`, `data/thesis/daily_archive.jsonl`, one hash-chained record per close, written with the stance
   log by recording builds before the next open, because `thesis_state.json` is replaced at every build); long stance
   records are also scored to their **rule's own exit** besides the fixed 5 sessions (`stance_log.rule_exit`);
   **evidence cards** from the backtester's `exports/evidence.json` (`thesis/evidence_cards.py`: sample size, excess
   with its 90% interval, worst point inside a trade, the TQQQ/UPRO version, 1993-2009, forward record, limitations)
   beside each rule that fired or is within 3% of firing, next-open entry only, worded as historical tendencies;
   missing or damaged is "unavailable"; IWM's daily history from 2000 in `etfs_long.csv` (only adds `iwm_*`
   columns; SPY/QQQ values unchanged); the date cross-check tolerates a **rounding tie** (a date whose verdict flips
   if that close moves 10 parts per million) and says so in the cautions (`signals.on_threshold`).
   **Also 2026-11-14:** **intraday base rates** from Yahoo's free hourly bars (`intraday_hourly.py`,
   `data/intraday_hourly/`, about 2.9 years, SPY/QQQ/IWM, refreshed each evening and kept, so the history grows):
   gap fill, first-hour share of the range, whether the day kept the first hour's direction after 10:30, and
   first-hour range breaks, by five gap buckets declared before looking, with 90% intervals. History only; the
   morning view points to the row the futures move suggests. **First-release values** (`thesis/alfred.py`): the
   headline as first announced against now and the typical revision, plus FRED's official Employment Situation and
   CPI dates checked against `data/events/events.csv`. Needs the user's free FRED key in
   `.secrets\fred_api_key.txt` (git-ignored, excluded from the build fingerprint; the key is never logged).
   **Macro tab** (`macro.html`, user agreed 2026-11-14 to a separate tab): rendered by `thesis/build.render_macro`
   from the same build, with the release values and first-release tables moved off the Daily thesis, plus FRED
   series in `thesis/macro.py` (fed funds and target range, 10y-3m, 10y breakeven, NFCI, St. Louis stress index,
   real-time Sahm rule) and a check of Cboe's VIX closes against FRED's `VIXCLS` (all 500 recent closes matched
   on 2026-11-14). Context only. The old "Jobs & macro" tab is now labelled "Jobs study".
   **Future data option (user, 2026-11-14):** Alpaca (free account + API key) offers minute bars back to 2016 as
   far as known; add it only if the user chooses to.
   Historical comparisons must show base rates, sample sizes and holdout results so the page can't manufacture
   confidence. Interactive candlestick charts with news pinned to the time it hit (TradingView Lightweight
   Charts is the candidate library).
4. **Back burner (user, 2026-11-07): backtesting to develop our own edge.** Perp-native backtester (perp entry
   times, discrete 4 PM funding, measured spreads, real fees, exposure-matched benchmark and the 1993-2009 holdout
   in every result), normal-drop exposure overlay, risk engine and sizing.

## Jobs / macro data fix
- Done 2026-11-13: latest values from the BLS API v1 and FRED claims are on the Daily thesis
  (`thesis/releases.py`). Still open: first-release values (ALFRED, needs the user's FRED key), the official
  release schedule, and any expectation to measure a surprise against. The older Jobs & macro tab still uses the
  blocked BLS web page.
- BLS web page and calendar requests return HTTP 403, so that tab has no release numbers. Static calendar dates are
  correct (checked in the 2026-11-06 audit).
- Plan: BLS Public Data API (v1 needs no key; v2 key is free) for payrolls `CES0000000001`, unemployment
  `LNS14000000`, average hourly earnings `CES0500000003`; ALFRED (FRED's vintage archive; free FRED API key the
  user must register) for first-release values so history has no revision look-ahead; FRED release-dates API
  for the official schedule; weekly jobless claims (FRED `ICSA`). Consensus: check whether Kalshi's own jobs/CPI
  markets give a timestamped market expectation; otherwise manual entry.
- Use: mainly event risk. Jobs-morning overnight gaps run about 1.2x normal; the jobs direction test is null
  (p = 0.69). Surprise data feeds the thesis as context, not a standalone trade signal.

## Rules
- Work directly in `C:\Claude\trading-research`, not in a git worktree. The runtime (`.venv`) and the data
  aren't tracked by git, so a worktree can't run the app or its tests. If a session starts under
  `.claude\worktrees`, move the session to this folder before doing anything else.
- No order placement or broker integration. Never use Kalshi's trading endpoints.
- Never fabricate data or consensus values. Unknown stays unknown (the app's existing principle).
- Use the best free sources, and don't let any number depend on one provider when a free independent check
  exists (user, 2026-11-07: "I don't want it to only come from Kalshi"). Prefer official sources (Cboe, FRED,
  BLS, the Fed); Kalshi is the only source only for its own perps' quotes, depth and funding.
- Sizing stays blocked until margin/liquidation is calibrated and a strategy has forward evidence.
- Never edit `data/monitor/paper_events.jsonl`, `data/thesis/calls.jsonl`, `data/thesis/stance_log.jsonl`,
  `data/thesis/journal.jsonl`, `data/thesis/ideas.jsonl`, `data/thesis/preclose.jsonl` or `data/thesis/daily_archive.jsonl` by hand (append-only, hash-chained; a new fact is a
  new record). Never change a frozen
  experiment (`data/monitor/experiment_lock.json`); a new experiment gets a new version.
- After every change: run the tests, commit with a clear message, then push `main` (`git push`) to the private
  GitHub repo https://github.com/ghzxdt/trading-research. Don't commit `data/raw/`, `output/`, `backups/`,
  `work/` or `.venv/` (already in `.gitignore`).
- The computer's clock is US Central; market times are Eastern (Central = Eastern minus 1 hour).

## How to run
- Desktop shortcut **Research** (beside the backtester's **Backtester**; older docs call it "Trading Research
  Control Panel") opens `desktop_app.pyw` from this folder. `setup_windows_tasks.ps1` updates whichever desktop
  shortcut already opens `desktop_app.pyw` and creates "Trading Research Control Panel" only if there is none.
- Dashboard: http://localhost:8766/thesis.html (Daily thesis; Intraday is `today.html`, Macro is `macro.html`).
  Binds to 127.0.0.1 only.
- The FRED API key (registered 2026-11-14 on the user's account, with their OK to accept FRED's terms) is in
  `.secrets\fred_api_key.txt`: git-ignored, outside `data/` so not in the data backup, covered by the user's manual
  copy of `C:\Claude`. Never print it, commit it or put it in a URL that gets logged.
- Tests: `.venv\Scripts\python -B -m unittest discover -s tests` (329 tests).
- New machine: install Python 3.12 and Git, `python -m venv .venv`, `.venv\Scripts\pip install -r
  requirements-frozen-2026-11-12.txt`, then `powershell -ExecutionPolicy Bypass -File .\setup_windows_tasks.ps1`
  recreates the three scheduled tasks and the desktop shortcut (triggers start the next day).
- Online builds also download FRED credit spreads (`data/raw/credit/`) and mega-cap earnings dates from Yahoo and
  Nasdaq (`data/raw/earnings/`); offline builds only read them. The thesis reads the backtester's
  `exports/trade_simulation.json` if present (`THESIS_BACKTESTER_EXPORT` overrides the path).
- All three data tasks also start two minutes after sign-in (user, 2026-11-13), so a night with the laptop off
  is caught up as soon as the user signs in; each script decides what to do from the time of day. After a
  reboot nothing runs until the user signs in (the tasks store no password). Task **Trading Research Dashboard**
  starts the dashboard server at sign-in (`start_dashboard.py`).
- Scheduled task **Trading Research Intraday Collection** (Mon-Fri 9:00, 9:30, 11:30 AM, 1:30, 2:50 and 7:10 PM
  Central) runs `scheduled_collect.py`: at 10:00 AM ET a same-day option snapshot only (`zero_dte.snapshot`, also
  taken at every later daytime run); liquidity snapshots at 10:30, 12:30 and 2:30 PM ET (`liquidity_free.sample`); at
  3:50 PM ET first the pre-close check (`thesis/preclose.py`), then minute bars, option chains and a fourth
  snapshot; at 8:10 PM ET Cboe's one-day and nine-day VIX histories, Yahoo hourly bars (`intraday_hourly.py`),
  minute bars, then OCC options
  volume and the day's record in the **snapshot** liquidity journal (`liquidity_free.update`), then the backup.
  The snapshot journal is a declared weaker policy (spreads from 4 snapshots, not session medians). It is shown
  separately on Today and used only with `run_intraday.py research --liquidity-journal snapshot`; the strict
  `verified` journal stays the default. Yahoo keeps only ~5 days of minute bars, so this is what builds intraday history. It waits for
  builds and for a Today-page collection. Log: `work\intraday_collect.log`. Since 2026-11-18 a minute-bar writer
  lock left by a dead run (e.g. a shutdown mid-collection) is removed automatically and logged in
  `data/intraday/v1/lock_recoveries.log`; one such lock blocked collection from Nov 15 to 18, and System status
  now judges this job by the bars delivered. The evening run then backs up all
  of `data/` except `data/raw/` (`data_backup.py`) to `backups/data/` (3 days plus one per week for 4 weeks).
  No cloud sync (user, 2026-11-13): the user backs up `C:\Claude` by hand; `backup_targets.json` lists no
  folders. This project's Claude chats are copied to `conversations/` (git-ignored) by the hub task
  **Claude Conversations Copy** (`C:\Claude\sync_conversations.ps1`).
- Companion app: **trading-backtester** (`C:\Claude\trading-backtester`, private repo
  https://github.com/ghzxdt/trading-backtester) reads this app's data read-only and tests indicator rules. Never
  make this app depend on it.
- Scheduled task **Trading Research Market Snapshots** (Mon-Fri 8:00 AM and 3:05 PM Central) runs
  `market_snapshot.py --scheduled`, which appends Kalshi perps and macro markets (`data/kalshi/perp_quotes.csv`,
  `event_quotes.csv`), S&P/Nasdaq futures from Yahoo (`data/futures/futures_quotes.csv`) and, at 4:05 PM, the
  Cleveland Fed inflation nowcast (`data/macro/inflation_nowcast.csv`), and archives Yahoo headlines for SPY, QQQ
  and IWM plus Fed releases (so the morning page has news). Log: `work\market_snapshot.log`. A start
  outside 8:00-9:30 AM or 4:00-4:45 PM ET records nothing.
- The Data quality tab checks Yahoo's SPY/QQQ daily returns against FRED's S&P 500 and Nasdaq-100 closes
  (`crosscheck.py`; online refreshes cache the FRED series in `data/raw/crosscheck/`).
- Scheduled task **Trading Research Evening Refresh** (Mon-Fri 8:15 PM Central, Tue-Sat 7:45 AM Central as the
  backstop before the open, and at sign-in; it started at 3:45 PM Central until 2026-11-17, when the user asked
  why it kept checking) runs `scheduled_refresh.py`: waits for the day's VIX close (at most 4 hours, exit 5, so
  the laptop can sleep), runs the app's refresh, checks that the page was published for that session and
  its stance logged (refreshing once more if not; exit 4 if the page still isn't published), then
  `git_backup.py` commits the data files and pushes `main`. Log: `work\scheduled_refresh.log`. Turn it off in
  Task Scheduler.
- All three tasks have "wake the computer to run" set, and the user enabled **Allow wake timers** on mains and
  battery (2026-11-13). A wake only works from sleep: on Fri 2026-11-13 the laptop was shut down from 1:17 AM to
  9:25 PM Central, so every daytime run was missed (no snapshots, option data, pre-close check or liquidity
  samples that day); the sign-in catch-up then logged the day's decisions and stance in time. For an unattended
  day the laptop must be left asleep or on, not shut down.
- Lid closed is fine (checked 2026-11-15): this ThinkPad uses classic S3 sleep, closing the lid means Sleep on
  mains and battery, the tasks may start on battery, and a timer wakes it with the lid shut. Keep it out of a
  bag while a wake is due (no airflow), and prefer mains: the evening refresh holds it awake while it waits for
  the VIX close (usually minutes after 8:15 PM Central; at most 4 hours). Since 2026-11-15 each scheduled script (`unattended.py`) waits up to 3 minutes for
  the network before downloading and asks Windows to stay awake until it finishes (Windows otherwise puts a
  timer-woken laptop back to sleep after about 2 minutes). On Sat 2026-11-14 the sign-in runs started 2.5
  minutes after boot with no network: 0 of 16 bar downloads, Cboe failed, the GitHub push failed.
  **Tested lid closed on 2026-11-17** with temporary copies of this app's evening task and the backtester's weekly
  task: Windows woke the laptop about 30 seconds before each task's time (System log names the task), the
  network was already up and GitHub reachable, the keep-awake held it for the full 3-minute hold, and it went
  back to sleep within seconds of release (backtester copy: about 2 minutes after the wake).
- Offline rebuild: `.venv\Scripts\python -B run_all.py --offline` (about 70 seconds).
- Online refresh: the control panel's **Run / Refresh data**, the pages' **Refresh data + validate**, or
  `run_all.py` without `--offline`. Until Cboe posts the session's VIX close (its file updated at about 9:30 PM ET
  on 16 Nov 2026), a refresh that logged the day's paper decisions would log them as data-blocked for good
  (`refresh_guard.py`). Since 2026-11-17 (user asked to refresh whenever they want) the panel and the pages then
  run a **data-only refresh** and say so: it downloads and rebuilds every page but appends nothing to the paper
  log or the stance log (`build_pipeline.build(record=False)`, `APP_NO_RECORD=1`). The evening task asks for a
  recording refresh only (`X-Require-Record`) and logs the day once the close is posted. `run_all.py` refuses
  with the reason unless given `--data-only`; `--skip-vix-guard` logs that day as data-blocked. The Cboe check
  retries on a fresh connection: a dropped idle connection made every other check fail on 2026-11-17.
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
- Cboe posts the VIX close well after 4:30 PM ET, so evening jobs must wait for it. Measured: `VIX_History.csv`
  changed at 9:30 PM ET (Nov 16) and 9:11 PM ET (Nov 17), and about 10 PM ET on Nov 9; the VIX1D, VIX9D and VIX3M
  files at about 5:31 PM ET (Last-Modified headers and the evening task's log).

## Open decisions (user)
- Risk limits: the user has set no max drawdown or max leverage (2026-11-07); the goal is good trades and large
  gains. Show outcomes at several leverage levels instead of one allowed size. Sizing stays blocked.
- Git commit identity is still the local placeholder `trading-research (local)`, so commits on GitHub don't link
  to the user's account (ghzxdt). Change it only if the user wants that.
