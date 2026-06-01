"""Tests for /add's anchored-event parser.

The full /add flow (inbox append + APScheduler add_job) is exercised
manually; here we pin down the forgiving time/date parsers and the
inbox-line format.
"""
from datetime import date

import bot


# --- time parser ------------------------------------------------------------

def test_parse_24h():
    assert bot._parse_event_time("@15:00") == "15:00"
    assert bot._parse_event_time("@09:30") == "09:30"


def test_parse_pm():
    assert bot._parse_event_time("@3pm") == "15:00"
    assert bot._parse_event_time("@7pm") == "19:00"
    assert bot._parse_event_time("@9:30pm") == "21:30"


def test_parse_am():
    assert bot._parse_event_time("@9am") == "09:00"
    assert bot._parse_event_time("@7:15am") == "07:15"
    assert bot._parse_event_time("@12am") == "00:00"   # midnight
    assert bot._parse_event_time("@12pm") == "12:00"   # noon


def test_parse_bare_hour_24h():
    """`@9` with no am/pm = 09:00 (24-hour convention)."""
    assert bot._parse_event_time("@9") == "09:00"
    assert bot._parse_event_time("@17") == "17:00"


def test_parse_rejects_garbage():
    assert bot._parse_event_time("3pm") is None      # missing @
    assert bot._parse_event_time("@25:00") is None
    assert bot._parse_event_time("@9:75") is None
    assert bot._parse_event_time("@nope") is None


# --- date parser ------------------------------------------------------------

TODAY = date(2026, 5, 31)


def test_parse_short_date_uses_current_year():
    assert bot._parse_event_date("6/15", TODAY) == date(2026, 6, 15)


def test_parse_two_digit_year_expands_to_20xx():
    assert bot._parse_event_date("6/15/27", TODAY) == date(2027, 6, 15)


def test_parse_full_year():
    assert bot._parse_event_date("6/15/2027", TODAY) == date(2027, 6, 15)


def test_parse_rejects_invalid():
    assert bot._parse_event_date("nope", TODAY) is None
    assert bot._parse_event_date("13/40", TODAY) is None
    assert bot._parse_event_date("6/15/27/extra", TODAY) is None


# --- inbox line format ------------------------------------------------------

def test_event_line_matches_cowork_spec():
    line = bot._format_event_inbox_line("Dentist", date(2026, 6, 15), "15:00")
    # Cowork's inbox.md header documents `due: fixed mm/dd` and `at: HH:MM`
    assert line == "Dentist | due: fixed 6/15 | at: 15:00"
