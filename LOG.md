# Trading research log

## Open
- Backtester hand-off, second batch (13 review findings A1-C13, received 2026-11-18). Step 1 (A2, A3, A5, B7,
  C10, C11, C12) done 2026-11-18. Step 2, in this order: A1, B6, C9, A4, B8, C13 (user's go-ahead relayed from the
  backtester chat; check with the user on any new data provider and on visible changes to the daily screen). Details in the backtester chat's message; reviews in
  `C:\Claude\trading-backtester\docs\reviews\APP_REVIEW_2026-11-18.md` and Codex's 2026-11-14 outputs.
- Second batch step 2 continues: B8, C13.
- The options import lock (`options_research/core.py` `_writer`) has the same no-recovery pattern the minute-bar
  lock had. Manual imports only, so lower risk; same fix if wanted.
- Reminder from the hand-off: daytime jobs only run while the laptop is asleep or on, never shut down.

## 2026-11-18 (night): replay timing (review A4)
User's go-ahead relayed by the backtester chat ("then A4, B8 and C13"). A replay at moment T now shows only what
was published by T:
- First-release vintages (`alfred.known_day`): a vintage dated today exists from 8:30 AM ET, when BLS and the
  claims report publish (a replay at 8:00 AM used to show the 8:30 numbers).
- FRED series (`data.fred`): in a replay, weekly and monthly series are held back by 1.3 times their observation
  spacing (NFCI publishes the Wednesday after its Friday; the Sahm rule with the next jobs report), since their
  release times aren't modelled; daily series keep the one-day rule. Live builds are unchanged.
- Earnings dates and the earnings calendar: a replay refuses a snapshot downloaded after its moment.
- `risk.latest_spreads` takes the moment and ignores later liquidity samples.
349 tests.

## 2026-11-18 (night): shorter daily screen (review C9); first missed records written
User: "Yes, as proposed" (relayed by the backtester chat).
- Tonight's evening refresh (9:33 PM ET) wrote the first B6 records as the dry run predicted: 8 "missed" stance
  records (Nov 9, 10, 11, 16) and the Nov 18 stances (SPY "abstain: no Lead"; QQQ had no fired rule). Chain ok.
- Daily thesis: the call, registered signals (with evidence cards), the paper ticket, VIX, events and earnings
  (new line: a weekend or holiday before the next open) and risk by leverage are shown first. The paper book's
  history and trend/credit/rates/history fold inside their cards; the pre-close check, System status (summary line
  names what needs attention), news, overnight, earnings calendar, hourly base rates and 0DTE are folded cards.
- GEX tab: the GEX-below-zero size result is context only, citing Codex's regime-matched check (1.18x, calendar-
  year interval 0.90-1.43, which includes no effect); the plain luck test's verdict is still quoted.
- Checked in the browser: section order as planned, no console errors. 345 tests.

## 2026-11-18 (evening): opportunity ids (review B6)
User: "Yes, go ahead" (relayed by the backtester chat).
- `thesis/opportunity.py`: id `<close>:<ETF>:<rule>:<policy>:<evidence sha12>`, derived from fields the logs keep.
- New stance records carry `opportunities` with the page's disposition. Calls get `opportunity_ids` and a
  `relation` from the stance record of their close and the ETF's index (inverse ETFs flip the view). Notes get
  `opportunity_ids` for the close the page showed. Paper-book trades (and pre-close trades) carry `opportunity_id`.
- Missed closes: a recording build appends a "missed" stance record (`recorded_after_entry`: true) for any
  session since the log began with no stance before its next open; summaries list them and don't score them.
  Dry run on a copy of the real log: tonight's refresh will add 8 (Nov 9, 10, 11 and 16, SPY and QQQ) before
  the Nov 18 stances (SPY "abstain: no Lead", QQQ "abstain: closing-price Lead only").
- Older records are untouched. Dashboard restarted so calls and notes link. 345 tests; page checked, no errors.

## 2026-11-18 (evening): exit levels on calls (review B7)
User: "yes, add the exit level to calls" (relayed by the backtester chat).
- Call form: optional "Exit level: ETF / closes below or above / price" (the ETF defaults to the call's own; the
  side to below for a long, above for a short). Stored with the call before entry, in new schema 2 records; it
  can never be added or changed later. Flat calls can't have one.
- Scoring: the call ends at the next session's open after the first daily close that breaks the level (from the
  entry day on), or at the horizon's close, whichever comes first; "ended_by" says which. Chosen because a trader
  who waits for the close can act at the next open without a pre-close estimate; stated on the page.
- The fixed-horizon result stays beside it (column and "Fixed-horizon mean"), so calls compare with the stance log.
- Dashboard restarted so the form records exit levels. No test call written to the real log. 341 tests.

## 2026-11-18 (evening): live minute bars from Yahoo (review A1)
User: "poll yahoo" (here) and "Yahoo, no account" (relayed by the backtester chat); what is polled must be easy to
revisit.
- `collection.live_minute_symbols` in `terminal_config.json` (SPY, QQQ, IWM) is the list; CLAUDE.md says how to add
  an ETF or stock. New scheduled task "Trading Research Live Minute Bars" (Mon-Fri 8:28 AM Central and at sign-in),
  registered on its own so tonight's other runs were not moved; first run Thu Nov 19.
- `live_minute.py` polls 5 seconds after each minute through the regular session and stores completed bars with
  their receipt time in per-day journals `data/intraday/v1/live/<date>.jsonl`. Writing to the 92 MB main journal
  costs about 10 s a call (verify 3.2, deepcopy 2.0, normalize 1.1, canonical twice), too slow every minute.
  "observed_live" only when first received within 120 s of the bar's close; later is "retrieved_archive";
  changed values are appended as revisions. It holds bars in memory while a build runs.
