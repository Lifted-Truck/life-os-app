"""Load the day's block template, with resilience for running detached.

Source of truth: ``<LIFE_OS_ROOT>/schedule/template.yaml`` — authored by Cowork.
This is the *structure* layer (the block skeleton); the scheduler reads it so a
day-shape redesign done in Cowork flows to the bot without a code change.

Because the bot may run where the Cowork data tree is not reachable (not yet
synced, file missing or corrupt), this loader is defensive. The fallback chain:

    1. live   — <LIFE_OS_ROOT>/schedule/template.yaml (and refresh the cache)
    2. cache  — a last-known-good copy kept in the app's own directory
    3. default— the built-in constants.DEFAULT_BLOCKS

Whenever the live source parses cleanly it is mirrored to the cache, so a later
detached run uses the most recent good structure rather than the built-in.

template.yaml format::

    blocks:
      - name: Morning Pages & Coffee
        start: "07:00"
        end:   "08:00"
        slot:  null            # null/blank = fixed block, never scheduled into
      - name: Deep Work 1
        start: "08:00"
        end:   "10:00"
        slot:  deep-work       # must be one of constants.SLOT_VOCAB
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from .constants import DEFAULT_BLOCKS, SLOT_VOCAB

logger = logging.getLogger(__name__)

# The app directory (where bot.py / morning.py live) — distinct from the Cowork
# data tree, so the cache survives running without LIFE_OS_ROOT mounted.
APP_DIR = Path(__file__).resolve().parent.parent
CACHE_PATH = APP_DIR / "cache" / "day_template.yaml"
SOURCE_REL = Path("schedule") / "template.yaml"

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _coerce_hhmm(val, field: str, name: str) -> str:
    """Normalise a block time to an 'HH:MM' string.

    YAML 1.1 parses an unquoted time like ``11:00`` as a sexagesimal *integer*
    (660), so a hand-edited template that forgets quotes would otherwise break.
    Accept both the string form and that minutes-from-midnight int form.
    """
    if isinstance(val, str) and _HHMM_RE.match(val):
        return val
    if isinstance(val, int) and 0 <= val < 24 * 60:
        return f"{val // 60:02d}:{val % 60:02d}"
    raise ValueError(f"block {name!r} {field} must be HH:MM 24h (got {val!r})")


def parse_blocks(data) -> list[dict]:
    """Validate a parsed template document into a list of block dicts.

    Raises ValueError on anything malformed so the caller can fall back. Blocks
    are returned sorted by start time. Slot is normalised to None for fixed
    (non-schedulable) blocks.
    """
    if not isinstance(data, dict) or "blocks" not in data:
        raise ValueError("template must have a top-level 'blocks' list")
    raw = data["blocks"]
    if not isinstance(raw, list) or not raw:
        raise ValueError("'blocks' must be a non-empty list")

    blocks: list[dict] = []
    for i, b in enumerate(raw):
        if not isinstance(b, dict):
            raise ValueError(f"block {i} is not a mapping")
        name = b.get("name")
        if not name or not isinstance(name, str):
            raise ValueError(f"block {i} is missing a name")
        start = _coerce_hhmm(b.get("start"), "start", name)
        end = _coerce_hhmm(b.get("end"), "end", name)
        slot = b.get("slot")
        if end <= start:
            raise ValueError(f"block {name!r} end must be after start")
        if slot in ("", None):
            slot = None
        elif slot not in SLOT_VOCAB:
            raise ValueError(
                f"block {name!r} has unknown slot {slot!r} "
                f"(allowed: {', '.join(SLOT_VOCAB)})"
            )
        immutable = bool(b.get("immutable", False))   # R5 — default false
        blocks.append({
            "name": name, "start": start, "end": end,
            "slot": slot, "immutable": immutable,
        })

    blocks.sort(key=lambda x: x["start"])
    return blocks


def _write_cache(blocks: list[dict], cache_path: Path) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            yaml.safe_dump({"blocks": blocks}, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    except OSError as e:  # caching is best-effort; never fail the day over it
        logger.warning("day template: could not refresh cache (%s)", e)


def load_day_template(root, *, cache_path: Path = CACHE_PATH) -> tuple[list[dict], str]:
    """Return (blocks, source) where source is 'live' | 'cache' | 'default'."""
    src = Path(root) / SOURCE_REL

    # 1. live source of truth
    try:
        if src.is_file():
            blocks = parse_blocks(yaml.safe_load(src.read_text(encoding="utf-8")))
            _write_cache(blocks, cache_path)
            return blocks, "live"
    except (OSError, yaml.YAMLError, ValueError) as e:
        logger.warning(
            "day template: live source unusable (%s); falling back to cache", e)

    # 2. last-known-good cache in app infrastructure
    try:
        if cache_path.is_file():
            blocks = parse_blocks(yaml.safe_load(cache_path.read_text(encoding="utf-8")))
            logger.info("day template: using cached structure (live source absent)")
            return blocks, "cache"
    except (OSError, yaml.YAMLError, ValueError) as e:
        logger.warning(
            "day template: cache unusable (%s); using built-in default", e)

    # 3. built-in default (copy so callers can't mutate the constant)
    return [dict(b) for b in DEFAULT_BLOCKS], "default"
