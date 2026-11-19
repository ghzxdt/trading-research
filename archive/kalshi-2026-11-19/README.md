# Kalshi and perpetual data, archived 2026-11-19

The user dropped all Kalshi and perpetual tracking on 2026-11-19 ("no more tracking that"; relayed by the
backtester chat). Collection stopped and the Leverage tab was removed. What had been collected was moved here
instead of being deleted:

- `data_kalshi/` (was `data/kalshi/`, committed to git): `perp_quotes.csv` and `event_quotes.csv` from the
  twice-daily market snapshots, and `snapshots.csv` from the Leverage tab's builds.
- `raw_kalshi/` (was `data/raw/kalshi/`, never committed; ignored here too): the Leverage tab's raw downloads
  (markets, risk parameters, funding history, hourly candles).

Nothing in the app reads these files any more. Delete this folder only after the user says so.
