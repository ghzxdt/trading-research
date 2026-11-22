"""Evidence cards from the backtester's exports/evidence.json (added 2026-11-18, backtester review).

One card per rule, exit and entry: its sample size and trades a year, the average excess over same-length trades
with a 90% interval, the worst point inside a trade at 1x, the same trades in the leveraged ETF (TQQQ or UPRO),
1993-2009, the forward record since the development window ended, limitations and age. The page shows the
next-open cards (the entry still available) beside each rule that fired or is near its trigger.

Wording, as the backtester states it: historical tendencies with their sample sizes and intervals, never a
probability of success. Read-only. This app never depends on the backtester: a missing or damaged file is
"unavailable" and the page carries on without cards.
"""
from __future__ import annotations

import hashlib
import json
import os
from numbers import Real
from pathlib import Path

from . import eligibility, signals

NEAR = 0.03  # without an ATR: a rule within 3% of its trigger close counts as near (it gets its cards too)
NEAR_ATR = 1.5  # with ATR(14): within 1.5 daily ranges of the trigger close (review v2 step 5.15)


def path() -> Path:
    return Path(os.environ.get("THESIS_BACKTESTER_EVIDENCE") or signals.export_path().with_name("evidence.json"))


def validate(payload: dict) -> None:
    """Raise ValueError unless every field the page reads is present and well-formed."""
    if not isinstance(payload, dict) or payload.get("kind") != "evidence" or payload.get("schema") != 1:
        raise ValueError("unexpected evidence format")
    cards = payload.get("cards")
    if not isinstance(cards, list) or not cards:
        raise ValueError("it has no cards")
    for card in cards:
        if not isinstance(card, dict) or any(not isinstance(card.get(k), str) for k in ("symbol", "signal", "exit", "entry", "verdict")):
            raise ValueError("a card is missing its symbol, signal, exit, entry or verdict")
        if not isinstance(card.get("trades"), int) or isinstance(card.get("trades"), bool) or card["trades"] < 0:
            raise ValueError("a card has no trade count")
        interval = card.get("excess_ci90")
        if interval is not None and (not isinstance(interval, list) or len(interval) != 2
                                     or not all(isinstance(x, Real) for x in interval)):
            raise ValueError("a card's 90% interval is malformed")
        for key in ("occurrence", "inside_trades", "leveraged", "forward", "holdout", "net_distribution"):
            if card.get(key) is not None and not isinstance(card[key], dict):
                raise ValueError(f"a card's {key} is malformed")
        if card.get("limitations") is not None and not isinstance(card["limitations"], list):
            raise ValueError("a card's limitations are malformed")


def load(export_info: dict | None = None, file: Path | None = None) -> dict:
    """{"status": "ok", "cards": [...], ...}, or "unavailable" / "invalid" with the reason."""
    file = Path(file or path())
    if not file.exists():
        return {"status": "unavailable", "path": str(file), "cards": [],
                "reason": "The backtester's evidence.json was not found (its trade simulation writes it)."}
    raw = file.read_bytes()
    try:
        payload = json.loads(raw)
        validate(payload)
    except (ValueError, TypeError, AttributeError) as exc:
        return {"status": "invalid", "path": str(file), "cards": [], "reason": f"evidence.json unreadable: {exc}"}
    made = ((payload.get("generated_from") or {}).get("trade_simulation") or {}).get("generated_at")
    export_made = (export_info or {}).get("generated_at") if (export_info or {}).get("status") == "ok" else None
    return {"status": "ok", "path": str(file), "sha256": hashlib.sha256(raw).hexdigest(), "cards": payload["cards"],
            "generated_at": made, "data_through": payload.get("data_through"), "wording": payload.get("wording"),
            # The cards should come from the same trade-simulation run as the export the stance uses.
            "same_run": None if not (made and export_made) else made == export_made}


def _base(name: str) -> str:
    return name.split("@")[0]  # the backtester versions its ids: "bollinger_lower_close@v1"


def summarize(card: dict) -> dict:
    inside, lev = card.get("inside_trades") or {}, card.get("leveraged") or {}
    exit_name = _base(card["exit"])
    return {"exit": exit_name, "exit_label": signals.EXIT_LABELS.get(exit_name, exit_name), "entry": card["entry"],
            "verdict": card["verdict"], "trades": card["trades"],
            "trades_per_year": (card.get("occurrence") or {}).get("trades_per_year"),
            "development": card.get("development"), "win_rate": card.get("win_rate"), "mean_net": card.get("mean_net"),
            "excess": card.get("excess"), "excess_ci90": card.get("excess_ci90"),
            "worst_inside": inside.get("mae_worst"), "inside_p10": inside.get("mae_p10"),
            "median_net": (card.get("net_distribution") or {}).get("median_net"),
            "net_p10": (card.get("net_distribution") or {}).get("net_p10"),
            "trades_mae_below_5pct": inside.get("trades_mae_below_5pct"),
            "worst_trade": (card.get("net_distribution") or {}).get("worst_net"),
            "leveraged": {k: lev.get(k) for k in ("instrument", "trades", "mean_net", "worst_net", "mae_worst")} if lev else None,
            "holdout": {k: (card.get("holdout") or {}).get(k) for k in ("trades", "excess", "p")} if card.get("holdout") else None,
            "forward": {k: (card.get("forward") or {}).get(k) for k in ("since", "trades", "mean_excess", "band_lower", "status")},
            "limitations": [str(x) for x in card.get("limitations") or []][:8],
            "ideas": [i.get("id") for i in card.get("ideas") or [] if isinstance(i, dict)]}


def attach(sigs: list[dict], cards: dict, atr: dict | None = None) -> None:
    """Give each signal its cards and say whether it is near its trigger.

    "Near" is scaled to volatility when the ETF's ATR(14) is known (review v2, 2026-11-21: within NEAR_ATR daily
    ranges of the trigger close; 3% was less than one day's move with VIX at 36 and several days' in a calm
    market); otherwise within 3%. `cards` are the next-open cards the Daily thesis shows; `close_cards` the
    closing-price ones, for the Review page's edge table."""
    for s in sigs:
        trigger, close = s.get("trigger_close"), s.get("close")
        width = (atr or {}).get(s.get("symbol"))
        s["near_atr"] = (close - trigger) / width if width and trigger and close else None
        if width:
            s["near_trigger"] = bool(not s.get("fired") and trigger and close and close - trigger <= NEAR_ATR * width)
            s["near_basis"] = f"within {NEAR_ATR:g} ATR(14)"
        else:
            s["near_trigger"] = bool(not s.get("fired") and trigger and close and trigger / close - 1 >= -NEAR)
            s["near_basis"] = f"within {NEAR:.0%}"
        mine = [c for c in cards.get("cards") or []
                if cards.get("status") == "ok" and c["symbol"] == s.get("symbol") and _base(c["signal"]) == s.get("signal")]
        s["cards"] = [summarize(c) for c in mine if c["entry"] == eligibility.ENTRY_MODE]
        s["close_cards"] = [summarize(c) for c in mine if c["entry"] == "etf_close"]


def meta(cards: dict) -> dict:
    """What the page says about the file itself (without the cards, which sit on each signal)."""
    return {k: v for k, v in cards.items() if k != "cards"}
