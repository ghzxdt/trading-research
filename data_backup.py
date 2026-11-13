"""Backup of the app's collected data and of this project's Claude chats, inside the project folder.

The intraday archive, option chains, first-seen news and other collected observations are git-ignored (too big
for git), and Yahoo keeps only a few days of minute bars, so losing this computer would lose them for good.
The user backs up C:\\Claude by hand (2026-11-13: no cloud sync), so everything worth keeping lands under it.
After the evening collection this:

- zips everything under data/ except data/raw/ (re-downloadable caches) into a dated archive in backups/data/,
  plus "Trading Research Backups" in the first folder listed in backup_targets.json that exists (none by default);
- copies this project's Claude Code chat transcripts and memory (~/.claude/projects/<project>/) to
  backups/conversations/, adding new and changed files and never deleting.

Retention for data archives: the last 3 days plus the newest one from each of the last 4 weeks.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGETS = ROOT / "backup_targets.json"
LOCAL = Path("backups/data")
CONVERSATIONS = Path("backups/conversations")
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


def conversation_folder(root: Path = ROOT) -> Path:
    """Where Claude Code keeps this project's chats: ~/.claude/projects/ plus the path with every
    non-alphanumeric character replaced by '-' (C:\\Claude\\trading-research -> C--Claude-trading-research)."""
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(root.resolve()))


def copy_conversations(source: Path, destination: Path) -> int:
    """Copy new or changed files from source into destination (never deletes). Returns files copied."""
    copied = 0
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        target = destination / path.relative_to(source)
        stat = path.stat()
        if target.exists() and target.stat().st_size == stat.st_size and target.stat().st_mtime >= stat.st_mtime:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return copied


def run(root: Path = ROOT, say=print, today: date | None = None, cloud: Path | None | bool = True,
        conversations: Path | None | bool = True) -> dict:
    today = today or date.today()
    local = write_archive(root, root / LOCAL, today)
    prune(root / LOCAL, today)
    size = local.stat().st_size / 1e6
    result = {"local": str(local), "megabytes": round(size, 1), "cloud": None, "conversations": None}
    target = cloud_folder() if cloud is True else (cloud or None)
    if target:
        copy = write_archive(root, target, today)
        prune(target, today)
        result["cloud"] = str(copy)
        say(f"Data backup: {size:.1f} MB archive saved to {LOCAL.as_posix()} and {target}.")
    else:
        say(f"Data backup: {size:.1f} MB archive saved to {LOCAL.as_posix()} (back up C:\\Claude by hand).")
    source = conversation_folder(root) if conversations is True else (conversations or None)
    if source:
        if source.is_dir():
            copied = copy_conversations(source, root / CONVERSATIONS)
            result["conversations"] = copied
            say(f"Conversations: {copied} new or changed file(s) copied to {CONVERSATIONS.as_posix()}.")
        else:
            say(f"Conversations: no chat folder at {source}; nothing copied.")
    return result


if __name__ == "__main__":
    run()
