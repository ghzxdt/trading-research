"""Validated append-only bars with revisions, provenance and knowledge-cutoff replay.

No fetches occur here. A provider adapter must supply honest available_at values.
Local recorded_at is retained separately; historical imports are not forward evidence.
"""
from __future__ import annotations
from contextlib import contextmanager
from collections import OrderedDict
import copy
from pathlib import Path
import hashlib
import json
import math
import os
import re
import threading
import pandas as pd
from .calendar import utc

VERSION = "v1"
_CACHE_LOCK = threading.RLock()
_EVENT_CACHE = OrderedDict()
_SYMBOL_CACHE = OrderedDict()
_BAR_CACHE = OrderedDict()


def _bounded_put(cache, key_, value, maximum):
    cache[key_] = value
    cache.move_to_end(key_)
    while len(cache) > maximum:
        cache.popitem(last=False)


def _signature(path):
    path = Path(path).resolve()
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns, stat.st_ino)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def readonly():
    return os.environ.get("APP_OFFLINE") == "1" or os.environ.get("APP_REPLAY") == "1"


def normalize(record):
    if not isinstance(record, dict):
        raise ValueError("Each bar must be an object")
    symbol = str(record.get("symbol", "")).strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", symbol):
        raise ValueError("Invalid symbol")
    start, known = utc(record["timestamp"]), utc(record["available_at"])
    seconds = record.get("interval_seconds", 60)
    if isinstance(seconds, bool) or not float(seconds).is_integer() or not 1 <= int(seconds) <= 3600:
        raise ValueError("interval_seconds must be an integer between 1 and 3600")
    seconds = int(seconds)
    if start.value % (seconds * 1_000_000_000):
        raise ValueError("Bar timestamp must be aligned to its interval")
    if known < start + pd.Timedelta(seconds=seconds):
        raise ValueError("available_at cannot precede the completed bar")
    values = {}
    for name in ("open", "high", "low", "close", "volume"):
        value = record[name]
        if isinstance(value, bool):
            raise ValueError("Boolean OHLCV values are invalid")
        values[name] = float(value)
        if not math.isfinite(values[name]) or values[name] < (0 if name == "volume" else 1e-300):
            raise ValueError("OHLC must be finite and positive; volume finite and nonnegative")
    if values["high"] < max(values["open"], values["close"], values["low"]) or values["low"] > min(values["open"], values["close"], values["high"]):
        raise ValueError("Invalid OHLC ordering")
    source = str(record.get("source", "")).strip()
    if not source or len(source) > 200:
        raise ValueError("A source identifier is required")
    basis = str(record.get("availability_basis", "unspecified")).strip()
    if not basis or len(basis) > 100:
        raise ValueError("Invalid availability_basis")
    return {"schema_version": 1, "symbol": symbol, "timestamp": start.isoformat(),
            "available_at": known.isoformat(), "interval_seconds": seconds, **values,
            "source": source, "availability_basis": basis}


def key(record):
    return record["symbol"], record["timestamp"], record["interval_seconds"]


def canonical(records, as_of=None):
    """Latest version per bar as known at cutoff; input order cannot alter a result."""
    cutoff = utc(as_of) if as_of is not None else None
    versions = {}
    for raw in records:
        row = normalize(raw)
        if cutoff is not None and utc(row["available_at"]) > cutoff:
            continue
        ident = key(row)
        old = versions.get(ident)
        if old and old["available_at"] == row["available_at"] and old != row:
            raise ValueError("Conflicting bar versions share an available_at timestamp")
        if old is None or utc(row["available_at"]) > utc(old["available_at"]):
            versions[ident] = row
    rows = sorted(versions.values(), key=lambda r: (r["symbol"], r["timestamp"], r["interval_seconds"]))
    previous = {}
    for row in rows:
        ident = row["symbol"]
        start = utc(row["timestamp"])
        if ident in previous and start < previous[ident]:
            raise ValueError("Overlapping intervals for a symbol are not supported")
        previous[ident] = start + pd.Timedelta(seconds=row["interval_seconds"])
    return rows


def folder(root):
    return Path(root) / "data" / "intraday" / VERSION


def _verified_events(path):
    """Private immutable-by-convention cache; public callers receive deep copies."""
    path = Path(path)
    for _ in range(3):
        signature = _signature(path)
        if signature is None:
            return None, []
        with _CACHE_LOCK:
            if signature in _EVENT_CACHE:
                _EVENT_CACHE.move_to_end(signature)
                return signature, _EVENT_CACHE[signature]
        previous, rows = "", []
        try:
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    raise ValueError(f"Blank journal row {line_number}")
                event = json.loads(line)
                payload = {k: v for k, v in event.items() if k != "hash"}
                if event.get("previous_hash") != previous or event.get("hash") != digest(payload):
                    raise ValueError(f"Event hash chain failed at row {line_number}; preserve the file")
                previous = event["hash"]
                rows.append(event)
        except (ValueError, OSError):
            if _signature(path) != signature:
                continue  # An append/replacement interrupted the observation.
            raise
        if _signature(path) != signature:
            continue
        with _CACHE_LOCK:
            _bounded_put(_EVENT_CACHE, signature, rows, 4)
        return signature, rows
    raise RuntimeError("Journal changed repeatedly during verification; retry the read")


