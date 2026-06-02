#!/usr/bin/env bash
#
# bootstrap.sh — first-time VPS bootstrap (Ubuntu 24.04).
#
# Run ONCE as root, immediately after your first SSH into a fresh Ionos VPS.
# Idempotent: re-running won't undo prior state, but won't break either.
#
# Usage:
#   ssh root@<vps-ip>
#   curl -fsSL https://raw.githubusercontent.com/Lifted-Truck/life-os-app/master/deploy/bootstrap.sh | PUBKEY="$(cat)" bash
# OR (offline copy, preferred — gives you a chance to review before running):
#   scp deploy/bootstrap.sh root@<vps-ip>:/root/
#   ssh root@<vps-ip>
#   PUBKEY="ssh-ed25519 AAAA... you@host" bash /root/bootstrap.sh
#
# Required env: PUBKEY = the OpenSSH-format public key from your Windows machine.
# Without it the script aborts before disabling password login (so you don't
# accidentally lock yourself out).
#
# What this does, in order:
#   1. apt update + upgrade
#   2. Install Python 3.12 venv, git, ufw, fail2ban, Caddy (official repo)
#   3. Create non-root user `life` with sudo + your SSH key
#   4. Harden sshd (no root login, no password auth)
#   5. Enable ufw (allow 22, 80, 443)
#   6. Enable + start fail2ban
#
# What this DOES NOT do (deliberate — your action, see deploy/README.md):
#   - Clone the app repo or the data tree (need your GitHub deploy key)
#   - Populate .env (contains secrets)
#   - Install systemd units (covered by deploy/install-services.sh)

set -euo pipefail

DEPLOY_USER="life"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root: sudo bash $0" >&2
    exit 1
fi

if [[ -z "${PUBKEY:-}" ]]; then
    cat >&2 <<EOF
Refusing to run without PUBKEY set — you'd lock yourself out.

From your Windows machine:
    Get-Content \$env:USERPROFILE\\.ssh\\id_ed25519.pub

Copy the single-line output, then:
    PUBKEY="<paste here>" bash $0
EOF
    exit 1
fi

echo "==> [1/7] Updating package index..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y

echo "==> [2/7] Installing system packages..."
apt-get install -y \
    python3.12 python3.12-venv python3-pip \
    git curl ca-certificates \
    ufw fail2ban \
    debian-keyring debian-archive-keyring apt-transport-https gnupg

echo "==> [3/7] Installing Caddy (official repo)..."
if ! command -v caddy >/dev/null; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y
    apt-get install -y caddy
fi

echo "==> [4/7] Creating deploy user '${DEPLOY_USER}'..."
if ! id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "${DEPLOY_USER}"
fi
usermod -aG sudo "${DEPLOY_USER}"
# The deploy user is created with --disabled-password, so the default
# %sudo policy (prompts for the user's own password) is unusable. Grant
# passwordless sudo on this single-tenant VPS so install-services.sh and
# Day-2 ops (deploy/restart) work non-interactively. Tighten if this VPS
# ever stops being single-tenant.
cat > /etc/sudoers.d/life-passwordless <<'EOF'
life ALL=(ALL) NOPASSWD:ALL
EOF
chmod 0440 /etc/sudoers.d/life-passwordless

echo "==> [5/7] Installing your SSH key for ${DEPLOY_USER}..."
mkdir -p "/home/${DEPLOY_USER}/.ssh"
echo "${PUBKEY}" > "/home/${DEPLOY_USER}/.ssh/authorized_keys"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "/home/${DEPLOY_USER}/.ssh"
chmod 700 "/home/${DEPLOY_USER}/.ssh"
chmod 600 "/home/${DEPLOY_USER}/.ssh/authorized_keys"

echo "==> [6/7] Hardening sshd..."
sed -i \
    -e 's/^#\?PermitRootLogin.*/PermitRootLogin no/' \
    -e 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' \
    -e 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' \
    /etc/ssh/sshd_config
systemctl reload ssh || systemctl reload sshd

echo "==> [7/7] Firewall (ufw) + fail2ban..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

systemctl enable --now fail2ban

cat <<EOF

============================================================
Bootstrap complete.

Next steps (from your Windows machine, NOT this root shell):

  1. Open a NEW SSH session as the deploy user:
       ssh life@$(hostname -I | awk '{print $1}')

  2. Verify it works (you should NOT be prompted for a password).

  3. Once you're logged in as 'life', exit this root shell and
     continue with deploy/README.md → "Phase 2: Application setup".

DO NOT close this root session until you've verified life@ access.
If you lock yourself out you can recover via the Ionos web console.
============================================================
EOF
