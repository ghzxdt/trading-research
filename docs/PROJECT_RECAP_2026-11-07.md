# Trading Research — recap and Stage 2 plan

Status date: November 7, 2026. This recap describes implemented software and separates it from unresolved research work. The original supplied app remains preserved.

## Where we are

**Stage 1: implemented, audited, and substantially repaired.** Its historical statistics, charts, risk descriptions, event studies, and data checks are available. Full independent price-vendor reconciliation and historical information-vintage verification remain incomplete, so Stage 1 is not a blanket certification that every input is true.

**Stage 2: research and evaluation infrastructure is implemented; the trading system is unfinished.** We have explicit-cost experiments, original-versus-corrected comparisons, a forward paper framework, and controls for operating the local app. We do not yet have a validated consolidated daily thesis, calibrated live position sizing, or demonstrated forward profitability. There is no order-submission integration.

The desktop control panel improves operation. It does not itself create a trading edge or change the strategy rules.

## What you originally supplied

The Python app downloaded public market inputs and generated a browser hub with four sections:

| Original section | Purpose |
|---|---|
| Indexes | Historical SPY/QQQ/index-ETF behavior, overnight/daytime returns, VIX calibration, event-day studies, correlations, leveraged ETF behavior and risk tails. |
| Tickers | Individual ETF prices, statistics, charts, drawdowns, daily volume/close-location proxies and headlines. |
| Leverage | Public Kalshi market information, leverage/funding estimates, ETF-proxy barrier frequencies, tracking and overnight comparisons. |
| GEX/DIX | Manually downloaded positioning data, historical studies and refresh reminders. |

The original software was descriptive and exploratory. It had no executable after-cost strategy backtest or automated daily trading call. Its employment support used release dates and event-day flags, rather than payroll/unemployment/wage surprises.

## Audit findings and repairs

We reviewed the supplied documents, the actual source, saved inputs, rendered pages, chart data and relevant official source documentation. Repairs included:

- Missing margin inputs now produce unavailable risk, rather than a false zero-hit result.
- Published long/short leverage inputs are retained separately. Remaining liquidation calculations are explicitly qualified as research approximations; uncalibrated live sizing is blocked.
- Forward returns preserve the exchange calendar when an intermediate price is missing. A two-session return is no longer relabeled as one session.
- Buy-and-hold wealth uses valid adjusted-price endpoints. Overnight/daytime decomposition uses a common sample and explicit log-growth labels. Tiny positive wealth is displayed with adequate precision.
- GEX risk comparisons use the appropriate ETF proxy and directional adverse excursions, with stale current readings suppressed.
- Scheduled and emergency Fed events are separated. Single-event tests use better weekday/gap controls and identify overlapping events.
- Predictor comparisons use common samples, leveraged ETF studies include a compounded daily-reset proxy benchmark, and tail/stop labels identify what is actually measured.
- Randomization tests use stable identifiers, adequate fixed draws and nonzero Monte Carlo p-values. The full test registry exposes raw, BH-adjusted and Holm-adjusted results.
- Candidate downloads are validated before replacement, previous usable caches are retained, and routine builds must pass transformation checks.
- Pages are built in a staging directory and published as a consistent validated bundle, with source/input/output provenance and rollback recovery.

These fixes improve correctness and make uncertainty visible. Some lower previously attractive results; that is useful information, not evidence that a profitable strategy was damaged.

## Five added research tabs

| Added tab | What is implemented | Important boundary |
|---|---|---|
| Original vs fixed | Frozen original reports and same-input code comparisons; full statistical registry. | This compares methodology. Statistical significance is not net trading profit. |
| Backtests | Four fixed candidates, original closing-price assumptions versus next-open entries, gross/scenario-net equity curves, drawdowns, trade ledgers, annual diagnostics and cost sensitivity. | These are retrospective ETF-proxy experiments. The original app did not contain these executable backtests; we introduced them to test its leads. |
| Paper monitor | Decisions timestamped before hypothetical entries, immutable experiment configuration, hash-chained records, eligibility checks and later outcomes. | No historical results are backfilled as forward success. Offline rebuilds do not create new forward decisions. |
| Data quality | Freshness, validation, provenance, source status and unresolved calibration. | A running app is not the same as fresh or independently verified data. |
| Jobs & macro | Release-calendar display, official BLS retrieval/archive code, source-failure reporting and timestamp-validated surprise imports. | The tested BLS requests returned HTTP 403; automatic values remained unavailable. Consensus and initial/revised historical releases are not fabricated. |

