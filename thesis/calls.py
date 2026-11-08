"""The user's thesis calls: append-only, hash-chained, separate from the frozen rules' paper log.

A call is recorded from the Daily thesis tab (long, short or flat; instrument; horizon in sessions; what would
invalidate it; why). Scores are computed from saved daily prices whenever the page or API reads the log; nothing
is written back. Entry is the next regular-session open after the call (a call made before 9:30 AM ET on a
session day enters that morning), and the exit is the close `horizon` sessions later. Each call is compared with
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
MAX_HORIZON = 60
MAX_TEXT = {"invalidation": 600, "reason": 1500}
OPEN = pd.Timedelta(hours=9, minutes=30)
_LOCK = threading.Lock()


def _digest(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def read(root: Path) -> list[dict]:
    path = Path(root) / LOG
    if not path.exists():
        return []
    rows, previous = [], ""
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        body = {k: v for k, v in row.items() if k != "hash"}
        if row.get("previous_hash") != previous or row.get("hash") != _digest(body):
            raise ValueError(f"calls.jsonl hash chain is broken at line {number}; do not edit the file by hand")
        previous = row["hash"]
        rows.append(row)
    return rows


def verify(root: Path) -> dict:
    try:
        return {"ok": True, "calls": len(read(root))}
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
    return {"instrument": instrument, "direction": direction, "horizon_sessions": horizon, **texts, "context": keep}


def append(root: Path, payload: dict, now: pd.Timestamp | None = None) -> dict:
    call = validate(payload)
    now = (now or pd.Timestamp.now(tz="UTC")).tz_convert("UTC")
    path = Path(root) / LOG
    with _LOCK:
        rows = read(root)
        body = {"schema": 1, "id": len(rows) + 1, "recorded_utc": now.isoformat(timespec="seconds"),
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


def score(call: dict, frame: pd.DataFrame | None) -> dict:
    out = {"id": call["id"], "recorded_et": call["recorded_et"], "instrument": call["instrument"],
           "direction": call["direction"], "horizon_sessions": call["horizon_sessions"],
           "invalidation": call.get("invalidation"), "reason": call.get("reason"),
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
    return {**out, "status": "scored" if done else "open", "entry_date": f"{frame.index[start]:%Y-%m-%d}",
            "entry_open": entry, "through_date": f"{frame.index[last]:%Y-%m-%d}",
            "exit_due": None if done else f"{call['horizon_sessions'] - (last - start + 1)} more sessions",
            "instrument_return": move, "call_return": sign * move, "always_long_return": move,
            "versus_always_long": sign * move - move}


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
            "note": "Returns are per call, unlevered, before costs. A handful of calls says little; the sample "
                    "size is shown so it can't look more certain than it is."}


def summary(root: Path, etfs: dict) -> dict:
    check = verify(root)
    if not check["ok"]:
        return {"status": "broken", "reason": check["reason"], "calls": [], "scoreboard": scoreboard([])}
    scored = [score(c, etfs.get(c["instrument"])) for c in read(root)]
    return {"status": "ok", "calls": list(reversed(scored)), "scoreboard": scoreboard(scored),
            "instruments": list(INSTRUMENTS), "max_horizon": MAX_HORIZON}
