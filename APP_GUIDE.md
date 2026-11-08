# App guide: what the app does and how to run it

As of **Nov 6, 2026** (market data through the Nov 5 close). Use this to review the whole app before stage 2. Related docs:
- [STAGE1_REVIEW.md](STAGE1_REVIEW.md): every Indexes-tab result in detail.
- [BUILD_LOG.md](BUILD_LOG.md): how each piece was built and fixed.
- [README.md](README.md): setup.

This is research, not financial advice. Nothing in the app is a buy or sell signal yet; that's stage 2.

---

## 1. The app in one picture

One **hub** in your browser with four tabs. Each tab is its own page, so they never mix.

| Tab | What it answers | Where its data comes from | Updates |
|---|---|---|---|
| **Indexes** | How SPY, QQQ and friends have normally behaved (history and base rates) | Yahoo (prices), Cboe (VIX family), FRED (yields), the events file | Automatically, when you run it |
| **Tickers** | Each ETF on its own page: stats, charts, order-flow stand-ins, news | The Indexes tab's daily table, Yahoo headlines, the Fed's press feed | Automatically, when you run it |
| **Leverage (perps)** | What each Kalshi perp offers and what leverage costs and risks | Kalshi's public API, plus the Indexes tab's history | Automatically, when you run it |
| **GEX / DIX** | What dealer positioning says about the next session's size | A SqueezeMetrics CSV **you** download, plus the other two tabs | Only when you click Update |

Data flows **one way**:
- The Leverage tab reads the Indexes tab's price history.
- The Tickers tab reads the Indexes tab (and shows related readings from Leverage and GEX / DIX).
- The GEX / DIX tab reads the Indexes and Leverage tabs.
- Nothing reads the GEX / DIX tab, so an old GEX copy never affects the other tabs.

## 2. How to run it

