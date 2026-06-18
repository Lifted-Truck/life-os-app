"""Shared fixtures: build a minimal Life-OS tree in a tmp dir."""
import textwrap
from pathlib import Path

import pytest


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolate_day_template_cache(tmp_path, monkeypatch):
    """Keep the day-template loader's last-known-good cache out of tests.

    ``load_day_template()`` defaults to a repo-relative ``CACHE_PATH``. Once the
    bot or dashboard has run locally, that cache holds the live template — and
    since the test fixtures carry no ``schedule/template.yaml``, the loader would
    fall back to that cache instead of ``DEFAULT_BLOCKS``, silently changing
    placement and breaking scheduling tests. Redirect the cache (both the module
    attr and the bound keyword default) to a per-test tmp path so tests are
    hermetic regardless of any local cache state.
    """
    from scheduler import day_template
    fake = tmp_path / "day_template_cache.yaml"
    monkeypatch.setattr(day_template, "CACHE_PATH", fake)
    kwdefaults = day_template.load_day_template.__kwdefaults__
    if kwdefaults and "cache_path" in kwdefaults:
        monkeypatch.setitem(kwdefaults, "cache_path", fake)


@pytest.fixture
def life_os(tmp_path: Path) -> Path:
    """A small but complete fixture root."""
    root = tmp_path / "life-os"

    _write(root / "thresholds.yaml", """\
        music-practice:
          min: 10
          target: 30
          mandatory-weekly: 60
          unit: minutes
          cadence: daily
        novel:
          min: 200
          target: 600
          unit: words
          cadence: daily
        production:
          target: 90
          mandatory-weekly: 1
          unit: minutes
          cadence: weekly
        career:
          min: 30
          target: 60
          unit: minutes
          cadence: daily
        fitness:
          min: 1
          target: 4
          unit: sessions
          cadence: weekly
        upkeep:
          cadence: as-scheduled
        """)

    _write(root / "inbox.md", """\
        # Inbox

        - [ ] Follow up on Ionos verification
        - [ ] File taxes | due: hard 2026-06-15
        - [ ] Email landlord | waiting: true
        """)

    _write(root / "domains" / "career" / "tasks.md", """\
        next-id: 4

        # Career — Task Records

        ```yaml
        - id: career-001
          goal: nyc-job-search
          type: 3
          subtype: project
          title: "Draft resume"
          importance: high
          duration: 90
          target: 1
          unit: sessions
          min: 30
          placement:
            class: floating
            slots: [deep-work]
            min-block: 60
        - id: career-002
          goal: nyc-job-search
          type: 3
          subtype: project
          title: "Send resume to recruiter"
          importance: critical
          duration: 30
          target: 1
          unit: sessions
          depends-on: [career-001]
          placement:
            class: floating
            slots: [admin]
            min-block: 30
        - id: career-003
          type: 3
          subtype: session-based
          title: "Blocked on review"
          importance: high
          target: 1
          unit: sessions
          waiting: true
          placement:
            class: floating
            slots: [admin]
        ```
        """)

    _write(root / "domains" / "novel" / "tasks.md", """\
        next-id: 1

        # Novel — Task Records

        ```yaml
        []
        ```
        """)

    (root / "daily" / "logs").mkdir(parents=True, exist_ok=True)
    (root / "schedule").mkdir(parents=True, exist_ok=True)
    _write(root / "schedule" / "queue.yaml", "generated: null\ntasks: []\nlint: []\n")

    return root
