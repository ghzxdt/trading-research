# Intraday tab (today.html)

The Intraday tab joins saved market data, charts, levels, news and research for manual trade review. It never submits orders. A research candidate is a hypothesis, not a validated edge or a position-size recommendation.

Updated 2026-11-22 for the trim of 2026-11-19 (the user's trim list): the universe went from 16 symbols to 7, single names are refused, and options data is no longer collected. What had been collected is in `archive/options-2026-11-19/` (see its README).

The configured universe (`terminal_config.json` `universe`) has **7 active symbols**: SPY, QQQ, IWM, TQQQ, SQQQ, UPRO and SPXU. DIA and RSP are inactive entries used by the research tabs only. The config refuses single names. Being listed does not establish liquidity or execution eligibility. Instrument metadata remains configured research context pending dated verification. Minute bars stored for tickers that were dropped stay on disk.

## Open and refresh

Run commands from `C:\Claude\trading-research` using its environment:

```powershell
.\.venv\Scripts\python.exe -B run_today.py --offline
```

This builds `output/today.html` from saved inputs (`run_all.py --offline` builds it with every other page). With the dashboard server running, open `http://localhost:8766/today.html`. Building or viewing the page does not collect market data or create paper outcomes.

Collection runs on a schedule and can also be started by hand:

- **Scheduled task "Trading Research Intraday Collection"** (`scheduled_collect.py`): minute bars in the 30 minutes before the close and again at 8:10 PM ET (after the extended session), plus share-liquidity snapshots at 10:30 AM, 12:30 PM, 2:30 PM ET and at the pre-close run. Yahoo keeps only about five days of one-minute bars, so these runs are what build the intraday history.
- **Scheduled task "Trading Research Live Minute Bars"** (`live_minute.py`): polls Yahoo five seconds after each minute of the regular session for the tickers in `collection.live_minute_symbols` (now SPY, QQQ and IWM; at most 20) and stores each completed bar in `data/intraday/v1/live/<date>.jsonl` with its receipt time.
- **By hand:** the page's collection action, or

```powershell
.\.venv\Scripts\python.exe -B run_intraday.py collect --all
```

Without `--all`, collection defaults to SPY, QQQ and IWM (`collection.default_symbols`). A smaller request is:

```powershell
.\.venv\Scripts\python.exe -B run_intraday.py collect --symbols SPY QQQ
```

Collection uses free Yahoo/yfinance data: a five-day, one-minute bar archive including available extended hours, and headlines (each headline's first-seen time is archived). `--without-options` is still accepted and changes nothing, since option chains are no longer collected. Coverage, delays and provider availability vary. Failures keep earlier useful observations and appear in the collection status (`data/terminal/collection_status.json`) and on the Daily thesis's System status card.

## Read the page correctly

The chart includes bar-based session VWAP, a completed 15-minute opening range, previous-session anchors when coverage is complete, and an explicitly incomplete observed extended-hours range. Weekend views can display the latest saved session while the market clock and thesis remain inactive.

The options panels and the options OI overlay remain, but show "unavailable" unless contracts have been imported (below). Imported strike concentrations are **unsigned observations**, not known dealer inventory, guaranteed support/resistance or barriers to execution. Quote times and OI publication dates must come with the import; displayed prices cannot establish fills or executable option P&L.

Risk values begin unavailable (`null`). Unknown account limits, permissions, quote quality or strategy evidence keep sizing blocked. Configuring a budget alone does not establish an edge. The terminal does not connect to a broker or place orders.

## Import your own observations

The import commands accept CSV, JSON lists, JSON objects containing a `records` list, or JSONL:

```powershell
.\.venv\Scripts\python.exe -B run_intraday.py import-bars "C:\path\bars.jsonl"
.\.venv\Scripts\python.exe -B run_intraday.py import-options "C:\path\contracts.jsonl"
.\.venv\Scripts\python.exe -B run_intraday.py import-liquidity "C:\path\liquidity.jsonl"
```

Use actual source data; the following are field schemas, not sample market observations.

**Bars:** `symbol`, `timestamp`, `available_at`, `open`, `high`, `low`, `close`, `volume`, `source`; optional `interval_seconds` defaults to 60, and `availability_basis` defaults to `unspecified`. The baseline requires one-minute bars. A CSV header is:

```csv
symbol,timestamp,available_at,interval_seconds,open,high,low,close,volume,source,availability_basis
```

`timestamp` is the UTC interval start. `available_at` is when the completed observation could actually be used and must be at or after interval end. Supply timezone-qualified timestamps, such as the format `YYYY-MM-DDTHH:MM:SS+00:00`. OHLC must be positive and consistent; volume must be nonnegative. The journal separately records local import time. Archive collection uses `retrieved_archive`. The live poller labels a bar `observed_live` only if it was first received within 120 seconds of the bar's close; a changed value later is stored as a revision, and an identical later archive copy does not replace the live bar. Never relabel a backfill `observed_live` to obtain forward eligibility.

**Options:** required identity/provenance fields are `symbol`, `contract_id`, `expiry` (ISO date), `right` (`C`/`P`), `strike`, actual `multiplier`, `timestamp`, `available_at` and `source`. Quote qualification additionally needs valid `bid`, `ask`, `bid_size`, `ask_size` and trustworthy source quote times. A last-trade timestamp is not a bid/ask timestamp.

Optional option fields include decimal annualized `iv`, `delta`, `gamma`, `volume`, `open_interest`, `open_interest_as_of`, `oi_available_at`, `quality`, `adjusted`, `deliverable` and `expiration_at`. OI requires its own publication timing before it can contribute a level. Adjusted contracts need actual deliverable metadata; same-day execution needs an explicit expiration cutoff. See `options_research/README.md` for complete requirements and supported scenario functions. Validation checks the supplied structure and consistency; it does not independently certify a vendor's claims.

**Liquidity sessions:** `symbol`, `session_date` (ISO date), explicit boolean `complete_session`, `source`, `source_timestamp`, `available_at`, `share_volume`, `share_median_spread_bps`, `options_volume`, `options_median_spread_bps`; provenance also requires `metric_method`, `spread_basis` set to `midpoint`, and nonempty `options_scope` when options metrics are supplied. A complete-session source timestamp cannot precede the exchange close; availability cannot precede the source timestamp. Describe actual coverage and the quote/contract population in those provenance fields. JSON/JSONL are preferred for exact booleans. Missing metrics fail the relevant screen. Imports are attested source history, not independent verification of a vendor's claims.

## The liquidity gate

`liquidity_screen.py` uses the 20 exchange sessions immediately before each target session, as known before it opens. Research requires the tests to pass on at least 80% of its requested window and excludes every individually failing session. Spreads use the median of session medians, not a pooled quote median. The configured thresholds (average share volume >=1,000,000, share spread <=10 bps; for options studies also average options volume >=10,000 contracts and options spread <=100 bps) are research policy assumptions, not fitted execution-capacity estimates.

- **Shares only for the shares baseline** (review C13, 2026-11-18): `orb-continuation-v1` trades shares, so its research and paper gate check share liquidity only. `research --options-gate` adds the options tests for an options study.
- **Two journals.** The default `verified` journal holds imported session histories. The `snapshot` journal is a declared weaker policy built from the free share-liquidity snapshots (spreads from four snapshots a day, not session medians); research uses it only with `--liquidity-journal snapshot`, and its results are labelled and counted as separate variants.
- **Status:** the gate needs 20 complete sampled days. On 2026-11-21 there were 2 (the Daily thesis's System status card shows the count), so research on the free snapshot journal is mid-December at the earliest. The earlier five-session SPY prototype is visibly marked as predating this prerequisite.

## Replay and research

Replay is read-only and uses a timezone-qualified **knowledge cutoff**:

```powershell
.\.venv\Scripts\python.exe -B run_intraday.py replay --symbol SPY --as-of "2026-11-06T15:00:00-05:00"
```

An archive received later cannot appear in an earlier replay merely because its bars describe that earlier date. Legacy daily context and configured event schedules have separately disclosed historical-availability limits; they do not become timestamped intraday evidence. Replay/offline mode cannot append observations or publish new research.

The single registered shares baseline is `orb-continuation-v1` (experiment A): first qualifying completed-bar crossing of the 15-minute opening range, VWAP confirmation, one position per session, opposite range boundary stop, 2R target and flatten five minutes before the cash-equity close by default. Entry uses a later observed event after knowledge and configured latency. Ambiguous stop/target bars use the stop first; gaps and costs receive explicit treatment. Cash-equity early closes are verified for 2025-2028 (`intraday/calendar.py`; 1 PM ET on days such as 2026-11-27); this is not an options-exchange hours model.

Actual supplied availability is respected by default:

```powershell
.\.venv\Scripts\python.exe -B run_intraday.py research --symbol SPY
.\.venv\Scripts\python.exe -B run_intraday.py research --symbol SPY --liquidity-journal snapshot
```

To explore a historical archive under an explicit bar-close timing assumption:

```powershell
.\.venv\Scripts\python.exe -B run_intraday.py research --symbol SPY --assume-bar-close-availability
```

The latter is a **historical timing and fill-cost scenario**, never forward evidence. Bar OHLC does not supply historical NBBO, capacity, borrow availability or actual stop fills. Incomplete paths are excluded with reasons, which can bias the available sample. Session bootstrap uncertainty requires at least 20 complete sessions and remains exploratory; serial dependence, trial selection and a short archive limit inference. No synthetic fixture result establishes trading performance.

Reports and the bounded trial registry live under `data/intraday/v1/research/`. Price-only shares research is separate from options-feature and options-execution comparisons, which need imported contracts. An import adapter is not a reconstructed historical option-chain database.

## Paper observations and protected history

```powershell
.\.venv\Scripts\python.exe -B run_intraday.py paper-record --symbol SPY
```

This explicitly logs an observation, abstention or blocked/late decision, judged on the current session's regular-hours bars only. Archive observations cannot qualify as forward trade evidence. The intraday journal freezes each experiment version and verifies a hash chain. Replay creates no records. **Automatic paper-trade outcome resolution is not implemented**; an observation log is not a forward P&L track record.

New bars and paper records live under `data/intraday/v1/` (live polls in `data/intraday/v1/live/`); contract imports use `data/options_research/`. A minute-bar writer lock left by a dead run is removed automatically and logged in `data/intraday/v1/lock_recoveries.log`. The daily paper journal and frozen experiment remain separate and must not be edited, replaced or retroactively upgraded.

## Capability boundaries

| Capability | Built now | Data or work still needed |
|---|---|---|
| Intraday tab across 7 configured symbols | Charts, context, quality states, levels, thesis abstentions | Adequate per-symbol coverage and current observations |
| Free collection | Scheduled and manual minute bars and headlines; live minute polling of up to 20 tickers; share-liquidity snapshots | Provider availability; no full-history or real-time guarantee |
| Causal replay | Knowledge-cutoff views and versioned observations | Contemporaneous archives for dates not previously collected |
| Shares research | One ORB baseline, shares-only gate, cost scenarios, trade ledger and session uncertainty | 20 complete sampled days, then longer data, suitable holdouts, executable quotes and validation |
| Options information | Import support for contracts with dated OI (free chain collection stopped 2026-11-19) | Imported contracts with verified quote/OI timing; unsigned OI is not dealer positioning |
| Options execution research | Contract import, quote checks and quoted-price/model scenarios | Suitable historical contracts/quotes, calibrated costs and external source verification |
| Options level diagnostics | Frozen-level and linked-control research utilities | Preregistered matched controls and genuine out-of-sample evidence |
| Paper evidence | Separate frozen decision journal | Valid contemporaneous inputs and future outcome automation/validation |
| Sizing and orders | Unavailable risk stays blocked; no order capability | Risk configuration and validated evidence do not by themselves add order routing |
