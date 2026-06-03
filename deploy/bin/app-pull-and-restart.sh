#!/usr/bin/env bash
#
# app-pull-and-restart.sh — auto-deploy life-os-app on push.
#
# Polled by life-os-app-pull.timer (1-min cadence). Fast-forward pulls
# master, reinstalls Python deps when requirements.txt changed, and
# restarts the bot + dashboard. No-op exit 0 when nothing's new.
#
# What this AUTO-handles:
#   - Python code (any file restarting bot/dashboard will pick up)
#   - requirements.txt (pip install + restart)
#   - dashboard/ assets
#
# What still needs manual `bash deploy/install-services.sh`:
#   - deploy/systemd/*  (unit files — needs daemon-reload + service install)
#   - deploy/Caddyfile  (needs Caddy reload)
#   - deploy/install-services.sh (the installer itself)
# Done intentionally so infrastructure changes require explicit attention.

set -uo pipefail

APP_DIR="${APP_DIR:-/home/life/app}"
BRANCH="${BRANCH:-master}"

cd "$APP_DIR"

# 1. Check upstream
git fetch --quiet origin "$BRANCH" 2>&1 || {
    echo "fetch failed" >&2
    exit 1
}
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [[ "$LOCAL" == "$REMOTE" ]]; then
    exit 0   # no change, quiet
fi

# 2. What changed?
CHANGED=$(git diff --name-only "$LOCAL..$REMOTE")
echo "auto-deploy: ${LOCAL:0:8} -> ${REMOTE:0:8}"
echo "$CHANGED" | sed 's/^/  /'

# 3. Pull (ff-only — if anything's diverged on the VPS, bail loudly)
git pull --ff-only --quiet origin "$BRANCH" || {
    echo "git pull --ff-only failed — local has diverged from origin" >&2
    exit 1
}

# 4. Reinstall deps only when requirements.txt changed (~30s saved otherwise)
if echo "$CHANGED" | grep -qx 'requirements.txt'; then
    echo "requirements.txt changed; reinstalling..."
    ./venv/bin/pip install -r requirements.txt --quiet || {
        echo "pip install failed" >&2
        exit 1
    }
fi

# 5. Restart code-bearing services. Both are quick (~2-3s).
echo "restarting life-os-bot and life-os-dashboard..."
sudo /bin/systemctl restart life-os-bot life-os-dashboard

# 6. Flag any deploy/ file changes that need a manual install run.
if echo "$CHANGED" | grep -qE '^deploy/(systemd/|Caddyfile|install-services\.sh)'; then
    echo "NOTE: deploy/ changed — infrastructure update needed:" >&2
    echo "      ssh life@<host> 'cd ~/app && bash deploy/install-services.sh'" >&2
fi

echo "auto-deploy: done"
