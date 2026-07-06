"""Atomic, lock-guarded file writes — the app's single write path to the data tree.

Why this exists: the tree has many concurrent writers (the VPS bot, the sync
timer, skill sessions on two machines, humans) and a mid-write truncation of
inbox.md has already been observed in the wild. Every write the app makes goes
through here so the failure modes are handled once:

  * ``atomic_write_text``  — whole-file writes land completely or not at all
    (temp file in the same directory + fsync + ``os.replace``). A reader/child
    process can never observe a half-written file.
  * ``locked_append_text`` — appends from concurrent processes on the same
    machine serialize instead of interleaving/tearing.
  * ``file_lock``          — context manager for read-modify-write sequences
    (e.g. checking off an inbox item) so two processes can't both read the old
    text and clobber each other's update.

Locks are advisory and per-machine (``fcntl.flock`` on POSIX, ``msvcrt`` on
Windows, no-op if neither is available — degrade, don't crash). Cross-machine
races remain git's job. Lock sidecars are ``.<name>.lock`` files next to the
target; they are ignored by the data repo's .gitignore.
"""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl

    def _lock_fd(fd) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _unlock_fd(fd) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
except ImportError:                       # Windows
    try:
        import msvcrt

        def _lock_fd(fd) -> None:
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

        def _unlock_fd(fd) -> None:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except ImportError:                   # neither — degrade to unlocked
        def _lock_fd(fd) -> None:
            pass

        def _unlock_fd(fd) -> None:
            pass


def _lock_path(path: Path) -> Path:
    return path.parent / f".{path.name}.lock"


@contextmanager
def file_lock(path: Path):
    """Exclusive advisory lock scoped to `path` (via a sidecar lock file).

    Hold it across any read-modify-write of `path`. Reentrant use in the same
    process is NOT supported — keep critical sections small and flat.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lp = _lock_path(path)
    fd = os.open(lp, os.O_CREAT | os.O_RDWR)
    try:
        _lock_fd(fd)
        try:
            yield
        finally:
            _unlock_fd(fd)
    finally:
        os.close(fd)


def atomic_write_text(path: Path, content: str) -> None:
    """Write `content` to `path` all-or-nothing (temp + fsync + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def locked_append_text(path: Path, content: str) -> None:
    """Append `content` to `path`, serialized against other processes."""
    path = Path(path)
    with file_lock(path):
        with path.open("a", encoding="utf-8", newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
