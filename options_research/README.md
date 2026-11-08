# Contract-level options research

This module adds options information and auditable quoted-price scenarios. It
does not supply a paid feed, submit orders, certify a strategy, or turn open
interest into observed dealer inventory.

## Import and replay

`ingest(root, records)` validates a complete batch before appending deduplicated
observations to `data/options_research/events.jsonl`. The event store is
hash-chained and single-writer locked. A failed chain is reported rather than
silently repaired. Offline/replay modes cannot append records.

`import_file(root, path)` accepts CSV, a JSON list, a JSON object with a `records`
list, or JSONL. All inputs use the same validation.

Required fields: `symbol`, `contract_id`, `expiry` (ISO date), `right` (`C` or
`P`), `strike`, `multiplier`, `timestamp`, `available_at`, and `source`.
Timestamps must contain explicit UTC offsets. `timestamp` identifies the source
observation; `available_at` identifies when it could actually be used. The store
also records import receipt time separately.

Quote fields are `bid`, `ask`, `bid_size`, and `ask_size`. Missing or invalid
quotes may remain information-only but cannot qualify an expression or P&L.
`quality` is a list of provider warnings. `timestamp_unverified` blocks execution.
A provider's last trade date is not a bid/ask timestamp.

Optional fields include decimal annualized `iv`, standard long-option `delta`
and `gamma`, `volume`, `open_interest`, `open_interest_as_of`,
`oi_available_at`, `adjusted`, `deliverable`, and `expiration_at`. OI contributes
no level until its own availability is known. Same-day execution requires an
explicit expiration cutoff. Adjusted contracts remain blocked from generic
execution until a product-specific deliverable adapter exists.

`history(root, symbol, as_of)` returns all knowledge-available observations.
`load(root, symbol, as_of)` returns the latest one per contract, avoiding OI
double counting. All replay functions are read-only.

## Information and expressions

`summarize(records, spot, as_of)` returns expiry groups, observed strike
concentrations, source times, unsigned gamma quantities, and explicitly
hypothetical dealer-sign scenarios. It reports quote age and qualification
counts. Old context is not promoted to fresh executable quotes. Cross-market
inputs are rejected rather than implicitly rescaled.

`select_expression(records, direction, account, as_of)` uses a fixed target
absolute delta and expiry range, then checks affordability. It does not move
farther out of the money to make a selected trade affordable. Default parameters
are research conventions, not calibrated universal thresholds.

Account keys: `options_permitted`, `quantity`, `max_trade_debit`,
`max_loss_per_trade`, `available_cash`, `fee_per_contract_per_side`,
`max_quote_age_seconds`, `max_spread_pct`, `min_dte`, `max_dte`, and
`target_abs_delta`. DTE is measured in calendar days. Spread fraction uses option
midpoint as denominator. Unknown budgets, fees, or permissions keep the result a
comparison only. Even `eligible` denotes quote/account feasibility; the module
never enables recommended position sizing or validates strategy expectancy.

`executable_pnl` buys the entry ask and sells the exit bid with actual multiplier,
displayed-size checks, causal timestamps, and per-contract/per-side fees.
`debit_spread_pnl` additionally checks matching deliverables and synchronized legs.
Neither function subtracts theta again. They are quoted execution scenarios,
not proof a historical order filled. Spread assignment and legging risks remain
explicit limitations.

`price_scenarios` jointly changes spot, decimal IV, and elapsed time using a
clearly labeled European approximation. It assigns no real-world probabilities
and does not certify American exercise, volatility-surface dynamics, or fills.

## Frozen-level diagnostics

`evaluate_levels` requires levels known before their first observed touch. It
does not order competing outcomes inside the touch bar. A later bar touching
both rejection and breakout thresholds is ambiguous and unscored. Gaps and
incomplete horizons are censored. Contract-source levels cannot be silently
rescaled to another underlying.

`level_study` reports resolved and unresolved counts and exploratory session-level
bootstrap intervals against explicitly linked controls. The caller must register
the design and verify matching for round numbers, distance, time, volatility,
expiry, and earlier-session coverage. These diagnostics create neither a fresh
holdout nor multiplicity adjustment, simulated trade P&L, or evidence of an edge.