def read_events(path):
    _, rows = _verified_events(path)
    return copy.deepcopy(rows)


@contextmanager
def writer_lock(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".writer.lock"
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("An intraday writer is active; do not overwrite its lock") from exc
    try:
        os.write(handle, str(os.getpid()).encode())
        yield
    finally:
        os.close(handle)
        lock.unlink()


def append_events(path, events, payloads):
    """Call under writer_lock, after validating the entire proposed batch."""
    previous = events[-1]["hash"] if events else ""
    additions = []
    for payload in payloads:
        item = {**payload, "previous_hash": previous}
        item["hash"] = digest(item)
        additions.append(item)
        previous = item["hash"]
    if additions:
        with Path(path).open("a", encoding="utf-8", newline="\n") as stream:
            stream.write("".join(json.dumps(item, sort_keys=True, allow_nan=False) + "\n" for item in additions))
            stream.flush()
            os.fsync(stream.fileno())
    return additions


def ingest_bars(root, records):
    if readonly():
        raise PermissionError("Replay/offline mode cannot append intraday observations")
    proposed = [normalize(row) for row in records]
    canonical(proposed)  # Validate interval conflicts before touching a journal.
    target = folder(root)
    with writer_lock(target):
        path = target / "bars.jsonl"
        events = read_events(path)
        proposed_symbols = {row["symbol"] for row in proposed}
        existing = [normalize(event["bar"]) for event in events if event["bar"]["symbol"] in proposed_symbols]
        canonical(existing + proposed)
        seen = {digest(row) for row in existing}
        by_version = {(key(row), row["available_at"]): row for row in existing}
        latest = {key(row): row for row in canonical(existing)}
        payloads, duplicates, revisions = [], 0, 0
        prior_keys = {key(row) for row in existing}
        now = pd.Timestamp.now(tz="UTC").isoformat()
        for row in sorted(proposed, key=lambda r: (r["available_at"], r["symbol"], r["timestamp"])):
            version = (key(row), row["available_at"])
            if version in by_version and by_version[version] != row:
                raise ValueError("Conflicting revision; use the actual later publication time")
            ident = digest(row)
            old = latest.get(key(row))
            unchanged_later_receipt = (old is not None and utc(row["available_at"]) >= utc(old["available_at"]) and
                {k: v for k, v in old.items() if k != "available_at"} == {k: v for k, v in row.items() if k != "available_at"})
            if ident in seen or unchanged_later_receipt:
                duplicates += 1
                continue
            revisions += int(key(row) in prior_keys)
            prior_keys.add(key(row)); seen.add(ident); by_version[version] = row
            if old is None or utc(row["available_at"]) > utc(old["available_at"]):
                latest[key(row)] = row
            payloads.append({"schema_version": 1, "type": "bar", "recorded_at": now, "bar": row})
        append_events(path, events, payloads)
    return {"accepted": len(payloads), "duplicates": duplicates, "revisions": revisions,
            "schema_version": 1, "path": str(path), "symbols": sorted({r["symbol"] for r in proposed}),
            "historical_import_is_forward_evidence": False}


def load_bars(root, symbol, as_of=None):
    symbol = str(symbol).strip().upper()
    cutoff = utc(as_of) if as_of is not None else None
    signature, events = _verified_events(folder(root) / "bars.jsonl")
    if signature is None:
        return []
    with _CACHE_LOCK:
        grouped = _SYMBOL_CACHE.get(signature)
        if grouped is None:
            grouped = {}
            for event in events:
                if event.get("type") == "bar":
                    row = event["bar"]
                    grouped.setdefault(row["symbol"], []).append(row)
            grouped = {s: (rows, max(utc(r["available_at"]) for r in rows)) for s, rows in grouped.items()}
            _bounded_put(_SYMBOL_CACHE, signature, grouped, 4)
        else:
            _SYMBOL_CACHE.move_to_end(signature)
        rows, latest_known = grouped.get(symbol, ([], None))
        if not rows:
            return []
        # Current requests use a shared latest view rather than a new cache key
        # for every wall-clock second. Earlier cutoffs retain original revisions.
        view = None if cutoff is None or cutoff >= latest_known else cutoff.isoformat()
        cache_key = (signature, symbol, view)
        if cache_key not in _BAR_CACHE:
            _bounded_put(_BAR_CACHE, cache_key, canonical(rows, view), 64)
        else:
            _BAR_CACHE.move_to_end(cache_key)
        result = _BAR_CACHE[cache_key]
    return copy.deepcopy(result)
