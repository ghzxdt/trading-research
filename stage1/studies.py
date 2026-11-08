"""The six base-rate studies. Each returns a plain dict the report knows how to draw.

Honesty rules used throughout:
  * A signal seen at day D's close is only compared with what happened on day D+1.
  * "Luck test": we pick the same number of random days thousands of times and count how often
    random picks look at least as different from normal as the signal days did.
  * Direction tests are done in "expected moves" (move / VIX-implied move), so a wild period like
    2020 can't dominate the result just because everything moved more then.
  * A result only counts as a possible edge if it beats luck AND points the same way in at least
    3 of the 4 time periods below.
  * Signal days are compared with days like them where that matters (an event that lands on
    Fridays is compared with other Fridays, not with every day).
  * Size tests ("are moves bigger on these days?") use the same luck test on move size instead of
    average return. They say how big, not which way.
"""

from __future__ import annotations

import hashlib
import zlib

import numpy as np
import pandas as pd

from .dataset import UNCONFIRMED

PERIODS = [
    ("2010-2014", "2010-01-01", "2014-12-31"),
    ("2015-2019", "2015-01-01", "2019-12-31"),
    ("2020-2022", "2020-01-01", "2022-12-31"),
    ("2023-now", "2023-01-01", "2100-01-01"),
]

# The long history (SPY from 1993) is split into its own four periods.
LONG_PERIODS = [
    ("1993-1999", "1993-01-01", "1999-12-31"),
    ("2000-2009", "2000-01-01", "2009-12-31"),
    ("2010-2019", "2010-01-01", "2019-12-31"),
    ("2020-now", "2020-01-01", "2100-01-01"),
]

VERDICTS = {
    "fact": "Fact",
    "edge": "Possible edge",
    "hint": "Weak hint",
    "none": "No edge",
}


# ----------------------------------------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------------------------------------

def pct(x, d=2, sign=True):
    if x is None or not np.isfinite(x):
        return "-"
    if round(x * 100, d) == 0:
        return f"{0:.{d}f}%"  # avoid "-0.00%"
    return f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"


def share(x, d=0):
    if x is None or not np.isfinite(x):
        return "-"
    return f"{x * 100:.{d}f}%"


def mult(x, d=2):
    if x is None or not np.isfinite(x):
        return "-"
    return f"{x:.{d}f}x"


def num(x, d=2):
    if x is None or not np.isfinite(x):
        return "-"
    return f"{x:.{d}f}"


def rms(s: pd.Series) -> float:
    s = s.dropna()
    return float(np.sqrt((s ** 2).mean())) if len(s) else np.nan


def clean(values):
    """Floats for JSON: NaN/inf become None."""
    out = []
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            out.append(None)
            continue
        out.append(round(f, 6) if np.isfinite(f) else None)
    return out


def forward_return(close: pd.Series, sessions: int) -> pd.Series:
    """Endpoint return over exactly this many rows of the exchange-session calendar.

    Missing prices must stay on that calendar: dropping them before shift changes the horizon.
    """
    if sessions < 1:
        raise ValueError("sessions must be positive")
    return close.shift(-sessions) / close - 1


def daily_reset_return(close: pd.Series, sessions: int, leverage: float) -> pd.Series:
    """Compound daily leveraged ETF-proxy returns, requiring every price in the window.

    This is an idealized daily-reset benchmark before financing/fees, using an ETF stand-in.
    It is not the fund's official index or a cost-adjusted tradable strategy.
    """
    daily = close / close.shift(1) - 1
    factors = 1 + leverage * daily
    return factors.rolling(sessions, min_periods=sessions).apply(np.prod, raw=True).shift(-sessions) - 1


def normalized_wealth(close: pd.Series) -> pd.Series:
    """Normalize valid adjusted closes without treating a missing daily return as a flat day."""
    valid = close.dropna()
    return close / valid.iloc[0] if len(valid) else close * np.nan


def adjust_pvalues(results: list[dict]) -> list[dict]:
    """BH false-discovery and Holm familywise adjustments across the supplied test family.

    This adjusts the existing exploratory p-values; it does not validate their null model,
    repair search over unregistered variants, or turn the development sample into a holdout.
    """
    rows = [dict(r) for r in results]
    valid = [(i, float(r.get("raw_p", r.get("p"))) if r.get("raw_p", r.get("p")) is not None else np.nan) for i, r in enumerate(rows)]
    valid = [(i, p) for i, p in valid if np.isfinite(p)]
    ordered = sorted(valid, key=lambda v: v[1])
    n = len(ordered)
    if not n:
        return rows
    ps = np.array([p for _, p in ordered])
    bh = np.minimum.accumulate((ps * n / np.arange(1, n + 1))[::-1])[::-1].clip(0, 1)
    holm = np.maximum.accumulate(ps * np.arange(n, 0, -1)).clip(0, 1)
    for rank, (i, p) in enumerate(ordered):
        rows[i].update(raw_p=p, p_bh=float(bh[rank]), p_holm=float(holm[rank]),
                       reject_bh_05=bool(bh[rank] < 0.05), reject_holm_05=bool(holm[rank] < 0.05),
                       family_tests=n)
    return rows


# ----------------------------------------------------------------------------------------------
# The luck test and the verdict
# ----------------------------------------------------------------------------------------------

