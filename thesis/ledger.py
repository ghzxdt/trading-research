"""Idea ledger: every research idea on one line, moving through fixed stages, so nothing tested is forgotten.

Stages: idea -> registered (the exact rule is written down before any result is seen) -> backtested ->
forward (logged before each entry, scored automatically) -> kept or dropped. An idea may also be dropped at any
stage. The ledger counts everything that was tested, including what was dropped: testing many ideas guarantees
that some look good by luck, so the count belongs next to every result.

data/thesis/ideas.jsonl is an append-only, hash-chained event log (never edit it by hand): one "create" event
per idea and one "update" event per change. The current state of each idea is rebuilt by replaying the events.

Schema 2 (review B8, 2026-11-18): new events may carry structured fields ("spec"): observation, mechanism,
instruments, rule, decision time, horizon, expected result, benchmark, what would confirm it, what would
invalidate it, and what to monitor. Schema 1 events stay valid as written. Once an idea is registered (or later),
its testable fields (rule, decision time, horizon, expected result, benchmark, confirm, invalidate) are fixed:
changing them is a new idea, because a rule rewritten after seeing results is no longer the registered rule.
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
SPEC = {"observation": 600, "mechanism": 600, "instruments": 120, "rule": 600, "decision_time": 120, "horizon": 120,
        "expected_result": 400, "benchmark": 300, "confirm": 400, "invalidate": 400, "monitor": 400}
FROZEN = ("rule", "decision_time", "horizon", "expected_result", "benchmark", "confirm", "invalidate")
CORE = ("rule", "decision_time", "horizon", "expected_result", "benchmark", "invalidate")  # a testable idea needs these
_LOCK = threading.Lock()


def _spec(payload: dict) -> dict:
    """The structured fields given (only non-empty ones), from payload["spec"] or top-level keys."""
    source = payload.get("spec") if isinstance(payload.get("spec"), dict) else payload
    out = {}
    for key, limit in SPEC.items():
        value = str(source.get(key) or "").strip()
        if len(value) > limit:
            raise ValueError(f"{key.replace('_', ' ').capitalize()} is limited to {limit} characters.")
        if value:
            out[key] = value
    return out


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
    body = {"schema": 2, "id": len(rows) + 1, "recorded_utc": now.isoformat(timespec="seconds"),
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
             "evidence_ref": _text(payload, "evidence_ref"), "spec": _spec(payload)}
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
             "result": _text(payload, "result"), "evidence_ref": _text(payload, "evidence_ref"), "spec": _spec(payload)}
    if not (event["stage"] or event["result"] or event["evidence_ref"] or event["spec"]):
        raise ValueError("Give a new stage, a result, an evidence reference or a structured field.")
    with _LOCK:
        rows = calls.read(root, LOG)
        current = next((i for i in fold(rows) if i["idea"] == idea), None)
        if current is None:
            raise ValueError(f"There is no idea #{idea}.")
        if current["stage"] != "idea":
            changed = [k for k in FROZEN if k in event["spec"] and current["spec"].get(k) and event["spec"][k] != current["spec"][k]]
            if changed:
                raise ValueError(f"Idea #{idea} is {current['stage']}: its {', '.join(k.replace('_', ' ') for k in changed)} "
                                 "can't change any more. Record a new idea for a changed rule.")
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
                                  "spec": dict(row.get("spec") or {}),
                                  "history": [{"date": when, "stage": row["stage"]}]}
        elif row.get("type") == "update" and row.get("idea") in ideas:
            item = ideas[row["idea"]]
            if row.get("stage") and row["stage"] != item["stage"]:
                item["stage"] = row["stage"]
                item["history"].append({"date": when, "stage": row["stage"]})
            for key in ("result", "evidence_ref"):
                if row.get(key):
                    item[key] = row[key]
            item["spec"].update(row.get("spec") or {})
            item["updated"] = when
    for item in ideas.values():
        item["missing"] = [k for k in CORE if not item["spec"].get(k)]  # what a testable statement still lacks
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
