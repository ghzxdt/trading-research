# Trading research log

## Open items (keep current)
- **User action:** close the control panel, reopen it from the desktop shortcut, and click **Restart app**. The
  dashboard server running since 7:08 PM CT on Nov 7, and the open panel, still have the code from before the
  VIX guard. A panel from before the guard waits only 1.2 s for the server, and the guard's first check can take
  about 1.5 s.
- **Costs are understated.** Kalshi perps fees are 0.12% taker / 0.02% maker per side at the base tier; the
  backtests and the frozen paper experiment assume 0.02% plus 0.03% spread and slippage. Use measured fees in the
  next experiment version.
- Roadmap 1: Leverage tab ignores closed-market spreads. (Market snapshots are done; the first scheduled one is
  Mon Nov 9, 9:00 AM ET, and the evening task commits and pushes them.)
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
