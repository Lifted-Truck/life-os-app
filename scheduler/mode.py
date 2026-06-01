"""Plan mode + Haiku-phrasing flag, persisted in `schedule/mode.yaml`.

The week-long logging experiment swaps the default `blocks` plan (timed
schedule) for `goals` (flat untimed list, reminders only for fixed life-
skeleton anchors and anchored /add events). The deterministic block
scheduler stays intact — flipping back requires no code change, just
`/mode blocks`.

`haiku_phrasing` is opt-in. When true, the goals-output renderer hands the
deterministic goal list to Haiku for a single wording pass — selection,
order, and reminder times stay deterministic (governing principle:
"AI may interpret language. AI may not make scheduling decisions.").
"""
from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_MODE: dict = {
    "plan_mode": "blocks",       # "blocks" | "goals"
    "haiku_phrasing": False,
}

VALID_PLAN_MODES = ("blocks", "goals")


def _mode_path(root) -> Path:
    return Path(root) / "schedule" / "mode.yaml"


def load_mode(root) -> dict:
    """Return today's mode config, falling back to defaults if file is absent/bad."""
    p = _mode_path(root)
    if not p.exists():
        return dict(DEFAULT_MODE)
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return dict(DEFAULT_MODE)
    merged = dict(DEFAULT_MODE)
    if isinstance(data, dict):
        if data.get("plan_mode") in VALID_PLAN_MODES:
            merged["plan_mode"] = data["plan_mode"]
        if isinstance(data.get("haiku_phrasing"), bool):
            merged["haiku_phrasing"] = data["haiku_phrasing"]
    return merged


def save_mode(root, mode: dict) -> None:
    """Persist mode config. Only known keys with valid values are written."""
    p = _mode_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    safe = dict(DEFAULT_MODE)
    if mode.get("plan_mode") in VALID_PLAN_MODES:
        safe["plan_mode"] = mode["plan_mode"]
    if isinstance(mode.get("haiku_phrasing"), bool):
        safe["haiku_phrasing"] = mode["haiku_phrasing"]
    p.write_text(yaml.safe_dump(safe, sort_keys=False), encoding="utf-8")


def set_plan_mode(root, plan_mode: str) -> dict:
    if plan_mode not in VALID_PLAN_MODES:
        raise ValueError(f"plan_mode must be one of {VALID_PLAN_MODES}")
    current = load_mode(root)
    current["plan_mode"] = plan_mode
    save_mode(root, current)
    return current


def set_haiku_phrasing(root, enabled: bool) -> dict:
    current = load_mode(root)
    current["haiku_phrasing"] = bool(enabled)
    save_mode(root, current)
    return current
