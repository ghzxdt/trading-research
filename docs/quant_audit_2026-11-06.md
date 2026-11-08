# Quant research app audit and proposed repair plan

Audit date: November 6, 2026. Saved market data ends November 5, 2026.

**Assessment:** useful research infrastructure, with several real calculation defects and promising risk descriptions. It does not yet establish a profitable trading strategy. I would repair the data/risk defects, then test a small number of precisely defined trades after all costs before building a combined daily directional call.

**Change status:** no application source, cached inputs, generated application reports, account settings, or positions were changed. The app was inspected read-only, the existing self-check was run offline, and separate scratch calculations were performed. This audit document is a new deliverable. Proposed changes below have not been implemented.

## Scope and evidence

Reviewed the supplied summary and all eight pages of the PDF, source modules in stage1/, tickers/, leverage/, and gex/, runners/server, saved raw and derived data, and generated chart specifications. Opened the running localhost report and representative Indexes and SQQQ charts. Compared relevant assumptions with official BLS, Cboe, and Kalshi documentation.

Project source root (all code references below are relative to this exact directory):

`C:\Users\gzdt\AppData\Local\Claude-Data\claude_pzs8sxrjxfjjc\scratch-workspaces\59d401cd-5704-4f9d-b932-996e64640858\fc1f47ab-6f46-46d4-95c0-8b535e5f753f\scratch-2026-11-06-c4ca96`

The current HTML report shows nine unadjusted "possible edge" findings, while the supplied summary/PDF describe eight. Its borderline QQQ-relative-weakness result is one source of the difference. Research summaries, runtime versions, inputs, and rendered reports need a common version/run identifier.

## What the app does

1. Downloads/caches adjusted daily ETF prices, Cboe volatility indexes, Treasury yields, public Kalshi market/funding/candle data, and headlines. Reads a manually maintained economic-event calendar and a manually downloaded GEX/DIX file.
2. Builds daily features and classifies SPY days by return divided by the prior VIX-implied daily move.
3. Calculates historical means, growth curves, risk statistics, event effects, and randomization-based exploratory findings.
4. Writes HTML pages and CSV tables. The browser hub has Indexes, Tickers, Leverage, and GEX/DIX tabs.
5. Displays 70 saved chart specifications: 11 Indexes, 54 across nine ticker pages, two Leverage, and three GEX/DIX.

It has no automated broker execution, live position management, or validated daily trading call. Daily volume/close-location measures are descriptive order-flow proxies; minute bars alone would not establish actual aggressor-side trade flow.

## Employment reports: included, but only at the calendar/event level

**Present:** jobs-release dates, historical jobs-day flags, upcoming-calendar entries, an overnight move-size study, and a full-day directional study.

**Absent:** actual nonfarm payrolls, unemployment, wages, participation/hours, consensus estimates, forecast surprises, first-release versus revised values, automated BLS calendar reconciliation, weekly claims, JOLTS, and ADP ingestion.

