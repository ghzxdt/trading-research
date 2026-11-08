"""Off-machine backup of the app's collected data.

The intraday archive, option chains, first-seen news and other collected observations are git-ignored (too big
for git), and Yahoo keeps only a few days of minute bars, so losing this computer would lose them for good.
After the evening collection, this zips everything under data/ except data/raw/ (re-downloadable caches) into
a dated archive and keeps copies in:

- backups/data/ on this computer (always), and
- "Trading Research Backups" in the first cloud-synced folder listed in backup_targets.json that exists
  (Google Drive for desktop or iCloud for Windows; install either and backups start going there).

Retention: archives from the last 3 days plus the newest one from each of the last 4 weeks.
"""
from __future__ import annotations

import json
import os
import zipfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGETS = ROOT / "backup_targets.json"
LOCAL = Path("backups/data")
CLOUD_SUBFOLDER = "Trading Research Backups"
PREFIX = "trading-research-data-"
KEEP_DAYS, KEEP_WEEKS = 3, 4


def cloud_folder(targets: Path = TARGETS) -> Path | None:
    """First configured cloud-synced folder that exists on this computer."""
    try:
        candidates = json.loads(targets.read_text(encoding="utf-8"))["cloud_folders"]
    except (OSError, ValueError, KeyError):
        return None
    for raw in candidates:
        folder = Path(os.path.expandvars(raw))
        if folder.is_dir():
            return folder / CLOUD_SUBFOLDER
    return None


def files_to_back_up(root: Path) -> list[Path]:
    data = root / "data"
    return sorted(p for p in data.rglob("*") if p.is_file() and "raw" not in p.relative_to(data).parts[:1]
                  and not p.name.endswith((".tmp", ".lock")))


def write_archive(root: Path, destination: Path, day: date) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{PREFIX}{day.isoformat()}.zip"
    partial = target.with_suffix(".zip.partial")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files_to_back_up(root):
            archive.write(path, path.relative_to(root).as_posix())
    with zipfile.ZipFile(partial) as archive:  # read back before trusting it
        if archive.testzip() is not None:
            raise OSError(f"Archive check failed for {partial.name}")
    partial.replace(target)
    return target


def prune(destination: Path, today: date) -> list[Path]:
    """Delete archives outside the retention window. Returns what was removed."""
    dated = []
    for path in destination.glob(f"{PREFIX}*.zip"):
        try:
            dated.append((date.fromisoformat(path.stem[len(PREFIX):]), path))
        except ValueError:
            continue
    keep = {p for d, p in dated if (today - d).days < KEEP_DAYS}
    newest_per_week: dict[tuple, tuple] = {}
    for d, p in dated:
        week = d.isocalendar()[:2]
        if (today - d).days < KEEP_WEEKS * 7 and (week not in newest_per_week or d > newest_per_week[week][0]):
            newest_per_week[week] = (d, p)
    keep |= {p for _, p in newest_per_week.values()}
    removed = [p for _, p in dated if p not in keep]
    for path in removed:
        path.unlink()
    return removed


def run(root: Path = ROOT, say=print, today: date | None = None, cloud: Path | None | bool = True) -> dict:
    today = today or date.today()
    local = write_archive(root, root / LOCAL, today)
    prune(root / LOCAL, today)
    size = local.stat().st_size / 1e6
    result = {"local": str(local), "megabytes": round(size, 1), "cloud": None}
    target = cloud_folder() if cloud is True else (cloud or None)
    if target:
        copy = write_archive(root, target, today)
        prune(target, today)
        result["cloud"] = str(copy)
        say(f"Data backup: {size:.1f} MB archive saved locally and to {target}.")
    else:
        say(f"Data backup: {size:.1f} MB archive saved locally only. No cloud folder found (install Google Drive "
            "for desktop or iCloud for Windows, or add a folder to backup_targets.json).")
    return result


if __name__ == "__main__":
    run()
