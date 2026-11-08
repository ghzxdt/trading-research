"""Build all pages in a staging directory; publish with journaled rollback.

Windows directory publication uses two renames. Readers can briefly need to
retry between renames. The next build recovers an interrupted publication.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from validation import ValidationError, input_manifest, now_et, output_dir, validate_daily_table

BUILDERS = ("run_stage1.py", "run_leverage.py", "run_tickers.py", "run_gex.py", "run_monitor.py", "run_today.py", "run_thesis.py")
COMPONENTS = ("indexes", "leverage", "tickers", "gex", "today", "thesis")


def _inside(path: Path, parent: Path) -> Path:
    path, parent = path.resolve(), parent.resolve()
    if path == parent or parent not in path.parents:
        raise ValidationError(f"Transaction path must be a child of {parent}: {path}")
    return path


def source_manifest(root: Path) -> dict:
    paths = []
    for p in root.rglob("*"):
        if not p.is_file() or any(part in {"backups", "output", ".venv", "__pycache__", ".git", ".claude", "data", "work"} or part.startswith(".output-") for part in p.relative_to(root).parts):
            continue
        if p.suffix.lower() in {".py", ".pyw", ".html", ".json", ".txt", ".ps1", ".cmd", ".bat"}:
            paths.append(p)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def validate_bundle(out: Path, run_id: str) -> None:
    required = ["index.html", "report.html", "tickers.html", "leverage.html", "gex.html", "monitor.html",
                "backtests.html", "paper.html", "quality.html", "jobs.html", "monitor_status.json",
                "daily_table.csv", "long_history.csv", "leverage_markets.csv", "validation_report.json", "today.html", "today_state.json", "thesis.html", "thesis_state.json"]
    required += [f"ticker_{tk}.html" for tk in ("SPY", "QQQ", "IWM", "DIA", "RSP", "TQQQ", "SQQQ", "UPRO", "SPXU")]
    missing = [name for name in required if not (out / name).is_file()]
    if missing:
        raise ValidationError(f"Bundle incomplete: {missing}")
    for component in COMPONENTS:
        p = out / f"manifest_{component}.json"
        if not p.exists() or json.loads(p.read_text(encoding="utf-8")).get("run_id") != run_id:
            raise ValidationError(f"Missing/mixed-run component: {component}")
    if json.loads((out / "validation_report.json").read_text(encoding="utf-8")).get("passed") is not True:
        raise ValidationError("Index validation gates did not pass.")
    validate_daily_table(pd.read_csv(out / "daily_table.csv", parse_dates=["date"], index_col="date"))
    for p in out.glob("*.html"):
        text = p.read_text(encoding="utf-8")
        if "{{CHART_DATA}}" in text or "{{BODY}}" in text:
            raise ValidationError(f"Unresolved page template: {p.name}")
        match = re.search(r'<script type="application/json" id="chart-data">(.*?)</script>', text, re.S)
        if not match:
            continue
        for chart_id, spec in json.loads(match.group(1)).items():
            x = spec.get("x", spec.get("categories", []))
            if not x:
                raise ValidationError(f"Empty chart {p.name}:{chart_id}")
            if "x" in spec and spec["x"] != sorted(set(spec["x"])):
                raise ValidationError(f"Unordered/duplicate chart dates {p.name}:{chart_id}")
            for series in spec["series"]:
                values = series["values"]
                present = [v for v in values if v is not None]
                if len(values) != len(x) or not all(np.isfinite(v) for v in present):
                    raise ValidationError(f"Invalid chart data {p.name}:{chart_id}")
                if spec.get("log") and any(v <= 0 for v in present):
                    raise ValidationError(f"Nonpositive logarithmic chart {p.name}:{chart_id}")


def recover_publish(target: Path) -> None:
    parent = target.parent.resolve()
    journal = parent / f".{target.name}-publish.json"
    if not journal.exists():
        return
    state = json.loads(journal.read_text(encoding="utf-8"))
    old = _inside(Path(state["old"]), parent)
    if not old.name.startswith(f".{target.name}-previous-"):
        raise ValidationError("Invalid recovery journal path.")
    if not target.exists() and old.exists():
        old.rename(target)
    elif not target.exists():
        raise ValidationError("Interrupted publish has no complete bundle to restore.")
    journal.unlink()


def publish_bundle(stage: Path, target: Path) -> None:
    parent = target.parent.resolve()
    _inside(stage, parent)
    old = parent / f".{target.name}-previous-{uuid.uuid4().hex}"
    journal = parent / f".{target.name}-publish.json"
    journal.write_text(json.dumps({"old": str(old), "stage": str(stage)}, indent=2), encoding="utf-8")
    moved = False
    try:
        if target.exists():
            target.rename(old)
            moved = True
        stage.rename(target)
    except Exception:
        if moved and not target.exists() and old.exists():
            old.rename(target)
        raise
    finally:
        if target.exists():
            journal.unlink(missing_ok=True)
    # Retain the immediately preceding complete output bundle.
    for p in parent.glob(f".{target.name}-previous-*"):
        checked = _inside(p, parent)
        if checked != old and checked.is_dir():
            shutil.rmtree(checked)


def build(root: Path, *, offline=False, as_of: str | None = None) -> Path:
    root = root.resolve()
    target = output_dir(root)
    if target.parent != root:
        raise ValidationError("Full transactional build must publish to a direct child of the app folder.")
    recover_publish(target)
    stage = root / f".{target.name}-stage-{uuid.uuid4().hex}"
    stage.mkdir()
    if (target / "baseline").exists():
        shutil.copytree(target / "baseline", stage / "baseline")
    stamp = pd.Timestamp(as_of) if as_of else now_et()
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("America/New_York")
    sources_before, inputs_before = source_manifest(root), input_manifest(root)
    run_id = hashlib.sha256(json.dumps({"inputs": inputs_before, "source": sources_before, "offline": offline,
        "as_of": stamp.isoformat()}, sort_keys=True).encode()).hexdigest()[:20]
    env = dict(os.environ, APP_OUTPUT_DIR=str(stage), APP_RUN_ID=run_id, APP_BUILD_TIME=stamp.isoformat(),
               APP_AS_OF=stamp.isoformat(), APP_REPLAY="1" if as_of else "0", APP_OFFLINE="1" if offline else "0", PYTHONDONTWRITEBYTECODE="1")
    try:
        for script in BUILDERS:
            if not (root / script).exists():
                raise ValidationError(f"Required builder missing: {script}")
            print(f"Building {script}...", flush=True)
            command = [sys.executable, "-B", str(root / script)] + (["--offline"] if offline else [])
            if script == "run_monitor.py" and not offline:
                command.append("--refresh-jobs")
            subprocess.run(command, cwd=root, env=env, check=True)
        sources_after, inputs_after = source_manifest(root), input_manifest(root)
        if sources_before != sources_after:
            raise ValidationError("App source changed during build; retry to publish one consistent version.")
        if offline and inputs_before != inputs_after:
            raise ValidationError("Offline build changed source data; publication refused.")
        validate_bundle(stage, run_id)
        outputs = {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(stage.rglob("*")) if p.is_file() and "baseline" not in p.relative_to(stage).parts}
        manifest = {"schema_version": 1, "run_id": run_id, "offline": offline, "as_of": stamp.isoformat(),
                    "source": sources_after, "inputs": inputs_after, "outputs": outputs,
                    "historical_snapshot": bool(offline), "validation_passed": True,
                    "reproducibility": "Use --offline --as-of with the recorded timestamp and unchanged inputs/source."}
        (stage / "build_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        publish_bundle(stage, target)
        return target
    except Exception:
        (stage / "BUILD_FAILED.txt").write_text("Not published. The previous complete output is unchanged.\n", encoding="utf-8")
        raise