**One-time setup** (already done in this folder):
```bash
python -m venv .venv
```
```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

**Every time you want fresh numbers** (about a minute):
```bash
.venv/Scripts/python run_all.py
```
This rebuilds all four tabs:
- **Indexes, Leverage and Tickers** download fresh data (Tickers fetches new headlines).
- **GEX / DIX** rebuilds from your saved copy and recalculates its Cold/Warm/Hot level from the new VIX.

**To look at it** (leave this running in its own terminal):
```bash
.venv/Scripts/python hub_server.py
```
Then open **http://localhost:8765**. The helper serves the pages and makes the GEX / DIX tab's Update button work. It only listens on this computer. Press Ctrl+C to stop it. (Inside this app's browser pane, the "hub" preview does the same thing.)

**Other commands:**

| Command | What it does |
|---|---|
| `.venv/Scripts/python run_all.py --offline` | Rebuild everything from the last downloads (no internet) |
| `.venv/Scripts/python run_stage1.py` | Indexes tab only |
| `.venv/Scripts/python run_stage1.py --check` | Self-check: no look-ahead, arithmetic, labels. Prints PASS/FAIL. |
| `.venv/Scripts/python run_leverage.py` | Leverage tab only |
| `.venv/Scripts/python run_tickers.py` | Tickers tab only (add `--offline` to reuse the saved headlines) |
| `.venv/Scripts/python run_gex.py --import` | Copy the newest DIX CSV from Downloads and rebuild the GEX / DIX tab (same as the Update button) |

**A suggested routine (until stage 2 automates it):**
1. **After 4:30 pm ET** (the app skips the current day until then): run `run_all.py`.
2. **Start the helper and open the hub.** Check the **GEX / DIX** badge in the tab bar.
3. **If it says Hot or Warm** and has no ✓:
   1. Open the GEX / DIX tab and click **Get the file**.
   2. On their page, click **CSV**.
   3. Back on the tab, click **Update**.

   SqueezeMetrics usually posts the day's value in the evening.
4. **Read the tabs.** There's no daily call yet.

## 3. Indexes tab (stage 1)

**Data:**
- 9 ETFs from 2010: SPY, QQQ, IWM, DIA, RSP, TQQQ, SQQQ, UPRO, SPXU.
- SPY from 1993 and QQQ from 1999, used for risk numbers only.
- VIX, VIX9D, VIX3M, VVIX, and 2- and 10-year Treasury yields.
- Jobs, CPI and Fed dates through Dec 2027.

Every column is tagged with when you could have known it.

**Seven studies, 30 luck tests, 8 possible edges** (about 1.5 would pass by chance alone):

| # | Study | Headline |
|---|---|---|
| 1 | Overnight vs. daytime | 68% of SPY's growth since 2010 came overnight (QQQ 69%) |
| 2 | Fear gauge vs. move size | VIX overstates moves by about 15%; VIX9D is the best size predictor |
| 3 | The day after (next day, overnight/daytime split, next 5 days) | Big rise → next day −0.12%, and −0.32% when VIX ≥ 20 (mostly overnight). Normal drop → next 5 days +0.51%. Big rise → next 5 days −0.02%. |
| 4 | Moving together | SPY, QQQ, DIA and RSP are basically one bet; QQQ ≈ 1.13× SPY |
| 5 | Event days | Jobs mornings gap 1.19× and Fed afternoons swing 1.29×; no event predicts direction |
| 6 | 3× ETFs | Choppy months drain TQQQ and SQQQ (both lose in 21% of them) |
| 7 | How far it can go against you (since 1993) | A 1-in-100 day is 1.4% at VIX < 13 and 8.9% at VIX 30+. A 2-expected-move stop gets hit 1 day in 40. Weekend gaps 1.14×, holiday gaps 1.50×. |

The tab ends with a **data check** (12 items) and has a **self-check** command. Full numbers are in [STAGE1_REVIEW.md](STAGE1_REVIEW.md).

## 3b. Tickers tab (one page per ETF)

The Indexes tab stays the summary. The Tickers tab gives **each of the 9 ETFs its own page**, grouped as Index ETFs (SPY, QQQ, IWM, DIA, RSP) and 3× ETFs (TQQQ, SQQQ, UPRO, SPXU). The overview (`tickers.html`) has a side-by-side table of all 9, the latest headlines, Fed releases and the upcoming calendar. A row of ticker buttons under the tab bar switches pages.

Each ticker page (`ticker_SPY.html`, `ticker_QQQ.html`, and so on) has:

| Section | What's in it |
|---|---|
| 1. Snapshot | Close, 1 day to 1 year returns, yearly growth since 2010, 52-week range, volatility, worst drop from a peak, dollar volume, and moves per 1% SPY move (all, last year, VIX > 25). Price chart for the last 12 months. |
| 2. Order flow (daily stand-ins) | Volume vs. its 20-day average and how rare that is; where it closed in the day's range; share of volume on up days; the accumulation/distribution line. Related readings: Kalshi perps for that market, and DIX/GEX on the SPY page. |
| 3. Overnight vs. daytime | Share of growth from overnight, the average night and day, years overnight won, and a growth-of-$1 chart |
| 4. After each kind of SPY day | This ticker's next day, next overnight, next daytime and next 5 days after each SPY day type, plus a chart |
| 5. Event days | Its gap and daytime sizes on jobs, CPI, Fed, expiration and month-end days |
| 6. How far it can go against you | Bad-day sizes by VIX, a stop table (1% to 10%), opening gaps, and a drawdown chart |
| 7. 3× tracking (3× funds only) | Gap from the exact multiple over 1 day to 3 months, and choppy months |
| News and calendar | Its Yahoo headlines, Fed press releases, and the next 45 days of scheduled events |

**Limits on this tab:**
- **Per-ticker numbers are descriptive, not luck-tested.** Testing all 9 would multiply the test count about 9×, and most of them move together. The tested versions are on the Indexes tab.
- **Order flow means daily stand-ins.** Trade-by-trade flow and order books aren't free for these ETFs; they come with minute data in stage 2.
- **News is headlines and links only.** Yahoo's list can include promotional pieces.

## 4. Leverage tab (Kalshi perps)

- **A sortable table of all 88 perps** (86 active). Highest leverage first; filter by type and platform.
  - Columns: max leverage, move to liquidation, funding, spread, volume, open interest, hours, and launch date.
  - Indexes, ETFs and stocks show by default.
- **Four studies on the index perps** (US500, US Tech 100, SPY, QQQ):
  1. **Liquidation odds**, using SPY since 1993 and QQQ since 1999. At max leverage, a long is liquidated within a day on 8.2% of days (US500), 13.4% (US Tech 100), 0.6% (SPY perp) and 2.3% (QQQ perp).
  2. **Funding:** US500 longs paid about $1.36 a day per $10k, roughly 61% a year of your cash at max leverage.
  3. **Tracking:** US500 lines up with SPY at 1.00, with an average gap of 0.04% a day.
  4. **Overnight:** the perp's 4 pm to 9 am move matched SPY's opening gap on 95% of 22 nights.
- **Trust:**
  - Prices, funding and hours come straight from Kalshi.
  - Max leverage is Kalshi's estimate.
  - Move to liquidation is calculated by the app (labeled as an estimate).
- Each run also saves a snapshot to `data/kalshi/snapshots.csv`, which builds the spread and open-interest history Kalshi doesn't provide.

## 5. GEX / DIX tab

**What's on it:**
1. **The Cold/Warm/Hot bar** and the Get-the-file and Update buttons (section 6).
2. **Today's reading:**
   - the latest GEX and DIX
   - today's VIX and expected move (from the Indexes tab)
   - how big the next day session has typically been after similar GEX
   - how the Leverage tab's cushions compare with that

   Example from today: US500's 1.9% cushion is about 1.8 typical day-session moves, and the day session alone moved that far 7% of the time on days like this.
3. **The last 6 months:** GEX and the S&P 500, as two charts.
4. **History** (3 luck tests, moved here from the Indexes tab). When GEX closed below zero, the next day session was 1.31× bigger even after adjusting for VIX (possible edge, size). DIX: no edge either way.
5. **A data check:** how old your copy is, and the other tabs' data dates.

**The manual step:** SqueezeMetrics' terms bar systematically retrieving their data, so the app never downloads it. The **Update** button copies the newest `DIX*.csv` from your Downloads folder:
- It checks the file's columns.
- It only replaces your copy if the new file is newer.
- It keeps the old copy as `DIX_previous.csv`.
- It rebuilds the tab and reloads the page.

## 6. What makes it Cold, Warm or Hot

The level is worked out from the data the other tabs already pulled. It runs every time `run_all.py`, `run_stage1.py` or the Update button runs.

**Hot** if **any one** of these is true:

| Hot trigger | Where it comes from | Why it counts (history since 2011) |
|---|---|---|
| VIX closed at **20 or higher** | Indexes tab, latest day | GEX was below zero on 17% of days with VIX 20-25, 39% with VIX 25-30, and 46% with VIX 30+ |
| Your last GEX reading was **below zero** | Your GEX copy | It stayed below zero the next day 70% of the time, and flips often, so it needs checking |
| Your last GEX reading was **near zero** (between $0 and $1B) | Your GEX copy | From there it went below zero the next day 14% of the time (vs 3% from higher levels) |
| SPY's latest day was a **big drop or big rise** (more than 1 expected move) | Indexes tab day type | Positioning tends to shift after big days |
| The **fear curve is inverted** (VIX above VIX3M) | Indexes tab | A sign of stress right now |

**Warm** if none of the Hot triggers apply, but **VIX is between 16 and 20**. GEX was below zero on 3.9% of those days.

**Cold** otherwise: VIX under 16, GEX comfortably positive, no big day, and a normal fear curve. GEX was below zero on 0.1% of days with VIX under 16 (1 day in about 1,800).

**Separately, the app checks whether your copy is current.** If your copy runs through the latest market day the app has, the label adds "your copy is up to date" and the tab badge shows a ✓, for example "Hot ✓". If not, it says "Hot: refresh recommended", "Warm: refresh optional" or "Cold: no need to refresh".

**Right now:** **Hot**, with your copy up to date. VIX closed at 28.2, SPY had a big drop (−4.4%), and the fear curve is inverted.

The level is a reminder about when GEX is worth checking. It isn't a market call.

## 7. Files and folders

| Path | What it is |
|---|---|
| `run_all.py`, `run_stage1.py`, `run_tickers.py`, `run_leverage.py`, `run_gex.py` | The commands |
| `hub_server.py` | The helper: serves the hub and runs the Update button |
| `stage1/` | Indexes tab code: download, daily table, studies, data check, self-check, page template |
| `tickers/` | Tickers tab code: news (`news.py`), per-ticker stats and order-flow stand-ins (`build.py`), pages (`report.py`) |
| `leverage/` | Leverage tab code: Kalshi download, market table, perp studies, page |
| `gex/` | GEX / DIX tab code: data and the Cold/Warm/Hot logic, importer, studies, page |
| `data/events/events.csv` | Jobs, CPI and Fed dates (typed in; through Dec 2027) |
| `data/manual/DIX.csv` | Your GEX/DIX copy (from the Update button) |
| `data/kalshi/snapshots.csv` | Saved Kalshi market snapshots (history Kalshi doesn't serve) |
| `data/raw/` | Cached downloads, including `data/raw/news/` headlines (safe to delete; re-downloaded next run) |
| `output/` | The pages (`report.html`, `tickers.html`, `ticker_SPY.html` and the other 8, `leverage.html`, `gex.html`, `index.html`), the tables (`daily_table.csv`, `long_history.csv`, `leverage_markets.csv`, `gex_daily.csv`), and `gex_status.json` |
| `requirements.txt` | Exact package versions |

## 8. How it's checked

- **Indexes tab self-check (`--check`):**
  - No look-ahead in the daily table or the long-history table (both rebuilt from data cut off at 6 dates).
  - Overnight × daytime = full day.
  - Day-type labels match their thresholds.
  - Every column has a "known at" label.
  - One expiration per month.
- **Data checks on every page** (warnings also show as a banner): stale or failed downloads, odd prices, missing values, and the event calendar running out.
- **Luck tests:**
  - Each has its own fixed random draws, so adding a test never changes another.
  - 5-day results use a test that handles overlapping windows.
  - Borderline results are flagged.
- **The helper** only accepts button requests from the hub's own pages (tested: other requests are refused). The Update flow was tested end to end with a stale copy and a test file, and your real copy was restored exactly afterwards.

## 9. Limits to keep in mind

- **No trading costs anywhere yet:** spreads, slippage, fees and Kalshi funding aren't included. Every lead still has to survive them.
- **Daily data only:** no premarket, opening range or VWAP. That's stage 2, with minute data.
- **No daily up/down call yet.** That's stage 2.
- Kalshi perps are days to weeks old, so their own numbers are first looks.
- GEX and DIX are SqueezeMetrics' numbers, and how they're calculated isn't published.
- The workspace folder belongs to this session; it's deleted if the session is deleted, unless you move it.

## 10. Stage 2 (next)

1. **A daily up/down call** (up, down, or no edge) for 1-day and 1-week holds, from the leads in section 3. It will say what would confirm or cancel the call.
2. **Turning the call into a Kalshi position:**
   - which perp to use
   - a stop placed with section 3's stop table, well inside liquidation
   - a size that survives a 1-in-100 day
   - extra care before weekends, holidays, jobs and Fed days, and when GEX is below zero
3. **Cost-tested versions of the leads**, plus minute data for entry timing.
4. **A log of every call**, so they can be scored.
5. **A "Refresh everything" button** in the helper.
