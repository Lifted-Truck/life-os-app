"""Canonical, root-based readers for the domain layer.

One source of truth for *what domains exist* and the parsed `thresholds.yaml`,
shared by the dashboard and the metrics layer (and available to anything else
that has a data-tree root). `utils.read_thresholds()` is the env-based
convenience that mirrors `read_thresholds(root)` for the bot.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def read_thresholds(root) -> dict:
    """Parsed `thresholds.yaml` for the tree at `root` ({} if absent/unparseable)."""
    try:
        return yaml.safe_load(
            (Path(root) / "thresholds.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def list_domains(root) -> list:
    """Canonical sorted domain list: thresholds keys (minus `config`) ∪ the
    `domains/` subfolders. This is the single definition of 'a domain exists'."""
    names = {k for k in read_thresholds(root) if k != "config"}
    ddir = Path(root) / "domains"
    if ddir.is_dir():
        names |= {p.name for p in ddir.iterdir() if p.is_dir()}
    return sorted(names)