class Judge:
    def __init__(self, seed: int = 7, draws: int = 20000):
        self.seed = seed
        self.draws = draws
        self.tests_run = 0
        self.registry: list[dict] = []
        self.last_mc: dict = {}
        if draws < 1:
            raise ValueError("draws must be positive")

    @staticmethod
    def stable_id(mask: pd.Series, pool: pd.Series, stat: str, method: str) -> str:
        """Fallback ID based on dates and membership, never floating-point return bytes."""
        digest = hashlib.sha256()
        digest.update("|".join(map(str, mask.index)).encode("utf-8"))
        digest.update(np.packbits(mask.to_numpy(dtype=bool)).tobytes())
        digest.update(np.packbits(pool.to_numpy(dtype=bool)).tobytes())
        return f"{method}:{stat}:{digest.hexdigest()[:20]}"

    def _rng(self, test_id: str) -> np.random.Generator:
        return np.random.default_rng([self.seed, zlib.crc32(test_id.encode("utf-8"))])

    def _mc_p(self, hits: int, draws: int) -> float:
        p = (hits + 1) / (draws + 1)
        self.last_mc = {"draws": draws, "hits": hits, "mc_resolution": 1 / (draws + 1),
                        "mc_standard_error": float(np.sqrt(p * (1 - p) / (draws + 1)))}
        return float(p)

    def adjusted_registry(self) -> list[dict]:
        return adjust_pvalues(self.registry)

    @staticmethod
    def effect(sample, pool, stat: str = "mean") -> float:
        """How different the sample is from the pool: gap in averages, or log of the size ratio."""
        s = np.asarray(sample, dtype=float)
        pl = np.asarray(pool, dtype=float)
        s, pl = s[np.isfinite(s)], pl[np.isfinite(pl)]
        if not len(s) or not len(pl):
            return np.nan
        if stat == "size":
            a, b = np.sqrt((s ** 2).mean()), np.sqrt((pl ** 2).mean())
            return float(np.log(a / b)) if a > 0 and b > 0 else np.nan
        return float(s.mean() - pl.mean())

    @staticmethod
    def matched_reference(sample: pd.Series, pool: pd.Series, strata: pd.Series,
                          stat: str = "mean") -> float:
        """Control statistic weighted to the signal's weekday/gap composition."""
        sample, pool = sample.dropna(), pool.dropna()
        if not len(sample) or not len(pool):
            return np.nan
        labels = strata.reindex(sample.index)
        control_labels = strata.reindex(pool.index)
        if labels.isna().any():
            return np.nan
        total = 0.0
        for label, count in labels.value_counts().items():
            controls = pool[control_labels == label]
            if not len(controls):
                return np.nan
            total += count * float((controls ** 2).mean() if stat == "size" else controls.mean())
        total /= len(sample)
        return float(np.sqrt(total)) if stat == "size" else total

    @classmethod
    def matched_effect(cls, sample: pd.Series, pool: pd.Series, strata: pd.Series,
                       stat: str = "mean") -> float:
        reference = cls.matched_reference(sample, pool, strata, stat)
        if stat == "size":
            value = rms(sample)
            return float(np.log(value / reference)) if value > 0 and reference > 0 else np.nan
        return float(sample.mean() - reference)

    def luck_matched(self, sample: pd.Series, pool: pd.Series, strata: pd.Series,
                     stat: str, test_id: str) -> float:
        """Resample each signal weekday/gap stratum from matching ordinary-day controls."""
        sample, pool = sample.dropna(), pool.dropna()
        self.last_mc = {}
        if len(sample) < 5 or len(pool) < 5:
            return np.nan
        self.tests_run += 1
        reference = self.matched_reference(sample, pool, strata, stat)
        gap = abs(self.matched_effect(sample, pool, strata, stat))
        if not np.isfinite(gap):
            return np.nan
        labels = strata.reindex(sample.index)
        control_labels = strata.reindex(pool.index)
        groups = [(int(count), pool[control_labels == label].to_numpy())
                  for label, count in labels.value_counts().sort_index().items()]
        rng, hits = self._rng(test_id), 0
        for first in range(0, self.draws, 512):
            count = min(512, self.draws - first)
            sums = np.zeros(count)
            for n_group, controls in groups:
                picks = rng.choice(controls, size=(count, n_group), replace=True)
                sums += (picks ** 2 if stat == "size" else picks).sum(axis=1)
            simulated = sums / len(sample)
            spread = (np.abs(np.log(np.sqrt(simulated) / reference)) if stat == "size"
                      else np.abs(simulated - reference))
            hits += int((spread >= gap - 1e-12).sum())
        p = self._mc_p(hits, self.draws)
        self.last_mc.update(matching="signal-weighted weekday and gap-length strata", matching_strata=len(groups))
        return p

    def luck(self, sample: pd.Series, population: pd.Series, stat: str = "mean",
             test_id: str | None = None) -> float:
        """Exploratory IID resampling null, with a fixed draw count and Monte Carlo correction.

        Exchangeability remains an assumption: this is not a substitute for a cost-aware,
        chronological holdout. Batches cap memory without changing the random stream.
        """
        s = sample.dropna().to_numpy()
        pop = population.dropna().to_numpy()
        self.last_mc = {}
        if len(s) < 5 or len(pop) < 5:
            return np.nan
        self.tests_run += 1
        if test_id is None:
            test_id = f"direct:{stat}:" + "|".join(map(str, sample.dropna().index))
        rng = self._rng(test_id)
        gap = abs(self.effect(s, pop, stat))
        if not np.isfinite(gap):
            return np.nan
        base = np.sqrt((pop ** 2).mean())
        hits = 0
        for first in range(0, self.draws, 512):
            count = min(512, self.draws - first)
            picks = rng.choice(pop, size=(count, len(s)), replace=True)
            if stat == "size":
                spread = np.abs(np.log(np.sqrt((picks ** 2).mean(axis=1)) / base))
            else:
                spread = np.abs(picks.mean(axis=1) - pop.mean())
            hits += int((spread >= gap - 1e-12).sum())
        return self._mc_p(hits, self.draws)

    def luck_shift(self, mask: pd.Series, target: pd.Series, test_id: str | None = None) -> float:
        """Luck test for results measured over several days (e.g. the next 5 days).

        Consecutive 5-day windows overlap, and signal days bunch together, so picking random days
        one at a time would make results look more certain than they are. Instead, slide the
        signal days along the calendar by a random amount (keeping their spacing and bunching)
        and see how often the slid-over days look at least as different.
        """
        vals = target.to_numpy(dtype=float)
        idx = np.flatnonzero(mask.to_numpy() & np.isfinite(vals))
        self.last_mc = {}
        if len(idx) < 5 or len(vals) < 2:
            return np.nan
        self.tests_run += 1
        n = len(vals)
        base = np.nanmean(vals)
        gap = abs(vals[idx].mean() - base)
        rng = self._rng(test_id or self.stable_id(mask, target.notna(), "mean", "shift"))
        # All non-identity rotations are eligible. Excluding nearby shifts would no longer be
        # a sample from the circular randomization group. It still assumes a stationary null.
        offsets = rng.integers(1, n, size=self.draws)
        hit_by_offset = {}
        counts = []
        for k in np.unique(offsets):
            v = vals[(idx + int(k)) % n]
            v = v[np.isfinite(v)]
            counts.append(len(v))
            hit_by_offset[int(k)] = bool(len(v)) and abs(v.mean() - base) >= gap - 1e-12
        p = self._mc_p(sum(hit_by_offset[int(k)] for k in offsets), self.draws)
        self.last_mc.update(shift_min_cases=min(counts), shift_max_cases=max(counts))
        return p

    @classmethod
    def periods(cls, mask: pd.Series, target: pd.Series, pool: pd.Series, stat: str = "mean",
                periods: list | None = None, strata: pd.Series | None = None) -> tuple[int, int, list]:
        """How many of the 4 periods point the same way as the whole sample."""
        overall = (cls.effect(target[mask], target[pool], stat) if strata is None
                   else cls.matched_effect(target[mask], target[pool], strata, stat))
        agree, counted, detail = 0, 0, []
        for name, a, b in (periods or PERIODS):
            tgt = target.loc[a:b]
            m, pl = mask.loc[a:b], pool.loc[a:b]
            s = tgt[m].dropna()
            if len(s) < 5:
                detail.append((name, np.nan, len(s)))
                continue
            eff = (cls.effect(s, tgt[pl], stat) if strata is None
                   else cls.matched_effect(s, tgt[pl], strata, stat))
            if not np.isfinite(eff):
                detail.append((name, np.nan, len(s)))
                continue
            counted += 1
            agree += int(np.sign(eff) == np.sign(overall))
            detail.append((name, eff, len(s)))
        return agree, counted, detail

    def test(self, mask: pd.Series, target: pd.Series, pool: pd.Series | None = None,
             stat: str = "mean", pool_name: str = "days", method: str = "random",
             periods: list | None = None, test_id: str | None = None,
             strata: pd.Series | None = None) -> dict:
        """Full test of 'does target behave differently on signal days than on pool days?'

        pool defaults to every day with data. stat="mean" tests direction (average return);
        stat="size" tests how big the moves were. method="shift" is for multi-day results whose
        windows overlap (see luck_shift).
        """
        mask = mask.fillna(False).astype(bool)
        valid = target.notna()
        mask = mask & valid
        pool = valid if pool is None else (pool.fillna(False).astype(bool) & valid)
        n = int(mask.sum())
        test_id = test_id or self.stable_id(mask, pool, stat, method)
        if any(r["test_id"] == test_id for r in self.registry):
            raise ValueError(f"Duplicate test ID in one family: {test_id}")
        if method == "shift":
            if strata is not None:
                raise ValueError("Use matched individual-day tests or an unstratified circular-shift test")
            if not pool.equals(valid):
                raise ValueError("Circular-shift tests require the full valid target pool")
            p = self.luck_shift(mask, target.where(valid), test_id=test_id)
        else:
            p = (self.luck(target[mask], target[pool], stat, test_id=test_id) if strata is None
                 else self.luck_matched(target[mask], target[pool], strata, stat, test_id))
        agree, counted, detail = self.periods(mask, target, pool, stat, periods, strata)
        if n < 30 or not np.isfinite(p):
            verdict = "none"
            why = f"Only {n} cases - too few to judge."
        elif p < 0.05 and counted >= 3 and agree >= 3:
            verdict = "edge"
            why = ("Unadjusted exploratory evidence of a size effect, with the same sign in most development periods. Check the global multiplicity table and forward validation."
                   if stat == "size" else
                   "Unadjusted exploratory evidence, with the same sign in most development periods. Check the global multiplicity table and cost-aware forward validation.")
        elif p < 0.05:
            verdict = "hint"
            why = f"Beats luck overall, but only points the same way in {agree} of {counted} periods, so it may be one period's story."
        elif p < 0.20:
            verdict = "hint"
            why = "Something may be there, but luck could easily produce this. Not reliable on its own."
        else:
            verdict = "none"
            why = "Random days looked this different often enough that this is most likely luck."
        if n >= 30 and np.isfinite(p) and 0.04 <= p < 0.06:
            why += " It sits right at the 5% line, so this label could easily go the other way."
        if method == "shift" and n >= 30 and np.isfinite(p):
            why += " Circular shifts preserve signal spacing; stationarity is still assumed."
        elif n >= 30 and np.isfinite(p):
            why += " Individual-day resampling assumes exchangeability and can understate regime dependence."
        result = {"test_id": test_id, "n": n, "pool_n": int(pool.sum()), "p": p, "raw_p": p,
                  "agree": agree, "counted": counted, "periods": detail, "verdict": verdict,
                  "why": why, "stat": stat, "pool_name": pool_name, "method": method,
                  "signal_mean": float(target[mask].mean()), "pool_mean": float(target[pool].mean()),
                  "effect": (self.effect(target[mask], target[pool], stat) if strata is None
                             else self.matched_effect(target[mask], target[pool], strata, stat)), **self.last_mc}
        self.registry.append(result)
        return result


def luck_sentence(res: dict) -> str:
    p = res["p"]
    if not np.isfinite(p):
        return ""
    if p < 0.001:
        luck = "almost never (under 0.1% of the time)"
    else:
        luck = f"{share(p, 1 if p < 0.1 else 0)} of the time"
    who = f"Random picks of {res['n']} {res.get('pool_name', 'days')}" if res.get("pool_name") != "shifted" else f"The same {res['n']} days slid to random dates"
    return (f"{who} looked at least this different {luck}. "
            f"Same direction in {res['agree']} of {res['counted']} periods.")


def finding(verdict: str, headline: str, detail: str = "", res: dict | None = None) -> dict:
    parts = [detail] if detail else []
    if res is not None:
        parts.append(luck_sentence(res))
        parts.append(res["why"])
    kind = "size" if res is not None and res.get("stat") == "size" else "direction"
    return {"verdict": verdict, "label": VERDICTS[verdict], "headline": headline,
            "detail": " ".join(p for p in parts if p), "kind": kind}


def period_table(rows_by_test: list[tuple[str, dict]], unit: str = "expected moves", title: str | None = None) -> dict:
    first = next((res for _, res in rows_by_test), None)
    cols = ["Test"] + ([d[0] for d in first["periods"]] if first else [p[0] for p in PERIODS])
    rows = []
    for name, res in rows_by_test:
        row = [name]
        for pname, eff, n in res["periods"]:
            if not np.isfinite(eff):
                row.append("-")
            elif res.get("stat") == "size":
                row.append(f"{np.exp(eff):.2f}x ({n} days)")
            else:
                row.append(f"{eff:+.2f} ({n} days)")
        rows.append(row)
    return {"title": title or f"Difference from a normal next day, by period (in {unit})", "columns": cols, "rows": rows}


# ----------------------------------------------------------------------------------------------
# Study 1: overnight vs. daytime
# ----------------------------------------------------------------------------------------------

