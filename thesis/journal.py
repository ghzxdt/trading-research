"""The user's research journal: observations and call-outs that aren't trades, kept to look back on.

Append-only and hash-chained like the call log (never edit data/thesis/journal.jsonl by hand). Each note saves
what the published Daily thesis showed when it was written (stance, regime, VIX, fired rules, closes), so a
later read sees the note in its context. Whenever the page or API reads the journal it adds a look-back: what
the note's ETF (SPY when none is given) did over the next 5 and 20 sessions from the next open. A look-back is
context for the note, not a score: a note makes no directional claim.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pandas as pd

from . import calls
from .data import NY

LOG = Path("data/thesis/journal.jsonl")
MAX_TEXT, MAX_TAGS = 2000, 8
LOOKBACK = (5, 20)
_TAG = re.compile(r"[a-z0-9][a-z0-9-]{0,23}")
_LOCK = threading.Lock()


def tags_from(value) -> list[str]:
    raw = value if isinstance(value, list) else str(value or "").replace("#", " ").replace(",", " ").split()
    out = []
    for item in raw:
        tag = str(item).strip().lower()
        if not tag:
            continue
        if not _TAG.fullmatch(tag):
            raise ValueError("Tags are short words: letters, numbers and hyphens (for example: vix, cpi, gap-up).")
        if tag not in out:
            out.append(tag)
    if len(out) > MAX_TAGS:
        raise ValueError(f"At most {MAX_TAGS} tags.")
    return out


def validate(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("A JSON object is required.")
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ValueError("Write the note first.")
    if len(text) > MAX_TEXT:
        raise ValueError(f"A note is limited to {MAX_TEXT} characters.")
    instrument = str(payload.get("instrument") or "").upper()
    if instrument and instrument not in calls.INSTRUMENTS:
        raise ValueError(f"ETF must be blank or one of {', '.join(calls.INSTRUMENTS)}.")
    return {"text": text, "tags": tags_from(payload.get("tags")), "instrument": instrument or None}


def page_snapshot(root: Path) -> dict | None:
    """What the published Daily thesis showed (read from output/thesis_state.json); None if there is no page."""
    from validation import output_dir
    try:
        state = json.loads((output_dir(Path(root)) / "thesis_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    regime, stance = state.get("regime") or {}, state.get("stance") or {}
    vol = regime.get("volatility") or {}
    return {"page_as_of": state.get("as_of"), "latest_close": state.get("latest_close"),
            "stance": stance.get("headline"), "direction": stance.get("direction"),
            "condition": (regime.get("history") or {}).get("condition"),
            "vix": vol.get("vix"), "vix_term_ratio": vol.get("term_ratio"),
            "trend": {k: v.get("state") for k, v in (regime.get("trend") or {}).items()},
            "closes": {k: v.get("close") for k, v in (regime.get("trend") or {}).items()},
            "fired": [f"{s['symbol']} {s['signal']}" for s in state.get("signals") or [] if s.get("fired")]}


def append(root: Path, payload: dict, now: pd.Timestamp | None = None, snapshot=page_snapshot) -> dict:
    note = validate(payload)
    now = (now or pd.Timestamp.now(tz="UTC")).tz_convert("UTC")
    path = Path(root) / LOG
    with _LOCK:
        rows = calls.read(root, LOG)
        body = {"schema": 1, "id": len(rows) + 1, "recorded_utc": now.isoformat(timespec="seconds"),
                "recorded_et": now.tz_convert(NY).isoformat(timespec="seconds"), **note,
                "snapshot": snapshot(root) if snapshot else None,
                "previous_hash": rows[-1]["hash"] if rows else ""}
        row = {**body, "hash": calls._digest(body)}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    return row


def look_back(note: dict, etfs: dict) -> dict:
    symbol = note.get("instrument") or "SPY"
    out = {"symbol": symbol}
    for horizon in LOOKBACK:
        scored = calls.score({"id": note["id"], "recorded_et": note["recorded_et"], "instrument": symbol,
                              "direction": "long", "horizon_sessions": horizon}, etfs.get(symbol))
        out[f"next_{horizon}"] = scored.get("instrument_return") if scored.get("status") == "scored" else None
        out[f"status_{horizon}"] = scored.get("status")
        out["entry_date"] = scored.get("entry_date", out.get("entry_date"))
    return out


def summary(root: Path, etfs: dict) -> dict:
    check = calls.verify(root, LOG)
    if not check["ok"]:
        return {"status": "broken", "reason": check["reason"], "notes": [], "tags": {}}
    notes, tags = [], {}
    for row in calls.read(root, LOG):
        for tag in row.get("tags") or []:
            tags[tag] = tags.get(tag, 0) + 1
        notes.append({k: row.get(k) for k in ("id", "recorded_et", "text", "tags", "instrument", "snapshot")}
                     | {"look_back": look_back(row, etfs)})
    return {"status": "ok", "count": len(notes), "notes": list(reversed(notes)), "tags": dict(sorted(tags.items())),
            "instruments": list(calls.INSTRUMENTS),
            "note": "The look-back is what the ETF did after the note (SPY when no ETF is given), from the next "
                    "open. It is context for reading the note later, not a score."}
