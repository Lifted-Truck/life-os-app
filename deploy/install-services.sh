#!/usr/bin/env bash
#
# install-services.sh — install + enable the systemd units for Life-OS.
#
# Run as the 'life' user (uses sudo for the install steps) AFTER:
#   * deploy/bootstrap.sh has run (Caddy, Python, ufw installed)
#   * The app repo is cloned at /home/life/app
#   * The data tree repo is cloned at /home/life/data
#   * .env is populated at /home/life/app/.env
#   * venv is created at /home/life/app/venv
#
# Idempotent.

set -euo pipefail

APP_DIR="${APP_DIR:-/home/life/app}"
DEPLOY_DIR="${APP_DIR}/deploy"
DOMAIN="${DOMAIN:-mindlathe.xyz}"

if [[ "${USER}" != "life" ]]; then
    echo "Run as user 'life', not '${USER}'" >&2
    exit 1
fi

if [[ ! -d "${APP_DIR}" ]]; then
    echo "App not found at ${APP_DIR} — clone the repo first." >&2
    exit 1
fi

if [[ ! -f "${APP_DIR}/.env" ]]; then
    echo "Missing ${APP_DIR}/.env — populate it before installing services." >&2
    exit 1
fi

echo "==> Copying systemd units to /etc/systemd/system..."
sudo install -m 0644 "${DEPLOY_DIR}/systemd/life-os-bot.service"        /etc/systemd/system/
sudo install -m 0644 "${DEPLOY_DIR}/systemd/life-os-dashboard.service"  /etc/systemd/system/
sudo install -m 0644 "${DEPLOY_DIR}/systemd/life-os-morning.service"    /etc/systemd/system/
sudo install -m 0644 "${DEPLOY_DIR}/systemd/life-os-morning.timer"      /etc/systemd/system/
sudo install -m 0644 "${DEPLOY_DIR}/systemd/life-os-pull.service"       /etc/systemd/system/
sudo install -m 0644 "${DEPLOY_DIR}/systemd/life-os-pull.timer"         /etc/systemd/system/
sudo install -m 0644 "${DEPLOY_DIR}/systemd/life-os-push.service"       /etc/systemd/system/
sudo install -m 0644 "${DEPLOY_DIR}/systemd/life-os-push.timer"         /etc/systemd/system/

echo "==> Installing Caddyfile for ${DOMAIN}..."
# Render the Caddyfile template by substituting the domain.
sudo bash -c "sed 's/__DOMAIN__/${DOMAIN}/g' '${DEPLOY_DIR}/Caddyfile' > /etc/caddy/Caddyfile"

echo "==> Reloading systemd + Caddy..."
sudo systemctl daemon-reload
sudo systemctl reload caddy

echo "==> Enabling + starting services..."
sudo systemctl enable --now life-os-pull.timer
sudo systemctl enable --now life-os-push.timer
sudo systemctl enable --now life-os-morning.timer
sudo systemctl enable --now life-os-dashboard.service
sudo systemctl enable --now life-os-bot.service

echo
echo "==> Done. Verify with:"
echo "    systemctl status life-os-bot life-os-dashboard"
echo "    journalctl -u life-os-bot -f"
echo "    curl -s https://${DOMAIN}/health"