def study_overnight(t: pd.DataFrame, judge: Judge) -> dict:
    years = (t.index[-1] - t.index[0]).days / 365.25
    summary_rows, tiles, findings = [], [], []
    shares = {}
    for tk in ["SPY", "QQQ", "IWM"]:
        k = tk.lower()
        d = t[[f"{k}_overnight", f"{k}_daytime", f"{k}_ret"]].dropna()
        lon = np.log1p(d[f"{k}_overnight"]).sum()
        lday = np.log1p(d[f"{k}_daytime"]).sum()
        held = np.log1p(d[f"{k}_ret"]).sum()
        shares[tk] = lon / (lon + lday) if lon + lday else np.nan
        summary_rows.append([
            tk,
            f"${np.exp(held):.2f}",
            f"${np.exp(lon):.2f}",
            f"${np.exp(lday):.2f}",
            share(shares[tk]),
            f"{len(d):,}",
        ])

    spy = t[["spy_overnight", "spy_daytime", "spy_ret"]].dropna()
    growth_all = np.exp(np.log1p(spy["spy_ret"]).cumsum())

    # Days with an unconfirmed open are left out of the split. How much would they change it?
    skipped = int((t["spy_flag"] == UNCONFIRMED).sum())
    previous = t["spy_close"] / (1 + t["spy_ret"])
    raw = pd.DataFrame({"on": t["spy_open"] / previous - 1,
                        "day": t["spy_close"] / t["spy_open"] - 1}).dropna()
    l_on, l_day = np.log1p(raw["on"]).sum(), np.log1p(raw["day"]).sum()
    share_with_skipped = l_on / (l_on + l_day)
    growth_on = np.exp(np.log1p(spy["spy_overnight"]).cumsum())
    growth_day = np.exp(np.log1p(spy["spy_daytime"]).cumsum())
    # Weekly points are plenty for a 16-year line and keep the page light.
    weekly = pd.DatetimeIndex(spy.index.to_series().groupby(spy.index.to_period("W")).last().values)
    chart = {
        "id": "overnight_growth", "type": "line", "log": True, "format": "dollar",
        "title": "What $1 in SPY grew to, depending on when you held it",
        "subtitle": "All three use the same dates with confirmed opens. Full session = overnight x daytime on those dates. Log scale; before costs.",
        "x": [d.strftime("%Y-%m-%d") for d in weekly],
        "series": [
            {"name": "Full sessions (same dates)", "values": clean(growth_all.loc[weekly])},
            {"name": "Overnight only", "values": clean(growth_on.loc[weekly])},
            {"name": "Daytime only", "values": clean(growth_day.loc[weekly])},
        ],
    }

    year_rows = []
    beat = 0
    by_year = spy.groupby(spy.index.year)
    qqq = t[["qqq_overnight", "qqq_daytime"]].dropna()
    for y, g in by_year:
        on = np.expm1(np.log1p(g["spy_overnight"]).sum())
        day = np.expm1(np.log1p(g["spy_daytime"]).sum())
        q = qqq[qqq.index.year == y]
        qon = np.expm1(np.log1p(q["qqq_overnight"]).sum())
        qday = np.expm1(np.log1p(q["qqq_daytime"]).sum())
        beat += int(on > day)
        year_rows.append([str(y), pct(on, 1), pct(day, 1), pct(qon, 1), pct(qday, 1)])

    period_rows = []
    for name, a, b in PERIODS:
        g = spy.loc[a:b]
        if len(g) < 20:
            continue
        on = np.expm1(np.log1p(g["spy_overnight"]).sum())
        day = np.expm1(np.log1p(g["spy_daytime"]).sum())
        period_rows.append([name, pct(on, 1), pct(day, 1)])
    period_winner = sum(1 for r in period_rows if float(r[1].rstrip("%")) > float(r[2].rstrip("%")))

    avg_night = spy["spy_overnight"].mean()
    last_price = t["spy_close"].iloc[-1]
    tiles = [
        {"label": "Overnight share of SPY log growth", "value": share(shares["SPY"]), "note": f"same confirmed-open dates since {t.index[0].year}"},
        {"label": "Years overnight beat daytime (SPY)", "value": f"{beat} of {len(year_rows)}", "note": "calendar years"},
        {"label": "Average overnight SPY move", "value": pct(avg_night, 3), "note": "per night, before costs"},
    ]
    findings.append(finding(
        "fact",
        f"Overnight accounted for {share(shares['SPY'])} of SPY's log growth on confirmed-open dates since {t.index[0].year}; for QQQ it was {share(shares['QQQ'])}, for IWM {share(shares['IWM'])}.",
        f"Overnight beat daytime in {beat} of {len(year_rows)} years and in {period_winner} of {len(period_rows)} periods. "
        "This is an additive log-return contribution, not a share of dollar profits. Above 100% means daytime log returns were negative. "
        f"{skipped} SPY days whose opening price exactly matched the prior close are left out, because that open may have been filled in; "
        f"counting the recorded opens, the overnight log-growth share would be {share(share_with_skipped)}. "
        "These historical close/open intervals are descriptive; a signal finalized after the close cannot assume a fill at that close.",
    ))
    findings.append(finding(
        "fact",
        f"The overnight edge is thin per trade: about {pct(avg_night, 3)} a night, roughly ${abs(avg_night) * last_price:.2f} on one ${last_price:,.0f} SPY share.",
        "Buying every close and selling every open means two trades a day, so spreads and slippage at the open could eat a large part of it. "
        "With TQQQ/SQQQ the overnight gap risk is also 3x.",
    ))
    return {
        "id": "overnight", "number": 1,
        "title": "Where the gains came from: overnight or during the day",
        "question": "If you'd split every trading day into 'overnight' (4:00 pm to 9:30 am) and 'daytime' (9:30 am to 4:00 pm), which part made the money?",
        "tiles": tiles, "charts": [chart], "findings": findings,
        "tables": [
            {"title": "Growth of $1 on the same confirmed-open dates", "columns": ["ETF", "Full sessions", "Overnight only", "Daytime only", "Overnight share of log growth", "Paired dates"], "rows": summary_rows},
            {"title": "By period (SPY)", "columns": ["Period", "Overnight", "Daytime"], "rows": period_rows},
            {"title": "By year", "columns": ["Year", "SPY overnight", "SPY daytime", "QQQ overnight", "QQQ daytime"], "rows": year_rows},
        ],
    }


# ----------------------------------------------------------------------------------------------
# Study 2: does the fear gauge predict the size of tomorrow's move?
# ----------------------------------------------------------------------------------------------

