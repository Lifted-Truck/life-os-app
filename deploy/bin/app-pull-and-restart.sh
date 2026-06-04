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
#   - deploy/systemd/*.service and *.timer (install + daemon-reload — bot
#     and dashboard pick up new config via their restart at the end;
#     timers re-read on next fire; the app-pull unit itself updates for
#     the *next* run, not this one)
#   - deploy/bin/*.sh (no install needed — units invoke them by path,
#     fresh each time)
#
# What still needs manual `bash deploy/install-services.sh`:
#   - deploy/Caddyfile (needs sed-render against $DOMAIN + caddy reload)
#   - deploy/install-services.sh (the installer itself)
# Done intentionally — these are infra-shape changes, not unit-content.

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

# 5. Auto-install changed systemd unit files. We install ANY .service or
# .timer file under deploy/systemd/ that the diff names — robust to new
# units added later. Don't restart oneshot services / timers explicitly;
# next fire picks up the new config. Bot + dashboard get restarted in
# step 6 below, which applies any new config to them.
#
# diff-filter=AM ensures we only try to install files that ACTUALLY EXIST
# in the new tree (Added or Modified) — `git diff --name-only` without a
# filter would also list Deleted files, and `install` would fail trying
# to read a missing source. Retired units need explicit cleanup via
# `bash deploy/install-services.sh` (which disables + removes them).
SYSTEMD_CHANGED=$(git diff --name-only --diff-filter=AM "$LOCAL..$REMOTE" | grep -E '^deploy/systemd/.*\.(service|timer)$' || true)
if [[ -n "$SYSTEMD_CHANGED" ]]; then
    echo "installing changed systemd units..."
    while IFS= read -r f; do
        [[ -z "$f" ]] && continue
        echo "  $f"
        sudo /usr/bin/install -m 0644 "$f" /etc/systemd/system/ || {
            echo "install failed for $f" >&2
            exit 1
        }
    done <<< "$SYSTEMD_CHANGED"
    sudo /bin/systemctl daemon-reload
fi

# 6. Restart code-bearing services. Both are quick (~2-3s).
echo "restarting life-os-bot and life-os-dashboard..."
sudo /bin/systemctl restart life-os-bot life-os-dashboard

# 7. Flag any deploy/ file changes that genuinely need a manual install
# run (Caddyfile needs sed-render + caddy reload; install-services.sh is
# the installer script itself).
if echo "$CHANGED" | grep -qE '^deploy/(Caddyfile|install-services\.sh)$'; then
    echo "NOTE: deploy/Caddyfile or install-services.sh changed —" >&2
    echo "      Re-run: ssh life@<host> 'cd ~/app && bash deploy/install-services.sh'" >&2
fi

echo "auto-deploy: done"
