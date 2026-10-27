"""
Portable file locking — works on Windows, Linux, and Mac.

Uses a .lock sidecar file with os.O_CREAT | os.O_EXCL, which is atomic
on all platforms. Replaces fcntl.flock (Unix-only) throughout the codebase.

Design:
- The .lock file contains the owner's PID
- Stale detection: check if the owning PID is still alive (not time-based)
- Multiple processes trying to delete a stale lock simultaneously are safe:
  O_CREAT | O_EXCL is the final guard — only one process wins the create
- Exponential backoff reduces CPU spin under high contention

Usage:
    from .file_lock import portable_lock

    with portable_lock(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(...)
            f.flush()
"""

import os
import sys
import time
import pathlib
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10    # seconds before raising TimeoutError
_INITIAL_WAIT    = 0.02  # 20ms starting retry interval
_MAX_WAIT        = 0.20  # 200ms max retry interval (exponential backoff cap)


def _is_pid_alive(pid: int) -> bool:
    """Return True if the process with this PID is still running."""
    try:
        os.kill(pid, 0)  # signal 0 = existence check only, no actual signal sent
        return True
    except PermissionError:
        return True  # process exists, we just can't signal it
    except (ProcessLookupError, OSError):
        return False  # process does not exist


def _read_lock_pid(lock_path: pathlib.Path) -> int | None:
    """Read the PID written into the lock file. Returns None on any error."""
    try:
        return int(lock_path.read_text().strip())
    except (OSError, ValueError):
        return None


@contextmanager
def portable_lock(path, timeout: float = _DEFAULT_TIMEOUT):
    """
    Acquire an exclusive lock on `path` before entering the block.
    Releases automatically on exit (even on exception or KeyboardInterrupt).

    Behaviour:
    - Creates `path.lock` atomically (O_CREAT | O_EXCL)
    - Writes own PID into the lock file
    - If lock already exists: checks whether the owning PID is still alive
        - Alive  → wait and retry (exponential backoff: 20ms → 40ms → … → 200ms)
        - Dead   → delete stale lock and retry (safe: O_CREAT | O_EXCL is still the guard)
    - Raises TimeoutError after `timeout` seconds
    """
    lock_path = pathlib.Path(str(path) + ".lock")
    deadline  = time.monotonic() + timeout
    acquired  = False
    wait      = _INITIAL_WAIT

    while time.monotonic() < deadline:
        try:
            # O_EXCL create is atomic; only one process wins.
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            owner_pid = _read_lock_pid(lock_path)
            if owner_pid is not None and not _is_pid_alive(owner_pid):
                # Stale lock is safe to remove; racing processes retry via O_EXCL.
                logger.warning(
                    "portable_lock: removing stale lock %s (PID %d is dead)",
                    lock_path, owner_pid,
                )
                try:
                    lock_path.unlink(missing_ok=True)
                except OSError:
                    pass
            time.sleep(wait)
            wait = min(wait * 2, _MAX_WAIT)

    if not acquired:
        raise TimeoutError(
            f"portable_lock: could not acquire lock on {path} after {timeout}s. "
            f"Check for stale lock file: {lock_path}"
        )

    try:
        yield
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass
