# Trading research log

## Open items (keep current)
- **GitHub (user said yes, 2026-11-07):** waiting for the final OK to create the private repo `trading-research`
  (in Chrome, where the user is signed in), add it as `origin` and push `main`. Then the evening task pushes
  nightly. Sign-in goes through Git Credential Manager's browser prompt.
- **A manual refresh before the VIX close logs the day as data_blocked.** Cboe posts the VIX close well after
  4:30 PM ET (file times on Fri Nov 6: VVIX 5:31 PM, VIX 9:21 PM ET), but the app's freshness check expects it at
  4:30 PM. A Run / Refresh in that gap records the day's four decisions as data_blocked for good. The scheduled
  task waits for the VIX close; the app itself still needs a fix (decide with the user whether deferring the
  record is a protocol change that needs a new experiment version).
- **Costs are understated.** Kalshi perps fees are 0.12% taker / 0.02% maker per side at the base tier; the
  backtests and the frozen paper experiment assume 0.02% plus 0.03% spread and slippage. Use measured fees in the
  next experiment version.
- Roadmap 1: Kalshi quote collector (also save KXCPI, KXFEDDECISION, KXPAYROLLS, KXINXU, KXNASDAQ100U and the
  public funding-rate estimate); Leverage tab ignores closed-market spreads.
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
