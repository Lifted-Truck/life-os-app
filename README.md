# life-os-app

Automation layer for a personal life operating system. Runs on a Linux VPS.

## Components

- `morning.py` — daily briefing script, cron-triggered
- `bot.py` — Telegram bot, persistent systemd service
- `utils.py` — shared file helpers

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in .env with your keys
```

## Structure

```
life-os-app/
  morning.py
  bot.py
  utils.py
  .env              # never committed
  .env.example
  requirements.txt
  systemd/
    life-os-bot.service
  cron/
    crontab.example
```
