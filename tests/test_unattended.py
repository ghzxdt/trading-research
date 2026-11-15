"""Unattended runs: waiting for the network after a wake or sign-in, and keeping a timer-woken laptop awake."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unattended  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class NetworkWaitTests(unittest.TestCase):
    def wait(self, answers, limit=180):
        clock, said, answers = Clock(), [], list(answers)
        ok = unattended.wait_for_network(said.append, check=lambda: answers.pop(0) if answers else False,
                                         sleep=clock.sleep, monotonic=clock.monotonic, limit=limit)
        return ok, said, clock.t

    def test_network_already_up_says_nothing(self):
        self.assertEqual(self.wait([True]), (True, [], 0.0))

    def test_waits_until_the_network_answers(self):
        ok, said, waited = self.wait([False, False, True])
        self.assertEqual((ok, waited), (True, 20.0))
        self.assertEqual(said, ["Network answered after 20 seconds."])

    def test_gives_up_after_the_limit_and_goes_on(self):
        ok, said, waited = self.wait([], limit=60)
        self.assertFalse(ok)
        self.assertEqual(waited, 60.0)
        self.assertIn("No network after 60 seconds", said[0])

    def test_unreachable_host_is_false(self):
        self.assertFalse(unattended.reachable(("host.invalid",), timeout=1))


class KeepAwakeTests(unittest.TestCase):
    def test_no_op_off_windows(self):
        with unattended.keep_awake(platform="linux"):
            ran = True
        self.assertTrue(ran)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_windows_request_is_set_and_released(self):
        import ctypes
        kernel = ctypes.windll.kernel32
        with unattended.keep_awake():
            previous = kernel.SetThreadExecutionState(unattended.ES_CONTINUOUS | unattended.ES_SYSTEM_REQUIRED)
            self.assertEqual(previous & unattended.ES_SYSTEM_REQUIRED, unattended.ES_SYSTEM_REQUIRED)
        previous = kernel.SetThreadExecutionState(unattended.ES_CONTINUOUS)
        self.assertEqual(previous & unattended.ES_SYSTEM_REQUIRED, 0)  # released on exit


if __name__ == "__main__":
    unittest.main()
