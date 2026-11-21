"""Network helpers for the feed (2026-11-17).

The run of 2026-11-17 lost 14 employer sites and 15 captures because Windows went into standby ten minutes into
the run and the network was not back yet when it woke. Two answers: ask Windows to stay awake while a run is
active, and wait for the network instead of failing when a name cannot be resolved.
"""
import ctypes
import socket
import sys
import time
import urllib.error

HOSTS = ("www.linkedin.com", "www.google.com")  # a name lookup only; no page is requested


def up():
    for h in HOSTS:
        try:
            socket.getaddrinfo(h, 443)
            return True
        except OSError:
            continue
    return False


def wait(max_seconds=600, step=10):
    """Wait until names resolve again. True when the network is there, False after max_seconds without it."""
    waited = 0
    while not up():
        if waited >= max_seconds:
            return False
        time.sleep(step)
        waited += step
    return True


def dns_failure(e):
    """True when a request never left the machine: the name could not be resolved."""
    return (isinstance(e, urllib.error.URLError) and not isinstance(e, urllib.error.HTTPError)
            and isinstance(getattr(e, "reason", None), socket.gaierror))


def keep_awake(on=True):
    """Ask Windows not to go into standby on idle while a run is active (released when the process ends).
    It cannot stop a closed lid or the power button, and on battery Windows may still override it."""
    if sys.platform != "win32":
        return False
    try:
        es_continuous, es_system_required = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | (es_system_required if on else 0))
        return True
    except Exception:  # noqa: BLE001
        return False