- `store.load_bars` merges the live journals; an archive copy identical to an earlier live version is left out
  of the view (nothing relabelled); a different one is a real revision and wins after its receipt time.
- `features.snapshot`: `availability_bases` now covers this session's regular-hours bars (it spanned the whole
  history, so every intraday paper decision would have been data_blocked; `paper.jsonl` has no records, so
  nothing recorded changes); `history_availability_bases` keeps the old view; limitations name Yahoo's feed.
- System status row "Live minute bars": tickers, polls, bars received live or late, gaps, a missed day.
- Checked with Yahoo after the close (nothing stored): 390 bars each for SPY, QQQ and IWM, 9:30-3:59 PM ET,
  all labelled "retrieved_archive" as they should be. 338 tests.

## 2026-11-18 (late afternoon): review fixes, step 1 (A2, A3, A5, B7, C10, C11, C12)
User's go-ahead relayed by the backtester chat ("send instructions for both 1 and 2 to get carried out in research chat").
- A2 pre-close check, schema 2: window = the 30 minutes before the exchange calendar's close (`intraday.calendar.
  close_minutes`; 1 PM ET on Nov 27); Yahoo's last-trade time and age; the page's evidence check recorded, and a
  session with unusable evidence gets no paper trades. `scheduled_collect.slot_for` and the same-day option
  snapshots follow the same close (on Nov 27 the 12:30 PM ET run is the pre-close run; later runs collect bars).
  Today's 3:50 PM ET check ran on the old code (schema 1).
- A3 same-day options settle on the session's raw close (`zero_dte.update_raw_closes`, saved by the 8:10 PM ET run
  from Yahoo unadjusted closes); a day waits until its raw close is saved.
- A5 `/api/v1/thesis/live` reports the export on disk; the page shows "Evidence state: current" or "Stale
  evidence". Checked live after restarting the dashboard: current (sha256 793a58bd49ec).
- B7 call scoreboard labelled fixed-horizon (invalidations shown, not applied). Structured invalidations would
  change the call form, so that is the user's call.
- C10 tabs "4-rule backtests" and "4-rule paper log", page headings "Daily thesis" and "Intraday", the paper
  ticket, pre-close paper trades and the call log say which paper record they mean.
- C11 a daily close counts 15 minutes after the calendar's close everywhere (the Intraday tab waited until 8 PM
  ET); "since the last close" starts at 1 PM on early closes; the Intraday day type says it is SPY's; the nowcast
  goes stale after 96 hours; the futures note names its 16-hour limit beside System status's 30 hours; the
  page labels VIX/sqrt(252) as a trading-session rule of thumb.
- C12 OCC volume is two-sided: all 152 series-group totals (SPY and QQQ Nov 17, IWM Nov 16) were even while
  single rows were even about half the time; halving kept, and `parse_occ` now refuses a file with an odd total.
333 tests. Pages checked in the browser: no console errors.

## 2026-11-18 (afternoon): daily archive, rule-exit scores, evidence cards, IWM history, rounding ties
User: "Build all three" (backtester hand-off items 4, 2 and 5).
- **Daily archive** (`thesis/archive.py`, `data/thesis/daily_archive.jsonl`): one append-only, hash-chained record
  per close with the stance and evidence status, regime condition, VIX, VIX3M and their ratio, trend, credit,
  rates, breadth, events and earnings in the next 5 sessions, news count, futures (when a snapshot exists), movers
  and each rule's state and distance to its trigger. Written with the stance log by recording builds only, before
  the next open; the first record comes with tonight's evening refresh. New System status row.
- **Stances scored to the rule's own exit** as well as the fixed 5 sessions (new column and summary line; each
  long record separately, the paper book's simulation).
- **Evidence cards** from `exports/evidence.json` beside each rule that fired or is within 3% of its trigger
  (next-open entry). Checked on the rebuilt page: 6 cards (SPY and QQQ RSI(2) fired, plus one near rule), no
  console errors, footer says the cards come from the same simulation run as the export. Wording is the
  backtester's: historical tendencies with sample sizes and intervals, not probabilities.
- **IWM from 2000** in `data/raw/etfs_long.csv` (downloaded and validated: 6,659 sessions from 2000-05-26).
  `build_long` only gains `iwm_*` columns: SPY, QQQ and VIX columns are identical with and without IWM. The
  frozen experiment's probe moved in the sixth decimal of study 7 and 4 rows of one count, from the usual
  re-download drift of SPY/QQQ adjusted closes (up to 1.5 parts per million), not from IWM.
- **Rounding ties** in the date cross-check: a date that differs from the backtester only because its verdict
  flips when that close moves 10 parts per million is tolerated, listed, and named in the cautions; any other
  difference still blocks the stance. 329 tests.

## 2026-11-18: minute bars were blocked for three days by a stale writer lock; fixed and backfilled
- Reported by the backtester's chat (user: "we need to fix that problem asap"). The Sun Nov 15 11:16 PM ET
  collection was cut off when the laptop was shut down at about 10:17 PM Central, leaving
  `data/intraday/v1/.writer.lock` (PID 10148). The lock had no way to tell its owner was dead, so every run since
  failed per symbol ("An intraday writer is active"): 0 of 16 on Nov 17 at 5:39, 5:41 and 8:10 PM ET. System
  status still said "ok" because it judged the job by when it ran.
- Checked PID 10148 was gone and no collector was running; moved the lock to
  `work/stale_intraday_writer_lock_2026-11-15_pid10148.txt`; ran the bars collection once at 2:21 PM ET: 16 of
  16. Archive now: Nov 16 11,949 bars and Nov 17 12,390 (16 tickers each, like earlier days), Nov 18 through
  2:22 PM ET. Nothing lost (Yahoo serves about 5 days).
- Code: `intraday/store.writer_lock` removes a lock whose writer is certainly gone (no process with that PID, or
  the process now holding the PID started after the lock was written, since Windows reuses PIDs; an empty lock
  after 10 minutes) and logs it in `data/intraday/v1/lock_recoveries.log`; a live or uncheckable owner is still
  respected (`app_control.process_started` is new). The test kills a real writer mid-run.
- System status's Intraday row now judges data delivered: 0 tickers collected is red with the first error,
  partial is amber with the tickers missed, and the row is amber whenever the archive's newest bar is older
  than the latest completed session.
- TNA's "Bar timestamp must be aligned to its interval" (Nov 17 evening) came from one off-minute row in Yahoo's
  reply; it collected fine in the backfill. The collector now skips such rows and lists them
  (`bars_skipped_off_minute`) instead of losing the ticker's batch. 324 tests.

## 2026-11-18: backtester Lead v3 read correctly
- The backtester's export is now Lead v3 (development window fixed at 2026-11-13, a forward record after it, and a
  new verdict "Forward below band"). Checked: the page loads it (status ok, cross-checks match) and sees the same
  two QQQ next-open Leads; tonight's page is flat (QQQ RSI(2) fired, a Lead only at the close).
- Item 1: the "provisional Lead" caution on a long call only appeared for v2; it now covers v3 too and names the
  fixed development window (`build.verdict_caution`).
- Item 3: a rule rated "Forward below band" is no longer silent. Fired: flat with its own headline (status
  `forward_below_band`), listed under "Fired, but not a setup now", and the stance record carries
  `forward_below_rules`. Not fired: a caution. The stance rules are unchanged (only "Lead" counts). 318 tests.

## 2026-11-17 (night): lid-closed wake test passed; duplicate desktop icon removed
- User: "Yes, test now" / "inlcude backtester test too". Two temporary tasks with the exact settings and principal
  of Trading Research Evening Refresh and Trading Backtester Weekly Run (wake to run, battery allowed, signed-in
  only), at 10:22 and 10:32 PM Central; lid closed at about 10:19 PM, on mains.
- System log (Power-Troubleshooter 1): wakes at 10:21:32 and 10:31:32 PM, each naming its test task; the lid
  opening at 10:51 PM was a USB wake. Windows wakes about 30 seconds early, so Wi-Fi was already up.
- This app's copy ran the real `unattended` code: network up at start, GitHub reachable (read-only `git ls-remote`),
  a line every 15 seconds for the 3-minute keep-awake hold with no gap, then sleep at 10:25:02, the second it
  released. The backtester copy ran like `run_weekly.ps1` (hidden PowerShell, the same Python): GitHub reachable at
  5 seconds, when the real run pushes; back to sleep at 10:33:40, about 2 minutes after the wake. Its real run
  takes about 6 seconds, well inside that. Both test tasks removed.
- Why two desktop icons: re-running `setup_windows_tasks.ps1` earlier tonight (for the 8:15 PM schedule) created
  its own "Trading Research Control Panel" shortcut next to the existing "Research" one (same target, same icon).
  The new copy went to the Recycle Bin; the script now updates any shortcut that already opens
  `desktop_app.pyw` and only creates one when there is none.

## 2026-11-17 (later): evening task starts when Cboe usually posts
- User: "when does that information usually get posted? i feel like constant checking is useless". Measured from
  Cboe's Last-Modified headers and the evening task's log: `VIX_History.csv` changed at 9:30 PM ET (Nov 16),
  9:11 PM ET (Nov 17) and about 10 PM ET (Nov 9). The 3:45 PM Central start meant about 4.5 hours of checks, and
  since 2026-11-15 the task holds the laptop awake while it waits.
- Evening Refresh now starts Mon-Fri 8:15 PM Central (9:15 PM ET), stops waiting after 4 hours (exit 5), and has a
  Tue-Sat 7:45 AM Central backstop that forces the refresh at 9:00 AM ET if Cboe never posted. Sign-in trigger
  unchanged. Tasks re-registered from `setup_windows_tasks.ps1`. 316 tests.
- Tonight's run (old schedule) logged Nov 17's decisions at 9:41 PM ET (VIX 25.46), published the page, logged the
  stance and pushed (`de87559`).
- **Lost: Mon Nov 16.** The laptop was shut down from Sun 10:17 PM to Tue 4:37 PM Central, so Monday's paper
  decisions and stance were never logged (now past Tuesday's open) and Monday's and Tuesday's daytime collection
  didn't run. Sleep, not shut down, is what lets the tasks run.

## 2026-11-17: refresh at any time (data-only refresh); Cboe check retries
- User got "Couldn't check whether Cboe has posted the VIX close for Tue Nov 17 (Connection aborted ...
  RemoteDisconnected)" from Run / Refresh data and asked for a refresh that works whenever they want.
- Two causes. (1) The dashboard server keeps one requests session for hours; Cboe closes idle keep-alive
  connections, so a check after a pause failed. The evening task's log shows the same: every other 15-minute check
  failed. Fixed: `refresh_guard.make_session()` retries a GET on a fresh connection (tested against a local server
  that drops the second request on a connection). (2) Cboe now updates `VIX_History.csv` late (the Nov 16 close
  appeared at about 9:30 PM ET; at 9:06 PM ET on Nov 17 the file still ended Nov 16), and until then the guard
  refused every manual refresh.
- New: a **data-only refresh**. When the guard would block, the panel and the pages' refresh button run it
  instead and say so: everything downloads and every page rebuilds, but nothing is appended to the paper log or
  the stance log. The evening task still asks for a recording refresh and logs the day once Cboe posts.
  `run_all.py --data-only` from the command line. 6 new tests (315).
- Live check at 9:11 PM ET: the panel's call returned the data-only note, the build published in about 2.5
  minutes, the paper log stayed at 18 lines and the stance log at 6. The page stayed at the Nov 16 close because
  Yahoo's daily history had no close for Nov 17 yet (open and volume only); the app drops such a row.

## 2026-11-15: two-app review; scheduled runs survive a wake from sleep
- **Two-app review (user asked; the backtester chat had finished).** The research app (116 Python files, about
  18,300 lines) collects about 15 sources and keeps the forward record; the backtester (20 files, about 2,400
  lines) turns ideas into evidence. They meet in two places: the backtester reads 3 of this app's raw files
  (daily ETFs and VIX), and this app reads one export. Checked live: this app's paper book rebuilds all 4,800
  backtester ETF trades (2026-11-14 run) with the same entry and exit dates, returns within 0.005 bp, and all
  1,275 signal days match. Claude's view: keep both, but put new work into the backtester (forward scoring since
  Nov 8, a regime filter, event-day and gap studies on data this app already collects); keep this app to
  collection and reliability. Every call rests on two overlapping QQQ oversold rules (130 trades since 2010, at
  most about 8 a year), and since 2010 neither beats buy-and-hold per unit of drawdown (0.30 and 0.38 against 0.49). The
  rules and exits are coded in both apps; a new backtester exit needs a copy here or the paper book skips it.
- **Wake from sleep.** Laptop checked: S3 sleep, lid and power button = Sleep on mains and battery, wake timers
  allowed, no hibernation, tasks allowed on battery, so the lid can be closed. Found: Saturday's sign-in runs
  (3:46 PM Central, 2.5 minutes after boot) had no network, so bars, Cboe and the GitHub push all failed. New
  `unattended.py`: the collection, snapshot and evening-refresh scripts wait up to 3 minutes for the network and
  hold a "system required" request while they run, so a timer-woken laptop doesn't fall back asleep mid-job.
  7 new tests (309). Still unproven: an actual timer wake on this laptop.

## 2026-11-14: backtester evidence is now Lead v2
- The backtester re-judged its trade simulation with Lead v2 (its commits 25350c7, 213f39e; report
  `2026-11-14-084052-trade-simulation`, data through 2026-11-13). Hand-over note read from the shared notes folder.
- This app: shows v2's edge test (excess over every same-length trade, p, q, quarters) and the export's verdict
  definition; the drawdown caution uses the scaled ("risk_matched") benchmark; a long call carries a caution that
  v2 Leads are provisional (1993-2009 helped choose the signals). Paper book: records logged under v1 keep v1's
  exits, marked "logged under v1; now No edge" where the verdict changed. 2 new tests (291).
- Result: next-open Leads are QQQ Bollinger and QQQ RSI(14) (5-day-average exit) only. SPY has none, so SPY's
  stance will log flat. "What would change the call" now lists only those two QQQ levels.
- Idea ledger: new result lines on ideas 1 and 2 with the v2 figures. Playbook Route A and B re-rendered with v2.
- **Later the same day (user chose Yahoo hourly, no account):** `intraday_hourly.py` downloads Yahoo's hourly
  bars (730 sessions, Dec 2023 on) for SPY, QQQ and IWM and keeps adding to them each evening; the Daily thesis
  shows gap-fill and first-hour base rates by gap size with 90% intervals. Findings at first look: gaps over 0.5%
  filled the same day only 27-37% of the time, 0.2-0.5% gaps 53-72%; after 10:30 the day kept the first hour's
  direction about half the time (49-59%), so the first hour alone says little. The first version of that measure
  counted the first hour twice (about 70%) and was corrected before commit.
- First-release values (`thesis/alfred.py`) built and tested. The FRED API key was requested on the user's
  account through Claude in Chrome (user: "Yes, I agree" to FRED's terms) and saved to `.secrets\fred_api_key.txt`.
  Live: 5 series, every vintage since 2015; e.g. May payrolls first announced +172K, now +63K; typical payrolls
  revision about ±69K. FRED's next official dates (jobs Dec 4, CPI Dec 10) match the app's calendar.
- **Macro tab** (user agreed to a separate tab): releases and first-release tables moved there from the Daily
  thesis, plus fed funds and target range, 10y-3m, 10y breakeven, NFCI, St. Louis stress index, real-time Sahm
  rule, and a Cboe-vs-FRED check of the VIX close (500 of 500 matched). The old tab label "Jobs & macro" is now
  "Jobs study" so the two aren't confused. 302 tests.
- **Future data option (user, 2026-11-14):** Alpaca, a free account with an API key, offers minute bars back to
  2016 as far as known. It would give minute resolution and a longer history for the intraday base rates and the
  15-minute opening-range rule. Not set up; add only if the user chooses to. Claude's view (2026-11-14): worth
  it before any intraday rule or the 3:50 PM flip rate is studied, since it turns months of waiting into a
  10-year history; not needed for the daily thesis.
- **Still open (user decision):** whether to measure a CPI "surprise" against the Cleveland Fed nowcast and
  Kalshi's CPI/payrolls markets, which are already collected (forward only; there is no free expectation history).

## 2026-11-13: review and first fix
- Read-only review of the app (user's prompt). Findings to act on, in order: (1) the page and the stance log call
  "long" when any pricing of a fired rule is a Lead, including "buy at the signal close", which has passed (SPY
  RSI(2) < 10 is a Lead only at the close); (2) the page says Flat when the export is missing and Long when a
  rule's dates mismatch, while the stance log skips both; (3) `scheduled_refresh.py` stops once paper decisions
  exist, so a failed page build is never retried and still exits 0; (4) a stale export still "matches" (dates
  only, no price or fingerprint check) and a malformed strategy row crashes the thesis build; (5) no liquidity
  sample has ever been recorded, so the snapshot gate can't open before about Dec 14-15 (not Dec 8).
- Fixed: `build_pipeline.source_manifest` no longer counts `conversations/` as app source, so the chat copy
  can't make a build refuse to publish. 1 new test (252 total).
- Thesis playbook for the user: `docs/THESIS_PLAYBOOK.pdf` (routes to a thesis, information gaps, 0DTE plan).
- **Built the same day (user: "lets do all of those"), playbook gaps 1-4 plus the journal and ledger:**
  - Stance rules v2 (`thesis/eligibility.py`, used by the page and the stance log): long needs a next-open Lead;
    close-only Leads show as "fired, but not a setup now" and log flat; "No call" when the evidence can't be
    used. The user agreed to about 10 days for stale evidence; implemented as a caution after 10 days and unusable
    after 45, because the simulation is still re-run by hand and a hard 10-day cut would blank the page within a
    week. New stance records carry `"stance_rules": 2`; the four existing records are v1 and untouched.
  - `signals.validate_export`: a damaged export is "invalid" instead of crashing the build.
  - `scheduled_refresh.py` step 5: checks the published page and the stance log after the decisions exist,
    refreshes once more if incomplete, exits 4 if the page still isn't published.
  - System status card (`thesis/ops.py`). It shows Nov 9-11 as missed paper-decision days.
  - Tasks set to wake the laptop; the power plan's "Allow wake timers" still has to be enabled by the user.
  - Journal and Idea ledger on the Daily thesis (new `/api/v1/thesis/note`, `/idea`, `/idea/update`,
    `/journal`). Ledger seeded with 11 ideas from what has been tested so far and the playbook's open ideas.
  - Optional "leans on" tags on calls, with a by-tag table once calls are scored.
- **Then (user: "build everything"):** paper ticket and paper book; pre-close check at 3:50 PM ET logged
  forward; same-day option snapshots (Cboe delayed feed) and one-day VIX history; news card and morning
  headline collection; futures caution; bad-print filter; tasks wake the laptop and also run at sign-in;
  dashboard starts at sign-in. Full list with reasons: `docs/CHANGES_2026-11-12_13.md`. 284 tests.
- **Check on Fri Nov 13 (first live runs):** `work\intraday_collect.log` for "Same-day options: {'saved': 3...}"
  at 10:00 AM ET and "Pre-close check: {'recorded': True...}" at 3:50 PM ET; the System status card for
  snapshots and liquidity samples; whether the laptop woke from sleep for a run.
- **Fri Nov 13 result:** the laptop was shut down 1:17 AM to 9:25 PM Central, so no daytime run happened (still
  zero liquidity samples, option snapshots, pre-close checks and market snapshots). At sign-in the catch-up ran:
  Friday's paper decisions logged before entry, page published, stance logged (v2 records, both flat), data
  pushed. The first real daytime test is now Mon Nov 16, if the laptop is asleep or on.
- **Evening of Nov 13 (user: "finish please"; asked why there was no earnings calendar):** rolling two-week
  earnings calendar, large-holding movers flag, latest release values (BLS API v1 and FRED claims). 289 tests.
  Sources checked live: Nasdaq calendar 40 companies over 10 sessions; Broadcom -4.8% flagged for Nov 13.
- **Still open:** backtester items (gap split, regime filter, leveraged-ETF pricing, weekly automatic
  simulation) wait until the backtester chat ends; the user wants the two-app review revisited then.
  First-release values and a surprise measure (needs the user's free FRED key and an expectation source).
  Intraday base rates wait for data. A second source for the VIX close.
- **Idea kept in mind, not built (user, brainstorm):** automatic paper trades in thinkorswim as a live running
  log. paperMoney has no supported API for automated orders as far as known, and this project's rule is no
  broker integration; options are a daily "ticket" the user enters by hand, or a paper-trading API built for
  automation, which would need the user to change that rule and open the account.

## 2026-11-12: moved to the reset laptop (`C:\Claude\trading-research`, user `timothy`)
- Restored from `C:\Claude\Claude-Backup-2026-11-12`. Python 3.12.10 and Git installed; `.venv` rebuilt from
  `requirements-frozen-2026-11-12.txt`; 251 tests pass. Path fixes: `runtime.json`, `CLAUDE.md`, and
  `thesis/signals.py` (backtester export is now the sibling `..\trading-backtester` folder).
- `setup_windows_tasks.ps1` recreated the Evening Refresh, Market Snapshots and Intraday Collection tasks and the
  desktop shortcut (first runs Fri Nov 13). Stale worktree `.claude\worktrees\wizardly-allen-40e985` removed.
- What the old laptop did Nov 9-12: it only ran jobs late in the evening (off or asleep during the day).
  The evening refresh never finished (Cboe's VIX file reset the connection on Nov 9; Nov 10 no run; Nov 11
  and 12 started but never got further), so no paper decisions or page stances were logged for Nov 9-11 and
  nothing was pushed after Nov 8. Market snapshots were skipped every day (outside their windows), so no Kalshi,
  futures or nowcast data exists for Nov 9-12. No daytime liquidity samples or option chains. Evening minute
  bars were collected Nov 9, 11 and 12 (Nov 12 missed TNA and LABD). Backups stayed local (no Google Drive).
- 00:37 ET Nov 13, from the new laptop: `scheduled_refresh.py` logged the Nov 12 paper decisions before entry and
  the page's stances (SPY and QQQ flat), then pushed the data (05542c2). Its page build was refused because
  `setup_windows_tasks.ps1` was edited mid-build; an offline rebuild then published the Nov 12 page. The thesis
  now reads the backtester's Nov 9 export from the sibling folder. Shortcut uses `assets\app.ico`.
- No Google Drive (user, 2026-11-13): "keep saving all our conversations to the claude folder and i will
  manually back up". Cloud targets removed. Chats for every project are now copied into each project's own
  `conversations/` folder by the hub task **Claude Conversations Copy** (`C:\Claude\sync_conversations.ps1`,
  nightly 10 PM, at sign-in and on unlock; each folder has a `.gitignore`, so transcripts never reach GitHub).

## Intraday extension implementation (2026-11-07)
- Added Today as the landing workspace and `/api/v1/thesis_state`, preserving existing tabs and controls.
- Added the sixteen-instrument shared universe, minute-bar archive/replay, VWAP/ORB/price levels,
  indicative current options chains, verified contract imports/P&L and causal level diagnostics.
- Added a separately frozen intraday paper journal and bounded historical ORB scenario registry.
- Added verified 20-session liquidity imports and an 80% joint share/options research prerequisite;
  missing free-feed historical quotes fail closed. The initial SPY prototype is labeled pre-qualification.
- Enforced a separate single-name research track: NVDL/TSLL cannot reuse index baseline parameters.
- Native leveraged-product prices are not charged another hypothetical decay haircut; no universal
  realized-volatility-only break-even holding period is claimed. Current baseline exits within the session.
- News now has a first-seen archive; existing latest-headline sources remain available. GET/replay is read-only.
- Free-feed collection received minute bars and chain indications for all sixteen configured instruments.
  Those archives are not contemporaneous historical fills or a demonstrated edge.
- Defaults retain unavailable risk budgets and blocked recommended sizing. No orders or new scheduled jobs.
- Existing frozen experiments and user data changes were preserved; code/data scope remains separated.
- Operator guide: `docs/INTRADAY_TERMINAL.md`.

## 2026-11-08
- Scheduled the intraday collector (`scheduled_collect.py`, task **Trading Research Intraday Collection**, Mon-Fri
  2:50 PM and 7:10 PM Central). The Codex release added collection but no schedule, and Yahoo keeps only ~5 days
  of minute bars, so unattended days were being lost. 6 new tests (216 total).
- Off-machine data backup (user approved): `data_backup.py` runs after the evening collection and zips `data/`
  except `data/raw/` to `backups/data/`, plus a cloud folder from `backup_targets.json`. No cloud app is
  installed yet (the OneDrive folder is a leftover; OneDrive isn't installed), so archives stay local until the
  user installs Google Drive for desktop or iCloud for Windows. Google Drive installed 2026-11-08; the first
  off-machine copy landed in G:\My Drive\Trading Research Backups (4.5 MB).
- Started the companion **trading-backtester** app (separate repo). First run: 90 daily indicator tests; oversold
  mean reversion (RSI(2) < 10, RSI(14) < 30, close below the lower Bollinger band) were candidates on SPY/QQQ
  and held on the 1993-2009 holdout. EMA touches, MACD crosses, breakouts, volume spikes and the 200-day state
  showed no evidence. RSI(2)'s next-day effect is mostly overnight (+19 bp from the close vs +7 bp from the next
  open), which favors a 4:05 PM perp entry, but that is below the 24 bp Kalshi taker round trip.
- Daily thesis tab (`thesis/`, `run_thesis.py`; landing page `thesis.html`). Regime (trend, VIX and term
  structure, FRED credit spreads, breadth, yields, SPY after days in the same pre-declared trend x VIX bucket),
  the backtester's oversold rules recomputed with its ETF evidence and a date-by-date definition check (all six
  rule/ETF pairs match), fixed stance rules (long candidate only when a Lead rule fires; flat otherwise; never
  short), CPI/jobs/Fed days with SPY's typical move, mega-cap earnings from Yahoo and Nasdaq (Broadcom's dates
  differ: Dec 9 vs Dec 10), ETF loss scenarios at 1x-10x, morning futures and nowcast, and the user's call log
  (`data/thesis/calls.jsonl`, hash-chained, scored vs always-long, included in the nightly data commit).
  19 new tests (247 total). Fixed line endings that an edit script had changed from LF to CRLF in six files.

## Pick up here (Mon 2026-11-09)

**Runs automatically tomorrow (Central times):**
- 8:00 AM: market snapshot (Kalshi perps and macro markets, futures).
- 9:30 AM, 11:30 AM, 1:30 PM: liquidity samples (first ever).
- 2:50 PM: minute bars, option chains, 4th liquidity sample. 3:05 PM: market snapshot with the inflation nowcast.
- 3:45 PM: evening refresh. It waits for Cboe's VIX close, records Monday's paper decisions, then commits and
  pushes the data ("Evening refresh data, 2026-11-09" on GitHub).
- 7:10 PM: minute bars, OCC volume, first snapshot-journal records, backup to `G:\My Drive\Trading Research Backups`.

**Check tomorrow:** `work\market_snapshot.log`, `work\intraday_collect.log`, `work\scheduled_refresh.log`,
the GitHub data commit and the Drive archive dated 2026-11-09. CPI is Tue Nov 10, 8:30 AM ET.

**Reference:** every change from Nov 7-8 and why: `docs/CHANGES_2026-11-07_08.md`.

**Built overnight Nov 8 (user: "we have time. you can build both"):**
- Backtester trade simulator (its `LOG.md`): 24 of 48 strategy pricings rated Lead, but in 2010-2026 every one
  had a lower CAGR per unit of drawdown than buy-and-hold at the same exposure; the edge is mainly in 1993-2009.
- **Daily thesis tab** (`thesis.html`, now the landing page; Intraday is the second tab). As of the Nov 6 close it
  shows a long candidate: SPY and QQQ closed below their lower Bollinger bands (a Lead rule), with the cautions
  (drawdown comparison, CPI Tue Nov 10, Nvidia earnings Nov 17 after the close, inverted VIX term structure).
- User decision 2026-11-08: no Kalshi in the morning/evening thesis; keep collecting it.

**Check Monday too:** after the 3:05 PM snapshot the "Overnight and inflation" card fills in (futures and the
Cleveland Fed nowcast); after the evening refresh the thesis moves to Monday's close and credit/earnings re-download.
Record calls on the Daily thesis tab ("Your calls"); the log is append-only and goes to GitHub nightly.

- **The page's own stance is now logged and scored** (user: "Yes, add it"): online builds append SPY/QQQ long or
  flat for the latest close to `data/thesis/stance_log.jsonl`, only before the next open, scored like a call over
  5 sessions. First entries: SPY long and QQQ long for the Nov 6 close (lower Bollinger band), recorded by a manual
  online refresh at 2:38 AM ET Sun Nov 8 so that stance wasn't lost; they're scored from Mon Nov 9's open through
  Fri Nov 13's close. Monday evening's data commit puts the file on GitHub.

**Next work:** the intraday side waits for data (snapshot liquidity policy around Dec 8). Ideas not built: a
registered trend/volatility filter for the oversold rules (new versions in the backtester); jobs/macro release
values (roadmap 2).

## Open items (keep current)
- **Free liquidity pipeline (user approved, built 2026-11-08):** `liquidity_free.py` samples share and
  near-the-money option spreads 4 times a day and adds Yahoo share volume and OCC options volume (standard
  contracts, cleared sides / 2; OCC keeps about a year of daily history). Each finished day goes to a separate
  `snapshot` journal; the strict `verified` journal and its gate are unchanged. The snapshot policy can start
  qualifying sessions after 20 sampled trading days (around Dec 8, 2026). Share spreads from Alpaca's free IEX
  quotes would be better than Yahoo snapshots but need the user to open a free account and supply an API key.
- Backtest app (user asked 2026-11-08): a separate app that reads this one's data read-only, starting with daily
  indicator studies (EMA/RSI/MACD/volume) on 1993+ history; intraday versions once collected minutes accumulate.
- Small polish: spreads under 0.01% show as "0.00%" on the Leverage tab and ticker pages. Show them in basis
  points (a new table format in `leverage/report.py`, plus `spread_text`).
- **Costs are understated.** Kalshi perps fees are 0.12% taker / 0.02% maker per side at the base tier; the
  backtests and the frozen paper experiment assume 0.02% plus 0.03% spread and slippage. Use measured fees in the
  next experiment version.
- Roadmap 1 is done (evening refresh, market snapshots, closed-market spreads). The first scheduled snapshot is
  Mon Nov 9, 9:00 AM ET, and the evening task commits and pushes it. Next: roadmap 2 (jobs/macro data).
- Second-source price checks cover SPY and QQQ closes only. Opens, IWM, DIA, RSP and the leveraged ETFs have no
  free second source yet (Stooq now blocks automated downloads; FRED has no Russell 2000).
- Roadmap 2: jobs/macro data fix (BLS API + ALFRED + FRED release dates; Kalshi CPI and Fed markets as dated
  market expectations).
- New data the user wants: mega-cap earnings calendar (yfinance history, Nasdaq calendar API, SEC EDGAR 8-K
  item 2.02 timestamps); credit spreads (BAA10Y back to 1986; ICE BofA HY/IG/CCC spreads on FRED only cover
  3 years).
- Design with the user: a perp-time paper experiment as a new frozen version (decision at ~4:01 PM ET on
  information known then, perp entry ~4:05 PM at the collector's quote, real 4 PM funding, measured fees); a log
  for the Today page's own calls; the Today page itself (roadmap 3).
- Proxy check before changing anything: US500's 4 PM mark tracked the S&P 500 total-return index more closely
  than the price index over 24 days (drift -0.013% vs -0.063% per 30 days, se 0.020%). If that holds, adjusted
  SPY prices are the right proxy and there is nothing to fix. Re-test with more data.
- Risk limits: the user has none set (2026-11-07). The Today page should show outcomes at several leverage
  levels; sizing stays blocked.
- GEX/DIX copy is through 2026-11-05; the user downloads it by hand (GEX/DIX tab, Update button).

## 2026-11-07
- Quant review of the Codex audit build: `docs/QUANT_REVIEW_2026-11-07.md` (holdout, beta, perp hours, funding, costs).
- Moved the app from the Codex outputs folder to `C:\Users\gzdt\trading-research` (robocopy, 10,036 files,
  0 failures). The old folder is left in place with a MOVED note.
- git initialized: import commit c73244a (no code changes), then e28dde6 (test scratch path fix). 59 tests pass.
- Offline rebuild from the new folder published a validated bundle (run f68cc453e76561e52560; data through 2026-11-06).
- Paper log: 4 decisions recorded for signal date 2026-11-06 (all no-signal), from the evening refresh in the old folder.
- User priorities set: thesis terminal first; jobs data fix; own-edge backtesting on the back burner.
- Scheduled task **Trading Research Evening Refresh** created: Mon-Fri 3:45 PM Central, runs `scheduled_refresh.py`
  with `.venv\Scripts\pythonw.exe`. It starts late if the computer was off or asleep, runs on battery, doesn't
  wake the computer, has a 20-hour limit and runs only while the user is signed in (no stored password).
  Test run at 7:51 PM CT: exit 0 (Friday's decisions already logged, no remote yet). First real run Mon Nov 9.
- Code: `scheduled_refresh.py` and `git_backup.py`, 19 new tests (78 total), commit c9c1b6e.
- Kalshi research: fee schedule above (kalshi.com/fee-schedule, Invest tab). Funding is the time-weighted
  premium of the perp over its index, paid once a day at 4 PM ET for index perps (the public estimate endpoint
  reports the next funding at 4 PM ET). Positive means longs pay shorts, and it is a transfer between traders,
  not a fee. The docs don't say whether a position must be open at 4 PM to pay. Liquidation uses isolated margin
  and market orders, with no stated fee. Kalshi publishes no contract specs for US500 or US Tech 100.
- Kalshi event markets on Saturday: CPI 159k contracts traded in 24h and Fed decision 353k (liquid); payrolls
  and the S&P/Nasdaq range markets were thin.
- Data checks: SPY adjusted prices beat the S&P 500 price index by 1.9%/yr in 2016-2025 (dividends), while raw SPY
  matches the index. ^GSPC opens equal the prior close on 70% of 1993-2009 days, so the index can't replace SPY
  for overnight tests.
- This session ran in a git worktree. The app blocks file edits in the main folder from worktree sessions, so it
  committed in the worktree and fast-forwarded `main`.
- Private GitHub repo https://github.com/ghzxdt/trading-research created in Chrome with the user's OK (empty, no
  README). `main` pushed after the user approved Git Credential Manager's sign-in, which is saved for ghzxdt. A
  manual run of the evening task at 9:02 PM ET pushed `main` unattended. New rule: push after every commit.
- Kalshi snapshots instead of a 15-minute collector (user agreed): `kalshi_snapshot.py` plus the task **Trading
  Research Kalshi Snapshots** (Mon-Fri 8:00 AM and 3:05 PM Central, starts late if missed but records nothing
  outside 8:00-9:30 AM / 4:00-4:45 PM ET). Each snapshot covers the 5 universe perps (bid/ask, sizes, mark,
  reference price, premium, funding estimate, open interest, volume, order-book dollars within 5 and 25 bp of the
  mid) and the open KXCPI, KXCPICORE, KXFEDDECISION and KXPAYROLLS markets (128 on Saturday). Public endpoints
  only, including `/margin/markets/{ticker}/orderbook` and `/margin/funding_rates/estimate`. 9 tests (87 total),
  commits 91460dc and f515568.
- A live dry run found Kalshi's no-quote placeholders (ask 922337203685477.5807; next funding in year 0001 for the
  inactive US 2000 perp). Both are now blank. The two test files that run wrote to `data/kalshi` were deleted
  before any commit. The final dry run went to a scratch folder.
- Free cross-checks added (user: don't rely on Kalshi alone). The snapshot became `market_snapshot.py` and the task
  **Trading Research Market Snapshots** (the Kalshi-only task was removed). It also saves Yahoo's S&P 500 and
  Nasdaq-100 E-mini futures (`ES=F`/`NQ=F`: last price, the price before the latest 4 PM ET close, change since)
  and, at 4:05 PM, the Cleveland Fed's daily nowcasts of monthly CPI, core CPI, PCE and core PCE
  (`nowcast_month.json`; actuals too once released). On Nov 6 the nowcast for October CPI was +0.24% (core +0.21%).
  Its points are dated from their tooltips because some series have fewer points than day labels.
- `crosscheck.py`: Yahoo's SPY/QQQ daily returns vs FRED's `SP500` (last 10 years) and `NASDAQ100` (since 1986)
  over the latest 60 sessions, flagging gaps above 0.25%. Typical gap is 0.03% and 99% of days fall within about
  0.2%; 1% gaps appear only on extreme days (2020-03-16, 2025-04-09). Shown on the Data quality tab (display only,
  the paper-log gate is unchanged). Offline rebuild in the main folder: PASS, largest gaps 0.08% (SPY) and 0.13%
  (QQQ). Commits c84546b and 7d0f90e; 97 tests.
- VIX guard (user approved): `refresh_guard.py` blocks an online refresh when the latest session's decisions
  aren't logged, it's before the next 9:30 open, and Cboe's VIX file doesn't have the session yet (or can't be
  reached). That closes the data_blocked trap without changing how the frozen experiment records decisions. The
  dashboard server answers 409 with the reason, shown in the control panel and on the dashboard's button.
  `run_all.py` refuses too unless given `--skip-vix-guard`, which the server passes after its own check. The
  evening task overrides the guard only at its 9:00 AM ET deadline. Offline rebuilds are never blocked.
  Live check: no block on Saturday night (Friday already logged); at a simulated Mon 5:00 PM ET it blocked
  because Cboe's file ends Nov 6. A check takes about 1-1.5 s the first time and 0.1 s once the connection is
  reused. Commits 85c6258, ae3dda5 and bcae46a; 111 tests.
- Leverage tab fix (commit e403c0d, 116 tests): a closed market now shows its latest saved open-market spread,
  with the time (from `data/kalshi/snapshots.csv` and `perp_quotes.csv`), or a blank if there is none. Before,
  it showed the closed book's quotes. A new "Spread quote" column says which, and the ticker pages use the same
  wording. Offline rebuild: US500 now shows a 0.0046% spread from Fri Nov 6, 1:17 AM ET instead of the closed
  market's 2.46%; crypto (24/7) stays live.
- Restarted the dashboard server on the new code (9:07 PM CT) through the app's own stop/start path. The control
  panel wasn't open.
