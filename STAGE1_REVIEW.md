# Stage 1 review: where everything stands

Snapshot as of the **Nov 5, 2026 close**, after tweaks A-G. This covers the Indexes tab; the Leverage tab is summarized at the end. For how it was built and every fix along the way, see [BUILD_LOG.md](BUILD_LOG.md).

**In one line:** stage 1 looks back at SPY, QQQ and friends (2010 on, and back to 1993 for risk numbers) and records what "normal" looks like. It runs **30 luck tests**. Passing: **4 direction leads** and **4 size effects**. About 1.5 would pass by chance alone. (GEX/DIX has since moved to its own tab, with 3 more tests; see [APP_GUIDE.md](APP_GUIDE.md).) Nothing is tested with trading costs yet, and none of it is a daily call. The daily call is stage 2's job.

---

## 1. What goes in

| Data | Source | Coverage |
|---|---|---|
| SPY, QQQ, IWM, DIA, RSP, TQQQ, SQQQ, UPRO, SPXU (daily open, high, low, close, volume) | Yahoo Finance, adjusted for splits and dividends | Jan 2010 to Nov 5, 2026 |
| **Long history:** SPY and QQQ | Yahoo Finance | SPY from Feb 1993, QQQ from Mar 1999. Used only for risk numbers. |
| VIX, VIX9D, VIX3M, VVIX | Cboe public files | VIX from 1990; VIX9D from 2011 |
| **GEX and DIX** | SqueezeMetrics' free CSV, **downloaded by hand** (their terms bar automated retrieval) | May 2011 to Nov 5, 2026 |
| 2-year and 10-year Treasury yields | FRED, shifted a day | 2010 on (not used by any study yet) |
| Jobs, CPI and Fed dates | BLS and Fed sites, typed in | 2010 through Dec 2027 |

**Main daily table:** 4,236 trading days by 113 columns. Every column is tagged with when you could have known it. GEX and DIX count as known only before the **next** open, because they're published after the close.

**Long-history table** (`output/long_history.csv`): 8,500 trading days of SPY and QQQ with the VIX, the expected move, and calendar days since the last session (for weekend and holiday gaps).

## 2. Rules every test follows

- **Day types:** SPY's move ÷ expected move (yesterday's VIX ÷ 16). Big drop (below −1), normal drop (−1 to −0.3), quiet (±0.3), normal rise (0.3 to 1), big rise (above +1).
- **Luck test:** pick the same number of random days 4,000 times. Borderline cases (2-10%) get 40,000 picks. Each test has its own fixed random draws.
- **Multi-day results (5 days):** back-to-back windows overlap, so the luck test slides the signal days along the calendar by a random amount instead. This keeps their spacing and clustering.
- **Like with like:** events that mostly fall on one weekday are compared with that weekday.
- **Size tests** ask whether moves are bigger, not which way. They're for stops and sizing.
- **Verdicts:**
  - **Possible edge:** luck under 5%, the same direction in at least 3 of 4 periods, and 30+ cases.
  - **Weak hint:** luck under 20%.
  - **No edge:** everything else.
  - **Fact:** a description, not a test.
  - Anything with luck from 4% to 6% notes that its label could go either way.
- **Periods:** 2010-14, 2015-19, 2020-22, 2023-now. The long-history tests use 1993-99, 2000-09, 2010-19, 2020-now.

## 3. Scoreboard

| Possible edge | Weak hint | No edge | Fact |
|---|---|---|---|
| 8 | 7 | 12 | 15 |

(Indexes tab only. The GEX / DIX tab adds 1 possible edge, 2 no edge and 1 fact.)

**Direction leads (which way):**

| # | Lead | Result | Normal | Luck | Periods |
|---|---|---|---|---|---|
| 1 | After a **big rise**, next day | −0.12%, up 50% | +0.06%, up 55% | 0.9% | 4 of 4 |
| 2 | After a **big rise with VIX ≥ 20**, next day | −0.32%, up 46% (112 cases) | +0.06% | 3.5% | 3 of 4 |
| 3 | **New:** after a **normal drop**, next 5 days | **+0.51%**, higher 64% | +0.28%, 61% | 1.2% | 4 of 4 |
| 4 | **New:** after a **big rise**, next 5 days | **−0.02%**, higher 59% | +0.28%, 61% | 3.0% | 4 of 4 |

Caveats:
- Lead 1 leans on 14 days in early 2020; without them it's −0.04%.
- Lead 2 was a split chosen after seeing lead 1.
- Leads 1 and 4 overlap: both are "after a big rally, the market stalls," over 1 day and 5 days.

**Size effects (how big, for stops and sizing):**

