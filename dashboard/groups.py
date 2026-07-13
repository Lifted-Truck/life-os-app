"""Domain umbrellas — PRESENTATION ONLY (grouped hub display).

Reads `dev/domain-groups.yaml` from the data tree and partitions the flat domain
rows into umbrella groups for the hub. The scheduler ignores this entirely;
domains stay flat (see dev/plans/domain-hierarchy.md — "canonical at the boundary,
presentation at the edge"). Tolerant by construction: a missing or malformed file
yields a single "All domains" group, so the hub degrades to the flat list rather
than breaking.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_FALLBACK = [{"key": "all", "label": "All domains", "domains": None}]


def load_umbrellas(root: Path) -> list[dict]:
    """The umbrella definitions, or a single catch-all group if unavailable."""
    p = root / "dev" / "domain-groups.yaml"
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return _FALLBACK
    raw = data.get("umbrellas")
    if not isinstance(raw, list):
        return _FALLBACK
    out = []
    for u in raw:
        if isinstance(u, dict) and u.get("label") and isinstance(u.get("domains"), list):
            out.append({"key": u.get("key") or u["label"], "label": u["label"],
                        "domains": [str(d) for d in u["domains"]]})
    return out or _FALLBACK


def group_rows(rows: list[dict], key: str, root: Path) -> list[dict]:
    """Partition `rows` into umbrella groups → [{label, rows}].

    `key` names the domain field on each row (e.g. "name" or "domain"). Groups
    follow the umbrella file's declared order; a domain not in any umbrella lands
    in a trailing "Other" group so nothing is ever silently dropped.
    """
    umbrellas = load_umbrellas(root)
    by_domain = {r[key]: r for r in rows}
    seen: set = set()
    groups: list[dict] = []
    for u in umbrellas:
        doms = u["domains"] if u["domains"] is not None else [r[key] for r in rows]
        grp = [by_domain[d] for d in doms if d in by_domain]
        seen.update(d for d in doms if d in by_domain)
        if grp:
            groups.append({"label": u["label"], "rows": grp})
    leftover = [r for r in rows if r[key] not in seen]
    if leftover:
        groups.append({"label": "Other", "rows": leftover})
    return groups
