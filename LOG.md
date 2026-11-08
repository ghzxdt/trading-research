# Trading research log

## Open items (keep current)
- **Before Monday Nov 9, 4:45 PM ET:** set up the scheduled evening refresh so the paper log records Monday's
  decisions (roadmap 1). Nothing records unless someone clicks Run / Refresh data.
- Roadmap 1: Kalshi quote collector; Leverage tab ignores closed-market spreads.
- Roadmap 2: jobs/macro data fix (BLS API + ALFRED + FRED release dates).
- Roadmap 3: design the "Today" thesis page with the user before building.
- Waiting on user: max drawdown % and max leverage; GitHub private repo yes/no.
- GEX/DIX copy is through 2026-11-05; the user downloads it by hand (GEX/DIX tab, Update button).

## 2026-11-07
- Quant review of the Codex audit build: `docs/QUANT_REVIEW_2026-11-07.md` (holdout, beta, perp hours, funding, costs).
- Moved the app from the Codex outputs folder to `C:\Users\gzdt\trading-research` (robocopy, 10,036 files,
  0 failures). The old folder is left in place with a MOVED note.
- git initialized: import commit c73244a (no code changes), then e28dde6 (test scratch path fix). 59 tests pass.
- Offline rebuild from the new folder published a validated bundle (run f68cc453e76561e52560; data through 2026-11-06).
- Paper log: 4 decisions recorded for signal date 2026-11-06 (all no-signal), from the evening refresh in the old folder.
- User priorities set: thesis terminal first; jobs data fix; own-edge backtesting on the back burner.
