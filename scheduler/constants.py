"""Controlled vocabularies, weights, and the canonical day structure.

These mirror DOMAIN-FORMAT.md §7.3 and schedule/template.md. The Slot Vocabulary
is *controlled*: changing it is a schema change (SYSTEM.md Schema Change Protocol),
so it lives here in one place and is referenced everywhere.
"""

# --- Controlled vocabularies (DOMAIN-FORMAT.md §7) -------------------------

IMPORTANCE_TIERS = ("critical", "high", "normal", "low")

# placement.slots values (kept in sync with schedule/template.md Slot Vocabulary)
SLOT_VOCAB = ("deep-work", "practice-creative", "admin", "exercise", "wind-down")

VALID_TYPES = (1, 2, 3, 4)

# subtype is only meaningful for Type 3
TYPE3_SUBTYPES = ("sequential", "session-based", "project")

VALID_UNITS = ("minutes", "words", "pages", "sessions")

PLACEMENT_CLASSES = ("fixed", "floating")

DEADLINE_TYPES = ("fixed", "hard", "soft")

# --- Priority model --------------------------------------------------------
# effective priority = importance base weight + computed urgency.
# Tiers are spaced 100 apart so accumulated urgency (cadence-debt / deadline
# proximity, each bounded ~0-120) can promote a task across one tier — the
# intended behaviour per DOMAIN-FORMAT.md §7.2.

IMPORTANCE_WEIGHT = {
    "critical": 400,
    "high": 300,
    "normal": 200,
    "low": 100,
}

# Urgency tuning (frozen for v1). All deterministic, no AI.
DEADLINE_URGENCY_AT_DUE = 100.0     # urgency when a deadline is today
DEADLINE_OVERDUE_PER_DAY = 10.0     # added per day a deadline is overdue
DEADLINE_URGENCY_CAP = 150.0
SOFT_DEADLINE_FACTOR = 0.5          # soft deadlines pull less than hard/fixed

CADENCE_URGENCY_PER_CYCLE = 50.0    # urgency per cadence-cycle of debt
CADENCE_OVERDUE_CYCLE_CAP = 3.0     # never accrue beyond this many cycles
MANDATORY_WEEKLY_BOOST = 80.0       # extra urgency for an unmet mandatory-weekly floor

CADENCE_DAYS = {
    "daily": 1,
    "weekly": 7,
    "as-scheduled": None,           # no cadence-debt
}

# --- Canonical day structure (FALLBACK ONLY) -------------------------------
# The live day structure is authored in <LIFE_OS_ROOT>/schedule/template.yaml and
# loaded by scheduler.day_template. DEFAULT_BLOCKS is the built-in fallback used
# only when neither that file nor the app's last-known-good cache is available.
# Keep it as a sensible standalone day. Each block: name, start "HH:MM",
# end "HH:MM", slot tag (None = not schedulable). Slot-bearing blocks receive tasks.

# Morning Pages is a fixed daily ritual (slot None = the engine never schedules
# a task into it). Two practice-creative blocks exist because the creative
# domains carry two mandatory-due recurring tasks (music-practice daily +
# production weekly) that cannot share a single one-task-per-block slot.
DEFAULT_BLOCKS = [
    {"name": "Morning Pages & Coffee", "start": "07:00", "end": "08:00", "slot": None},
    {"name": "Deep Work 1", "start": "08:00", "end": "10:00", "slot": "deep-work"},
    {"name": "Break", "start": "10:00", "end": "10:30", "slot": None},
    {"name": "Deep Work 2", "start": "10:30", "end": "12:30", "slot": "deep-work"},
    {"name": "Lunch", "start": "12:30", "end": "13:30", "slot": None},
    {"name": "Practice / Creative 1", "start": "13:30", "end": "15:00", "slot": "practice-creative"},
    {"name": "Admin / Career", "start": "15:00", "end": "16:30", "slot": "admin"},
    {"name": "Exercise", "start": "16:30", "end": "18:00", "slot": "exercise"},
    {"name": "Practice / Creative 2", "start": "18:00", "end": "19:30", "slot": "practice-creative"},
    {"name": "Evening Wind-Down", "start": "20:00", "end": "21:00", "slot": "wind-down"},
    {"name": "Evening Review", "start": "21:00", "end": "21:30", "slot": None},
]
