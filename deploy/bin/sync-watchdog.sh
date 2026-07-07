#!/usr/bin/env bash
#
# sync-watchdog.sh — alert when the data-tree sync has gone SILENT.
#
# life-os-sync.service's own OnFailure= catches a sync that RUNS and FAILS
# (rebase conflict, push error). It cannot catch a sync that stops running
# at all — a disabled/dead timer, a wedged VPS — because nothing runs, so
# nothing fails, so no OnFailure fires. That silent death is exactly how a
# write can reach the VPS and never make it to GitHub, invisibly (see the
# 2026-07-06 review-capture incident).
#
# This watchdog runs on its own timer and exits non-zero when the last
# successful-sync heartbeat is older than MAX_AGE, so ITS OnFailure= fires
# the standard Telegram alert.
set -uo pipefail

HEARTBEAT="${HEARTBEAT:-$HOME/.cache/life-os/last-sync}"
MAX_AGE="${MAX_AGE:-1200}"          # 20 min — sync runs every 5, so ~4 missed

now=$(date +%s)

if [[ ! -f "$HEARTBEAT" ]]; then
    echo "sync-watchdog: no heartbeat at $HEARTBEAT — sync has never completed" >&2
    exit 1
fi

last=$(cat "$HEARTBEAT" 2>/dev/null || echo 0)
age=$(( now - last ))

if (( age > MAX_AGE )); then
    echo "sync-watchdog: data-tree sync STALE — last success ${age}s ago (> ${MAX_AGE}s)." >&2
    echo "  Check: systemctl status life-os-sync.timer; journalctl -u life-os-sync -n 40" >&2
    exit 1
fi

echo "sync-watchdog: ok — last sync ${age}s ago"