def study_vix(t: pd.DataFrame, judge: Judge) -> dict:
    d = pd.DataFrame({
        "ret": t["spy_ret"],
        "exp": t["expected_move"],
        "vix_prev": t["vix"].shift(1),
        "z": t["spy_move_vs_expected"],
    }).dropna()
    within = (d["ret"].abs() <= d["exp"]).mean()
    overstate = rms(d["exp"]) / rms(d["ret"]) - 1

    edges = [0, 13, 16, 20, 25, 30, 1000]
    labels = ["Under 13", "13-16", "16-20", "20-25", "25-30", "30+"]
    d["bucket"] = pd.cut(d["vix_prev"], edges, labels=labels, right=False)
    rows, exp_vals, act_vals = [], [], []
    for b in labels:
        g = d[d["bucket"] == b]
        e, a = rms(g["exp"]), rms(g["ret"])
        exp_vals.append(e)
        act_vals.append(a)
        rows.append([b, f"{len(g):,}", pct(e, 2, False), pct(a, 2, False), share((g["ret"].abs() <= g["exp"]).mean())])
    chart = {
        "id": "vix_buckets", "type": "bar", "format": "pct", "unsigned": True,
        "title": "Expected vs. actual daily SPY move, by yesterday's VIX",
        "subtitle": "Expected = VIX / 16 rule. Actual = typical size of the next day's move.",
        "categories": [f"VIX {b}" for b in labels],
        "series": [
            {"name": "Expected move (from VIX)", "values": clean(exp_vals)},
            {"name": "Actual typical move", "values": clean(act_vals)},
        ],
    }

    # Which single number, known at yesterday's close, best predicts the size of today's move?
    size = t["spy_ret"].abs()
    predictors = {
        "VIX (yesterday's close)": t["vix"].shift(1),
        "VIX9D (yesterday's close)": t["vix9d"].shift(1),
        "Last 10 days' actual moves": t["spy_realized_10d"].shift(1),
        "Yesterday's move size": t["spy_ret"].abs().shift(1),
    }
    common = pd.concat({"move_size": size, **predictors}, axis=1).dropna()
    pred_rows = []
    for name in predictors:
        rc = common[["move_size", name]].rank().corr().iloc[0, 1]
        pred_rows.append((name, rc))
    pred_rows.sort(key=lambda r: -r[1])

    # Does the SHAPE of the fear curve add anything beyond the VIX level?
    shape_rows, shape_findings = [], []
    z_next = t["spy_move_vs_expected"]
    for col, label in [("short_vs_30d_fear", "Near-term fear above 30-day fear (VIX9D > VIX)"),
                       ("30d_vs_3m_fear", "30-day fear above 3-month fear (VIX > VIX3M, 'inverted')")]:
        flag = (t[col].shift(1) > 1)
        ok = t[col].shift(1).notna() & z_next.notna()
        on, off = flag & ok, ~flag & ok
        raw_ratio = rms(t["spy_ret"][on]) / rms(t["spy_ret"][off])
        adj_ratio = rms(z_next[on]) / rms(z_next[off])
        res = judge.test(on, z_next.where(ok), test_id=f"indexes:curve:{col}:direction")
        shape_rows.append([label, f"{int(on.sum()):,}", mult(raw_ratio), mult(adj_ratio), pct(t["spy_ret"][on].mean(), 2), res["label"] if "label" in res else VERDICTS[res["verdict"]]])
        shape_findings.append((label, on, raw_ratio, adj_ratio, res))

    best, worst = pred_rows[0], pred_rows[-1]
    findings = [
        finding("fact",
                f"The VIX/sqrt(252) heuristic was {share(overstate)} above SPY's realized daily RMS move, and {share(within)} of days stayed within that band.",
                "VIX is a 30-calendar-day options-implied volatility measure; conversion to one trading day assumes a time-scaling rule. "
                "A 68% band would additionally assume normal returns. This comparison alone does not establish option profitability."),
        finding("fact",
                f"Highest in-sample common-date correlation with next-day move size: {best[0].split(' (')[0]}, score {best[1]:.2f}. "
                f"VIX itself scored {dict(pred_rows)[next(n for n in dict(pred_rows) if n.startswith('VIX ('))]:.2f}; weakest was {worst[0].lower()}, {worst[1]:.2f}.",
                f"All predictors use the same {len(common):,} dates ({common.index[0]:%Y-%m-%d} to {common.index[-1]:%Y-%m-%d}). "
                "Score = rank correlation; compare models on future holdout data before calling this predictive skill."),
    ]
    for label, on, raw_ratio, adj_ratio, res in shape_findings:
        findings.append(finding(
            "fact",
            f"{label}: the next day moved {mult(raw_ratio)} as much as usual.",
            f"After adjusting for the VIX level it was {mult(adj_ratio)}. Near 1.0x means the curve's shape adds little beyond the VIX level itself.",
        ))
        findings.append(finding(
            res["verdict"],
            f"Direction after '{label.split(' (')[0].lower()}': next day averaged {pct(t['spy_ret'][on].mean(), 2)} vs {pct(t['spy_ret'].mean(), 2)} on all days.",
            "", res))

    return {
        "id": "vix", "number": 2,
        "title": "Does the fear gauge predict how big tomorrow's move will be?",
        "question": "VIX / 16 is the market's guess for a typical one-day SPY move. How good is that guess, and is anything better?",
        "tiles": [
            {"label": "Days within VIX/sqrt(252) band", "value": share(within), "note": "historical coverage; not a normality guarantee"},
            {"label": "VIX heuristic vs. realized RMS", "value": share(overstate), "note": "relative difference, full sample"},
            {"label": "Highest common-date size correlation", "value": best[0].split(" (")[0], "note": f"{best[1]:.2f}; {len(common):,} common dates"},
        ],
        "charts": [chart],
        "findings": findings,
        "tables": [
            {"title": "By yesterday's VIX level", "columns": ["VIX level", "Days", "Expected move", "Actual typical move", "Days within expected"], "rows": rows},
            {"title": f"Move-size correlations on {len(common):,} common dates", "columns": ["Known after the previous completed session", "Rank correlation"], "rows": [[n, f"{v:.2f}"] for n, v in pred_rows]},
            {"title": "Shape of the fear curve", "columns": ["Condition at yesterday's close", "Days", "Next-day move size vs. usual", "Same, after adjusting for VIX level", "Next-day average return", "Direction verdict"], "rows": shape_rows},
        ],
    }


# ----------------------------------------------------------------------------------------------
# Study 3: what happens the day after big or quiet days?
# ----------------------------------------------------------------------------------------------

DAY_TYPES = ["big drop", "normal drop", "quiet", "normal rise", "big rise"]


def study_day_after(t: pd.DataFrame, judge: Judge) -> dict:
    today = t["spy_day_type"]
    nxt_ret = t["spy_ret"].shift(-1)
    nxt_z = t["spy_move_vs_expected"].shift(-1)
    valid = today.notna() & nxt_ret.notna() & nxt_z.notna()
    all_mean = nxt_ret[valid].mean()
    all_up = (nxt_ret[valid] > 0).mean()
    all_size = rms(nxt_ret[valid])
    all_zsize = rms(nxt_z[valid])

    # How much does the big-rise result lean on a few days in early 2020?
    big_rise = valid & (today == "big rise")
    covid = pd.Series((t.index >= "2020-02-15") & (t.index <= "2020-06-30"), index=t.index)
    n_covid = int((big_rise & covid).sum())
    rise_caveat = (f"Caveat: {n_covid} of these days fell in Feb-Jun 2020. Leave them out and the next day averaged "
                   f"{pct(nxt_ret[big_rise & ~covid].mean(), 2)}.")

    # B: where the next day's move happens, overnight (4:00 pm to 9:30 am) or during the day.
    nxt_on, nxt_day = t["spy_overnight"].shift(-1), t["spy_daytime"].shift(-1)

    rows, mean_vals, size_vals, tests = [], [all_mean], [], []
    findings = []
    for dt in DAY_TYPES:
        m = valid & (today == dt)
        res = judge.test(m, nxt_z.where(valid), test_id=f"indexes:day_after:{dt}:1d")
        tests.append((f"After a {dt} day", res))
        mean_vals.append(nxt_ret[m].mean())
        size_vals.append(rms(nxt_ret[m]) / all_size)
        rows.append([dt.capitalize(), f"{int(m.sum()):,}", pct(nxt_ret[m].mean(), 2), share((nxt_ret[m] > 0).mean()),
                     pct(nxt_on[m].mean(), 2), pct(nxt_day[m].mean(), 2),
                     mult(rms(nxt_ret[m]) / all_size), mult(rms(nxt_z[m]) / all_zsize), VERDICTS[res["verdict"]]])
        if dt in ("big drop", "normal drop", "big rise", "quiet"):
            findings.append(finding(
                res["verdict"],
                f"After a {dt} day ({int(m.sum()):,} times), SPY's next day averaged {pct(nxt_ret[m].mean(), 2)} and was up {share((nxt_ret[m] > 0).mean())} of the time, vs {pct(all_mean, 2)} and {share(all_up)} normally.",
                rise_caveat if dt == "big rise" else "", res))

    # Big rises split by the fear level at that close. This split was chosen after seeing the
    # overall result, so it counts as two more tests and deserves extra suspicion.
    for label, cond in [("VIX 20 or higher", t["vix"] >= 20), ("VIX under 20", t["vix"] < 20)]:
        m = big_rise & cond
        res = judge.test(m, nxt_z.where(valid), test_id=f"indexes:day_after:big_rise:{label}:1d")
        tests.append((f"After a big rise, {label}", res))
        rows.append([f"Big rise, {label}", f"{int(m.sum()):,}", pct(nxt_ret[m].mean(), 2), share((nxt_ret[m] > 0).mean()),
                     pct(nxt_on[m].mean(), 2), pct(nxt_day[m].mean(), 2),
                     mult(rms(nxt_ret[m]) / all_size), mult(rms(nxt_z[m]) / all_zsize), VERDICTS[res["verdict"]]])
        findings.append(finding(
            res["verdict"],
            f"After a big rise with {label} at the close ({int(m.sum()):,} times), the next day averaged {pct(nxt_ret[m].mean(), 2)} and was up {share((nxt_ret[m] > 0).mean())} of the time.",
            "This split was added after seeing the overall big-rise result, so treat it with extra caution.", res))
    rows.append(["All days", f"{int(valid.sum()):,}", pct(all_mean, 2), share(all_up),
                 pct(nxt_on[valid].mean(), 2), pct(nxt_day[valid].mean(), 2), "1.00x", "1.00x", ""])

    hi = big_rise & (t["vix"] >= 20)
    findings.append(finding(
        "fact",
        f"Where the post-rally dip happens: after a big rise, the next overnight averaged {pct(nxt_on[big_rise].mean(), 2)} and the next daytime "
        f"{pct(nxt_day[big_rise].mean(), 2)}; with VIX 20 or higher, {pct(nxt_on[hi].mean(), 2)} overnight and {pct(nxt_day[hi].mean(), 2)} during the day.",
        f"On all days: {pct(nxt_on[valid].mean(), 2)} overnight, {pct(nxt_day[valid].mean(), 2)} during the day. "
        "This splits the tested results above; it isn't a separate test. Useful for perps, which can be held through the night.",
    ))

    # D: the next 5 trading days. Expected move over 5 days = today's VIX / 16 x sqrt(5).
    close = t["spy_close"]
    fwd5 = forward_return(close, 5)
    z5 = fwd5 / (t["vix"] / 100 / np.sqrt(252) * np.sqrt(5))
    valid5 = today.notna() & z5.notna()
    all5 = fwd5[valid5].mean()
    rows5, vals5, tests5 = [], [all5], []
    for dt in DAY_TYPES:
        m = valid5 & (today == dt)
        res = judge.test(m, z5.where(valid5), method="shift", pool_name="shifted", test_id=f"indexes:day_after:{dt}:5d")
        tests5.append((f"Next 5 days after a {dt} day", res))
        vals5.append(fwd5[m].mean())
        rows5.append([dt.capitalize(), f"{int(m.sum()):,}", pct(fwd5[m].mean(), 2), share((fwd5[m] > 0).mean()), VERDICTS[res["verdict"]]])
        if dt in ("big drop", "big rise") or res["verdict"] != "none":
            findings.append(finding(
                res["verdict"],
                f"Over the next 5 trading days after a {dt} day ({int(m.sum()):,} times), SPY averaged {pct(fwd5[m].mean(), 2)} and was higher "
                f"{share((fwd5[m] > 0).mean())} of the time, vs {pct(all5, 2)} and {share((fwd5[valid5] > 0).mean())} for any 5 days.",
                "For holds of about a week.", res))
    rows5.append(["Any day", f"{int(valid5.sum()):,}", pct(all5, 2), share((fwd5[valid5] > 0).mean()), ""])

    quiet_size = rms(nxt_ret[valid & (today == "quiet")]) / all_size
    big_size = rms(nxt_ret[valid & today.isin(["big drop", "big rise"])]) / all_size
    findings.insert(0, finding(
        "fact",
        f"Calm follows calm, and storms follow storms: after a quiet day the next move was {mult(quiet_size)} the usual size; after a big day it was {mult(big_size)}.",
        "This is why sizing by volatility matters: a big day is a warning that tomorrow is likely big too, in either direction.",
    ))

    charts = [
        {
            "id": "day_after_return", "type": "bar", "format": "pct",
            "title": "SPY's average next-day return, by what kind of day today was",
            "subtitle": "Day type is measured against the expected move, so a 1% drop counts as 'big' when VIX is low.",
            "categories": ["All days"] + [d.capitalize() for d in DAY_TYPES],
            "series": [{"name": "Average next-day return", "values": clean(mean_vals)}],
        },
        {
            "id": "day_after_size", "type": "bar", "format": "mult", "reference": {"value": 1.0, "label": "average day"},
            "title": "How big the next day's move was, vs. an average day",
            "subtitle": "1.00x = an average day. Above it = a bigger-than-usual next day, in either direction.",
            "categories": [d.capitalize() for d in DAY_TYPES],
            "series": [{"name": "Next day's move size vs. average", "values": clean(size_vals)}],
        },
        {
            "id": "day_after_5d", "type": "bar", "format": "pct",
            "title": "SPY's average return over the next 5 trading days, by what kind of day today was",
            "subtitle": "For holds of about a week. Close to close, before costs.",
            "categories": ["Any day"] + [d.capitalize() for d in DAY_TYPES],
            "series": [{"name": "Average next-5-day return", "values": clean(vals5)}],
        },
    ]
    return {
        "id": "day_after", "number": 3,
        "title": "After a big up or down day: does it keep going or bounce?",
        "question": "Every day gets sorted by how big SPY's move was compared with what VIX expected. What did the next day look like?",
        "tiles": [
            {"label": "Normal next day", "value": pct(all_mean, 2), "note": f"up {share(all_up)} of days"},
            {"label": "Next-day size after a big day", "value": mult(big_size), "note": "vs. an average day"},
            {"label": "Next-day size after a quiet day", "value": mult(quiet_size), "note": "vs. an average day"},
        ],
        "charts": charts,
        "findings": findings,
        "tables": [
            {"title": "Next day, by today's day type (SPY)", "columns": ["Today was", "Days", "Next-day average", "Next day up", "Next overnight", "Next daytime",
                                                                     "Next-day size vs. avg", "Size, VIX-adjusted", "Direction verdict"], "rows": rows},
            period_table(tests),
            {"title": "Next 5 trading days, by today's day type (SPY)", "columns": ["Today was", "Days", "Next-5-day average", "Higher after 5 days", "Verdict"], "rows": rows5},
            period_table(tests5, title="Next 5 days: difference from any 5 days, by period (in expected moves)"),
        ],
    }


