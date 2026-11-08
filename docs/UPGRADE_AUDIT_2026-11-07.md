# Trading Research: upgrade, operation, and audit guide

Release date: November 7, 2026 (America/Chicago).

## What this update does

This extends the existing local application. Today is the new landing workspace, and the existing daily research, perp comparisons, macro pages, original-versus-corrected studies, and frozen paper experiment remain available.

The update adds an intraday research foundation: minute-bar storage and replay, chart-based context, options information and execution-accounting helpers, a registered historical baseline, first-seen news history, and a separate observation journal. It does not establish a profitable strategy, approve personalized sizing, or place orders.

The code is in `C:\Users\gzdt\trading-research`. The new intraday, options, and first-seen-news archives, generated outputs, and local runtime are excluded from this code upload. Some legacy datasets, including Kalshi snapshots and manual DIX data, are already tracked by the repository; this update preserves that existing arrangement.

## How to open and run it

1. Open the **Trading Research Control Panel** desktop shortcut. Alternatively, double-click **START_APP.cmd** inside the project folder.
2. Click **Open dashboard**. The control panel starts the local server if needed and opens **Today** at [http://localhost:8766/today.html](http://localhost:8766/today.html).
3. Check the decision-snapshot time, market-session state, price-coverage date, and **Data health & available capabilities** before interpreting the display.

The existing control panel also provides Start, Stop, Restart, Refresh, Rebuild saved data, logs, and startup repair. Closing the panel leaves the server running. A failed rebuild preserves the previous complete report bundle.

If using a terminal instead of the control panel, from the project folder run:

```powershell
.\.venv\Scripts\python.exe -B hub_server.py
```

Keep that process open, then visit the Today address. Do not start a second server on port 8766 while the app is already running.

## The sixteen-instrument universe

The shared configuration includes the original five and the eleven additions you confirmed:

**SPY, QQQ, IWM, TQQQ, SQQQ, SOXL, TNA, LABD, KORU, BITX, ERY, FNGU, UPRO, SPXL, NVDL, TSLL.**

`terminal_config.json` defines the universe, exposure groups, research settings, provider settings, and initially unavailable risk budgets. FNGU is classified as an ETN. NVDL and TSLL carry single-name flags. DIA, RSP, and SPXU remain in the older research scope.

Listing an instrument does not establish execution eligibility. Product terms are configured research metadata pending dated issuer verification. Related instruments share an exposure group rather than appearing to be independent sources of diversification. NVDL/TSLL remain available for data and chart inspection; the index baseline, index candidates, and index observation journal reject them until a separate event-driven study exists.

## What changed

| Area | Implemented behavior | Main audit location |
|---|---|---|
| Today workspace | Sixteen-instrument selector; candlesticks; regular/extended-hours view; VWAP and level layers; news/events; candidate/evidence panels; options information; research and journal views | `today/template.html`, `today/build.py` |
| Shared scope and settings | One instrument registry used by the terminal and research commands; unknown risk budgets remain unavailable | `terminal_config.py`, `terminal_config.json` |
| Intraday collection | Explicit free-feed collection of minute bars and optional current options indications; failures retain prior useful data | `intraday_collect.py` |
| Bar history and replay | Validated, hash-chained observations; revisions; receipt timestamps; knowledge-cutoff reads; bounded verified-read caches | `intraday/store.py` |
| Intraday features | Bar-based session VWAP; completed 15-minute opening range; complete prior-session anchors; observed extended-hours extremes | `intraday/features.py`, `intraday/calendar.py` |
| Liquidity prerequisite | Verified session imports; 20 prior exchange sessions available before each session opens; joint share/options qualification for at least 80% of the requested research window; failing sessions excluded individually | `liquidity_screen.py`, `terminal_config.json`, `run_intraday.py` |
| Historical baseline | One registered ORB-continuation strategy with VWAP confirmation, causal next-event entries, costs, conservative stops/targets, flattening, and session-level diagnostics | `intraday/backtest.py`, `run_intraday.py` |
| Options research | Verified contract imports; expiry/strike concentrations; unsigned gamma context; deterministic selection; long-option and debit-spread accounting; theoretical scenarios; frozen-level/control diagnostics | `options_research/core.py`, `options_research/levels.py` |
| News history | First-seen headline versions and source links, separate from publication times and the older latest-headline caches | `news_history.py` |
| State and actions | Versioned read-only state endpoint and explicit collection/research/observation actions | `terminal_state.py`, `terminal_api.py`, `hub_server.py` |
| New observation journal | Separately versioned/frozen, hash-chained research observations and abstentions; replay cannot invent forward records | `intraday/paper.py` |
| Publication and startup | Today added to validated bundle requirements and navigation; desktop landing destination updated | `build_pipeline.py`, `stage1/report.py`, `desktop_ui.py` |

No new runtime dependency was required for these additions.

## What the controls mean

**Reload view** rereads saved/current local state. It does not contact a provider or record a paper decision.

**Collect intraday** explicitly collects the selected symbol. **Include options snapshot** additionally requests the free current-chain indications. This is separate from the legacy **Refresh data + validate** action, which refreshes and rebuilds the daily application.

**Rebuild saved data** performs the existing offline rebuild. It preserves forward-record protections and does not create a fictional historical paper record.

The chart defaults to regular-session observations. Extended hours are optional. Individual price levels, session VWAP, options-OI overlays, and first-seen news markers can be switched on or off. Options overlays start off. News markers use the time the application first archived the headline, never an earlier publication time it could not yet have observed.

**Run baseline research** first enforces the rolling liquidity prerequisite, then runs the registered historical share scenario. Missing verified liquidity history blocks the run. Current free chains cannot fill this gap. The archive-timing checkbox is an explicit assumption that historical bars were available at bar close; it cannot bypass liquidity qualification. Leaving it unchecked respects recorded receipt times. Neither mode creates forward proof.

**Record observation** records the observed setup or abstention in the new research journal. It does not simulate an executed trade, place an order, or certify profitability. Ordinary page views do not write observations.

JSON downloads expose the selected snapshot, options observations, and research details for inspection. The walkthrough documents each panel and control in more detail.

## Options: what is useful now and what remains limited

The free-feed options table exposes observed strike concentrations by expiry/right. These can be investigated as candidate areas of interest. Open interest does not reveal signed dealer inventory, and a concentration is not automatically support or resistance.

Yahoo current-chain indications do not provide verified bid/ask quote timestamps or OI-publication dates. The application preserves that uncertainty. A last-trade timestamp is not promoted into a quote timestamp, and local receipt time is not presented as proof of a fresh executable quote.

For verified imports, the research package checks contract identity, availability, quote age, spread, size, expiry, deliverables, account feasibility, and fees. P&L uses appropriate quote sides and multipliers; it does not deduct theta a second time. Debit spreads require synchronized legs. Theoretical joint spot/IV/time scenarios are European pricing approximations, separately labeled from executable returns; they do not model American early exercise or arbitrary post-expiration repricing.

The support/resistance diagnostics require levels fixed before the touch and expose unresolved/censored outcomes and control-level assumptions. They do not establish that options improve levels, let alone by a particular multiple.

A complete end-to-end options strategy simulator, calibrated trade probabilities, automated strategy qualification, and broad walk-forward validation are not delivered as proven capabilities in this release. The contract-data and accounting foundations are implemented; those broader research claims require additional integration and suitable historical data. The four-arm comparison explicitly distinguishes computed share scenarios from options-dependent work that is unavailable.

## Historical research and evidence

The initial real-data smoke run used five sessions of SPY minute bars with the explicit assumed bar-close availability setting and produced five historical simulated trades. It predates the verified liquidity gate and is labeled an unqualified prototype scenario. It demonstrates the simulator, not a durable edge. New research cannot rerun until the liquidity prerequisite passes; sizing stays blocked.

The baseline uses explicit spread/slippage/fee assumptions, one trade per complete session, a next-event entry after signal availability/latency, a stop at the opposite range boundary, a 2R target, and a scheduled flatten before the cash close. It handles missing paths, gap stops, same-bar ambiguity, and insolvency boundaries conservatively. Actual quotes, borrow, capacity, and guaranteed stop fills are not supplied by OHLCV.

Research runs have dataset/configuration identifiers and a bounded variant registry. Older inspected history is not relabeled a fresh untouched holdout. Existing daily/perp experiments retain their frozen assumptions; they were not silently rewritten to look like actual perp or option execution.

## Liquidity policy and leveraged-product accounting

The initial configurable research policy requires 20 preceding verified sessions: average share volume at least 1,000,000; the median of session-level share-spread medians no more than 10 bps; average options volume at least 10,000 contracts; and the median of session-level options-spread medians no more than 100 bps. These are explicit screening assumptions, not calibrated capacity estimates or proof of achievable fills. The statistic is a median of daily medians, not a pooled quote-level median. Both sides of the liquidity screen are required before signal research, while the snapshot exposes a separate share-only diagnostic. Every traded research session must also pass individually. A full-window 80% aggregate does not permit entries on failed earlier sessions.

Verified imports need full-session coverage, real source/availability timestamps, and provenance. Unknown coverage, missing days, and data received after the relevant decision open fail closed. The free-feed archives currently do not qualify any research window under this policy. The new `import-liquidity` command accepts verified session observations; the operating guide describes its fields. Importing a file asserts the supplied source metadata; it does not independently certify a provider's honesty or representativeness. Threshold changes are research choices that should be frozen before independent evaluation.

The original volatility-only "break-even holding period" request needs a mathematical correction. Daily-reset compounding depends on the benchmark path, including direction and volatility; a universal cutoff cannot be inferred from realized volatility alone. This is consistent with the [TQQQ prospectus](https://www.proshares.com/globalassets/proshares/prospectuses/tqqq_summary_prospectus.pdf) and the [SEC leveraged/inverse ETF bulletin](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-alerts/sec).

The current baseline is flat within the same cash session and uses observed instrument prices for every configured leveraged product. Our accounting inference is that another generic decay haircut would count product performance twice. Reports record this basis explicitly, with no claimed volatility-only cutoff. Synthetic leveraged histories, overnight holding models, funding/tracking attribution, and a fully estimated horizon model remain separate future research. Signals in this baseline use each traded instrument's own price direction; inverse products are not flipped a second time.

## Where to audit

Start with these operator documents:

- [App walkthrough](UI_WALKTHROUGH.md): every screen/control and the normal workflow.
- [Intraday terminal guide](INTRADAY_TERMINAL.md): commands, import schemas, storage, and capability matrix.
- [Options audit notes](OPTIONS_AUDIT_NOTES.md): options accounting and model limits.

Then inspect:

1. `terminal_config.json` for scope, defaults, and unset risk limits.
2. `terminal_state.py` for how current facts, research artifacts, uncertainty, and waiting reasons are combined.
3. `intraday/store.py`, `news_history.py`, and `options_research/core.py` for timestamp semantics and replay filtering.
4. `intraday/features.py` for exact VWAP/ORB/level definitions; `intraday/backtest.py` for entry/exit and cost assumptions.
5. `options_research/levels.py` for fixed-level reaction/control methodology and invalidation.
6. `intraday/paper.py` versus the unchanged `monitor/paper.py` for the separate journals and frozen experiments.
7. `terminal_api.py` and `hub_server.py` for read-only GETs, explicit write actions, validation, and writer locks.
8. `build_pipeline.py` and `output/build_manifest.json` for validated publication and source/input/output hashes.

Local data/artifacts:

- `data/intraday/v1/bars.jsonl`: received bar history and revisions.
- `data/intraday/v1/research/`: research runs and trial registry.
- `data/intraday/v1/paper.jsonl`: new research observations, once used.
- `data/options_research/`: verified imported contract observations, once provided.
- `data/terminal/free_options/`: immutable free-chain snapshots plus convenience latest files.
- `data/terminal/collection_status.json`: collection results and provider failures.
- `data/news_history/headlines-v1.jsonl`: first-seen headline archive.
- `data/liquidity/v1/`: verified session-level liquidity observations, once imported.
- `output/today_state.json`: the saved default snapshot; the live endpoint/JSON download reflects the selected current view.

These local market/research folders are excluded from the code commit. Do not hand-edit hash-chained records or frozen experiments.

## Verification performed

- All **94 new tests passed**: 23 intraday-engine, 34 options-research, 10 Today-interface, 18 terminal-integration, and 9 liquidity-screen tests.
- The complete suite ran **210 tests**: 209 passed; the existing `test_pushes_main_to_origin` local-Git-transport test failed in the restricted Windows background runner. It had the same failure before this update. Its source was left intact; this result is not reported as a complete suite pass.
- The full offline application build passed its temporal-prefix, arithmetic, labeling, component, and transactional-publication gates.
- Real free-feed minute bars and current chain indications were received for all sixteen configured instruments.
- The installed HTTP API was exercised for SPY, SOXL, and TSLL; all returned the shared universe and non-actionable evidence state.
- Replay before the new collection returned no future intraday observations, options levels, or first-seen headlines.
- Before/after offline-build hashes matched for the existing frozen experiment, paper log, and the two pre-existing modified data files. Those user data changes were not included in the code commit.
- Browser inspection checked the actual Today layout, chart, selected instrument state, options information, and visible evidence limitations.

To rerun locally:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
.\.venv\Scripts\python.exe -B run_all.py --offline
```

## Practical limits and next work

The new intraday collection is manual; existing scheduled tasks are unchanged. Free history is short and provider-dependent. Source delays and independent intraday reconciliation remain limitations.

Personalized sizing remains blocked because risk limits, product verification, and strategy evidence are incomplete. Automatic forward trade-outcome resolution is not implemented. There is no broker/order-submission integration.

The most useful next research step is to freeze one precisely defined opportunity and collect enough point-in-time observations to compare price-only information with options-informed information under realistic execution assumptions. Add more signal families only through explicit registered experiments and independent evaluation.
