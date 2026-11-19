"""The user's thesis calls: append-only, hash-chained, separate from the frozen rules' paper log.

A call is recorded from the Daily thesis tab (long, short or flat; instrument; horizon in sessions; what would
invalidate it; why). Scores are computed from saved daily prices whenever the page or API reads the log; nothing
is written back. Entry is the next regular-session open after the call (a call made before 9:30 AM ET on a
session day enters that morning), and the exit is the close `horizon` sessions later, or, for a call recorded
with an exit level ("invalid if [ETF] closes below / above [price]", schema 2 since 2026-11-18), the next open
after the first daily close that breaks it, if that comes first. Each call is compared with
simply holding the same ETF over the same days ("always long"), so the scoreboard shows whether the calls added
anything beyond owning the market.

Never edit data/thesis/calls.jsonl by hand: a broken chain is reported and blocks new records.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pandas as pd

from .data import NY

LOG = Path("data/thesis/calls.jsonl")
INSTRUMENTS = ("SPY", "QQQ", "IWM", "UPRO", "SPXU", "TQQQ", "SQQQ")
DIRECTIONS = ("long", "short", "flat")
BASIS = ("signal", "regime", "event", "news", "levels", "other")  # what the call leaned on (optional tags)
MAX_HORIZON = 60
MAX_TEXT = {"invalidation": 600, "reason": 1500}
OPEN = pd.Timedelta(hours=9, minutes=30)
_LOCK = threading.Lock()


def _digest(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def read(root: Path, log: Path = LOG) -> list[dict]:
    path = Path(root) / log
    if not path.exists():
        return []
    rows, previous = [], ""
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        body = {k: v for k, v in row.items() if k != "hash"}
        if row.get("previous_hash") != previous or row.get("hash") != _digest(body):
            raise ValueError(f"{path.name} hash chain is broken at line {number}; do not edit the file by hand")
        previous = row["hash"]
        rows.append(row)
    return rows


def verify(root: Path, log: Path = LOG) -> dict:
    try:
        return {"ok": True, "calls": len(read(root, log))}
    except (ValueError, OSError) as exc:
        return {"ok": False, "reason": str(exc)}


def validate(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("A JSON object is required.")
    instrument = str(payload.get("instrument", "")).upper()
    direction = str(payload.get("direction", "")).lower()
    if instrument not in INSTRUMENTS:
        raise ValueError(f"Instrument must be one of {', '.join(INSTRUMENTS)}.")
    if direction not in DIRECTIONS:
        raise ValueError("Direction must be long, short or flat.")
    try:
        horizon = int(payload.get("horizon_sessions"))
    except (TypeError, ValueError):
        raise ValueError("Horizon must be a whole number of sessions.") from None
    if not 1 <= horizon <= MAX_HORIZON:
        raise ValueError(f"Horizon must be 1 to {MAX_HORIZON} sessions.")
    texts = {}
    for key, limit in MAX_TEXT.items():
        value = str(payload.get(key) or "").strip()
        if len(value) > limit:
            raise ValueError(f"{key.capitalize()} is limited to {limit} characters.")
        texts[key] = value
    if direction != "flat" and not texts["invalidation"]:
        raise ValueError("Say what would invalidate a long or short call.")
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    keep = {k: context[k] for k in ("suggestion", "page_as_of", "latest_close") if k in context}
    raw = payload.get("basis") or []
    raw = raw if isinstance(raw, list) else [raw]
    basis = [b for b in BASIS if b in {str(x).lower() for x in raw}]
    if len(basis) != len({str(x).lower() for x in raw}):
        raise ValueError("Basis must be chosen from " + ", ".join(BASIS) + ".")
    return {"instrument": instrument, "direction": direction, "horizon_sessions": horizon, **texts, "context": keep,
            "basis": basis, "exit_level": exit_level(payload, instrument, direction)}


def exit_level(payload: dict, instrument: str, direction: str) -> dict | None:
    """Optional "invalid if [ETF] closes below / above [price]" (user, 2026-11-18). Recorded with the call, before
    entry; calls.jsonl is append-only, so it can never be added or changed afterwards."""
    given = payload.get("exit_level") if isinstance(payload.get("exit_level"), dict) else {}
    price = payload.get("exit_price", given.get("price"))
    if price in (None, ""):
        return None
    if direction == "flat":
        raise ValueError("A flat call has no exit level.")
    try:
        price = float(price)
    except (TypeError, ValueError):
        raise ValueError("The exit level must be a price.") from None
    if not 0 < price < 1e6:
        raise ValueError("The exit level must be a positive price.")
    side = str(payload.get("exit_side") or given.get("side") or ("below" if direction == "long" else "above")).lower()
    if side not in ("below", "above"):
        raise ValueError("The exit level is a close below or above a price.")
    level_instrument = str(payload.get("exit_instrument") or given.get("instrument") or instrument).upper()
    if level_instrument not in INSTRUMENTS:
        raise ValueError(f"The exit level's ETF must be one of {', '.join(INSTRUMENTS)}.")
    return {"instrument": level_instrument, "side": side, "price": price}


def append(root: Path, payload: dict, now: pd.Timestamp | None = None) -> dict:
    call = validate(payload)
    now = (now or pd.Timestamp.now(tz="UTC")).tz_convert("UTC")
    path = Path(root) / LOG
    with _LOCK:
        rows = read(root)
        # schema 2 (2026-11-18): every new call carries "exit_level" (null when none was given); schema 1 calls stay.
        body = {"schema": 2, "id": len(rows) + 1, "recorded_utc": now.isoformat(timespec="seconds"),
                "recorded_et": now.tz_convert(NY).isoformat(timespec="seconds"), **call,
                "previous_hash": rows[-1]["hash"] if rows else ""}
        row = {**body, "hash": _digest(body)}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    return row


def entry_position(index: pd.DatetimeIndex, recorded_et: pd.Timestamp) -> int | None:
    day = recorded_et.normalize().tz_localize(None)
    before_open = recorded_et - recorded_et.normalize() < OPEN
    for position, session in enumerate(index):
        if session > day or (session == day and before_open):
            return position
    return None


LEVEL_EXIT = ("A call with an exit level ends at the next session's open after the first daily close that breaks "
              "the level (from the entry day on), or at the horizon's close, whichever comes first.")


def _level_break(level: dict, frame: pd.DataFrame, level_frame: pd.DataFrame | None, start: int, end: int) -> int | None:
    """Position (in the call's ETF) of the first close from entry to the horizon's end that breaks the level."""
    if level_frame is None or level_frame.empty:
        return None
    closes = level_frame["close"]
    for position in range(start, min(end, len(frame) - 1) + 1):
        day = frame.index[position]
        if day not in closes.index:
            continue
        close = float(closes.loc[day])
        if (close < level["price"]) if level["side"] == "below" else (close > level["price"]):
            return position
    return None


def score(call: dict, frame: pd.DataFrame | None, frames: dict | None = None) -> dict:
    """The call's result under its own exit (its level or its horizon), plus the fixed-horizon result beside it."""
    level = call.get("exit_level")
    out = {"id": call["id"], "recorded_et": call["recorded_et"], "instrument": call["instrument"],
           "direction": call["direction"], "horizon_sessions": call["horizon_sessions"],
           "invalidation": call.get("invalidation"), "reason": call.get("reason"),
           "basis": call.get("basis") or [], "exit_level": level,
           "suggestion": (call.get("context") or {}).get("suggestion")}
    if frame is None or frame.empty:
        return {**out, "status": "no_data"}
    recorded = pd.Timestamp(call["recorded_et"]).tz_convert(NY)
    start = entry_position(frame.index, recorded)
    if start is None:
        return {**out, "status": "pending", "detail": "Waiting for the entry session's prices."}
    end = start + call["horizon_sessions"] - 1
    entry = float(frame["open"].iloc[start])
    done = end < len(frame)
    last = end if done else len(frame) - 1
    move = float(frame["close"].iloc[last]) / entry - 1
    sign = {"long": 1, "short": -1, "flat": 0}[call["direction"]]
    result = {**out, "status": "scored" if done else "open", "entry_date": f"{frame.index[start]:%Y-%m-%d}",
              "entry_open": entry, "through_date": f"{frame.index[last]:%Y-%m-%d}",
              "exit_due": None if done else f"{call['horizon_sessions'] - (last - start + 1)} more sessions",
              "instrument_return": move, "call_return": sign * move, "always_long_return": move,
              "versus_always_long": sign * move - move, "ended_by": "horizon" if done else None,
              "fixed_horizon_return": sign * move if done else None}
    if level:
        level_frame = frame if level["instrument"] == call["instrument"] else (frames or {}).get(level["instrument"])
        broke = _level_break(level, frame, level_frame, start, end)
        if broke is not None and broke < end:  # broken on the horizon's last close: the horizon exit comes first
            result["level_broken_on"] = f"{frame.index[broke]:%Y-%m-%d}"
            if broke + 1 < len(frame):
                exit_price = float(frame["open"].iloc[broke + 1])
                moved = exit_price / entry - 1
                result.update(status="scored", ended_by="exit level", exit_due=None,
                              through_date=f"{frame.index[broke + 1]:%Y-%m-%d}", exit_open=exit_price,
                              instrument_return=moved, call_return=sign * moved, always_long_return=moved,
                              versus_always_long=sign * moved - moved)
            else:
                result.update(status="open", exit_due="exits at the next open (exit level broken)")
    return result


def scoreboard(scored: list[dict]) -> dict:
    final = [s for s in scored if s.get("status") == "scored"]
    directional = [s for s in final if s["direction"] != "flat"]
    mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    return {"calls": len(scored), "scored": len(final), "open": sum(s.get("status") == "open" for s in scored),
            "pending": sum(s.get("status") == "pending" for s in scored),
            "directional_scored": len(directional),
            "hit_rate": mean([1.0 if s["call_return"] > 0 else 0.0 for s in directional]),
            "mean_call_return": mean([s["call_return"] for s in final]),
            "mean_always_long": mean([s["always_long_return"] for s in final]),
            # Review B7 (2026-11-18, user: "yes, add the exit level to calls"): a call ends at its exit level or its
            # horizon; the fixed-horizon result stays beside it so calls compare with the stance log.
            "mean_fixed_horizon_return": mean([s["fixed_horizon_return"] for s in scored
                                               if s.get("fixed_horizon_return") is not None]),
            "fixed_horizon_scored": sum(s.get("fixed_horizon_return") is not None for s in scored),
            "ended_by_level": sum(s.get("ended_by") == "exit level" for s in final),
            "scoring": "exit_level_or_horizon",
            "note": LEVEL_EXIT + " Calls without one are held to the horizon. The free-text invalidation is shown "
                    "but not applied. The fixed-horizon result (held to the horizon whatever happens) is kept "
                    "beside it, so calls stay comparable with the stance log. Returns are per call, unlevered, "
                    "before costs. A handful of calls says little; the sample size is shown so it can't look more "
                    "certain than it is."}


def summary(root: Path, etfs: dict) -> dict:
    check = verify(root)
    if not check["ok"]:
        return {"status": "broken", "reason": check["reason"], "calls": [], "scoreboard": scoreboard([])}
    scored = [score(c, etfs.get(c["instrument"]), etfs) for c in read(root)]
    final = [s for s in scored if s.get("status") == "scored"]
    by_basis = []
    for tag in BASIS:
        mine = [s for s in final if tag in (s.get("basis") or [])]
        if mine:
            by_basis.append({"basis": tag, "scored": len(mine),
                             "mean_call_return": sum(s["call_return"] for s in mine) / len(mine),
                             "mean_versus_always_long": sum(s["versus_always_long"] for s in mine) / len(mine)})
    return {"status": "ok", "calls": list(reversed(scored)), "scoreboard": scoreboard(scored),
            "instruments": list(INSTRUMENTS), "max_horizon": MAX_HORIZON, "basis_options": list(BASIS),
            "by_basis": by_basis}