The validated report bundle contains 85 chart specifications. Their structural checks are part of publication. This is separate from certifying the provider's underlying historical observations.

## What the first experiments indicate

The four candidates came from the existing research leads: short after a big rise for one session; that same condition with VIX at least 20; long after a normal drop for five sessions; and short after a big rise for five sessions.

Under the original saved-data period and configured execution scenario, three corrected-next-open candidates lost money and the five-session normal-drop long was positive. Its uncertainty interval still crossed zero. These are historical diagnostics, not a live record or a promise that the positive candidate will persist.

The next-open tests deliberately change the entry interval: for the one-session candidate they measure the next open to that day's close. They do not settle whether an after-4:30 p.m. perp entry could capture an overnight edge. That requires actual timestamped tradable prices.

Costs remain configurable assumptions rather than verified historical Kalshi bid/ask, fee and funding paths. Fund/ETF adjusted returns, perp mark returns, dividends and funding must be reconciled before making a venue-specific profitability claim.

## New Windows control panel

The desktop shortcut **Trading Research Control Panel** opens a native window without requiring terminal commands. Its controls are:

- Open dashboard: start the local server if needed, then open the browser.
- Run / Refresh data: download current sources and run the validated build.
- Start, Stop and Restart app: manage this identified local app. Restart preserves inputs, reports, paper records and backups.
- Rebuild saved data: network-free recalculation.
- Repair startup: conservative cleanup of a definitely abandoned build lock.
- View logs, Open app folder and Help.

The panel separates server state from the saved market-data date, recalculates freshness using the current clock, and refuses stop/restart during an active or uncertain writer. Repeated launches reuse one control window. Closing the panel leaves the dashboard server running. Refreshes remain manual; there is no new recurring scheduler.

## Preservation and rollback

- The 83 supplied files were copied and SHA-256 verified before repair. The original Claude workspace was not edited.
- The original code/data/report archive is retained in the app's backups folder, with a manifest.
- Frozen original reports remain accessible from the comparison tab.
- The pre-desktop corrected app is separately saved as backups/before_desktop_controls_v1.zip.
- The rollback script previews changes by default and creates a recovery ZIP before an applied rollback. Current paper logs and market data are retained by the default code/report rollback.
- The app has its own local runtime; it does not depend on keeping the Claude scratch virtual environment.

## What remains before Stage 2 can become a trading system

1. **Reliable current and historical inputs.** Reconcile suspect prices against an independent provider and solve dependable employment-release/calendar retrieval. Acquire timestamped pre-release expectations and initial/revised observations before testing surprises.
2. **A precise tradable interval.** Pick one product and one holding period for the first serious experiment. Define signal availability, an executable entry and exit, overlap rules and market-closure handling.
3. **Actual execution economics.** Collect venue quotes and spreads, determine the applicable fees, use actual funding timestamps and model liquidity, gaps and slippage. Replace scenario assumptions where measured data exists.
4. **Calibrated risk.** Reconcile long/short liquidation examples across prices and sizes, then specify account risk budgets, portfolio concentration, drawdown limits and stop/gap behavior. Maximum permitted leverage is not a sizing recommendation.
5. **A frozen evaluation protocol.** Register the hypotheses and thresholds, distinguish development diagnostics from genuinely unseen tests, handle overlapping observations and multiple testing, and compare with meaningful exposure-matched benchmarks.
6. **Forward evidence.** Refresh consistently to record eligible paper decisions, examine actual costs and model errors, and assess net expectancy and drawdown over a meaningful sample. A few days can expose software problems but cannot establish an edge.

## Proposed next game plan

**First: verify current-data operation.** Use the control panel to refresh, inspect source failures and freshness, and resolve feeds before depending on current market readings.

**Second: narrow the research scope.** Choose one product and one time horizon. The normal-drop/five-session long is a candidate worth investigating because it was the only positive corrected scenario in the initial comparison. That selection is itself informed by historical results, so it must face a fresh protocol and forward test. Keep alternative candidates visible rather than silently discarding failures.

**Third: replace hypothetical fills with measured venue economics.** Especially test whether the proposed overnight opportunities remain after an entry actually available when the signal is known.

**Fourth: freeze and monitor.** Record paper decisions without changing the rules after every loss. Review data failures, gross versus net results, costs, drawdowns and uncertainty. Build the consolidated up/down/no-edge thesis and sizing only after this evidence supports them.

No account trades or orders have been placed by this app. The target is demonstrable after-cost expectancy under stated risk limits; the software currently helps us measure that target rather than claiming it has already been achieved.
