# Trading research: thesis terminal for a few index ETFs

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

## Pages
Tabs, in order: **Review** (front page since 2026-11-19, `review.html`), **Daily thesis** (`thesis.html`, its
detail page), **Intraday** (`today.html`), **Macro** (`macro.html`), Indexes, Tickers, 4-rule paper log, Data
quality, and **Archive** ("Original vs fixed" and "4-rule backtests", still built, moved there 2026-11-19).

**Removed 2026-11-19** (the user's trim list, relayed by the backtester chat: "Yes, send both"): the GEX/DIX tab,
the Jobs study tab, Kalshi and perpetuals (the Leverage tab, perp quotes, Kalshi macro markets), and options data
(same-day 0DTE snapshots, option chains, OCC volume, option spreads). What had been collected is in
`archive/kalshi-2026-11-19/`, `archive/gex-2026-11-19/`, `archive/jobs-study-2026-11-19/` and
`archive/options-2026-11-19/`, each with a README. Delete those only on the user's word.

## Universe
- Active instruments (`terminal_config.json` `universe`, trimmed 2026-11-19 from 16): **SPY, QQQ, IWM, TQQQ,
  SQQQ, UPRO, SPXU.** The config refuses single names. DIA and RSP are inactive entries used in the research tabs
  only (RSP vs SPY is useful breadth context). Stored minute bars of dropped tickers stay on disk.
- Organized by underlying; within each, the instruments are ways to express the same view (user, 2026-11-07):
  S&P 500: SPY, UPRO (3x), SPXU (-3x); Nasdaq-100: QQQ, TQQQ (3x), SQQQ (-3x); Russell 2000: IWM. Higher
  volatility scales wins and losses equally; it is a leverage choice on the same view, not a separate idea.
- The thesis shows ETFs only (user, 2026-11-08). Kalshi and all perpetuals were dropped on 2026-11-19 (user: "no
  more tracking that"). Single stocks and crypto are out of scope.
- Which tickers are gathered minute by minute is a separate list (see "Live minute bars" under How to run).

## Review page (front page)
`thesis/review.py` and `thesis/review_template.html`, rendered by `thesis/build.render_review` from the Daily
thesis build (`state`) plus the backtester's optional files: `exports/trade_simulation.json`, `exports/evidence.json`
(through the signals' evidence cards), `exports/filter_tests.json` and the trade list `exports/trades/<run>.csv`
(named in trade_simulation.json `trade_list`). Any of them missing leaves its part "unavailable". It is a read model:
no new log, and the same inputs give the same page.
- v1 2026-11-19; **v2 2026-11-21** from the backtester chat's spec `docs/REVIEW_PAGE_V2_2026-11-21.md` in that repo
  (user: "Yes, send it"). The loop: information builds a thesis, the thesis becomes a plan, the plan a trade, the
  trade's result evidence.
- Shows: callouts marked act / watch / info with their source; one plan per ETF when several Leads fire on the same
  close ("one bet, one size"), with entry, the **exit close** (the mean of the last 4 closes, which is what exits the
  5-day-average rule), the time stop, the holding window's catalysts (counted in exchange sessions), each rule's
  spread from the evidence cards and the size; open trades of every Lead, close-only included, labelled "rule trade,
  not a stance" (`paper_book.rule_trades`) with past trades of the same rule whose worst point reached the same
  drawdown; a Thesis section (regime in two tagged lines, levels with ATR(14) and swing points plus a copy list from
  `thesis/levels.py`, catalysts, the last 8 trades of each plan rule, what would change the call, a pre-filled thesis
  saved as a call); a year table per Lead; edge health per Lead (with the same-VIX test); the user's record against
  the rule by opportunity id; the research queue and the tests due.
- Guardrails (spec): tested evidence outranks information. Context items carry the tag of their registered filter
  test for the rule in play (tested edge / tested, no effect / unresolved / untested); the mapping is
  `review.CONTEXT`, and a new filter test needs one row there. Every number shows its n and an interval where one is
  exported; small samples say so. No composite score and no probability of profit computed by the app; agreeing
  context is not added up. Statistics come from the backtester's files; only price levels and the open rule
  trades' paths are computed here.
- Views: Evening, Pre-close (the 30 minutes before a session's close: the latest live minute bar against the
  close-entry Leads' triggers, via `/api/v1/review/preclose`, watch only, writes nothing) and Weekly (Saturday and
  Sunday: edge health, the year, the record and the queue open). Chosen by the clock, switchable on the page.
- "Near a trigger" is within 1.5 ATR(14) of the trigger close (3% if no ATR), on the Review page and the Daily
  thesis's evidence cards (spec step 5, 2026-11-21).
- Sizing: arithmetic on the user's own limit only, after they set `risk.max_loss_per_trade` in
  `terminal_config.json` (below 1 = a fraction of the account; a dollar amount needs `risk.account_equity`). Until
  then the plan says "set a loss limit". It is not an approved size.
- Not built yet: a forward count for the unresolved gap filter (the backtester doesn't export one) and the optional
  check of stated confidence on calls.

## Daily thesis (detail page)
`thesis/`, `run_thesis.py`, built 2026-11-08 (design in `docs/TODAY_PAGE_PLAN.md`; playbook of 15 information gaps
in `docs/THESIS_PLAYBOOK.pdf`, gaps 1-4 fixed). Changes of 2026-11-12/13 are in `docs/CHANGES_2026-11-12_13.md`.
- **Stance rules v2** (since 2026-11-13, shared by the page and the stance log in `thesis/eligibility.py`): never
  short; long only when a rule fired whose *next-open* pricing is a Lead; a rule that is a Lead only at the close is
  "fired, but not a setup now"; "No call" when the evidence is missing, damaged, mismatched, unchecked or over 45
  days old, with a caution after 10 days. The page's stance is logged forward by recording builds
  (`data/thesis/stance_log.jsonl`, SPY/QQQ long or flat, only before the next open; user asked 2026-11-08), scored at
  5 sessions and to the rule's own exit (`stance_log.rule_exit`).
- **Backtester verdicts:** the export moved to Lead v2 on 2026-11-14 and **Lead v3 on 2026-11-18** (same schema;
  development window fixed at 2010-01-01 to 2026-11-13; later trades are its forward record). A Lead whose forward
  record falls below its band becomes "Forward below band": if it fires the stance is flat with status
  `forward_below_band` (listed in `forward_below_rules`), otherwise it is a caution. The provisional-Lead caution
  stays (`build.verdict_caution`). Now only QQQ has next-open Leads (Bollinger and RSI(14), 5-day-average exit), so
  SPY logs flat. Stance records logged before 2026-11-13 follow v1's exits in the paper book (`verdict_v1`).
- **Shown first** (review C9; user, 2026-11-18: "Yes, as proposed"): the call, registered signals with evidence
  cards and evidence state, the paper ticket, VIX, events and earnings (with a weekend or holiday warning before
  the next open) and risk by leverage (ETF loss scenarios at 1x-10x). **Folded:** the paper book's history,
  trend/credit/rates/history, the pre-close check, System status (`thesis/ops.py`; its summary line names anything
  not ok), news since the last close, overnight futures and inflation nowcast, the earnings calendar and hourly
  base rates.
- **Evidence cards** (`thesis/evidence_cards.py`, from the backtester's `exports/evidence.json`): sample size, excess
  with its 90% interval, worst point inside a trade, the TQQQ/UPRO version, 1993-2009, forward record and
  limitations, worded as historical tendencies; next-open cards beside rules that fired or are near their trigger.
- **Logs (all append-only, hash-chained):** the user's calls (`data/thesis/calls.jsonl`, scored automatically;
  schema 2 since 2026-11-18 with an optional exit level, user: "yes, add the exit level to calls": a call ends at the
  next open after the first daily close that breaks the level, or at the horizon's close, with the fixed-horizon
  result beside it); the Journal (`thesis/journal.py`); the Idea ledger (`thesis/ledger.py`; schema 2, review B8:
  once an idea is registered its testable fields `ledger.FROZEN` can't change, a changed rule is a new idea); the
  pre-close check (`thesis/preclose.py`, `data/thesis/preclose.jsonl`, about 3:50 PM ET or 30 minutes before an
  early close, schema 2); the daily archive of the page's key values (`thesis/archive.py`,
  `data/thesis/daily_archive.jsonl`, one record per close, user: "Build all three", 2026-11-18).
- **Opportunity ids** (review B6; user, 2026-11-18: "Yes, go ahead"; `thesis/opportunity.py`): one id per rule firing
  on an ETF at a close, for an entry policy and evidence export (`<close>:<ETF>:<rule>:<policy>:<sha12>`). Stance
  records list theirs with the disposition; a close with no stance before its next open gets a "missed" record
  (labelled, not scored); calls record `opportunity_ids` and a `relation` (take, veto, override, agree flat, own
  view, unlinked); notes record `opportunity_ids`; paper-book trades compute the same id.
- **Paper book and ticket** (`thesis/paper_book.py`): each logged long followed to its rule's own exit, with the
  backtest beside it; a view, not a new log. `/api/v1/thesis/live` refreshes the ticket and the pre-close card
  without a rebuild.
- **Context sources:** events and mega-cap earnings; a rolling two-week earnings calendar
  (`thesis/earnings_calendar.py`, Nasdaq.com, companies of $25B or more; the ten mega-caps cross-checked with Yahoo);
  large moves in the ten biggest holdings (`thesis/movers.py`, flagged at 4%); news since the last close
  (`thesis/news.py`); intraday base rates from Yahoo's hourly bars (`intraday_hourly.py`, `data/intraday_hourly/`,
  about 2.9 years and growing; five gap buckets declared before looking, with 90% intervals; history only). These
  download in online builds to `data/raw/` and keep the last good copy on failure.
- **Signal checks:** the rules are recomputed here; their fired dates are checked against the backtester's
  `signal_days`, tolerating a rounding tie (a date whose verdict flips if that close moves 10 parts per million,
  `signals.on_threshold`), which the cautions mention. IWM's daily history goes back to 2000 in `etfs_long.csv`.
- **Macro tab** (user agreed 2026-11-14): `thesis/build.render_macro` from the same build: latest release values
  (`thesis/releases.py`: payrolls, unemployment, hourly earnings, CPI and core CPI from the BLS API v1, jobless claims
  from FRED; no expectation, so no surprise), first-release values (`thesis/alfred.py`, ALFRED; FRED's official
  Employment Situation and CPI dates checked against `data/events/events.csv`), FRED series (`thesis/macro.py`: fed
  funds and target range, 10y-3m, 10y breakeven, NFCI, St. Louis stress index, real-time Sahm rule) and a check of
  Cboe's VIX closes against FRED's `VIXCLS`. Context only.

## Intraday tab (user, 2026-11-07)
Built as an extension of this app; see `docs/INTRADAY_TERMINAL.md` for capabilities and commands (written before
the 2026-11-19 trim: it still lists 16 tickers and options collection).
- `terminal_config.json` is the shared source of scope; inclusion never establishes execution eligibility.
- Free feeds only. Minute bars keep their receipt times. Yahoo's last-trade time is not a verified quote time.
  No paid subscription or broker integration has been added. Options collection stopped on 2026-11-19;
  `options_research/` remains for manual imports, and contract-level execution would need verified timestamped
  imports.
- `intraday/`, `options_research/`, `today/`, the versioned state API and the news first-seen archive are separate
  from the frozen daily experiment. Never relabel archive scenarios as forward evidence.
- Paper buttons record research observations and abstentions. Automatic forward trade-outcome resolution is not
  implemented. Offline builds and GET/replay requests do not collect data or create paper events.
- For any future change to registered strategy behaviour, create a new study/experiment version.
- `liquidity_screen.py` gates new research on 20 prior verified sessions and 80% window eligibility; failing sessions
  are excluded individually. Thresholds in `terminal_config.json` are research assumptions, not measured capacity.
  The ORB baseline (experiment A, traded in shares) is screened on share liquidity only (review C13,
  `run_intraday.research(execution="shares")`; `--options-gate` for options). Intraday research needs 20 complete
  sampled days; none existed on 2026-11-13, so mid-December at the earliest.

## Roadmap (user priorities, 2026-11-07)
1. **Operations:** done (scheduled evening refresh 2026-11-07; morning and close snapshots; collection jobs; lid-closed
   wakes tested 2026-11-17). The user agreed a full every-15-minutes collector isn't worth it unless a strategy needs
   intraday entries or limit-order fills; live minute bars came later for the pre-close view and intraday history.
2. **Jobs / macro data:** done except an expectation to measure a surprise against (see below).
3. **Thesis terminal:** built (Review and Daily thesis). Historical comparisons must show base rates, sample sizes
   and holdout results so the page can't manufacture confidence. Still open: interactive candlestick charts with
   news pinned to the time it hit (TradingView Lightweight Charts is the candidate library).
4. **Backtesting to develop our own edge:** now the companion app trading-backtester (below). The perp-native parts
   (perp entry times, 4 PM funding) were dropped with Kalshi on 2026-11-19.
- **Future data option (user, 2026-11-14):** Alpaca (free account + API key) offers minute bars back to 2016 as far
  as known; add it only if the user chooses to.

## Jobs / macro data
- Done: latest values from the BLS API v1 and FRED claims (2026-11-13); first-release values from ALFRED and FRED's
  official release dates (2026-11-14, with the user's FRED key). The BLS web page and calendar return HTTP 403; the
  Jobs study tab that used them was removed on 2026-11-19.
- Still open: an expectation to measure a surprise against. There is no free timestamped consensus; Kalshi's
  markets are no longer collected, so it would be manual entry. Never fabricate one.
- Use: mainly event risk. Jobs-morning overnight gaps run about 1.2x normal; the jobs direction test is null
  (p = 0.69). Release data is context, not a standalone trade signal.

## Rules
- Work directly in `C:\Claude\trading-research`, not in a git worktree. The runtime (`.venv`) and the data
  aren't tracked by git, so a worktree can't run the app or its tests. If a session starts under
  `.claude\worktrees`, move the session to this folder before doing anything else.
- No order placement, no broker integration and no trading endpoint of any service.
- Never fabricate data or consensus values. Unknown stays unknown (the app's existing principle).
- Use the best free sources, and don't let any number depend on one provider when a free independent check
  exists (user, 2026-11-07: "I don't want it to only come from Kalshi"). Prefer official sources (Cboe, FRED,
  BLS, the Fed).
- Sizing stays blocked until margin/liquidation is calibrated and a strategy has forward evidence. The Review page's
  sizing arithmetic on the user's own loss limit is not an approved size.
- Never edit `data/monitor/paper_events.jsonl`, `data/thesis/calls.jsonl`, `data/thesis/stance_log.jsonl`,
  `data/thesis/journal.jsonl`, `data/thesis/ideas.jsonl`, `data/thesis/preclose.jsonl`,
  `data/thesis/daily_archive.jsonl` or the intraday journals by hand (append-only, hash-chained; a new fact is a new
  record). Never change a frozen experiment (`data/monitor/experiment_lock.json`); a new experiment gets a new
  version.
- The backtester is the one source of edge statistics. This app reads its files read-only and never depends on
  them; never edit the backtester's repo from this chat.
- After every change: run the tests, commit with a clear message, then push `main` (`git push`) to the private
  GitHub repo https://github.com/ghzxdt/trading-research. Don't commit `data/raw/`, `output/`, `backups/`,
  `work/` or `.venv/` (already in `.gitignore`). Keep LF line endings (about 34 files have been CRLF since their
  first commit; keep those CRLF).
- The computer's clock is US Central; market times are Eastern (Central = Eastern minus 1 hour).

## How to run
- Desktop shortcut **Research** (beside the backtester's **Backtester**; older docs call it "Trading Research
  Control Panel") opens `desktop_app.pyw` from this folder, whose browser button opens the Review page.
  `setup_windows_tasks.ps1` updates whichever desktop shortcut already opens `desktop_app.pyw` and creates "Trading
  Research Control Panel" only if there is none.
- Dashboard: http://localhost:8766/review.html (Review; `index.html` redirects there). Binds to 127.0.0.1 only. Task
  **Trading Research Dashboard** starts the server at sign-in (`start_dashboard.py`). After a code change to an API
  route, restart that server (it loads the code once).
- Tests: `.venv\Scripts\python -B -m unittest discover -s tests` (339 tests, 2 skipped).
- Offline rebuild: `.venv\Scripts\python -B run_all.py --offline` (about 70 seconds).
- Online refresh: the control panel's **Run / Refresh data**, the pages' **Refresh data + validate**, or
  `run_all.py` without `--offline`. Until Cboe posts the session's VIX close (its file updated at about 9:30 PM ET
  on 16 Nov 2026), a refresh that logged the day's paper decisions would log them as data-blocked for good
  (`refresh_guard.py`). Since 2026-11-17 (user asked to refresh whenever they want) the panel and the pages then
  run a **data-only refresh** and say so: it downloads and rebuilds every page but appends nothing to the paper
  log or the stance log (`build_pipeline.build(record=False)`, `APP_NO_RECORD=1`). The evening task asks for a
  recording refresh only (`X-Require-Record`). `run_all.py` refuses with the reason unless given `--data-only`;
  `--skip-vix-guard` logs that day as data-blocked. The Cboe check retries on a fresh connection.
- Online builds also download FRED credit spreads (`data/raw/credit/`) and mega-cap earnings dates from Yahoo and
  Nasdaq (`data/raw/earnings/`); offline builds only read them. The thesis reads the backtester's
  `exports/trade_simulation.json` if present (`THESIS_BACKTESTER_EXPORT` overrides the path;
  `THESIS_BACKTESTER_EVIDENCE` the evidence file).
- The FRED API key (registered 2026-11-14 on the user's account, with their OK to accept FRED's terms) is in
  `.secrets\fred_api_key.txt`: git-ignored, excluded from the build fingerprint, outside `data/` so not in the data
  backup, covered by the user's manual copy of `C:\Claude`. Never print it, commit it or put it in a logged URL.
- Review checks: `.venv\Scripts\python -B research\holdout_checks.py` and `research\review_checks.py`.
- New machine: install Python 3.12 and Git, `python -m venv .venv`, `.venv\Scripts\pip install -r
  requirements-frozen-2026-11-12.txt`, then `powershell -ExecutionPolicy Bypass -File .\setup_windows_tasks.ps1`
  recreates the four data tasks, the dashboard task and the desktop shortcut (triggers start the next day).

### Scheduled tasks
All four data tasks also start two minutes after sign-in (user, 2026-11-13), so a night with the laptop off is
caught up at sign-in; each script decides what to do from the time of day. After a reboot nothing runs until the
user signs in (the tasks store no password). The collection scripts wait for a running build before writing (an
offline rebuild refuses to publish if `data/` changes underneath it).
- **Trading Research Evening Refresh** (Mon-Fri 8:15 PM Central, Tue-Sat 7:45 AM Central as the backstop before the
  open, and at sign-in; it started at 3:45 PM Central until 2026-11-17, when the user asked why it kept checking)
  runs `scheduled_refresh.py`: waits for the day's VIX close (at most 4 hours, exit 5, so the laptop can sleep),
  runs the app's refresh, checks that the page was published for that session and its stance logged (refreshing
  once more if not; exit 4 if the page still isn't published), then `git_backup.py` commits the data files
  (paper events, `data/thesis`, `data/futures`, `data/macro`) and pushes `main`. Log: `work\scheduled_refresh.log`.
- **Trading Research Market Snapshots** (Mon-Fri 8:00 AM and 3:05 PM Central) runs `market_snapshot.py
  --scheduled`: S&P/Nasdaq futures from Yahoo (`data/futures/futures_quotes.csv`), at 4:05 PM the Cleveland Fed
  inflation nowcast (`data/macro/inflation_nowcast.csv`), and Yahoo headlines for SPY, QQQ and IWM plus Fed releases
  (so the morning page has news). Kalshi collection ended 2026-11-19. A start outside 8:00-9:30 AM or 4:00-4:45 PM ET
  records nothing. Log: `work\market_snapshot.log`.
- **Trading Research Intraday Collection** (Mon-Fri 9:00, 9:30, 11:30 AM, 1:30, 2:50 and 7:10 PM Central) runs
  `scheduled_collect.py`: share-liquidity snapshots at 10:30, 12:30 and 2:30 PM ET (`liquidity_free.sample`); in the
  30 minutes before the calendar's close (`intraday.calendar.close_minutes`; 12:30 PM ET before a 1 PM early close)
  first the pre-close check, then minute bars and a fourth snapshot; at 8:10 PM ET minute bars, Yahoo hourly bars
  (`intraday_hourly.py`), the day's record in the **snapshot** liquidity journal (`liquidity_free.update`), then the
  backup of all of `data/` except `data/raw/` (`data_backup.py`, to `backups/data/`: 3 days plus one per week for 4
  weeks). The 10:00 AM ET run does nothing since options stopped. The snapshot journal is a declared weaker policy
  (spreads from 4 snapshots, not session medians), used only with `run_intraday.py research --liquidity-journal
  snapshot`; the strict `verified` journal stays the default. Yahoo keeps only about 5 days of minute bars, so this
  builds the intraday history. A minute-bar writer lock left by a dead run is removed automatically and logged in
  `data/intraday/v1/lock_recoveries.log` (since 2026-11-18; one such lock blocked collection Nov 15-18). Log:
  `work\intraday_collect.log`.
- **Trading Research Live Minute Bars** (Mon-Fri 8:28 AM Central and at sign-in): **what is gathered minute by minute
  (user, 2026-11-18: "poll yahoo"; revisit any time).** The list is `collection.live_minute_symbols` in
  `terminal_config.json` (now SPY, QQQ, IWM; read by `terminal_config.live_minute_symbols`). To add an ETF or stock:
  it must first be an active instrument in that file's `universe` (add an entry if it is new to the app; the config
  refuses single names, so a stock needs that rule changed first), then add it to `live_minute_symbols`; at most 20,
  since one Yahoo request a minute covers them all. The next weekday's run picks up a change. `live_minute.py` polls
  5 seconds after each minute from the open to just after the calendar's close, holds the laptop awake, and stores
  each completed regular-session bar in `data/intraday/v1/live/<date>.jsonl` (`store.ingest_live`, hash-chained, own
  lock) with its receipt time: "observed_live" only if first received within 120 seconds of the bar's close,
  otherwise "retrieved_archive"; changed values are revisions. `store.load_bars` merges these journals. Bars
  received while a build runs are held and written after it. Status: `data/terminal/live_minute_status.json`
  (System status's "Live minute bars" row); log `work\live_minute.log`. Yahoo's bars are free and indicative and
  may be delayed.

### Sleep, wake and backups
- All four data tasks have "wake the computer to run" set, and the user enabled **Allow wake timers** on mains and
  battery (2026-11-13). A wake only works from sleep: on Fri 2026-11-13 the laptop was shut down from 1:17 AM to
  9:25 PM Central, so every daytime run was missed. For an unattended day the laptop must be left asleep or on, not
  shut down (shutdowns also cost the daytime runs of Nov 16, 19 and 20).
- Lid closed is fine (checked 2026-11-15, **tested 2026-11-17** with temporary copies of this app's evening task and
  the backtester's weekly task): this ThinkPad uses classic S3 sleep, closing the lid means Sleep on mains and
  battery, and Windows wakes it about 30 seconds before a task's time with the network already up. Each scheduled
  script (`unattended.py`, since 2026-11-15) waits up to 3 minutes for the network and asks Windows to stay awake
  until it finishes (otherwise a timer-woken laptop goes back to sleep after about 2 minutes). Keep it out of a bag
  while a wake is due, and prefer mains: the evening refresh can hold it awake up to 4 hours waiting for the VIX close.
- No cloud sync (user, 2026-11-13): the user backs up `C:\Claude` by hand; `backup_targets.json` lists no folders.
  This project's Claude chats are copied to `conversations/` (git-ignored) by the hub task **Claude Conversations
  Copy** (`C:\Claude\sync_conversations.ps1`).
- The Data quality tab checks Yahoo's SPY/QQQ daily returns against FRED's S&P 500 and Nasdaq-100 closes
  (`crosscheck.py`; online refreshes cache the FRED series in `data/raw/crosscheck/`).

## Companion app
**trading-backtester** (`C:\Claude\trading-backtester`, private repo https://github.com/ghzxdt/trading-backtester)
reads this app's data read-only and tests indicator rules; its exports feed the Daily thesis and the Review page.
Never make this app depend on it. Requests from its chat arrive relayed with the user's approval quoted.

## History
- 2026-11-05/06: original 4-tab app built in a Claude session (scratch workspace; original copy preserved in
  `backups/original_20261106T064353Z.zip`).
- 2026-11-06/07: audited and repaired in Codex at
  `C:\Users\gzdt\Documents\Codex\2026-11-06\x20-au\outputs\trading_research` (5 evaluation tabs, control panel).
  Portable archives (`trading_research_desktop_2026-11-07.zip` etc.) remain in that `outputs` folder.
- 2026-11-07: moved here, git initialized, quant review in `docs/QUANT_REVIEW_2026-11-07.md`. Evening refresh task
  set up; private GitHub repo created; the evening task pushes `main` to it.
- 2026-11-08 to 18: Daily thesis, Intraday and Macro tabs; the backtester hand-offs (details in `LOG.md`).
- 2026-11-19: the trim list (GEX/DIX, Jobs study, Kalshi and perps, options data removed; universe trimmed to 7) and
  the Review front page. 2026-11-21: Review page v2.

## Key facts from the review (details in docs/QUANT_REVIEW_2026-11-07.md)
- Only normal-drop long 5 survives the untouched SPY 1993-2009 holdout; the three rally shorts don't.
- Normal-drop long 5 is mostly beta: +0.34%/trade gross vs +0.25% for random entries in the same windows.
- The review's Kalshi perp facts (trading hours, daily 4 PM funding, spreads, fees) are in that document; Kalshi
  was dropped on 2026-11-19.
- Cboe posts the VIX close well after 4:30 PM ET, so evening jobs must wait for it. Measured: `VIX_History.csv`
  changed at 9:30 PM ET (Nov 16) and 9:11 PM ET (Nov 17), and about 10 PM ET on Nov 9; the VIX3M file at about
  5:31 PM ET (Last-Modified headers and the evening task's log).
- At the same total volatility, holding QQQ beat every Lead's yearly return in 2010-2026 (the backtester's
  2026-11-18 review). The case for a Lead is its result per trade as an add-on, an overlay or the 3x ETF during the
  trade, not a replacement for holding.

## Open decisions (user)
- Risk limits: the user has set no max drawdown or max leverage (2026-11-07); the goal is good trades and large
  gains. Show outcomes at several leverage levels instead of one allowed size. Sizing stays blocked.
- Not decided yet (the Review page assumes neither): a maximum loss per trade, and whether QQQ trades add to a held
  position or stand alone.
- Git commit identity is still the local placeholder `trading-research (local)`, so commits on GitHub don't link
  to the user's account (ghzxdt). Change it only if the user wants that.