# ----------------------------------------------------------------------------------------------
# Study 4: how the indexes move together, and what happens when one breaks away
# ----------------------------------------------------------------------------------------------

def _breakaway_z(t: pd.DataFrame, k: str, window: int = 60) -> pd.Series:
    """How unusual today's move in `k` was relative to SPY, using only past data for 'usual'."""
    x, s = t[f"{k}_ret"], t["spy_ret"]
    beta = (x.rolling(window).cov(s) / s.rolling(window).var()).shift(1)
    resid = x - beta * s
    sd = resid.rolling(window).std().shift(1)
    return resid / sd


def study_together(t: pd.DataFrame, judge: Judge) -> dict:
    names = {"spy": "SPY", "qqq": "QQQ", "iwm": "IWM", "dia": "DIA", "rsp": "RSP"}
    r = pd.DataFrame({v: t[f"{k}_ret"] for k, v in names.items()})
    r["VIX change"] = t["vix"].pct_change()
    r = r.dropna()
    corr = r.corr()
    corr_rows = [[a] + [f"{corr.loc[a, b]:.2f}" for b in corr.columns] for a in corr.index]

    beta_rows = []
    for k in ["qqq", "iwm", "dia", "rsp"]:
        row = [names[k]]
        for _, a, b in [("All", "2010-01-01", "2100-01-01")] + PERIODS:
            g = r.loc[a:b]
            row.append(f"{g[names[k]].cov(g['SPY']) / g['SPY'].var():.2f}")
        beta_rows.append(row)
    qqq_beta = r["QQQ"].cov(r["SPY"]) / r["SPY"].var()

    calm = t["vix"].shift(1) < 15
    stress = t["vix"].shift(1) > 25
    regime_rows = []
    for pair in [("SPY", "QQQ"), ("SPY", "IWM"), ("SPY", "VIX change")]:
        c_calm = r.loc[r.index.intersection(t.index[calm.values]), list(pair)].corr().iloc[0, 1]
        c_stress = r.loc[r.index.intersection(t.index[stress.values]), list(pair)].corr().iloc[0, 1]
        regime_rows.append([f"{pair[0]} with {pair[1]}", f"{c_calm:.2f}", f"{c_stress:.2f}"])

    roll = pd.DataFrame({
        "SPY with QQQ": r["SPY"].rolling(60).corr(r["QQQ"]),
        "SPY with IWM": r["SPY"].rolling(60).corr(r["IWM"]),
        "SPY with VIX change": r["SPY"].rolling(60).corr(r["VIX change"]),
    }).dropna()
    weekly = pd.DatetimeIndex(roll.index.to_series().groupby(roll.index.to_period("W")).last().values)
    roll_chart = {
        "id": "rolling_corr", "type": "line", "format": "num", "yMin": -1, "yMax": 1,
        "title": "How tightly SPY moved with QQQ, IWM and VIX (60-day window)",
        "subtitle": "+1 = always moved together, 0 = unrelated, -1 = always moved opposite.",
        "x": [d.strftime("%Y-%m-%d") for d in weekly],
        "series": [{"name": c, "values": clean(roll.loc[weekly, c])} for c in roll.columns],
    }

    # Breakaway tests
    z_q = _breakaway_z(t, "qqq")
    z_r = _breakaway_z(t, "rsp")
    nxt_spy_z = t["spy_move_vs_expected"].shift(-1)
    nxt_qqq_z = (t["qqq_ret"] / t["expected_move"]).shift(-1)
    nxt_spy = t["spy_ret"].shift(-1)
    nxt_qqq = t["qqq_ret"].shift(-1)
    base = z_q.notna() & z_r.notna() & nxt_spy.notna()

    signals = [
        ("QQQ much weaker than usual vs. SPY", (z_q < -2) & base, nxt_qqq_z, "QQQ"),
        ("QQQ much stronger than usual vs. SPY", (z_q > 2) & base, nxt_qqq_z, "QQQ"),
        ("Average stock much weaker than SPY (RSP)", (z_r < -2) & base, nxt_spy_z, "SPY"),
        ("Average stock much stronger than SPY (RSP)", (z_r > 2) & base, nxt_spy_z, "SPY"),
    ]
    cats = ["All days"]
    spy_vals = [nxt_spy[base].mean()]
    qqq_vals = [nxt_qqq[base].mean()]
    sig_rows, tests, findings = [], [], []
    for name, m, target, tk in signals:
        res = judge.test(m, target.where(base), test_id=f"indexes:breakaway:{name}")
        tests.append((name, res))
        cats.append(name.replace(" than usual vs. SPY", "").replace(" than SPY (RSP)", " (RSP)"))
        spy_vals.append(nxt_spy[m].mean())
        qqq_vals.append(nxt_qqq[m].mean())
        nxt = nxt_qqq if tk == "QQQ" else nxt_spy
        sig_rows.append([name, f"{int(m.sum()):,}", pct(nxt_spy[m].mean(), 2), pct(nxt_qqq[m].mean(), 2), tk, VERDICTS[res["verdict"]]])
        findings.append(finding(
            res["verdict"],
            f"{name} ({int(m.sum())} times): next day {tk} averaged {pct(nxt[m].mean(), 2)} vs {pct(nxt[base].mean(), 2)} on all days.",
            "'Much weaker/stronger' = at least 2x its usual gap from SPY, judged only from the prior 60 days.", res))
    sig_rows.append(["All days", f"{int(base.sum()):,}", pct(nxt_spy[base].mean(), 2), pct(nxt_qqq[base].mean(), 2), "", ""])

    findings.insert(0, finding(
        "fact",
        f"SPY, QQQ, DIA and RSP are close to one bet (they move together {corr.loc['SPY', 'QQQ']:.2f} to {corr.loc['SPY', 'DIA']:.2f} of the way). QQQ moved about {qqq_beta:.2f}x SPY.",
        f"IWM is the loosest ({corr.loc['SPY', 'IWM']:.2f}). VIX moved against SPY ({corr.loc['SPY', 'VIX change']:.2f}). "
        "In stressed markets the links tighten, so holding two of them is not diversification when you need it most.",
    ))
    bars = {
        "id": "breakaway", "type": "bar", "format": "pct",
        "title": "Next-day returns after one index breaks away from SPY",
        "subtitle": "Average next-day return for SPY and QQQ.",
        "categories": cats,
        "series": [{"name": "Next-day SPY", "values": clean(spy_vals)}, {"name": "Next-day QQQ", "values": clean(qqq_vals)}],
    }
    return {
        "id": "together", "number": 4,
        "title": "How the big indexes move together, and what happens when one breaks away",
        "question": "How tightly do SPY, QQQ, IWM, DIA, RSP and VIX move together? And when QQQ or the average stock goes its own way, does that say anything about tomorrow?",
        "tiles": [
            {"label": "QQQ's typical move vs. SPY", "value": f"{qqq_beta:.2f}x", "note": "SPY +1% means QQQ about this much"},
            {"label": "SPY moving with QQQ", "value": f"{corr.loc['SPY', 'QQQ']:.2f}", "note": "1.00 = in lockstep"},
            {"label": "SPY moving with VIX", "value": f"{corr.loc['SPY', 'VIX change']:.2f}", "note": "negative = opposite"},
        ],
        "charts": [roll_chart, bars],
        "findings": findings,
        "tables": [
            {"title": "How closely daily moves line up (1 = lockstep, -1 = opposite)", "columns": [""] + list(corr.columns), "rows": corr_rows},
            {"title": "Calm vs. stressed markets", "columns": ["Pair", "When VIX was under 15", "When VIX was over 25"], "rows": regime_rows},
            {"title": "Typical move vs. SPY (SPY +1% means this many %)", "columns": ["ETF", "All"] + [p[0] for p in PERIODS], "rows": beta_rows},
            {"title": "Breakaway signals", "columns": ["Signal (at today's close)", "Days", "Next-day SPY", "Next-day QQQ", "Tested on", "Verdict"], "rows": sig_rows},
            period_table(tests),
        ],
    }


