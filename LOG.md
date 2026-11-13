# Trading research log

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
