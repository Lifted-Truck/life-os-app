"""Data models for the scheduling layer.

`Task` is the uniform normalized record every source (thresholds.yaml, schedule/,
tasks.md, inbox.md) is mapped onto. `urgency` and `eligible` are COMPUTED by
compile() and must never be authored by hand (DOMAIN-FORMAT.md §7.1).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional


@dataclass
class LintIssue:
    """A warning/error surfaced through queue.lint (SYSTEM.md surfacing)."""
    level: str          # "warning" | "error"
    where: str          # source file / record id
    message: str

    def to_dict(self) -> dict:
        return {"level": self.level, "where": self.where, "message": self.message}


@dataclass
class Placement:
    cls: str = "floating"                 # "fixed" | "floating"  (YAML key: class)
    slots: list = field(default_factory=list)
    min_block: Optional[int] = None       # min contiguous minutes
    window: Optional[list] = None         # ["HH:MM", "HH:MM"] or None
    energy: Optional[str] = None          # "high" | "low" | None
    days: list = field(default_factory=list)   # R6: expanded ["mon".."sun"] subset

    def to_dict(self) -> dict:
        d = {"class": self.cls, "slots": list(self.slots)}
        if self.min_block is not None:
            d["min-block"] = self.min_block
        if self.window is not None:
            d["window"] = list(self.window)
        if self.energy is not None:
            d["energy"] = self.energy
        if self.days:
            d["days"] = list(self.days)
        return d


@dataclass
class Task:
    """Uniform normalized task record."""
    id: str
    title: str
    type: int                              # 1 | 2 | 3 | 4
    source: str                            # tasks | thresholds | schedule | inbox
    domain: str = ""
    goal: str = ""
    subtype: Optional[str] = None
    importance: str = "normal"
    duration: Optional[int] = None         # estimated minutes
    target: Optional[float] = None
    unit: Optional[str] = None
    min: Optional[int] = None              # partial-credit + compression floor
    not_before: Optional[date] = None
    depends_on: list = field(default_factory=list)
    waiting: bool = False
    placement: Placement = field(default_factory=Placement)

    # Type 2 (anchored)
    deadline: Optional[date] = None
    deadline_type: Optional[str] = None    # fixed | hard | soft

    # Type 4 (perpetual recurring)
    cadence: Optional[str] = None          # daily | weekly | as-scheduled
    mandatory_weekly: Optional[float] = None

    # --- COMPUTED by compile() (never authored) ---
    urgency: float = 0.0
    eligible: bool = True
    blocked_reason: Optional[str] = None
    mandatory_due: bool = False            # mandatory-weekly floor unmet this week

    def to_queue_dict(self) -> dict:
        """Serialize for schedule/queue.yaml. ISO-format dates, drop empties."""
        d = {
            "id": self.id,
            "title": self.title,
            "type": self.type,
            "source": self.source,
            "domain": self.domain,
            "importance": self.importance,
            "placement": self.placement.to_dict(),
            "waiting": self.waiting,
            # computed
            "urgency": round(self.urgency, 2),
            "eligible": self.eligible,
        }
        if self.goal:
            d["goal"] = self.goal
        if self.subtype:
            d["subtype"] = self.subtype
        if self.duration is not None:
            d["duration"] = self.duration
        if self.target is not None:
            d["target"] = self.target
        if self.unit is not None:
            d["unit"] = self.unit
        if self.min is not None:
            d["min"] = self.min
        if self.not_before is not None:
            d["not-before"] = self.not_before.isoformat()
        if self.depends_on:
            d["depends-on"] = list(self.depends_on)
        if self.deadline is not None:
            d["deadline"] = self.deadline.isoformat()
        if self.deadline_type is not None:
            d["deadline-type"] = self.deadline_type
        if self.cadence is not None:
            d["cadence"] = self.cadence
        if self.mandatory_weekly is not None:
            d["mandatory-weekly"] = self.mandatory_weekly
        if self.blocked_reason:
            d["blocked-reason"] = self.blocked_reason
        if self.mandatory_due:
            d["mandatory-due"] = True
        return d

    def effective_priority(self, importance_weight: dict) -> float:
        """Base importance weight modulated by computed urgency."""
        return importance_weight.get(self.importance, 0) + self.urgency

    @classmethod
    def from_queue_dict(cls, d: dict) -> "Task":
        """Reconstruct a Task from a schedule/queue.yaml record (round-trip)."""
        def _d(key):
            v = d.get(key)
            if not v:
                return None
            if isinstance(v, date):
                return v
            return datetime.strptime(str(v), "%Y-%m-%d").date()

        pl = d.get("placement") or {}
        placement = Placement(
            cls=pl.get("class", "floating"),
            slots=list(pl.get("slots") or []),
            min_block=pl.get("min-block"),
            window=pl.get("window"),
            energy=pl.get("energy"),
            days=list(pl.get("days") or []),
        )
        return cls(
            id=d["id"],
            title=d.get("title", d["id"]),
            type=int(d.get("type", 3)),
            source=d.get("source", "tasks"),
            domain=d.get("domain", ""),
            goal=d.get("goal", ""),
            subtype=d.get("subtype"),
            importance=d.get("importance", "normal"),
            duration=d.get("duration"),
            target=d.get("target"),
            unit=d.get("unit"),
            min=d.get("min"),
            not_before=_d("not-before"),
            depends_on=list(d.get("depends-on") or []),
            waiting=bool(d.get("waiting", False)),
            placement=placement,
            deadline=_d("deadline"),
            deadline_type=d.get("deadline-type"),
            cadence=d.get("cadence"),
            mandatory_weekly=d.get("mandatory-weekly"),
            urgency=float(d.get("urgency", 0.0)),
            eligible=bool(d.get("eligible", True)),
            blocked_reason=d.get("blocked-reason"),
            mandatory_due=bool(d.get("mandatory-due", False)),
        )
