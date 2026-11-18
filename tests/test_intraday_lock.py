"""The minute-bar writer lock recovers from a writer that died (2026-11-15: a shut-down laptop left a lock that
blocked every collection for three days), and System status judges collection by the bars delivered."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intraday import store  # noqa: E402
import intraday_collect  # noqa: E402
from thesis import ops  # noqa: E402

NY = "America/New_York"
HOLDER = ("import sys,time; sys.path.insert(0, sys.argv[1]); from intraday.store import writer_lock\n"
          "import os\nwith writer_lock(sys.argv[2]):\n    print(os.getpid(), flush=True); time.sleep(120)\n")


class WriterLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.lock = self.dir / ".writer.lock"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_writer_killed_mid_run_leaves_a_lock_the_next_writer_recovers(self):
        # A venv's python.exe may start the real interpreter as a child, so the writer reports its own PID.
        holder = subprocess.Popen([sys.executable, "-B", "-c", HOLDER, str(ROOT), str(self.dir)],
                                  stdout=subprocess.PIPE, text=True)
        writer = None
        try:
            writer = int(holder.stdout.readline().strip())
            with self.assertRaises(RuntimeError):  # alive: respected
                with store.writer_lock(self.dir):
                    pass
        finally:
            if writer:
                os.kill(writer, 9)  # like a shutdown: the writer's own cleanup never runs (TerminateProcess)
            holder.kill()
            holder.wait(timeout=30)
            holder.stdout.close()
        deadline = time.time() + 10
        from app_control import process_alive
        while process_alive(writer) is not False and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(self.lock.read_text(encoding="ascii"), str(writer))
        with store.writer_lock(self.dir):
            self.assertEqual(self.lock.read_text(encoding="ascii"), str(os.getpid()))
        self.assertFalse(self.lock.exists())
        note = (self.dir / store.RECOVERY_LOG).read_text(encoding="utf-8")
        self.assertIn(f"by PID {writer}, which is no longer running", note)

    def test_a_reused_pid_counts_as_gone_but_an_uncheckable_one_is_kept(self):
        self.lock.write_text(str(os.getpid()), encoding="ascii")
        with self.assertRaises(RuntimeError):  # this process is alive and older than the lock
            with store.writer_lock(self.dir):
                pass
        old = time.time() - 30 * 86400  # the lock predates this process: its PID was reused
        os.utime(self.lock, (old, old))
        with self.assertRaises(RuntimeError):
            with store.writer_lock(self.dir, alive=lambda pid: None, started=lambda pid: None):
                pass
        self.assertTrue(self.lock.exists())
        with store.writer_lock(self.dir):
            pass
        self.assertFalse(self.lock.exists())

    def test_an_empty_lock_is_kept_briefly_then_recovered(self):
        self.lock.write_text("", encoding="ascii")
        with self.assertRaises(RuntimeError):
            with store.writer_lock(self.dir):
                pass
        old = time.time() - store.EMPTY_LOCK_GRACE - 5
        os.utime(self.lock, (old, old))
        with store.writer_lock(self.dir):
            pass
        self.assertIn("unknown (empty lock)", (self.dir / store.RECOVERY_LOG).read_text(encoding="utf-8"))


class BarRecordTests(unittest.TestCase):
    def test_an_off_minute_row_is_skipped_not_fatal(self):
        index = pd.DatetimeIndex(["2026-11-17 15:58", "2026-11-17 15:59", "2026-11-17 15:59:47"], tz=NY)
        frame = pd.DataFrame({k: [10.0, 10.1, 10.2] for k in ("Open", "High", "Low", "Close", "Volume")}, index=index)
        skipped = []
        records = intraday_collect.bar_records("TNA", frame, pd.Timestamp("2026-11-17 17:00", tz=NY), skipped)
        self.assertEqual(len(records), 2)
        self.assertEqual(skipped, ["2026-11-17T20:59:47+00:00"])


class StatusTests(unittest.TestCase):
    def row(self, results, bars=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status = root / "data" / "terminal" / "collection_status.json"
            status.parent.mkdir(parents=True)
            status.write_text(json.dumps({"finished_at": "2026-11-17T22:10:00+00:00", "results": results}), encoding="utf-8")
            if bars:
                path = root / "data" / "intraday" / "v1" / "bars.jsonl"
                path.parent.mkdir(parents=True)
                path.write_text("".join(json.dumps({"bar": {"timestamp": b}}) + "\n" for b in bars), encoding="utf-8")
            return ops._intraday_row(root, pd.Timestamp("2026-11-17 18:00", tz=NY), ["2026-11-16", "2026-11-17"])

    def test_zero_tickers_collected_is_never_ok(self):
        blocked = {"bar_status": "failed", "bar_error": "An intraday writer is active; do not overwrite its lock"}
        out = self.row([{"symbol": "SPY", **blocked}, {"symbol": "QQQ", **blocked}], ["2026-11-13T20:59:00+00:00"])
        self.assertEqual(out["state"], "missing")
        self.assertIn("none of the 2 tickers: An intraday writer is active", out["detail"])
        self.assertIn("Newest archived bar: 2026-11-13 15:59 ET", out["detail"])

    def test_partial_or_behind_is_late_and_complete_is_ok(self):
        good = {"symbol": "SPY", "bar_status": "collected"}
        out = self.row([good, {"symbol": "TNA", "bar_status": "failed", "bar_error": "aligned"}], ["2026-11-17T20:59:00+00:00"])
        self.assertEqual(out["state"], "late")
        self.assertIn("Not collected: TNA", out["detail"])
        self.assertEqual(self.row([good], ["2026-11-16T20:59:00+00:00"])["state"], "late")  # archive lacks Nov 17
        self.assertEqual(self.row([good], ["2026-11-17T20:59:00+00:00"])["state"], "ok")


if __name__ == "__main__":
    unittest.main()
