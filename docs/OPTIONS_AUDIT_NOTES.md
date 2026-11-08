# Options upgrade: audit and operating notes

The upgrade separates **options as information** from **options as a trade
expression**. A strike concentration can be useful context without establishing
support, resistance, signed dealer inventory, or a profitable options trade.

## Source map and actual capabilities

- `options_research/core.py`: canonical contract validation; JSON/JSONL/CSV imports;
  an append-only, hash-chained observation store with an exclusive writer;
  availability-filtered history and latest-per-contract replay; expiry/strike
  summaries; deterministic long-call/put selection; quoted long-option and debit
  vertical P&L; joint theoretical spot/IV/time scenarios.
- `options_research/levels.py`: frozen-level reaction diagnostics and explicitly
  linked control comparisons. Historical versions of the same contract-level
  concentration supersede older versions.
- `options_research/README.md`: API, field units, research conventions, and limits.
- `intraday_collect.py`: the separate free current-chain collection path.
- `terminal_state.py`: combines options context, expression feasibility, data
  health, and the chart without promoting a research observation to a trade.
- `tests/test_options_research.py`: **34 targeted tests passed** in the final
  package verification. The full-project test report is separate.

## Data required and free-feed boundary

Execution-quality imports require a contract identifier, underlying, expiry,
call/put right, strike, actual multiplier, source observation timestamp, and
actual availability timestamp. Quoted entry/exit scenarios additionally require
valid bid/ask prices and adequate displayed sizes. Adjusted contracts need their
actual deliverable and remain blocked from the generic execution adapter.

OI features require both an observation date and their own availability time.
Unknown or future OI availability produces no OI-derived level. Same-day
execution requires an explicit expiration cutoff. Imports retain receipt
provenance separately; a historical import cannot create a forward paper record.

Yahoo's current chain is **indicative information**, stored separately from
verified execution observations. Its last-trade time is not a bid/ask timestamp.
Local receipt does not certify quote time or OI publication date. The free path
does not reconstruct historical chains, certify fills, or make dealer positions
observable. No paid source, broker integration, or order submission was added by
the options package.

## Accounting and selection

Long-option scenarios buy the entry ask and sell the exit bid, multiplied by
integer quantity and the supplied contract multiplier. Fees apply per contract
per side. Spreads are already reflected in those prices: theta and spread costs
are not deducted a second time. Feasibility checks reserve closing fees as well
as entry debit. Unknown budgets, permissions, or fees prevent a completed
feasibility verdict; even `eligible` never enables recommended sizing.

Selection follows the declared delta/expiry rule before affordability. It does
not switch to a cheap, far-out-of-the-money contract to force the budget.

Debit-spread scenarios require matching contract terms, correct strike order,
synchronized legs, displayed size, and exits after complete entry information.
The bounded payoff assumes an intact spread; assignment, legging, and temporary
stock exposure are not simulated guarantees.

Theoretical scenarios use a European Black–Scholes approximation with specified
rates, dividend yield, IV changes, and elapsed time. They reject expired contracts
and horizons beyond expiration. American exercise, discrete dividends, surface
dynamics, and actual execution remain outside that approximation. No physical
success probabilities are assigned.

## Level-study interpretation and tests

Levels must be known before the touch. The touch bar is not internally ordered;
later bars reaching both outcomes are ambiguous. Gaps, incomplete horizons, and
invalidation censor observations. First observed touch requires a separate
session-coverage check before it can mean first actual touch.

Control matching remains a registered research responsibility. Reports retain
unresolved counts and exploratory session-level intervals; neither a reaction
rate nor a bootstrap creates after-cost expectancy or an untouched holdout.
Tests cover causality, tampering, duplicates/conflicts, stale/invalid quotes,
fees/multipliers, affordability, expiry, spread synchronization, hypothetical
scenarios, cross-market level misuse, and superseded level versions.