# ----------------------------------------------------------------------------------------------
# Study 5: event days
# ----------------------------------------------------------------------------------------------

def event_strata(t: pd.DataFrame) -> pd.Series:
    """Weekday plus exact elapsed calendar days; Good Friday jobs gaps are not weeknights."""
    gaps = t.get("gap_days", pd.Series(t.index, index=t.index).diff().dt.days)
    return pd.Series(t.index.day_of_week, index=t.index).astype(str) + ":" + gaps.astype("Int64").astype(str)


def study_events(t: pd.DataFrame, judge: Judge) -> dict:
    # The size test for each event looks at the part of the day it lands in, decided by the clock
    # (not by the results): 8:30 am reports hit the overnight gap; the 2:00 pm Fed decision and
    # closing-time flows (expiration, month-end) hit the daytime session.
    events = [
        ("Jobs report", "is_jobs_report", "overnight"),
        ("Inflation (CPI)", "is_cpi", "overnight"),
        ("Fed decision", "is_fed_decision", "daytime"),
        ("Options expiration", "is_monthly_opex", "daytime"),
        ("Month-end", "is_month_end", "daytime"),
    ]
    zo, zd, z = t["spy_overnight_vs_expected"], t["spy_daytime_vs_expected"], t["spy_move_vs_expected"]
    valid = zo.notna() & zd.notna() & z.notna()
    ordinary = valid & t["is_ordinary_day"]
    strata = event_strata(t)
    listed_count = t[[col for _, col, _ in events]].astype(bool).sum(axis=1)
    emergency = t.get("is_unscheduled_fed_decision", pd.Series(False, index=t.index)).astype(bool)
    cats, on_vals, day_vals, rows = [], [], [], []
    size_findings, dir_findings, size_tests, dir_tests = [], [], [], []
    for name, col, window in events:
        # A single-event comparison cannot attribute an overlapping CPI/Fed/expiry day to one
        # release. Keep those dates in the dataset but exclude them from this attribution test.
        m = valid & t[col].astype(bool) & (listed_count == 1) & ~emergency
        n = int(m.sum())
        base_o = judge.matched_reference(zo[m], zo[ordinary], strata, "size")
        base_d = judge.matched_reference(zd[m], zd[ordinary], strata, "size")
        ro, rd = rms(zo[m]) / base_o, rms(zd[m]) / base_d
        cats.append(name)
        on_vals.append(ro)
        day_vals.append(rd)

        # Size: are moves in that part of the day bigger than on ordinary days?
        part = zo if window == "overnight" else zd
        size_res = judge.test(m, part.where(valid), pool=ordinary, stat="size", strata=strata,
                              pool_name="weekday/gap-matched ordinary days", test_id=f"indexes:event:{col}:size")
        size_tests.append((f"{name}, {window} size", size_res))
        ratio = ro if window == "overnight" else rd
        what = "overnight gap" if window == "overnight" else "daytime move"
        size_findings.append(finding(
            size_res["verdict"],
            f"{name}, single-event dates ({n}): the {what} was {mult(ratio)} the matched ordinary-day size.",
            "Controls match weekday and elapsed calendar days and are weighted to the event mix. "
            "VIX-normalized full windows include other market news; they do not isolate the exact release reaction.", size_res))

        vs = "weekday/gap-matched ordinary days"
        res = judge.test(m, z.where(valid), pool=ordinary, pool_name=vs, strata=strata,
                         test_id=f"indexes:event:{col}:direction")
        dir_tests.append((f"{name}, direction vs {vs}", res))
        on_avg, day_avg = t["spy_overnight"][m].mean(), t["spy_daytime"][m].mean()
        raw_reference = judge.matched_reference(t["spy_ret"][m], t["spy_ret"][ordinary], strata)
        rows.append([name, f"{n:,}", mult(ro), mult(rd), VERDICTS[size_res["verdict"]], pct(t["spy_ret"][m].mean(), 2),
                     share((t["spy_ret"][m] > 0).mean()), f"{pct(raw_reference, 2)} ({vs})", VERDICTS[res["verdict"]]])
        dir_findings.append(finding(
            res["verdict"],
            f"{name}, single-event dates ({n}): SPY averaged {pct(t['spy_ret'][m].mean(), 2)}, up {share((t['spy_ret'][m] > 0).mean())} of the time, vs {pct(raw_reference, 2)} on {vs}.",
            f"Overnight gap averaged {pct(on_avg, 2)}, daytime {pct(day_avg, 2)}.", res))
    rows.append(["Ordinary days", f"{int(ordinary.sum()):,}", "1.00x", "1.00x", "", pct(t["spy_ret"][ordinary].mean(), 2),
                 share((t["spy_ret"][ordinary] > 0).mean()), "", ""])
    findings = size_findings + dir_findings

    biggest_on = cats[int(np.nanargmax(on_vals))]
    biggest_day = cats[int(np.nanargmax(day_vals))]
    findings.insert(0, finding(
        "fact",
        f"Biggest overnight jolts: {biggest_on} ({mult(max(on_vals))} an ordinary night). Biggest daytime swings: {biggest_day} ({mult(max(day_vals))} an ordinary day).",
        "Jobs/CPI comparisons use the full prior-close-to-open window, including releases on closed equity days. "
        "Scheduled Fed comparisons use the full open-to-close session, not an exact announcement window. "
        "Emergency decisions and overlapping listed events are excluded from these single-event tests. Sizes are VIX-adjusted.",
    ))
    chart = {
        "id": "event_size", "type": "bar", "format": "mult", "reference": {"value": 1.0, "label": "ordinary day"},
        "title": "Single-event dates vs. weekday/gap-matched ordinary dates",
        "subtitle": "Full overnight/daytime windows; VIX-normalized. Controls weighted to each event's weekday and gap-length mix.",
        "categories": cats,
        "series": [{"name": "Overnight gap size", "values": clean(on_vals)}, {"name": "Daytime move size", "values": clean(day_vals)}],
    }
    return {
        "id": "events", "number": 5,
        "title": "How much bigger are moves on jobs, inflation and Fed days?",
        "question": "Scheduled events are known in advance, so they're fair game for an evening plan. How much do they move the market, and when?",
        "tiles": [
            {"label": "Biggest overnight jolt", "value": biggest_on, "note": f"{mult(max(on_vals))} an ordinary night"},
            {"label": "Biggest daytime swing", "value": biggest_day, "note": f"{mult(max(day_vals))} an ordinary day"},
            {"label": "Ordinary days", "value": f"{int(ordinary.sum()):,}", "note": "no scheduled event"},
        ],
        "charts": [chart],
        "findings": findings,
        "tables": [
            {"title": "Event days (SPY)", "columns": ["Event", "Days", "Overnight gap size", "Daytime move size", "Size verdict",
                                                      "Average day", "Up days", "Compared with", "Direction verdict"], "rows": rows},
            period_table(size_tests, title="Size vs. matched ordinary days, by development period"),
            period_table(dir_tests, title="Direction: difference from comparison days, by period (in expected moves)"),
        ],
    }


# ----------------------------------------------------------------------------------------------
# Study 6: do 3x ETFs really deliver 3x?
# ----------------------------------------------------------------------------------------------

