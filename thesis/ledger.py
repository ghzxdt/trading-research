"""Idea ledger: every research idea on one line, moving through fixed stages, so nothing tested is forgotten.

Stages: idea -> registered (the exact rule is written down before any result is seen) -> backtested ->
forward (logged before each entry, scored automatically) -> kept or dropped. An idea may also be dropped at any
stage. The ledger counts everything that was tested, including what was dropped: testing many ideas guarantees
that some look good by luck, so the count belongs next to every result.

data/thesis/ideas.jsonl is an append-only, hash-chained event log (never edit it by hand): one "create" event
per idea and one "update" event per change. The current state of each idea is rebuilt by replaying the events.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pandas as pd

from . import calls
from .data import NY

LOG = Path("data/thesis/ideas.jsonl")
STAGES = ("idea", "registered", "backtested", "forward", "kept", "dropped")
TESTED = ("backtested", "forward", "kept")
LIMITS = {"title": 140, "claim": 700, "test": 700, "result": 900, "evidence_ref": 240, "route": 40}
_LOCK = threading.Lock()


def _text(payload: dict, key: str, required: bool = False) -> str:
    value = str(payload.get(key) or "").strip()
    if required and not value:
        raise ValueError(f"{key.capitalize()} is required.")
    if len(value) > LIMITS[key]:
        raise ValueError(f"{key.capitalize()} is limited to {LIMITS[key]} characters.")
    return value


def _stage(value, default=None) -> str | None:
    stage = str(value or "").strip().lower() or default
    if stage is not None and stage not in STAGES:
        raise ValueError("Stage must be one of " + ", ".join(STAGES) + ".")
    return stage


def _write(root: Path, rows: list[dict], event: dict, now: pd.Timestamp | None) -> dict:
    now = (now or pd.Timestamp.now(tz="UTC")).tz_convert("UTC")
    body = {"schema": 1, "id": len(rows) + 1, "recorded_utc": now.isoformat(timespec="seconds"),
            "recorded_et": now.tz_convert(NY).isoformat(timespec="seconds"), **event,
            "previous_hash": rows[-1]["hash"] if rows else ""}
    row = {**body, "hash": calls._digest(body)}
    path = Path(root) / LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    return row


def create(root: Path, payload: dict, now: pd.Timestamp | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("A JSON object is required.")
    event = {"type": "create", "title": _text(payload, "title", True), "claim": _text(payload, "claim", True),
             "test": _text(payload, "test"), "route": _text(payload, "route"),
             "stage": _stage(payload.get("stage"), "idea"), "result": _text(payload, "result"),
             "evidence_ref": _text(payload, "evidence_ref")}
    note = payload.get("from_note")
    if note not in (None, ""):
        try:
            event["from_note"] = int(note)
        except (TypeError, ValueError):
            raise ValueError("from_note must be a journal note number.") from None
    with _LOCK:
        rows = calls.read(root, LOG)
        event["idea"] = sum(1 for r in rows if r.get("type") == "create") + 1
        return _write(root, rows, event, now)


def update(root: Path, payload: dict, now: pd.Timestamp | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("A JSON object is required.")
    try:
        idea = int(payload.get("idea"))
    except (TypeError, ValueError):
        raise ValueError("Say which idea (its number).") from None
    event = {"type": "update", "idea": idea, "stage": _stage(payload.get("stage")),
             "result": _text(payload, "result"), "evidence_ref": _text(payload, "evidence_ref")}
    if not (event["stage"] or event["result"] or event["evidence_ref"]):
        raise ValueError("Give a new stage, a result or an evidence reference.")
    with _LOCK:
        rows = calls.read(root, LOG)
        if not any(r.get("type") == "create" and r.get("idea") == idea for r in rows):
            raise ValueError(f"There is no idea #{idea}.")
        return _write(root, rows, event, now)


def fold(rows: list[dict]) -> list[dict]:
    """Current state of every idea, oldest first, with its history of stage changes."""
    ideas: dict[int, dict] = {}
    for row in rows:
        when = str(row.get("recorded_et") or "")[:10]
        if row.get("type") == "create":
            ideas[row["idea"]] = {"idea": row["idea"], "title": row["title"], "claim": row["claim"],
                                  "test": row.get("test"), "route": row.get("route"), "stage": row["stage"],
                                  "result": row.get("result"), "evidence_ref": row.get("evidence_ref"),
                                  "from_note": row.get("from_note"), "created": when, "updated": when,
                                  "history": [{"date": when, "stage": row["stage"]}]}
        elif row.get("type") == "update" and row.get("idea") in ideas:
            item = ideas[row["idea"]]
            if row.get("stage") and row["stage"] != item["stage"]:
                item["stage"] = row["stage"]
                item["history"].append({"date": when, "stage": row["stage"]})
            for key in ("result", "evidence_ref"):
                if row.get(key):
                    item[key] = row[key]
            item["updated"] = when
    return [ideas[k] for k in sorted(ideas)]


def summary(root: Path) -> dict:
    check = calls.verify(root, LOG)
    if not check["ok"]:
        return {"status": "broken", "reason": check["reason"], "ideas": [], "counts": {}, "stages": list(STAGES)}
    ideas = fold(calls.read(root, LOG))
    counts = {stage: sum(1 for i in ideas if i["stage"] == stage) for stage in STAGES}
    # Tested: it reached a backtest, a forward log or "kept", or it was dropped with a recorded result
    # (an idea dropped before any test, with no result, was never tested).
    tested = lambda i: (any(h["stage"] in TESTED[:3] for h in i["history"])  # noqa: E731
                        or (i["stage"] == "dropped" and bool(i.get("result"))))
    return {"status": "ok", "ideas": ideas, "counts": counts, "stages": list(STAGES), "total": len(ideas),
            "tested": sum(1 for i in ideas if tested(i)),
            "kept": counts["kept"], "dropped": counts["dropped"],
            "note": "Tested counts every idea that reached a backtest or forward log, including the dropped ones. "
                    "The more ideas are tested, the more likely one looks good by luck."}
