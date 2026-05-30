# life-os-app

Automation layer for a personal life operating system. The data layer is a
markdown/YAML file tree (the Life-OS folder); this app reads it, builds a daily
plan, and drives a Telegram bot for real-time check-ins.

**Governing principle:** AI may interpret language. AI may **not** make
scheduling decisions. The scheduling path is fully deterministic and testable;
the Anthropic API is only used for language tasks (`/ai` notes, `/evening`).

Currently run **locally** on Windows. VPS deployment (Ionos) is deferred.

## Components

- `morning.py` — daily briefing: compiles the queue, runs the scheduler, writes
  `daily/README.md`, creates the day's log, and emails the plan.
- `bot.py` — the Telegram bot (persistent long-polling process) plus the
  `--notify` / `--checkin` one-shot senders for block triggers.
- `scheduler/` — the deterministic scheduling package (no AI):
  - `compile_queue.py` — reads the 4 task sources + logs → `schedule/queue.yaml`
    (computes urgency, eligibility, critical-path, lint).
  - `schedule.py` — deterministic placement (fixed anchors → mandatory floors →
    effective-priority fill → carry/surface).
  - `day.py` — shared `daily/README.md` writer + per-day drop/boost state.
  - `tasks_parser.py`, `logs.py`, `urgency.py`, `models.py`, `constants.py`.
- `utils.py` — shared file helpers (thresholds, logs, inbox, ingest).
- `tests/` — pytest suite for the scheduler (`pytest -q`).

## Setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
# create .env (see below) — never committed
```

`.env` keys:

| Key | Purpose |
|-----|---------|
| `LIFE_OS_ROOT` | Absolute path to the Life-OS data folder |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your chat id — the bot ignores all other chats |
| `ANTHROPIC_API_KEY` | Language tasks only (`/ai`, `/evening`) |
| `RESEND_API_KEY` | Email delivery of the morning briefing |
| `EMAIL_FROM`, `EMAIL_TO` | Briefing email addresses |

## Running

### Morning briefing

```powershell
.\venv\Scripts\python.exe morning.py
```

Recompiles `schedule/queue.yaml`, writes `daily/README.md`, creates
`daily/logs/YYYY-MM-DD.md`, and emails the plan. Run it once each morning
(manually or via Windows Task Scheduler).

### The bot

```powershell
.\venv\Scripts\python.exe bot.py
```

Runs long-polling in the foreground until stopped (Ctrl-C). Keep it in an open
terminal or a local process manager. It only responds to `TELEGRAM_CHAT_ID`.

### Block notifications & check-ins

These are one-shot sends, intended to be fired by a scheduler at block times:

```powershell
.\venv\Scripts\python.exe bot.py --notify "Deep Work 1"     # "block starting"
.\venv\Scripts\python.exe bot.py --checkin "Deep Work 1"    # "how did it go?" buttons
```

## Bot commands

| Command | What it does |
|---------|--------------|
| `/plan` | Recompute today, show the blocks (plus any of today's block edits), and attach check-in buttons for the in-progress task block. |
| `/behind` | Running behind — pick a scheduled task to **drop** for today; the day reshuffles. |
| `/add` | Pin a **carried** task into the day; the day reshuffles. |
| `/skip` | Skip a block for today (e.g. lunch). No args → tap-to-pick keyboard; tap again to restore. One-off, resets overnight. |
| `/move <block> <HH:MM-HH:MM>` | Retime a block for today only, e.g. `/move Admin 15:00-17:00`. |
| `/clearday` | Clear today's block edits; back to the standing day shape. |
| `/log [domain] <text>` | Record a completed entry in today's log (retroactive / off-schedule). A leading domain makes it count toward that cadence. |
| `/ai <text>` | Freeform note — Haiku tags the domain and cleans it, then saves to `ingest/`. |
| `/note [domain] <text>` | Save an ingest note; optional leading domain tag. `/note ai ...` is an alias for `/ai`. |
| `/edit inbox <text>` | Append a task to `inbox.md`. |
| `/edit threshold <domain>.<field> <value>` | Update a numeric threshold (e.g. `/edit threshold novel.target 600`). |
| `/domain list` | List the known domains. |
| `/evening <brief>` | Haiku summarizes your evening into the day's log. |
| `/start` | Connectivity check. |

### Check-in buttons

A check-in (from `/plan` or a `--checkin` send) offers **✅ Done**,
**⏩ Partial**, and **🔁 Reschedule**. Tapping one writes a log entry with the
block's `task:` id (so cadence-debt and dependencies resolve) and reshuffles the
remainder of the day. **🔁 Reschedule** also drops the task from today.

## The scheduling model (brief)

`compile()` reads four task sources plus the logs:

- `thresholds.yaml` — recurring per-domain tasks (Type 4).
- `domains/<d>/tasks.md` — authored task records (Type 3).
- `inbox.md` — quick tasks (Type 1; Type 2 if a line carries a `due:` date).
- `daily/logs/` — completion history → urgency + dependency clearing.

Urgency = deadline proximity + cadence-debt (frozen v1 formulas) and can promote
a `normal` task above a `high` one. The scheduler then places at most one task
per fixed-size block from the **day template**.

The day's block skeleton is Cowork-owned, authored in
`<LIFE_OS_ROOT>/schedule/template.yaml`. The loader (`scheduler/day_template.py`)
is resilient for detached runs: **live** source → last-known-good **cache** (in
this app's `cache/`, refreshed on every clean live read) → built-in
`constants.DEFAULT_BLOCKS`. `/skip` and `/move` layer one-off, single-day edits
on top via `schedule/today-state.yaml`; they reset at the next morning rebuild.

See `SYSTEM.md → Scheduling Layer` and `DOMAIN-FORMAT.md §7` in the data tree for
the authoring contract.

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

## Notes

- **Script-owned files** (the only files this app writes): `daily/README.md`,
  `daily/logs/YYYY-MM-DD.md`, `schedule/queue.yaml`, `schedule/today-state.yaml`,
  and bot-writable targets (`ingest/`, `inbox.md` append, `thresholds.yaml`
  value updates). `schedule/template.yaml` is **read** by the app but authored in
  Cowork. Everything else in the data tree belongs to authoring sessions.
- **Secrets** live only in `.env` (git-ignored). Never commit it. `httpx` request
  logging is raised to WARNING so the bot token stays out of logs.
- `schedule/queue.yaml` is a derived store — edit the sources, never the queue.