def study_leveraged(t: pd.DataFrame, judge: Judge) -> dict:
    pairs = [("TQQQ", "QQQ", 3), ("SQQQ", "QQQ", -3), ("UPRO", "SPY", 3), ("SPXU", "SPY", -3)]
    horizons = [(1, "1 day"), (5, "1 week"), (21, "1 month"), (63, "3 months")]
    rows, med, reset_rows, reset_med = [], {}, [], {}
    for lev, base, L in pairs:
        lc, bc = t[f"{lev.lower()}_close"], t[f"{base.lower()}_close"]
        med[lev] = []
        reset_med[lev] = []
        row = [f"{lev} vs {'+' if L > 0 else ''}{L}x {base}"]
        reset_row = [f"{lev} vs daily-reset {L:+d}x {base} proxy"]
        for h, _ in horizons:
            rl = forward_return(lc, h)
            rb = forward_return(bc, h)
            gap = (rl - L * rb).dropna()
            med[lev].append(gap.median())
            row.append(f"{pct(gap.median(), 2)} (behind {share((gap < 0).mean())})")
            target_gap = (rl - daily_reset_return(bc, h, L)).dropna()
            reset_med[lev].append(target_gap.median())
            reset_row.append(f"{pct(target_gap.median(), 2)} ({len(target_gap):,} windows)")
        rows.append(row)
        reset_rows.append(reset_row)

    chart = {
        "id": "lev_gap", "type": "bar", "format": "pct",
        "title": "Gap vs. naive multiple of QQQ's whole-period return",
        "subtitle": "Median percentage-point gap. This mixes daily-reset compounding with costs and tracking; it is not a promised multi-day target.",
        "categories": [h[1] for h in horizons],
        "series": [{"name": "TQQQ vs +3x QQQ", "values": clean(med["TQQQ"])}, {"name": "SQQQ vs -3x QQQ", "values": clean(med["SQQQ"])}],
    }
    reset_chart = {
        "id": "lev_daily_reset_gap", "type": "bar", "format": "pct",
        "title": "Gap vs. a compounded daily-reset ETF-proxy benchmark",
        "subtitle": "Median actual return minus product of daily +/-3x QQQ returns. Before benchmark financing/fees; QQQ is a proxy for the official index.",
        "categories": [h[1] for h in horizons],
        "series": [{"name": "TQQQ vs daily +3x proxy", "values": clean(reset_med["TQQQ"])},
                   {"name": "SQQQ vs daily -3x proxy", "values": clean(reset_med["SQQQ"])}],
    }

    # Choppy vs. trending months (21 trading days)
    qc, tq, sq = t["qqq_close"], t["tqqq_close"], t["sqqq_close"]
    month = pd.concat({"q": forward_return(qc, 21), "t": forward_return(tq, 21),
                       "s": forward_return(sq, 21)}, axis=1).dropna()
    rq, rt, rs = month["q"], month["t"], month["s"]
    month_rows = []
    for label, m in [("Small net change: QQQ within +/-2%", rq.abs() < 0.02),
                     ("QQQ up more than 8%", rq > 0.08),
                     ("QQQ down more than 8%", rq < -0.08)]:
        month_rows.append([label, f"{int(m.sum()):,}", pct(rq[m].mean(), 1), pct(rt[m].mean(), 1), pct(rs[m].mean(), 1),
                           pct((rt[m] - 3 * rq[m]).mean(), 1), pct((rs[m] + 3 * rq[m]).mean(), 1),
                           share(((rt[m] < 0) & (rs[m] < 0)).mean())])
    chop = rq.abs() < 0.02
    up = rq > 0.08
    both_lost = ((rt[chop] < 0) & (rs[chop] < 0)).mean()
    chop_t = (rt[chop] - 3 * rq[chop]).mean()
    chop_s = (rs[chop] + 3 * rq[chop]).mean()
    up_t = (rt[up] - 3 * rq[up]).mean()
    if abs(chop_s - chop_t) < 0.002:
        drain_note = " about equally"
    else:
        drain_note = ", SQQQ more" if chop_s < chop_t else ", TQQQ more"

    findings = [
        finding("fact",
                f"Over one day they track closely: TQQQ was typically {pct(med['TQQQ'][0], 3)} off exactly 3x. "
                f"Over 3 months the typical gap grows to {pct(med['TQQQ'][3], 1)} for TQQQ and {pct(med['SQQQ'][3], 1)} for SQQQ.",
                "Because they reset every day, a 3x fund's return over several days is NOT 3x the index's return over those days. "
                "Which way it misses depends on the path the index took."),
        finding("fact",
                f"In 21-session windows with QQQ's net change within +/-2%, TQQQ came out {pct(chop_t, 1)} vs. naive 3x and SQQQ {pct(chop_s, 1)} vs. naive -3x. "
                f"Both lost money in {share(both_lost)} of those windows.",
                "These overlapping windows are selected by their ending return, not by a measured choppiness statistic. "
                f"When QQQ rose over 8%, TQQQ beat the naive 3x whole-window return by {pct(up_t, 1)}. "
                "The separate daily-reset benchmark distinguishes compounding from the remaining fee/financing/proxy/tracking gap."),
    ]
    return {
        "id": "leveraged", "number": 6,
        "title": "Do 3x ETFs really deliver 3x?",
        "question": "TQQQ aims for 3x QQQ's move each day, SQQQ for -3x. What happens when you hold them for a day, a week, a month?",
        "tiles": [
            {"label": "TQQQ gap from 3x, 1 day", "value": pct(med["TQQQ"][0], 3), "note": "typical: tracks closely"},
            {"label": "SQQQ gap when QQQ's net change was small", "value": pct(chop_s, 1), "note": "21 sessions; vs. naive -3x QQQ"},
            {"label": "Small-net-change windows where both lost", "value": share(both_lost), "note": "overlapping 21-session windows"},
        ],
        "charts": [chart, reset_chart],
        "findings": findings,
        "tables": [
            {"title": "Gap from naive whole-period multiple (not the fund's promised target)", "columns": ["Fund"] + [h[1] for h in horizons], "rows": rows},
            {"title": "Gap from compounded daily-reset ETF-proxy target", "columns": ["Fund"] + [h[1] for h in horizons], "rows": reset_rows},
            {"title": "21-day holding periods", "columns": ["What QQQ did", "Periods", "QQQ avg", "TQQQ avg", "SQQQ avg", "TQQQ vs exactly 3x", "SQQQ vs exactly -3x", "Both TQQQ and SQQQ lost"], "rows": month_rows},
        ],
    }


# ----------------------------------------------------------------------------------------------
# Study 7: how far can it go against you? (long history, back to 1993)
# ----------------------------------------------------------------------------------------------

VIX_EDGES = [0, 13, 16, 20, 25, 30, 1000]
VIX_LABELS = ["Under 13", "13-16", "16-20", "20-25", "25-30", "30+"]


def _q(s: pd.Series, q: float) -> float:
    s = s.dropna()
    return float(s.quantile(q)) if len(s) else np.nan


def _day(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts:%b} {ts.day}, {ts.year}"


