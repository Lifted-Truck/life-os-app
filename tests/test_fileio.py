"""scheduler.fileio — atomicity + real multi-process concurrency.

The concurrency tests spawn actual OS processes (not threads): the failure
mode being guarded against is the bot, timers, and skill sessions writing the
same files from separate processes.
"""
import multiprocessing as mp
import re
from pathlib import Path

from scheduler.fileio import atomic_write_text, file_lock, locked_append_text


# --- atomic writes -----------------------------------------------------------

def test_atomic_write_creates_parents_and_content(tmp_path):
    p = tmp_path / "a" / "b" / "note.md"
    atomic_write_text(p, "hello\n")
    assert p.read_text(encoding="utf-8") == "hello\n"


def test_atomic_write_replaces_fully_and_leaves_no_temp(tmp_path):
    p = tmp_path / "f.md"
    atomic_write_text(p, "old " * 1000)
    atomic_write_text(p, "new\n")
    assert p.read_text(encoding="utf-8") == "new\n"
    leftovers = [x for x in tmp_path.iterdir() if x.suffix == ".tmp"]
    assert leftovers == []


# --- multi-process workers (module level for spawn pickling) ----------------

def _append_worker(args):
    path_str, worker, n = args
    for i in range(n):
        locked_append_text(Path(path_str), f"w{worker}-{i:04d}\n")


def _rmw_worker(args):
    path_str, n = args
    p = Path(path_str)
    for _ in range(n):
        with file_lock(p):
            value = int(p.read_text(encoding="utf-8"))
            atomic_write_text(p, str(value + 1))


def test_concurrent_appends_no_torn_lines(tmp_path):
    p = tmp_path / "inbox.md"
    workers, per = 4, 150
    with mp.Pool(workers) as pool:
        pool.map(_append_worker, [(str(p), w, per) for w in range(workers)])
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == workers * per
    assert all(re.fullmatch(r"w\d-\d{4}", ln) for ln in lines), "torn/interleaved line"
    # every worker's every line arrived exactly once
    assert len(set(lines)) == workers * per


def test_file_lock_serializes_read_modify_write(tmp_path):
    p = tmp_path / "counter.txt"
    p.write_text("0", encoding="utf-8")
    workers, per = 4, 50
    with mp.Pool(workers) as pool:
        pool.map(_rmw_worker, [(str(p), per)] * workers)
    # without the lock, concurrent RMW loses increments
    assert int(p.read_text(encoding="utf-8")) == workers * per