| # | Effect | Size | Luck | Periods |
|---|---|---|---|---|
| 5 | Jobs-report mornings: overnight gap | 1.19× ordinary | 3.1% | 3 of 4 |
| 6 | Fed afternoons: daytime move | 1.29× ordinary | 0.4% | 4 of 4 |
| 7 | **New:** weekend gaps (Fri close → Mon open) | 1.14× weeknights, VIX-adjusted | under 0.1% | 3 of 4 |
| 8 | **New:** holiday / long-weekend gaps | 1.50× weeknights | under 0.1% | 4 of 4 |
| 9 | **Now on the GEX / DIX tab:** days after GEX closed below zero | 1.31× normal, after adjusting for VIX | under 0.1% | 4 of 4 |

## 4. The eight studies, with current results

### Study 1. Overnight vs. daytime
| | SPY | QQQ | IWM |
|---|---|---|---|
| $1 held all the time | $8.69 | $16.09 | $5.30 |
| Overnight only | $4.12 | $7.19 | $7.94 |
| Daytime only | $1.97 | $2.46 | $0.65 |
| Share of growth from overnight | **68%** | **69%** | 127% |

- Overnight beat daytime in 10 of 17 years and in all 4 periods.
- SPY's average night: +0.036% before costs.
- 36 days with an unconfirmed open are left out; counting them gives 66%.

### Study 2. Does the fear gauge predict move size?
- VIX overstated real moves by about **15%**, and **81%** of days stayed within one expected move. Above VIX 30 it **understated** them.
- Best predictor of tomorrow's move size: **VIX9D** (0.43). VIX scored 0.40, the last 10 days 0.34, and yesterday's move 0.14.
- When the fear curve is inverted (VIX > VIX3M), the next day moved 2.70× normal (1.47× adjusted for VIX).
- Neither fear-curve signal predicts direction (no edge).

### Study 3. After a big up or down day (now with B, D and F)

**Next day**, with the **overnight and daytime split (B)**:

| Today was | Days | Next day | Up | Next overnight | Next daytime | Verdict |
|---|---|---|---|---|---|---|
| Big drop | 380 | +0.08% | 55% | +0.05% | +0.02% | No edge |
| Normal drop | 797 | +0.13% | 57% | +0.05% | +0.08% | **Weak hint (F: now its own finding)** |
| Quiet | 1,503 | +0.05% | 56% | +0.05% | −0.01% | No edge |
| Normal rise | 1,152 | +0.07% | 55% | +0.03% | +0.04% | No edge |
| Big rise | 403 | **−0.12%** | 50% | −0.06% | −0.06% | **Possible edge** |
| Big rise, VIX ≥ 20 | 112 | **−0.32%** | 46% | **−0.28%** | −0.05% | **Possible edge** |
| Big rise, VIX < 20 | 291 | −0.04% | 51% | +0.02% | −0.06% | Weak hint |
| All days | 4,235 | +0.06% | 55% | +0.04% | +0.02% | |

- **Key for perps:** after a big rally with VIX at 20 or higher, almost the whole next-day dip happens **overnight** (−0.28%), when only perps and futures trade.

**Next 5 trading days (D):**

| Today was | Days | Next 5 days | Higher | Verdict |
|---|---|---|---|---|
| Big drop | 379 | +0.33% | 62% | No edge (only 1 of 4 periods) |
| Normal drop | 796 | **+0.51%** | 64% | **Possible edge** (1.2%, 4 of 4) |
| Quiet | 1,502 | +0.23% | 60% | No edge |
| Normal rise | 1,152 | +0.28% | 60% | No edge |
| Big rise | 402 | **−0.02%** | 59% | **Possible edge** (3.0%, 4 of 4) |
| Any day | 4,231 | +0.28% | 61% | |

- Calm follows calm (0.89× normal size), and storms follow storms (1.26×).

### Study 4. Moving together
- SPY, QQQ, DIA and RSP move together 0.93 to 0.95 of the way. IWM is at 0.88, and VIX at −0.75.
- QQQ moves ≈ **1.13× SPY** (1.28× since 2023), and the links tighten in stress.
- Breakaways:
  - QQQ much weaker than SPY: next-day QQQ 0.00% vs +0.08%. Weak hint, at 5.2% right on the line.
  - QQQ much stronger than SPY: weak hint (18%).
  - RSP (the average stock) breakaways: no edge.

### Study 5. Event days
| Event | Gap size (overnight) | Day size | Size verdict | Direction verdict |
|---|---|---|---|---|
| Jobs report | **1.19×** | 1.11× | Possible edge | No edge |
| CPI | 1.13× | 0.95× | Weak hint | No edge |
| Fed decision | 0.98× | **1.29×** | Possible edge | No edge |
| Options expiration | 0.92× | 0.93× | No edge | Weak hint (−0.06% vs +0.07% other Fridays) |
| Month-end | 0.92× | 1.02× | No edge | Weak hint |

