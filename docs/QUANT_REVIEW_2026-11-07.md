# Quant review (Claude), 2026-11-07

Independent read-only review of the app and its saved data (market data through 2026-11-06),
answering `docs/Trading_Research_Quant_Review_Packet_2026-11-07.pdf`. Reproduce with
`research/holdout_checks.py` and `research/review_checks.py`. All returns are SPY, gross of costs,
signed for the rule's side (positive = the rule made money), unless marked net.

## Verdict
Solid, honest research infrastructure. No demonstrated edge yet. Three of the four backtest rules
fail on history they were never fitted to. One rule (buy after a normal drop, hold 5 sessions)
survives, but most of its return is ordinary market drift. The backtests also model entry times and
funding in ways that don't match how Kalshi perps actually trade.

## 1. Untouched holdout: SPY 1993-2009
Direction tests in the app only used 2010-2026, so 1993-2009 is a clean test. Mean per signal vs. all days, same window:

| Rule (window) | 2010-2026 | 1993-2009 holdout | Excl. Feb 15-Jun 30 2020 | 2021-2026 |
|---|---|---|---|---|
| Rally short 1 (close to next close) | +0.118% vs -0.057%, p .001 | -0.005% vs -0.037%, p .59 | +0.041% vs -0.057%, p .05 | +0.020% vs -0.058%, p .37 |
| Rally + VIX>=20 short 1 (close to next open) | +0.277% vs -0.036%, p <.001 | -0.037% vs -0.046%, p .84 | +0.074% vs -0.037%, p .07 | +0.053% vs -0.034%, p .33 |
| Rally short 5 (close to close+5) | +0.019% vs -0.282%, p .007 | +0.005% vs -0.176%, p .13 | -0.119% vs -0.285%, p .11 | -0.011% vs -0.287%, p .14 |
| **Normal drop long 5 (close to close+5)** | +0.508% vs +0.282%, p .004 | **+0.315% vs +0.176%, p .10** | +0.482% vs +0.285%, p .007 | **+0.639% vs +0.287%, p .006** |

Signal counts (2010-26 / 1993-2009): rally 403 / 436, rally + VIX 112 / 206, normal drop 797 / 887.
p-values are two-sided random-draw tests; for 5-session windows the signals overlap, so those p-values are optimistic.

- The rally shorts don't replicate. The VIX>=20 overnight effect is mostly the COVID crash window.
- Rally short 5 shows a *relative* effect (weaker than normal 5-day returns) in both samples, but the absolute
  return is about zero, so a short loses money. As a signal it means "be less long", not "go short".
- Normal drop long 5 holds its direction in the holdout and in 2021-2026. It is consistent with documented
  short-term mean reversion in equity indexes.

## 2. Normal drop long 5 is mostly beta
Using the app's own corrected trade ledger (non-overlapping trades, next-open entry):

| Rule | Trades | Gross/trade | Cost/trade | Net/trade | Random same-window entries | Share of random portfolios >= rule |
|---|---|---|---|---|---|---|
| Rally short 1 | 403 | +0.054% | 0.096% | -0.043% | -0.021% | 0.03 |
| Rally + VIX short 1 | 112 | +0.044% | 0.096% | -0.053% | -0.020% | 0.20 |
| Normal drop long 5 | 451 | +0.339% | 0.183% | +0.156% | +0.246% | 0.17 |
| Rally short 5 | 299 | -0.146% | 0.018% | -0.164% | -0.247% | 0.20 |

- SPY buy-and-hold over the same span (2010-01-13 to 2026-11-06): +766.8%. Normal drop long 5 is in the market
  2,255 of 4,231 sessions (53%) and returns +82% net at 1x.
- The excess over drift is about +0.1% to +0.2% per trade before costs. 12 of 17 calendar years positive,
  largest in high-volatility years (2020-2022, 2025).
- Treat it as an exposure overlay (add exposure after dips on top of a base position) judged against
  buy-and-hold with the same average exposure, not as a standalone strategy.

