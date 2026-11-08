# Intraday Today terminal

Today joins saved market data, charts, levels, options context, news and research for manual trade review. It never submits orders. A research candidate is a hypothesis, not a validated edge or a position-size recommendation.

The configured universe contains **16 symbols**: SPY, QQQ, IWM, TQQQ, SQQQ, SOXL, TNA, LABD, KORU, BITX, ERY, FNGU, UPRO, SPXL, NVDL and TSLL. Being listed does not establish liquidity or execution eligibility. Instrument metadata remains configured research context pending dated verification.

## Open and refresh

Run commands from `C:\Users\gzdt\trading-research` using its existing environment:

```powershell
.\.venv\Scripts\python.exe -B run_today.py --offline
```

This builds `output/today.html` from saved inputs. With the dashboard server running, open `http://localhost:8766/today.html`. Building or viewing Today does not collect market data or create paper outcomes.

Use Today's explicit collection action, or:

```powershell
.\.venv\Scripts\python.exe -B run_intraday.py collect --all
```

Without `--all`, collection defaults to SPY, QQQ and IWM. A smaller explicit request is:

```powershell
.\.venv\Scripts\python.exe -B run_intraday.py collect --symbols SPY QQQ --without-options
```

Collection uses free Yahoo/yfinance data: a requested five-day, one-minute bar archive including available extended hours, current indicative option chains for up to three expiries, and headline adapters. Coverage, delays and provider availability vary. Failures retain earlier useful observations and appear in collection status. Collection is manual; this extension changes no scheduled tasks or existing daily refresh cadence.

## Read the page correctly

The chart includes bar-based session VWAP, a completed 15-minute opening range, previous-session anchors when coverage is complete, and an explicitly incomplete observed extended-hours range. Weekend views can display the latest saved session while the market clock and thesis remain inactive.

Options strike concentrations are **unsigned observations**, not known dealer inventory, guaranteed support/resistance or barriers to execution. Current free-chain quote times and OI publication dates are unverified. Their displayed prices cannot establish fills or executable option P&L.

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

`timestamp` is the UTC interval start. `available_at` is when the completed observation could actually be used and must be at or after interval end. Supply timezone-qualified timestamps, such as the format `YYYY-MM-DDTHH:MM:SS+00:00`. OHLC must be positive and consistent; volume must be nonnegative. The journal separately records local import time. Free collection uses `retrieved_archive`; never relabel a backfill `observed_live` to obtain forward eligibility.

**Options:** required identity/provenance fields are `symbol`, `contract_id`, `expiry` (ISO date), `right` (`C`/`P`), `strike`, actual `multiplier`, `timestamp`, `available_at` and `source`. Quote qualification additionally needs valid `bid`, `ask`, `bid_size`, `ask_size` and trustworthy source quote times. A last-trade timestamp is not a bid/ask timestamp.

Optional option fields include decimal annualized `iv`, `delta`, `gamma`, `volume`, `open_interest`, `open_interest_as_of`, `oi_available_at`, `quality`, `adjusted`, `deliverable` and `expiration_at`. OI requires its own publication timing before it can contribute a level. Adjusted contracts need actual deliverable metadata; same-day execution needs an explicit expiration cutoff. See `options_research/README.md` for complete requirements and supported scenario functions. Validation checks the supplied structure and consistency; it does not independently certify a vendor's claims.

**Liquidity sessions:** `symbol`, `session_date` (ISO date), explicit boolean `complete_session`, `source`, `source_timestamp`, `available_at`, `share_volume`, `share_median_spread_bps`, `options_volume`, `options_median_spread_bps`; provenance also requires `metric_method`, `spread_basis` set to `midpoint`, and nonempty `options_scope` when options metrics are supplied. A complete-session source timestamp cannot precede the exchange close; availability cannot precede the source timestamp. Describe actual coverage and the quote/contract population in those provenance fields. JSON/JSONL are preferred for exact booleans. Missing metrics fail the relevant screen. Imports are attested source history, not independent verification of a vendor's claims; current free chains are never automatically converted into this history.