- No event predicts direction; they only make moves bigger.
- The Fed effect is growing: 1.52× since 2023.

### Study 6. 3× ETFs
- Close to 3× over one day.
- Typical 3-month gap from exact 3×: TQQQ −1.83%, UPRO −1.51%.
- In choppy months, TQQQ and SQQQ each come out about 1.2% short of exact 3×, and **both lose in 21%** of them.
- Strong uptrends help TQQQ (+1.3% over 3×).

### Study 7. How far can it go against you? (A, C, E: new, history back to 1993)

**How big a bad day gets (A)**, SPY close to close, by yesterday's VIX:

| VIX | Days | Expected move | Typical | 1 in 20 above | 1 in 100 above | Biggest |
|---|---|---|---|---|---|---|
| Under 13 | 1,532 | 0.75% | 0.52% | 1.07% | 1.42% | 3.9% |
| 13-16 | 1,843 | 0.91% | 0.67% | 1.39% | 2.03% | 3.2% |
| 16-20 | 1,935 | 1.12% | 0.89% | 1.77% | 2.50% | 4.4% |
| 20-25 | 1,677 | 1.40% | 1.16% | 2.24% | 3.13% | 7.2% |
| 25-30 | 804 | 1.70% | 1.52% | 2.99% | 4.21% | 5.8% |
| 30+ | 705 | 2.19% | 2.58% | 5.09% | **8.85%** | 14.5% |

**How often noise alone reaches a stop**, measured from yesterday's close:

| Stop distance | Long stop hit | Short stop hit |
|---|---|---|
| 1 expected move | 17.8% of days | 16.4% |
| 1.5 expected moves | 6.9% | 4.3% |
| **2 expected moves** | **2.5% (about 1 day in 40)** | 0.9% |
| 3 expected moves | 0.4% | 0.1% |

**By era (E):**

| Era | Typical move | 1 in 100 above | Worst point in a day | Days 5%+ below prior close |
|---|---|---|---|---|
| 1993-1999 | 0.98% | 3.00% | −8.1% (Aug 31, 1998) | 4 |
| 2000-2009 | 1.41% | 4.81% | −10.2% (Oct 15, 2008) | **23** |
| 2010-2019 | 0.93% | 3.16% | −10.1% (May 6, 2010) | 4 |
| 2020-now | 1.26% | 4.47% | −11.9% (Mar 16, 2020) | 9 |

- **QQQ since 1999:** 113 days traded 5%+ below the prior close, **73 of them in 2000-2002**. Its worst point was **−17.2% on Aug 24, 2015**, an opening flash crash in ETFs, exactly the kind of drop a stop fills into.

**Opening gaps (C):**

| Gap | Count | Typical | 1 in 20 above | Over 2% | Biggest | vs. weeknight | Verdict |
|---|---|---|---|---|---|---|---|
| Weeknight | 6,538 | 0.64% | 1.23% | 1.6% | −8.3% (Oct 24, 2008) | 1.00× | |
| Weekend | 1,505 | 0.76% | 1.36% | 2.3% | −10.4% (Mar 16, 2020) | **1.14×** | **Possible edge** |
| Holiday / long weekend | 297 | 0.92% | 1.65% | 3.0% | −8.2% (Sep 17, 2001) | **1.50×** | **Possible edge** |

### GEX and DIX (G: now on its own tab)
| | Days | Avg VIX | Day-session move size | VIX-adjusted | Verdict |
|---|---|---|---|---|---|
| GEX below 0 (previous evening) | 346 | 28.6 | 1.61% | **1.31×** | **Possible edge (size)** |
| GEX 0 or above | 3,521 | 17.2 | 0.69% | 1.00× | |

| DIX vs. its past year | Days | Next 5 sessions | Higher | Verdict |
|---|---|---|---|---|
| Top 20% | 814 | +0.36% | 61% | No edge |
| Middle 60% | 2,082 | +0.22% | 60% | |
| Bottom 20% | 803 | +0.24% | 62% | No edge |

- **GEX:** below zero means bigger moves, even beyond what VIX already says. That's useful for stops and size. It says nothing about direction.
- **DIX:** no edge either way.
- SqueezeMetrics doesn't publish how it calculates either number.

## 5. Data check (runs on every build)