## 3. Entry timing: perps trade overnight
- Kalshi index perps trade Sunday 6 PM ET to Friday about 5 PM ET (hourly candles with volume: Sun 19-23h,
  Mon-Thu 00-23h, Fri 00-17h ET). 379 of 547 traded US500 hours fall outside 10 AM-4 PM.
- A signal known at the 4:00 PM close can be traded at about 4:05 on the perp. The audit's "corrected" timing
  enters at the next 9:30 open, which drops the overnight window (where about 68% of SPY's 2010-2026 growth occurred).
- Day type uses SPY's close and the prior day's VIX, so it is complete at 4:00 PM. The VIX>=20 filter uses that
  day's VIX close (4:15 PM); using the prior day's VIX gives 151 signals with a similar 2010-26 result.
- Test at perp-executable times (e.g. 4:05 PM entry, 9:30 AM or 4:00 PM exits), not only the ETF's next open.

## 4. Funding is a 4 PM payment, not a continuous charge
- Every saved funding record is stamped 16:00 ET, 24 hours apart.
  US500: 33 records (Oct 6-Nov 7), mean 1.37 bp per record, 20 positive / 12 zero / 1 negative.
  US Tech 100: 25 records, mean 1.17 bp, 10 / 8 / 7. SPY and QQQ perps: 3 records each, about zero.
- The backtest prorates 1.36 bp per calendar day continuously. If Kalshi charges whoever holds at 4:00 PM
  (typical for perps; confirm in Kalshi's docs), a 4:05 PM to 9:30 AM position pays no funding at all.

## 5. Costs and liquidity
- Open-session half-spreads (4 snapshots, Nov 6 00:14-01:17 ET): US500 0.23-0.54 bp, US Tech 100 0.44-0.59 bp,
  SPY perp 0.48-1.23 bp, QQQ perp 0.57-0.73 bp. The backtest assumes 3 bp per side (1 half-spread + 2 slippage).
- Closed-market quotes are meaningless (Saturday: US500 123 bp, US Tech 100 80 bp, QQQ perp no ask). The Leverage
  tab currently shows these closed-market spreads as the current spread. Bug.
- Fees: unknown. Kalshi's fees are notional-based with maker/taker tiers; the 2 bp per side is a placeholder.
- Liquidity (Saturday snapshot): US500 open interest $6.15M, 24h volume $59M; US Tech 100 $4.11M / $313M;
  SPY perp $0.20M / $1.0M; QQQ perp $0.12M / $1.6M; US 2000 inactive.
- Published max leverage: US500 14.65x long / 12.24x short; US Tech 100 11.82x / 10.56x; SPY and QQQ perps 4.96x.

## 6. Operations
- The forward paper record started 2026-11-08 00:04 UTC with 4 decisions (signal date 2026-11-06, all "no signal").
  Refresh is manual, so every missed evening is a gap.
- At about 27 non-overlapping trades a year, a convincing forward record for the 5-session rule takes about a year.
- Jobs data: the BLS web page and calendar return HTTP 403. The static calendar dates are correct (earlier audit).
- Kalshi quote history: only 5 snapshots exist; Kalshi doesn't serve historical spreads.

## 7. Other defects noticed
- `tests/test_validation.py` wrote to a folder outside the app (fixed in commit e28dde6).
- `runtime.json` points at a Claude scratch-workspace Python. Nothing reads it; stale.

## Answers to the packet's main questions (short)
- First test definition: one underlying (US500 perp, SPY as history proxy), normal-drop exposure overlay,
  4:05 PM decision/entry, benchmark = buy-and-hold with the same average exposure.
- Simpler baseline to beat: random entries in the same windows, and buy-and-hold at matched exposure.
- What changes my mind on the positive candidate: excess over matched random entries <= 0 after a pre-registered
  number of forward trades, or failure on intraday (perp-time) data.
- Feature value: volatility/event/GEX effects are size effects; use them for risk and sizing, not direction.
