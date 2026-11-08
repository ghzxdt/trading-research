"""Back up the app's tracked data to GitHub after the evening refresh.

Commits only the data files a refresh writes (paper log, Kalshi snapshots, jobs-data archive),
then pushes main to the 'origin' remote. Code is never committed here; pushing main also sends
any code commits made since the last push. Skips when the folder isn't on main, when another git
command is running, or when the paper log fails its hash check. Never prompts for credentials:
if Git Credential Manager has no saved sign-in, the push fails and is logged.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from app_control import hidden_process_flags

DATA_PATHS = ("data/monitor/paper_events.jsonl", "data/kalshi/snapshots.csv", "data/employment")
FROZEN = "data/monitor/experiment_lock.json"


def git(root: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    exe = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    return subprocess.run([exe, *args], cwd=root, env=env, capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, creationflags=hidden_process_flags())


def changed(root: Path, *paths: str) -> list[str]:
    """Modified, added, deleted or untracked files (not ignored ones) under the given paths."""
    out = git(root, "status", "--porcelain", "--untracked-files=all", "--", *paths).stdout
    return [line[3:].strip().strip('"') for line in out.splitlines() if line.strip()]


def sync(root: Path, say, message: str = "Evening refresh data") -> str:
    root = Path(root)
    if not (root / ".git").exists():
        say("Git backup skipped: not a git repository.")
        return "skipped"
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != "main":
        say(f"Git backup skipped: the folder is on branch '{branch}', not main.")
        return "skipped"
    if (root / ".git" / "index.lock").exists():
        say("Git backup skipped: another git command is running.")
        return "skipped"
    if changed(root, FROZEN):
        say(f"Warning: {FROZEN} has changed. The experiment is frozen; that file was not committed.")
    data = changed(root, *DATA_PATHS)
    result = "nothing to commit"
    if data:
        paper = root / "data/monitor/paper_events.jsonl"
        if paper.exists():
            from monitor.paper import read_log
            try:
                read_log(paper)
            except ValueError as exc:
                say(f"Git backup refused: {exc}. Nothing was committed.")
                return "refused"
        added = git(root, "add", "--", *data)
        committed = git(root, "commit", "--only", "-m", message, "--", *data) if added.returncode == 0 else added
        if committed.returncode != 0:
            say("Data commit failed: " + (committed.stderr or committed.stdout).strip()[-300:])
            return "commit failed"
        say(f"Committed {len(data)} data file(s): {', '.join(data[:6])}")
        result = "committed"
    others = [path for path in changed(root) if not path.startswith("data/")]
    if others:
        say(f"Left {len(others)} uncommitted change(s) outside data/ alone (not pushed): {', '.join(others[:5])}")
    if "origin" not in git(root, "remote").stdout.split():
        say("No GitHub remote yet; " + ("data committed locally only." if result == "committed" else "nothing to push."))
        return result
    pushed = git(root, "push", "origin", "main", timeout=180)
    if pushed.returncode != 0:
        say("Push to GitHub failed; it will be retried next evening: " + (pushed.stderr or pushed.stdout).strip()[-300:])
        return "push failed"
    say("Pushed main to GitHub.")
    return result if result != "nothing to commit" else "pushed"