| Status | Check | Result |
|---|---|---|
| OK | Downloads | All sources came down fresh |
| OK | Freshness | Prices and VIX through Nov 5; yields through Nov 4 |
| OK | Dates | No duplicates, in order |
| OK | Prices outside the day's range | None |
| Note | Open exactly equals prior close | SPY 36, RSP 78, SPXU 78 and others (since 2010); left out of the overnight/daytime split |
| Note | **Long history** | SPY from Feb 1, 1993, QQQ from Mar 10, 1999; 122 SPY opens before 2010 match the prior close (left out of the gap numbers) |
| OK | **GEX/DIX file** | Runs through Nov 5, 2026. Warns if more than 2 trading days old. |
| Note | Bad prices removed | SPXU Oct 18, 2010 |
| Note | 3× funds over 3 points off | 7 fund-days, real extreme days |
| Note | Zero volume | SQQQ's first 2 months |
| Note | Missing fear-gauge values | VIX9D before 2011; VVIX 2 days |
| OK | Yields, event calendar | Complete; next jobs report Nov 6, CPI Nov 10, Fed Dec 9 |

**Self-check: all pass.**
- No look-ahead in the main table, now including GEX/DIX, or in the long-history table. Both were rebuilt from data cut off at 6 dates.
- Arithmetic, day-type labels, "known at" labels, and one expiration per month all check out.

## 6. What stage 1 still does not do

- **No daily call.** That's stage 2.
- **No trading costs.** Spreads, slippage and Kalshi funding aren't included. A +0.51% 5-day lead still has to survive costs.
- **Daily prices only.** No premarket, no first 30 minutes.
- Direction tests start in 2010. Only the risk numbers go back to 1993.
- The GEX/DIX file has to be refreshed by hand for current values.

## 7. How stage 2 will use each piece

| Stage 1 piece | Use in stage 2 |
|---|---|
| Day type, big-rise leads (1 day and 5 days), normal-drop 5-day lead | Today's lean: up, down, or no edge, for 1-day and 1-week holds |
| Overnight vs. daytime split of the leads | Whether to hold a perp position through the night |
| Expected move, VIX9D, bad-day sizes and stop table (study 7) | Where to put the stop, and how big a position survives a 1-in-100 day |
| Weekend/holiday gaps, jobs and Fed size effects, GEX below 0 | Size down, or flatten, before closures and big-event mornings |
| Long-history liquidation odds (Leverage tab) | Choosing leverage on Kalshi |
| SPY/QQQ together, QQQ ≈ 1.13× SPY | Treat them as one bet; size QQQ smaller |
| 3× decay | When TQQQ/SQQQ make sense vs. a Kalshi perp |
| Data check | Don't make a call on stale data |

## 8. Tweaks A-G: status

| # | Tweak | Status | What it found |
|---|---|---|---|
| A | How big a bad day gets, by VIX | **Done** (study 7) | 1-in-100 day: 1.4% (VIX < 13) to 8.9% (VIX 30+). A 2-expected-move stop gets hit 1 day in 40. |
| B | Next day split into overnight and daytime | **Done** (study 3) | The VIX ≥ 20 post-rally dip is almost all overnight (−0.28%) |
| C | Weekend and holiday gaps | **Done** (study 7) | Weekends 1.14×, holidays 1.50× a weeknight gap. Both possible edges (size). |
| D | 5-day horizon | **Done** (study 3) | Two new possible edges: normal drop +0.51%, big rise −0.02% (vs +0.28%) |
| E | History back to 1993 for risk numbers | **Done** (study 7 + Leverage tab) | 2000-09 had 23 days 5%+ down vs 13 since 2010. Liquidation odds went up (see appendix). |
| F | Normal-drop hint as a finding | **Done** | Weak hint for the next day; a possible edge over 5 days |
| G | GEX and DIX | **Done** (study 8) | GEX below 0: 1.31× bigger moves beyond VIX (possible edge, size). DIX: no edge. |

---

## Appendix: the Leverage tab (separate from stage 1)

- A sortable table of all 88 Kalshi perps (86 active), plus four index-perp studies: liquidation odds, funding, tracking, and overnight vs. the ETF's open.
- The liquidation odds now use the long history (SPY since 1993, QQQ since 1999), so 2000-02 and 2008 count:

| Perp | Max leverage | Move to liquidation (est.) | Long liquidated within 1 day | Within 1 week | Before (2010-on only) |
|---|---|---|---|---|---|
| US500 | 12.2× | 1.9% | **8.2%** of days (since 1993) | 31.1% | 6.7% |
| US Tech 100 | 10.6× | 2.2% | **13.4%** (since 1999) | 38.8% | 8.1% |
| SPY | 5.0× | 4.6% | 0.6% | 6.7% | 0.4% |
| QQQ | 5.0× | 4.6% | **2.3%** | 14.7% | 0.8% |