The static calendar agrees with the official BLS November 6, 2026 jobs-release date and time: 8:30 a.m. Eastern / 7:30 a.m. Chicago. The checked future jobs dates also match; I did not find a fabricated date error. The gap is ongoing verification and economic-content ingestion. [BLS Employment Situation schedule](https://www.bls.gov/schedule/news_release/empsit.htm)

Evidence: stage1/sources.py:219; stage1/dataset.py:151-157; stage1/studies.py:756-848; stage1/health.py:163-184; tickers/news.py:112-129.

## Priority findings and concrete repairs

### 1. Missing margin inputs can become zero historical risk — confirmed bug

leverage/build.py:111 creates an unavailable/NaN cushion if margin inputs are absent. At :169-185, comparisons against that NaN are false, so hit rates become 0%. study_liquidation at :199-208 can then describe the event as having happened "never." An in-memory synthetic check reproduced this.

**Repair:** validate finite positive leverage, multiplier, cushion, and usable historical observations before calculation. Return unavailable with a reason; suppress risk headlines and any future position size. Never translate unknown into zero.

**Acceptance:** missing, NaN, zero, negative, infinite, and absent risk settings all produce explicit unavailable outputs. Valid cases preserve the intended calculation. A report cannot display "0%" merely because risk inputs are missing.

### 2. Long and short margin estimates are collapsed — confirmed inconsistency

The saved API contains distinct side estimates, while leverage/build.py:109-111 reads only generic leverage_estimate and :175-181 applies the same cushion to both sides. Saved US500 estimates are approximately 14.65x long versus 12.24x short; US Tech 100 is 11.85x versus 10.56x. These are audit-snapshot values, not current executable offers.

**Repair:** retain side, position size, entry price, mark price, margin, funding, and relevant exchange thresholds. Reconcile modeled liquidation prices with actual displayed product-specific examples before allowing sizing.

**Important clarification:** Kalshi's official API does support initial margin = maintenance margin × the per-market initial-margin multiplier. The 1.3 relationship itself is not an invented assumption. It does not establish that a fixed entry-notional cushion is an exact liquidation model for every product and size. A proposed security-futures filing is also not proof of the retail broad-index liquidation formula. [Kalshi risk API](https://docs.kalshi.com/margin-rest/risk/get-risk-parameters), [Kalshi liquidation guidance](https://help.kalshi.com/en/articles/15357646-understanding-liquidation), [SEC-hosted proposed SFP rules](https://www.sec.gov/files/rules/sro/kalshiex/2026/34-106422-ex4.pdf)

### 3. ETF threshold crossings are labeled too strongly as liquidation odds

leverage/build.py:169-185 measures ETF regular-session high/low threshold crossings from the prior close or over five sessions. This does not observe overnight perp extrema, live mark/basis differences, changing margin, exact entry times, funding, or liquidation execution. The five-session windows overlap.

**Repair:** label these historical proxy barrier-hit frequencies, identify all assumptions and sample sizes, and add uncertainty. Use actual perp mark paths when available for liquidation validation. Keep the long ETF history as a stress proxy rather than presenting it as calibrated live odds.

### 4. SPXU holding-period calculations skip a trading session — confirmed bug

stage1/studies.py:862-869 and tickers/build.py:162-166 remove missing-price dates before shifting forward. The removed October 18, 2010 price causes the valid October 15-to-October 19 move to be labeled one day, although it spans two sessions. Longer horizons crossing that date are also affected.

**Repair:** keep the full exchange-session index, shift by the requested session count, and then exclude invalid endpoints. Record valid counts by horizon.

**Acceptance:** the missing October 18 observation cannot turn October 15-to-October 19 into a one-session return. Synthetic missing-middle-session cases preserve one-, five-, 21-, and 63-session horizons.

### 5. SPXU buy-and-hold growth omits a valid price change — confirmed chart bug

tickers/build.py:88 fills missing returns with zero before compounding. Removing a bad close also makes the following daily return unavailable. The growth chart treats both days as flat and loses the approximately +2.401% change between the valid October 15 and October 19 closes.

Terminal wealth currently calculates to approximately 0.000178641 per initial dollar versus 0.000182931 from valid price endpoints: about **2.345% too low** relative to the endpoint-based wealth.

**Repair:** calculate a buy-and-hold wealth curve directly from normalized adjusted closes; show a gap at an unknown intermediate close. Do not invent a daily return to repair a descriptive wealth curve.

### 6. Overnight/daytime components use a different sample from buy-and-hold

stage1/studies.py:290-300 and tickers/build.py:83-89 exclude unconfirmed opens for the split, but the all-days curve includes those dates. SPY's all-days terminal wealth is approximately $8.688 per initial dollar; the filtered overnight × daytime product is $8.117. QQQ's corresponding values are $16.094 versus $17.701.

The 68%/69% figures are filtered **log-growth shares**, not a direct share of all-sample dollar profit. The missing-open limitation is disclosed, but the chart invites an inconsistent decomposition.

**Repair:** use a common sample for the decomposition, provide the full-sample benchmark as a separately labeled comparison, and state that the contribution uses log growth. Identify dividend-adjusted ETF total returns; do not automatically transfer them to an index-price perp without reconciling dividends and funding.

### 7. Tiny positive wealth is printed as $0.00 — confirmed display defect

stage1/report_template.html:225 and stage1/report.py:62 use fixed two-decimal dollar formatting. SQQQ has approximately $0.00000535 remaining per original $1, so numerous distinct logarithmic levels and endpoints display as $0.00. This was visible in the running browser chart.

**Repair:** use adaptive precision/scientific notation and label the log scale. Avoid rounding a nonzero remaining investment to an apparent total loss in supporting text/tables.

### 8. The GEX risk table mixes SPY scaling and endpoint movement

gex/build.py:38-43 estimates conditional SPY daytime size; :61-69 divides all products' cushions by that same SPY value, including QQQ/Tech. Its frequency uses absolute open-to-close changes, which can miss an adverse intraday barrier touch followed by recovery and counts favorable moves as well.

**Repair:** use each product's proxy distribution and separate long/short adverse excursions from endpoint move sizes. Suppress current conditional estimates if GEX is stale. Keep a separate, precisely labeled endpoint-volatility statistic if useful.

### 9. Emergency Fed actions are treated as scheduled information

data/events/events.csv:327 and :330 include the March 3, 2020 emergency cut and Sunday March 15 action mapped to March 16. stage1/dataset.py:151-157 labels all Fed entries known in advance; stage1/studies.py:763 sends every Fed event to the daytime window, including the Sunday announcement.

**Repair:** separate scheduled decisions and unscheduled announcements; retain actual release time and when the schedule became known. Map the effect to the actual tradable interval.

Removing the two emergency entries in an exploratory check leaves a scheduled-Fed size ratio near 1.28x versus the original 1.29x. The classification error is real, but it does not appear to explain away the whole effect.

### 10. Jobs size tests need better controls

Only event direction tests receive weekday controls (stage1/studies.py:794-804). The jobs size test at :785 compares all ordinary weekdays. Closed-day releases shifted to Monday can mix employment news with a holiday-length gap.

**Repair:** control weekday, gap length, volatility regime, overlapping events, and release time; add pre-release versus post-release intraday windows. In an exploratory Friday-only sensitivity check, the jobs size effect strengthens rather than disappears. This is a control-design issue, not proof the finding is false.

### 11. Signal timing does not yet match an executable trade

The day-after studies use the completed day classification and sometimes that day's final VIX, then describe returns beginning at that day's 4 p.m. close. The app normally builds after 4:30 p.m. Final VIX continues to 4:15 p.m. on ordinary sessions. A later-known signal cannot assume execution at an earlier closing price. [Cboe VIX methodology](https://cdn.cboe.com/resources/vix/VIX_Methodology.pdf)

**Repair:** specify a decision timestamp for each rule and use the next executable bid/ask after all inputs are available. Alternatively test a genuinely earlier signal with only information available then. Recalculate overnight and five-session P&L from that entry.

### 12. The directional evidence is fragile and selected on the research sample

The four historical sign checks reuse the development sample. The VIX 20 split was selected after seeing the parent result. Several leads overlap, so they are not independent confirmations.

Across 33 existing tests (30 Indexes plus three GEX/DIX), using the project's Python environment and cached inputs:

| Existing-test correction at 5% | Findings retained |
|---|---|
| Holm family-wise correction | Weekend, holiday, and negative-GEX size effects only |
| Benjamini-Hochberg false-discovery correction | Those three, Fed size, and general post-big-rise next-day direction |

The general post-big-rise result has p approximately 0.00675 and BH q approximately 0.04455 in this diagnostic. The other three featured directional leads fail that BH correction. These calculations adjust the app's existing p-values; they do not fix the resampling assumptions or reconstruct every unrecorded research trial.

Using the app's already-disclosed February 15-June 30, 2020 sensitivity window:

| Signal | All signal dates | Excluding that window's signal dates |
|---|---:|---:|
| Big rise and VIX >=20 | 112 cases; next-day mean -0.320% | 98 cases; -0.043% |
| Any big rise | 403 cases; -0.118% | 389 cases; -0.041% |

**Repair:** freeze candidate rules and a research registry; apply suitable dependence-aware inference and multiple-testing controls; use walk-forward evaluation, purge overlapping outcomes, and reserve genuinely unseen forward data. Align the tested statistic with the traded portfolio: the current tests use VIX-normalized returns while headlines show raw means.

The one-day random draws lose residual serial dependence; whole-history circular shifts improve overlapping-window handling but still depend on regime/exchangeability assumptions. Seeds currently hash floating-point sample bytes, so CSV rounding can change the draws. Use stable test IDs, enough fixed draws for shortlisted candidates, Monte Carlo uncertainty, and (hits+1)/(draws+1) rather than literal zero p-values. Neither 33 tests nor their corrections captures every exploratory choice made during development.

### 13. No executable after-cost profit test exists

The +0.51% five-session normal-drop result is about +0.23 percentage points above its +0.28% unconditional baseline. That is a research lead, not net profit. Likewise, a -0.02% five-session mean after a rally is a weak absolute short-return proposition even when its underperformance of the baseline is statistically interesting.

**Repair:** construct timestamped trades and account P&L with entry/exit bid-ask costs, actual maker/taker fees, realistic slippage/partial fills, funding at exact payment times, changing notional, gaps, stops, and portfolio exposure. Avoid double-counting spread when using bid/ask fills. Compare with cash and sensible matched-exposure benchmarks. Report confidence intervals, drawdowns, turnover, tail losses, and sensitivity to worse costs. Kalshi confirms that fees use notional value and apply at both entry and exit. [Kalshi perps fees](https://help.kalshi.com/en/articles/16071417-perps-fees-explained)

### 14. Data validation does not gate normal publication

Any nonempty Yahoo response can replace the cache (stage1/sources.py:86-110), even if a ticker or history segment is missing. Normal run_all.py builds do not run the separate self-check; stage1 CSVs are written before health checks and warnings do not block report publication. Different tabs can therefore represent different runs if a later builder fails.

**Repair:** validate candidate downloads by required ticker, exchange calendar, coverage, uniqueness, OHLC constraints, corporate actions, expected latest session, and source provenance before atomic cache replacement. Keep the previous known-good input. Publish a validated report bundle with a shared run ID and source manifest. Block any future trade call when required inputs fail; optional news failures need not invalidate prices.

### 15. Passing the current self-check does not prove historical availability

stage1/selfcheck.py:34-40 truncates today's historical data and keeps today's complete event file. It is a useful transformation/prefix-invariance check. It does not observe historical vendor revisions, schedule changes, or publication availability, and the current stage1 check does not validate the separate GEX join/studies.

**Repair:** keep the check, label its scope accurately, preserve immutable download snapshots with timestamps/hashes, track release vintages, and test decision-time replay. Revalidate official calendars automatically while retaining schedule-change history.

### 16. Risk and funding labels need more precision

- The "1-in-100 bad day" chart uses absolute close-to-close return quantiles, not directional losses or maximum adverse excursion (stage1/studies.py:966-977). At VIX 30+, its roughly 8.85% is an absolute move quantile. Use side-specific adverse tails for stops and sizing, and expected shortfall/stress scenarios beyond the quantile.
- "Noise alone" stop-hit percentages include news and crash days (stage1/studies.py:981-989). They are threshold-touch frequencies, not a decomposition of noise or stop-fill performance.
- Funding summary arithmetic reproduces: saved US500 average is about $1.36/$10,000/calendar day, simple annualized 4.96% of notional and about 60.7% of posted margin at the generic maximum leverage. This extrapolates a short sample, not a forecast.
- Funding code says shorts paid "on the rest" even though the saved 31 US500 records contain 19 positive, 11 zero, and only one negative rate (leverage/build.py:279). Separate positive, negative, and zero. Compare funding and returns on consistent calendar/trading-day horizons.
- The 95% overnight sign agreement largely compares overlapping already-realized intervals. It is not evidence of profitable prediction from a 9 a.m. entry. Test the return after the actionable signal.
- VIX is a 30-day options-implied measure. The 68% normal-coverage heuristic and VIX/16 conversion are useful approximations, not exact next-day probability guarantees or a proof that buying/selling options is profitable.
- Predictor rankings currently use different available samples. On a common 3,983-observation sample, VIX/VIX9D rank correlations are about 0.410/0.435. The ranking persists, but fair comparisons need identical dates and forward evaluation.
- The market-table spread is the full (ask-bid)/mid. Describe half-spread per side relative to midpoint, or a full spread for an immediate unchanged-quote round trip, rather than ambiguously calling the full spread one crossing's cost.
- Trailing-30-day funding and since-launch funding use different samples intentionally; expose the horizons prominently. In the saved US500 data they are about $1.30 and $1.36 per $10,000/day respectively.
- The DIX rank begins after 200 observations even though supporting text says a year is required. Align the threshold and description.

### 17. Daily-reset compounding and ETF implementation tracking should be separated

The 3x study compares the fund with three times the entire holding-period underlying return. That illustrates path dependence but is not an ideal daily-reset benchmark. Add product(1 + L * daily underlying return) - 1, then show actual minus ideal separately. Call the overlapping 21-session observations windows, rather than independent calendar months.

The current "choppy" classification means only that the underlying ends within +/-2%; it does not measure the intervening path's choppiness. Rename it near-flat endpoint or explicitly measure realized path variation.

For the saved choppy windows, deviations from naive +/-3x are around -1.21% TQQQ/-1.23% SQQQ; against an ideal daily-reset QQQ proxy, the residual is approximately -0.40%/+0.35%. The latter still includes fund/proxy differences and is not a clean attribution of fees alone.

## Checks that passed, and limits of those checks

- The existing offline self-check passes: six historical prefix rebuilds, return multiplication, day labels, known-at label coverage, and no repeated options-expiration month.
- All 70 saved chart specifications have matching series/axis lengths, ordered unique dates, finite-or-explicitly-missing values, and positive log-chart values.
- All 11 Indexes charts reproduce exactly from the saved full-precision raw inputs; 54 ticker charts reproduce from the exported daily table within the stated CSV precision tolerance.
- Both Leverage charts and all three GEX/DIX charts also reproduce from their saved inputs. Separate historical truncation checks of GEX-known/DIX-known/rank joins pass at five dates; the backward-looking shifts themselves are implemented correctly.
- Independent latest-return, 20-session volatility, and maximum-drawdown calculations pass for all nine ETFs, allowing rounding.
- Saved raw ETF checks found no duplicate-date, nonpositive-price, or OHLC enclosure violations. Main/long SPY and QQQ overlapping histories agree to much less than one basis point.
- Kalshi candle boundaries represent period ends; saved boundary timestamps and DST conversion are consistent. No extra contract-size multiplication error was found in saved dollar notionals.
- US500 tracking correlation is approximately 0.999312 across 22 returns, with RMS return difference about 0.04397%. These descriptive figures reproduce. Rounded 1.00 correlation is not proof of zero basis, executable fills, or an edge.

**External accuracy is not yet certified:** reproducing a chart from Yahoo inputs does not prove every Yahoo observation is correct. A full independent vendor reconciliation, point-in-time historical archive, live account liquidation-price reconciliation, and after-cost strategy validation remain outstanding. No present result justifies a promise of profitability.

## Proposed implementation order and completion criteria

| Batch | Planned changes | Evidence required before completion |
|---|---|---|
| A: calculation and chart repairs | Unknown-risk handling; side-specific margin inputs; preserved session horizons; endpoint-based wealth; common-sample decomposition; adaptive tiny-value formatting; GEX proxy/path fixes | Regression examples for the actual failures; before/after tables; reproducible chart data; visual checks |
| B: trustworthy inputs | Candidate-download validation, independent price spot checks and anomaly reconciliation, calendar/timestamp handling, source snapshots, freshness gates, common run manifest | Missing ticker/stale source/failed builder cannot publish a current actionable call; exceptions are visible and traceable |
| C: employment data | Initial payroll/unemployment/wage releases, consensus captured before release, prior values and revisions, publication/availability timestamps; claims/JOLTS next if independently justified | Historical replay cannot see revisions or expectations that were unavailable at the decision time; report-missing states work |
| D: profitability test | Frozen candidate rules; executable timing; trade/account ledger; full costs/funding; overlapping-position rules; walk-forward tests and stress/cost sensitivity | Reproducible net expectancy and risk estimates on unseen data, with uncertainty and benchmark comparison |
| E: forward validation and sizing | Immutable paper-call log, no-edge abstention, joint SPY/QQQ exposure budget, stops/gap scenarios, liquidity limits, calibrated margin monitoring | Predeclared forward criteria; actual slippage/fee/funding comparison; no sizing from unavailable/unvalidated risk |

Start research with one venue/product and a small fixed candidate set. The normal-drop five-session long is worth evaluating because its absolute gross return is economically larger than the five-session short lead; this is a test priority, not a recommendation to place the trade. Keep volatility/event/GEX effects primarily as risk controls until incremental directional value is demonstrated.

For every implemented batch, provide the exact files changed, reason, before/after behavior, verification, remaining limitations, and rollback copy. Decisions about actual leverage or deployed capital should follow measured strategy and liquidation validation rather than precede them.

## Reviewed source documents

:codex-file-citation{path="C:\Users\gzdt\AppData\Local\Claude-Data\claude_pzs8sxrjxfjjc\scratch-workspaces\59d401cd-5704-4f9d-b932-996e64640858\fc1f47ab-6f46-46d4-95c0-8b535e5f753f\scratch-2026-11-06-c4ca96\CHATGPT_SUMMARY.md" purpose="source"}

:codex-file-citation{path="C:\Users\gzdt\AppData\Local\Claude-Data\claude_pzs8sxrjxfjjc\scratch-workspaces\59d401cd-5704-4f9d-b932-996e64640858\fc1f47ab-6f46-46d4-95c0-8b535e5f753f\scratch-2026-11-06-c4ca96\APP_BREAKDOWN.pdf" purpose="source"}
