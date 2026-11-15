"""Unattended runs: keep a timer-woken laptop awake while a scheduled job works, and wait for the network.

The scheduled tasks wake the laptop from sleep, lid open or closed. Two things can still spoil such a run:
- The job starts within seconds of the wake, before Wi-Fi has reconnected. Sign-in runs have the same problem:
  on Sat 2026-11-14 the runs two minutes after sign-in found no network, so every download and the GitHub push
  failed. Each scheduled script therefore waits up to three minutes for the network before downloading.
- Windows puts a timer-woken computer back to sleep after about two minutes without keyboard or mouse input,
  even mid-job. Each scheduled script holds a "system required" request for as long as it runs. It is released
  when the script exits, and it never stops the lid, the power button or the user from putting the laptop to sleep.
"""
from __future__ import annotations

import contextlib
import socket
import sys
import time

HOSTS = ("query1.finance.yahoo.com", "cdn.cboe.com", "github.com")  # any one reachable means the network is up
NETWORK_WAIT = 180  # seconds
ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


@contextlib.contextmanager
def keep_awake(platform: str = sys.platform):
    """Ask Windows not to sleep for lack of input while the block runs (a no-op elsewhere)."""
    kernel = None
    if platform == "win32":
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.SetThreadExecutionState.argtypes = [ctypes.c_uint]
        kernel.SetThreadExecutionState.restype = ctypes.c_uint
        kernel.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    try:
        yield
    finally:
        if kernel is not None:
            kernel.SetThreadExecutionState(ES_CONTINUOUS)


def reachable(hosts=HOSTS, timeout: float = 5.0) -> bool:
    """True if a TCP connection to port 443 of any host opens (nothing is sent)."""
    for host in hosts:
        try:
            with socket.create_connection((host, 443), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def wait_for_network(say, *, check=reachable, sleep=time.sleep, monotonic=time.monotonic,
                     limit: float = NETWORK_WAIT, every: float = 10) -> bool:
    """Wait until the network answers, up to `limit` seconds. Says how long it took, or that it gave up."""
    start = monotonic()
    while not check():
        if monotonic() - start >= limit:
            say(f"No network after {int(limit)} seconds; going on, so downloads may fail.")
            return False
        sleep(every)
    waited = monotonic() - start
    if waited >= 1:
        say(f"Network answered after {waited:.0f} seconds.")
    return True