def study_risk(L: pd.DataFrame | None, judge: Judge) -> dict:
    base = {"id": "risk", "number": 7, "title": "How far can it go against you? (history back to 1993)",
            "question": "For stops, sizing and leverage, the bad days matter more than the average day. How big do they get, at each fear level, and how big are the gaps over weekends and holidays?"}
    if L is None or "spy_close" not in L:
        return {**base, "tiles": [], "charts": [], "tables": [],
                "findings": [finding("fact", "Long history not loaded, so this study was skipped.")]}
    prev = L["spy_close"].shift(1)
    d = pd.DataFrame({
        "ret": L["spy_ret"], "exp": L["expected_move"], "vix_prev": L["vix"].shift(1),
        "down": L["spy_low"] / prev - 1, "up": L["spy_high"] / prev - 1,
    }).dropna(subset=["ret", "exp", "vix_prev"])
    d["abs"] = d["ret"].abs()
    d["bucket"] = pd.cut(d["vix_prev"], VIX_EDGES, labels=VIX_LABELS, right=False)
    first = d.index[0]

    # A: how big a bad day gets, by yesterday's VIX
    rows_a, rows_b, p95, p99, adverse_long99, adverse_short99 = [], [], [], [], [], []
    for b in VIX_LABELS:
        g = d[d["bucket"] == b]
        p95.append(_q(g["abs"], 0.95))
        p99.append(_q(g["abs"], 0.99))
        adverse_long99.append(-_q(g["down"], 0.01))
        adverse_short99.append(_q(g["up"], 0.99))
        rows_a.append([b, f"{len(g):,}", pct(g["exp"].median(), 2, False), pct(rms(g["ret"]), 2, False),
                       pct(_q(g["abs"], 0.90), 2, False), pct(p95[-1], 2, False), pct(p99[-1], 2, False), pct(g["abs"].max(), 1, False)])
        rows_b.append([b, pct(-_q(g["down"], 0.05), 2, False), pct(-_q(g["down"], 0.01), 2, False),
                       pct(_q(g["up"], 0.95), 2, False), pct(_q(g["up"], 0.99), 2, False)])

    # Historical threshold touches: include news and crises; do not imply executable fills.
    rows_s, stop2 = [], None
    recent = d.index >= "2010-01-01"
    for k in (1, 1.5, 2, 3, 4):
        lo = (d["down"] <= -k * d["exp"]).where(d["down"].notna())
        hi = (d["up"] >= k * d["exp"]).where(d["up"].notna())
        if k == 2:
            stop2 = lo.mean()
        rows_s.append([f"{k:g} expected moves", share(lo.mean(), 1), share(hi.mean(), 1), share(lo[recent].mean(), 1), share(hi[recent].mean(), 1)])

    # E: by era, so 2000-02 and 2008 are visible next to the recent years.
    rows_e = []
    for name, a, b in LONG_PERIODS:
        g = d.loc[a:b]
        if len(g) < 20:
            continue
        w = g["down"].idxmin()
        rows_e.append([name, f"{len(g):,}", pct(rms(g["ret"]), 2, False), pct(_q(g["abs"], 0.99), 2, False),
                       f"{pct(g['down'].min(), 1)} ({_day(w)})", f"{int((g['down'] <= -0.05).sum())}"])
    worst_all = d["down"].idxmin()
    since10 = d.loc["2010-01-01":]
    worst_10 = since10["down"].idxmin()
    n5_08 = int((d.loc["2008-01-01":"2009-12-31", "down"] <= -0.05).sum())
    n5_10 = int((since10["down"] <= -0.05).sum())

    # QQQ, from 1999
    q_rows = []
    if "qqq_close" in L and L["qqq_close"].notna().sum() > 250:
        qp = L["qqq_close"].shift(1)
        qd = pd.DataFrame({"ret": L["qqq_ret"], "down": L["qqq_low"] / qp - 1, "up": L["qqq_high"] / qp - 1, "exp": L["expected_move"]}).dropna()
        qx = qd.loc["2000-01-01":"2002-12-31", "down"]
        q_rows = [["QQQ since " + str(qd.index[0].year), f"{len(qd):,}", pct(_q(qd["ret"].abs(), 0.95), 2, False), pct(_q(qd["ret"].abs(), 0.99), 2, False),
                   f"{pct(qd['down'].min(), 1)} ({_day(qd['down'].idxmin())})", f"{int((qd['down'] <= -0.05).sum())}",
                   f"{int((qx <= -0.05).sum())}" if len(qx) else "-"]]

    # C: weekend and holiday gaps (Friday close to Monday open, etc.)
    on = L["spy_overnight"]
    zg = on / L["expected_move"]
    gd = L["gap_days"]
    monday = pd.Series(L.index.day_of_week == 0, index=L.index)
    weeknight = (gd == 1)
    weekend = (gd == 3) & monday
    holiday = gd.notna() & ~weeknight & ~weekend
    ok = zg.notna() & on.notna()
    rows_c, cats_c, typ_c, p95_c, findings_c, tests_c = [], [], [], [], [], []
    base_z = rms(zg[weeknight & ok])
    for label, m, test_it in [("Weeknight", weeknight, False), ("Weekend (Fri close to Mon open)", weekend, True), ("Holiday or long weekend", holiday, True)]:
        m = m & ok
        g = on[m]
        res = judge.test(m, zg.where(ok), pool=weeknight & ok, stat="size", pool_name="weeknights", periods=LONG_PERIODS,
                         test_id=f"indexes:gap:{label}:size") if test_it else None
        if res is not None:
            tests_c.append((label, res))
        big = g.abs().idxmax() if len(g) else None
        rows_c.append([label, f"{int(m.sum()):,}", pct(rms(g), 2, False), pct(_q(g.abs(), 0.95), 2, False), pct(_q(g.abs(), 0.99), 2, False),
                       share((g.abs() > 0.01).mean(), 1), share((g.abs() > 0.02).mean(), 1),
                       f"{pct(g[big], 1)} ({_day(big)})" if big is not None else "-", mult(rms(zg[m]) / base_z), VERDICTS[res["verdict"]] if res else ""])
        cats_c.append(label.split(" (")[0])
        typ_c.append(rms(g))
        p95_c.append(_q(g.abs(), 0.95))
        if res is not None:
            findings_c.append(finding(
                res["verdict"],
                f"{label} gaps ({int(m.sum()):,}): typically {pct(rms(g), 2, False)}, {mult(rms(zg[m]) / base_z)} the size of a weeknight gap after adjusting for VIX. "
                f"1 in 20 moved more than {pct(_q(g.abs(), 0.95), 2, False)}; the biggest was {pct(g[big], 1)} on {_day(big)}.",
                "Kalshi's index perps close Friday at 5:00 pm ET. No stop can fill while a market is closed, so the reopening gap is the risk to size for.", res))

    findings = [
        finding("fact",
                f"Absolute move size grows with fear. With yesterday's VIX under 13, the historical 99th percentile was {pct(p99[0], 1, False)} close to close; "
                f"with VIX 20-25, {pct(p99[3], 1, False)}; with VIX 30+, {pct(p99[5], 1, False)}.",
                f"Since {first.year}. Absolute returns include favorable moves as well as adverse ones. "
                "Use the side-specific intraday table for adverse excursions. Historical quantiles are estimates, not future loss bounds."),
        finding("fact",
                f"Historical threshold touches: measured from yesterday's close, SPY traded at least 2 expected moves lower at some point on {share(stop2, 1)} of observed days "
                f"(about 1 day in {round(1 / stop2) if stop2 else '-'}).",
                "This includes news and crisis days. It does not distinguish noise, use an intraday entry price, or model executable stop fills and slippage."),
        finding("fact",
                (f"The worst single day since {first.year} is still {_day(worst_all)} ({pct(d.loc[worst_all, 'down'], 1)} at its low), but the older years add many more bad days: "
                 if worst_all >= pd.Timestamp("2010-01-01") else
                 f"Including the older years changes the worst case: since {first.year}, SPY's worst point in a day was {pct(d.loc[worst_all, 'down'], 1)} ({_day(worst_all)}), "
                 f"vs {pct(since10.loc[worst_10, 'down'], 1)} since 2010. ")
                + f"2008-2009 alone had {n5_08} days where SPY traded 5% or more below the prior close at some point; 2010 to now has had {n5_10}.",
                "Liquidation risk comes in clusters: bad days arrive together in crashes like 2008, which the 2010-on studies never saw."
                + (f" QQQ's worst point in a day was {q_rows[0][4]}; that was an opening flash crash in ETFs, the kind of drop a stop fills into." if q_rows else "")),
    ] + findings_c

    charts = [
        {"id": "risk_tails", "type": "bar", "format": "pct", "unsigned": True,
         "title": "Absolute close-to-close move size, by yesterday's VIX",
         "subtitle": f"Historical 95th/99th percentiles, including both up and down moves, since {first.year}.",
         "categories": [f"VIX {b}" for b in VIX_LABELS],
         "series": [{"name": "1 day in 20 moved more than", "values": clean(p95)}, {"name": "1 day in 100 moved more than", "values": clean(p99)}]},
        {"id": "risk_adverse", "type": "bar", "format": "pct", "unsigned": True,
         "title": "Side-specific intraday adverse excursions from the prior close",
         "subtitle": "Historical 99th percentiles. ETF highs/lows are proxies, not executable perp stop prices.",
         "categories": [f"VIX {b}" for b in VIX_LABELS],
         "series": [{"name": "Long: prior close to low", "values": clean(adverse_long99)},
                    {"name": "Short: prior close to high", "values": clean(adverse_short99)}]},
        {"id": "risk_gaps", "type": "bar", "format": "pct", "unsigned": True,
         "title": "Opening gaps: weeknights vs. weekends and holidays (SPY)",
         "subtitle": f"Prior close to the open, since {first.year}. Opens that exactly match the prior close are left out.",
         "categories": cats_c,
         "series": [{"name": "Typical gap", "values": clean(typ_c)}, {"name": "1-in-20 gap", "values": clean(p95_c)}]},
    ]
    tables = [
        {"title": f"Close-to-close move size by yesterday's VIX (SPY, since {first.year})",
         "columns": ["VIX level", "Days", "Expected move", "Typical move", "1 in 10 above", "1 in 20 above", "1 in 100 above", "Biggest"], "rows": rows_a},
        {"title": "Worst point during the day vs. yesterday's close (SPY)",
         "columns": ["VIX level", "Drop to low, 1 in 20", "Drop to low, 1 in 100", "Rise to high, 1 in 20", "Rise to high, 1 in 100"], "rows": rows_b},
        {"title": "Historical price-threshold touches (not stop fills or noise attribution)",
         "columns": ["Distance from yesterday's close", f"Long threshold (since {first.year})", f"Short threshold (since {first.year})", "Long threshold (since 2010)", "Short threshold (since 2010)"],
         "rows": rows_s},
        {"title": "By era (SPY)", "columns": ["Era", "Days", "Typical move", "1 in 100 above", "Worst point in a day", "Days 5%+ below prior close at some point"], "rows": rows_e},
    ]
    if q_rows:
        tables.append({"title": "QQQ", "columns": ["", "Days", "1 in 20 above", "1 in 100 above", "Worst point in a day", "Days 5%+ below prior close", "Of those in 2000-2002"], "rows": q_rows})
    tables.append({"title": "Opening gaps by type (SPY)", "columns": ["Gap", "Count", "Typical", "1 in 20 above", "1 in 100 above", "Over 1%", "Over 2%", "Biggest", "Size vs. weeknight (VIX-adjusted)", "Verdict"], "rows": rows_c})
    tables.append(period_table(tests_c, title="Gap size vs. weeknights, by period"))
    return {**base,
            "tiles": [
                {"label": "99th-percentile absolute move, VIX 16-20", "value": pct(p99[2], 1, False), "note": "historical close-to-close move"},
                {"label": "Long threshold at 2 expected moves touched", "value": share(stop2, 1), "note": "observed lows; includes news/crises"},
                {"label": "Worst point in a day since " + str(first.year), "value": pct(d.loc[worst_all, "down"], 1), "note": _day(worst_all)},
            ],
            "charts": charts, "findings": findings, "tables": tables,
            "notes": "Risk numbers use SPY back to 1993 and QQQ back to 1999. The other studies start in 2010. Facts unless marked."}


def run_all(t: pd.DataFrame, long: pd.DataFrame | None = None, judge: Judge | None = None) -> tuple[list[dict], int]:
    judge = Judge() if judge is None else judge
    studies = [
        study_overnight(t, judge),
        study_vix(t, judge),
        study_day_after(t, judge),
        study_together(t, judge),
        study_events(t, judge),
        study_leveraged(t, judge),
        study_risk(long, judge),
    ]
    return studies, judge.tests_run
