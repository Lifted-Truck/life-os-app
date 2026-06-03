#!/usr/bin/env bash
#
# notify-failure.sh — send a Telegram message describing a failed systemd unit.
#
# Called by `notify-failure@<unit>.service` (a template instantiated when any
# of our life-os-* services hit OnFailure=). The instance name (e.g.,
# "life-os-bot.service") is passed as $1.
#
# Reuses the bot's existing TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID from
# /home/life/app/.env — no separate credentials. Sends as plain text so the
# journal tail can contain arbitrary characters without breaking Markdown
# parse.
#
# Designed to be quiet on its OWN failure (no OnFailure on this unit) so a
# Telegram outage can't cascade into a notification storm.

set -uo pipefail   # NOT -e: we want to limp through soft errors and exit 0.

UNIT="${1:-unknown}"
ENV_FILE="${ENV_FILE:-/home/life/app/.env}"

# Pull the bot's token + chat id out of the env file. We don't `source` it
# because .env may have shell-incompatible values; pluck the two keys we need.
TELEGRAM_BOT_TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" 2>/dev/null \
    | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
TELEGRAM_CHAT_ID=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" 2>/dev/null \
    | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")

if [[ -z "${TELEGRAM_BOT_TOKEN}" || -z "${TELEGRAM_CHAT_ID}" ]]; then
    echo "notify-failure: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in $ENV_FILE" >&2
    exit 0    # don't loop OnFailure
fi

# Best-effort journal tail. Capped so a runaway log doesn't blow Telegram's
# 4096-char message limit. journalctl needs root or adm/systemd-journal
# group — the template runs as root for this reason.
TAIL=$(journalctl -u "$UNIT" -n 12 --no-pager -o cat 2>/dev/null | tail -c 2500 || true)
if [[ -z "$TAIL" ]]; then
    TAIL="(no recent journal entries — check 'journalctl -u $UNIT' manually)"
fi

HOST=$(hostname -s 2>/dev/null || echo "vps")
TS=$(date -u +'%Y-%m-%dT%H:%M:%SZ')

TEXT="🚨 ${UNIT} failed
host: ${HOST}
when: ${TS}

last log lines:
${TAIL}"

# Best-effort POST. Silent on success, brief stderr on failure.
curl -sS --max-time 10 \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${TEXT}" \
    -o /dev/null \
    || echo "notify-failure: Telegram POST failed (network or API)" >&2

exit 0
