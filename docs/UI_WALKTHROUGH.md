# Trading Research: app walkthrough

The app is a workspace for reviewing market observations, forming a testable trade thesis, checking its evidence, and preserving a research record. You still decide whether to trade and place any trade yourself. A research candidate is a hypothesis; the current terminal does not certify an edge, approve a position size, or send orders.

## Open the app

1. Open the **Trading Research Control Panel** desktop shortcut, or double-click **START_APP.cmd** in `C:\Users\gzdt\trading-research`.
2. Click **Open dashboard**. This starts the local server if needed and opens [Today](http://localhost:8766/today.html).
3. Check the snapshot time, session, price coverage, and data-health panel before interpreting the chart or plan.

Closing the control panel leaves the server running. **Stop app** stops it; **Restart app** restarts it while preserving records. Opening the dashboard does not download provider data or record a paper decision.

If you prefer to start the server from PowerShell, run this only when the desktop app is not already serving that port:

```powershell
Set-Location 'C:\Users\gzdt\trading-research'
.\.venv\Scripts\python.exe -B hub_server.py
```

Then open [http://localhost:8766/today.html](http://localhost:8766/today.html). The desktop control panel is the normal way to start and manage the app; no terminal commands are required for everyday use.

## What each update control does

| Control | What it actually does |
|---|---|
| **Reload view** on Today | Reads the latest saved state from the local service. It does not contact market-data providers, run a backtest, or create a journal record. |
| **Collect intraday** | Explicitly collects the selected instrument's available free one-minute archive and headlines, retaining receipt times and source limitations. Coverage and delays depend on the provider. |
| **Include options snapshot** | Adds a free current-chain snapshot to that collection request. These are indicative observations; trustworthy quote/OI publication times and executable fills are not established by collecting them. |
| **Refresh data + validate** in the shared navigation, or **Run / Refresh data** in the desktop panel | Runs the existing full daily-data refresh and validated page build. This is separate from the selected instrument's intraday collector. The existing daily paper workflow may append its scheduled research decisions. |
| **Rebuild saved data** | Recalculates pages from saved inputs without new downloads or new forward paper records. |
| **Restart app** | Restarts the local server. It does not refresh market data, fix provider access failures, or erase logs. |

Collection and research can take time. The page waits for the operation to finish, shows its status, and then reloads the state. The intraday action buttons stay disabled during that operation. A failed source remains visible as a limitation; a green server status alone does not mean every feed is current.

## Read Today from top to bottom

### Watchlist and snapshot ribbon

Choose a ticker to load that instrument's saved observations and research. The configured active list is **SPY, QQQ, IWM, TQQQ, SQQQ, SOXL, TNA, LABD, KORU, BITX, ERY, FNGU, UPRO, SPXL, NVDL, and TSLL**. The names and exposure groups come from the shared instrument configuration. Being on the list does not mean an instrument has enough data, a liquid option contract, or a qualified trade.

The snapshot time says when the terminal assembled the view. Each source has its own observation time. On a weekend, a current terminal snapshot can correctly show Friday's last saved prices and a closed market.

Expand **Data health & available capabilities** to see which feeds exist, their timestamps, coverage, and limitations. Missing inputs remain unavailable. A daily chart is explicitly labeled daily context when usable intraday bars are absent.

### Chart and levels

The default intraday chart uses available regular-session candles. It shows volume and a bar-based session VWAP, plus price-derived anchors where the source coverage supports them. Hover over the candles, or focus the chart and use the arrow keys, to inspect OHLC and volume. **Show price observations** provides a table of the latest visible observations.

- **Session VWAP** shows or hides the available VWAP line. This is computed from bars, rather than individual trades.
- **Price levels** shows or hides the price-derived anchors. The individual level checkboxes let you choose which anchors to display; their source and availability time appear in the level tooltip.
- **Options OI overlay** is off by default. It draws supplied strike concentrations as an optional comparison. Open interest does not reveal signed dealer inventory, and these lines are not established support or resistance.
- **Extended hours** is off by default and is available only when extended-hours candles exist. Turning it on changes the displayed bars and price readout; the VWAP still represents the regular session.
- **News first seen** places markers only when the app's archived first-seen timestamp falls within the visible intraday interval. A headline first archived on Saturday is not placed on Friday's chart just because its publication date was Friday. Hover over a marker for its archived timestamp and headline.

Levels beyond the visible price scale may remain listed without a visible line. A level, price touch, or VWAP relationship is an observation to test, not a promise of a bounce or breakout.

### News and events

The news list links to the originating publisher and distinguishes publication time from the app's first-seen archive time. The events list shows scheduled releases and its verification status. The terminal does not manufacture missing consensus values or assume that an article was available to the app when it was originally published.

### Candidate plan and evidence

The plan shows the current research direction, entry condition, invalidation, exit rule, and flattening time when those fields are supplied. **Waiting for evidence** and a flat direction are legitimate outcomes. They can mean no qualifying setup, stale data, incomplete observations, or insufficient validation.

Read **Why this is waiting** alongside any research-candidate label. A long or short research candidate does not override those blockers.

The evidence card shows the supporting sample size, net expectancy, uncertainty, and limitations when available. A historical win rate is not the probability that the next trade will win. Results from a short archive, assumed fills, or an assumed timing scenario do not become forward evidence because they look profitable.

### Shares and options

**Shares** shows the proposed instrument and research direction, with size unavailable until the required risk and evidence checks support it.

**Options** shows a selected contract only when the supplied contract observations and selection rules support one. Where available, the panel exposes its right, strike, expiry, multiplier, bid/ask, spread, scenario debit, maximum premium loss, fees, and reasons it remains blocked or incomplete. It also shows contract-selection assumptions, comparable IV observations, and an OI concentration table.

Quote/account feasibility and strategy profitability are separate checks. A contract marked feasible is not an approved trade. Free-chain indications alone cannot certify option execution; verified, timestamped contract imports have a separate qualification path. The panel also preserves the exercise-related limitations of a premium-loss estimate.

## Run research and preserve observations

**Run baseline research** first requires the verified rolling share/options liquidity prerequisite: 20 preceding sessions and at least 80% eligibility over the requested research window. Failed sessions are individually excluded. Missing free-feed historical quote coverage blocks new runs; the archive-timing checkbox does not bypass that gate. The initial SPY smoke result is labeled a prototype that predates qualification. When eligible, the single registered shares baseline tests opening-range continuation with VWAP confirmation, declared costs and timing, an invalidation stop, a target, and an end-of-session exit. It does not search automatically for profitable parameters. NVDL/TSLL cannot use this index playbook; their separate event-driven study remains unavailable.

Leave **Assume archive bars were available at bar close** unchecked to respect recorded availability timestamps. Recently downloaded historical bars were received recently; respecting that fact can correctly produce few or no historical trades.

Checking that box permits a historical timing scenario in which bars are treated as available when they closed. This can help explore an archive, but it cannot qualify archive-based decisions as forward trade evidence.

The research panel shows selected metrics, timing and cost assumptions, and the latest ten simulated trades. Expand its limitations and coverage details to inspect excluded sessions and ambiguous bars. **Download full research JSON** includes the complete saved result beyond those ten displayed trades. An empty trade list is a valid outcome, not an instruction to loosen the rules until trades appear.

**Record observation** is a separate, explicit journal action. It captures a current research observation or abstention and reports whether it was recorded, duplicated, late, or data-blocked. Reading Today never records one automatically. The intraday journal freezes experiment definitions and checks its hash chain.

Recording an observation does not imply an executed trade. **Automatic paper-trade outcome resolution is not implemented**, so this journal is not yet an automatically scored forward P&L record. The existing daily **Paper monitor** is a separate experiment and remains separate from these intraday observations.

## Export and replay

**Download current snapshot JSON** exports the currently selected state, including its symbol, snapshot identity, as-of time, evidence, and limitations. Options and research panels have their own JSON downloads. These export real saved/returned fields; they do not fill in missing prices or probabilities. The journal download contains the visible journal context, rather than promising a full historical ledger.

The saved `output/today_state.json` is the build's seed snapshot. The current-snapshot download follows the ticker currently selected in the browser, so it can differ from that static file.

There is no replay-date picker on Today. For an explicit read-only historical knowledge cutoff, use:

```powershell
.\.venv\Scripts\python.exe -B run_intraday.py replay --symbol SPY --as-of "2026-11-06T15:00:00-05:00"
```

The corresponding read-only API is `/api/v1/thesis_state?symbol=SPY&as_of=2026-11-06T15%3A00%3A00-05%3A00`. Data received after that cutoff cannot appear merely because it describes an earlier market date. Replay does not append paper records. Older daily context has separately disclosed availability limits; it is not a substitute for a contemporaneous intraday archive.

## Existing research screens

| Screen | What to use it for |
|---|---|
| **Indexes** | Historical daily ETF behavior, event effects, volatility, compounding, and adverse-move context. |
| **Tickers** | Per-ETF daily snapshots, historical charts, relative-volume/close-location proxies, news, and related markets. Daily proxies are not trade-by-trade order flow. |
| **Leverage (perps)** | Observed Kalshi perp quotes, spreads, funding context, and disclosed risk scenarios. ETF-proxy history is not actual historical perp execution. |
| **GEX / DIX** | Manually imported aggregate daily GEX/DIX history and its freshness indicator. This is separate from Today's contract/strike information. |
| **Original vs fixed** | The audit comparison showing calculation and statistical repairs relative to the original research app. |
| **Backtests** | Existing frozen daily ETF-proxy strategy scenarios, timing comparisons, and cost sensitivity. These are separate from the new intraday baseline. |
| **Paper monitor** | The existing daily experiment's immutable decisions and eligible later outcomes. It does not represent every new intraday observation. |
| **Data quality** | Source freshness, integrity, reconciliation, missing inputs, and remaining qualification limits. |
| **Jobs & macro** | Scheduled-release context, archived source status, and valid imported release/consensus vintages where supplied. Missing expectations remain unavailable. |

## Where to audit the app

These links assume this guide is stored in the repository's `docs` folder.

| Question | Implementation to inspect |
|---|---|
| What is displayed, and what does a control call? | [today/template.html](../today/template.html), [today/build.py](../today/build.py) |
| How is the current state assembled? | [terminal_state.py](../terminal_state.py), [terminal_api.py](../terminal_api.py) |
| Which instruments and risk settings are configured? | [terminal_config.py](../terminal_config.py) |
| What do free feeds collect, and when was it received? | [intraday_collect.py](../intraday_collect.py), [news_history.py](../news_history.py), [intraday/store.py](../intraday/store.py) |
| How are levels and the baseline defined? | [intraday/features.py](../intraday/features.py), [intraday/backtest.py](../intraday/backtest.py) |
| How are option quotes, OI, selection, and scenarios handled? | [options_research/core.py](../options_research/core.py), [options_research/levels.py](../options_research/levels.py) |
| How are research trials and paper records preserved? | [run_intraday.py](../run_intraday.py), [intraday/paper.py](../intraday/paper.py) |
| How are complete page bundles validated and published? | [build_pipeline.py](../build_pipeline.py), [validation.py](../validation.py) |
| What remains in the older daily research? | [stage1/studies.py](../stage1/studies.py), [monitor/backtest.py](../monitor/backtest.py), [monitor/paper.py](../monitor/paper.py) |
| How do startup, refresh, and local serving work? | [desktop_ui.py](../desktop_ui.py), [app_control.py](../app_control.py), [hub_server.py](../hub_server.py) |

The detailed import and capability reference is [INTRADAY_TERMINAL.md](INTRADAY_TERMINAL.md). Saved intraday bars and paper records are under `data/intraday/v1/`; research reports, run snapshots, and the trial registry are under `data/intraday/v1/research/`. Contract imports are under `data/options_research/`, headline history is under `data/news_history/`, and collection status is under `data/terminal/`.

The desktop **View logs** control exposes app/refresh status. `work/last_refresh.log` holds the full-build log. `output/build_manifest.json` records the validated bundle's source/input/output fingerprints. Preserve frozen experiments and append-only journals; use a new study or experiment version for a changed definition.
