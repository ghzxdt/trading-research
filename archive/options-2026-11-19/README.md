# Options data, archived 2026-11-19

Options data collection stopped on 2026-11-19 (the user's trim list, relayed by the backtester chat). What had
been collected was moved here instead of being deleted:

- `data_zero_dte/` (was `data/zero_dte/`): same-day (0DTE) option snapshots from Cboe's delayed feed for SPY, QQQ
  and IWM (from 2026-11-13), their summary, and the raw closes used to settle them.
- `data_terminal_free_options/` (was `data/terminal/free_options/`): Yahoo's indicative option chains collected at
  3:50 PM ET and from the Today page.
- `occ_volume.csv` (was `data/liquidity/occ_volume.csv`): OCC daily cleared options volume (both sides; review C12).

Share-liquidity sampling continues (the intraday shares gate needs it). Older liquidity sample files in
`data/liquidity/samples/` still contain their option fields; they stay where they are and are ignored.
These files were never committed to git (data folders that are git-ignored). Delete only after the user says so.