The configured policy uses 20 immediately preceding exchange sessions available before each target session opens. Research requires share and options tests to pass on at least 80% of its requested window, and excludes every individually failing session. Initial configurable thresholds are average share volume >=1,000,000, share spread <=10 bps, average options volume >=10,000 contracts, and options spread <=100 bps. Spreads use the median of session medians, not a pooled quote median. These are research policy assumptions, not fitted execution-capacity estimates. Free feeds currently lack the verified history to pass this gate, so new baseline research is blocked until suitable imports exist. The earlier five-session SPY prototype is visibly marked as predating this prerequisite.

NVDL and TSLL retain charts and data collection, but cannot use index baseline candidates, research parameters, or the index observation journal. Their separate event-driven study remains to be built.

## Replay and research

Replay is read-only and uses a timezone-qualified **knowledge cutoff**:

```powershell
.\.venv\Scripts\python.exe -B run_intraday.py replay --symbol SPY --as-of "2026-11-06T15:00:00-05:00"
```

An archive received later cannot appear in an earlier replay merely because its bars describe that earlier date. Legacy daily context and configured event schedules have separately disclosed historical-availability limits; they do not become timestamped intraday evidence. Replay/offline mode cannot append observations or publish new research.

The single registered shares baseline is `orb-continuation-v1`: first qualifying completed-bar crossing of the 15-minute opening range, VWAP confirmation, one position per session, opposite range boundary stop, 2R target and flatten five minutes before the cash-equity close by default. Entry uses a later observed event after knowledge and configured latency. Ambiguous stop/target bars use the stop first; gaps and costs receive explicit treatment. Cash-equity early-close coverage is verified for 2025–2028; this is not an options-exchange hours model.

Actual supplied availability is respected by default:

```powershell
.\.venv\Scripts\python.exe -B run_intraday.py research --symbol SPY
```

To explore a historical archive under an explicit bar-close timing assumption:

```powershell
.\.venv\Scripts\python.exe -B run_intraday.py research --symbol SPY --assume-bar-close-availability
```

The latter is a **historical timing and fill-cost scenario**, never forward evidence. Bar OHLC does not supply historical NBBO, capacity, borrow availability or actual stop fills. Incomplete paths are excluded with reasons, which can bias the available sample. Session bootstrap uncertainty requires at least 20 complete sessions and remains exploratory; serial dependence, trial selection and a short archive limit inference. No synthetic fixture result establishes trading performance.

Reports and the bounded trial registry live under `data/intraday/v1/research/`. Price-only shares research is separate from the still-data-dependent comparisons of options features and options execution. An import adapter is not a reconstructed historical option-chain database.

## Paper observations and protected history

```powershell
.\.venv\Scripts\python.exe -B run_intraday.py paper-record --symbol SPY
```

This explicitly logs an observation, abstention or blocked/late decision. Archive observations cannot qualify as forward trade evidence. The intraday journal freezes each experiment version and verifies a hash chain. Replay creates no records. **Automatic paper-trade outcome resolution is not implemented**; an observation log is not a forward P&L track record.

New bars and paper records live under `data/intraday/v1/`; contract imports use `data/options_research/`. The existing daily paper journal and frozen experiment remain separate and must not be edited, replaced or retroactively upgraded.

## Capability boundaries

| Capability | Built now | Data or work still needed |
|---|---|---|
| Today across 16 configured symbols | Charts, context, quality states, levels, thesis abstentions | Adequate per-symbol coverage and current observations |
| Free collection | Explicit bar, indicative chain and headline collection | Provider availability; no full-history or real-time guarantee |
| Causal replay | Knowledge-cutoff views and versioned observations | Contemporaneous archives for dates not previously collected |
| Shares research | One ORB baseline, cost scenarios, trade ledger and session uncertainty | Longer data, suitable holdouts, executable quotes and validation |
| Options information | Expiry/strike context and dated-OI import support | Verified quote/OI timing; unsigned OI is not dealer positioning |
| Options execution research | Contract import, quote checks and quoted-price/model scenarios | Suitable historical contracts/quotes, calibrated costs and external source verification |
| Options level diagnostics | Frozen-level and linked-control research utilities | Preregistered matched controls and genuine out-of-sample evidence |
| Paper evidence | Separate frozen decision journal | Valid contemporaneous inputs and future outcome automation/validation |
| Sizing and orders | Unavailable risk stays blocked; no order capability | Risk configuration and validated evidence do not by themselves add order routing |
