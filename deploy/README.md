# Deploying Life-OS to the Ionos VPS

End-to-end runbook for first-time deployment of the bot + dashboard to a
fresh Ionos Ubuntu 24.04 VPS.

| | Value |
|---|---|
| Domain | `mindlathe.xyz` |
| VPS IPv4 | `162.222.206.53` |
| OS | Ubuntu 24.04 LTS |
| App repo | `https://github.com/Lifted-Truck/life-os-app` |
| Data tree | Private GitHub repo (to be created — see Phase 3) |
| Web stack | Caddy → uvicorn (FastAPI) on `127.0.0.1:8000` |
| Bot transport | Telegram long-poll (outbound only — no inbound port required) |

The sequence is **six phases**. Each phase ends with a verification step;
don't move on until it passes.

> Phases 1–2 touch your Windows machine + the Ionos panel.
> Phases 3–6 are all on the VPS, as the `life` user.

---

## Phase 1 — SSH keygen on Windows

Open **PowerShell** (not WSL — keep the key on Windows so RDP/Explorer can
manage it):

```powershell
ssh-keygen -t ed25519 -C "sport@mindlathe.xyz"
```

Accept the default path (`C:\Users\sport\.ssh\id_ed25519`). Set a
passphrase if you want — ssh-agent will cache it.

Print the public key (you'll paste this into the bootstrap script):

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
```

You'll see one long line starting `ssh-ed25519 AAAA…`. Copy it.

**Verify:** `ssh -V` should print `OpenSSH_for_Windows_…`. If not, install
the OpenSSH client via Settings → Apps → Optional features → OpenSSH Client.

---

## Phase 2 — DNS at Ionos

Log into the Ionos panel → **Domains & SSL → mindlathe.xyz → DNS**.

Add (or edit) these records:

| Type | Host | Value | TTL |
|---|---|---|---|
| A | `@`   | `162.222.206.53` | 1h |
| A | `www` | `162.222.206.53` | 1h |

Delete any conflicting old records pointing at parking pages or the prior host.

**Verify** (from PowerShell, may take 5–60 min after edit):

```powershell
nslookup mindlathe.xyz
```

The answer section should show `162.222.206.53`. Don't proceed until it does
— Caddy's automatic HTTPS will fail otherwise.

---

## Phase 3 — Create the private data-tree repo

This is a *one-time* GitHub setup. The bot will read+write the data tree on
the VPS; a systemd timer pushes changes back to GitHub every 5 minutes; your
Windows clone pulls them.

### 3a. Make the OneDrive Life-OS folder a git repo

```powershell
cd $env:USERPROFILE\OneDrive\Documents\Life-OS
git init -b main
git add .
git commit -m "Initial commit — Life-OS data tree"
```

> ⚠ Before pushing, verify you're not committing anything sensitive. Add a
> `.gitignore` if the folder contains drafts you don't want versioned —
> probably nothing right now, but worth a glance.

### 3b. Create the private GitHub repo

On github.com → **New repository**:
- Name: `life-os-data`
- **Private**
- Don't initialize with README (you already have content)

Push:

```powershell
git remote add origin git@github.com:Lifted-Truck/life-os-data.git
git push -u origin main
```

(You may need to set up a GitHub-to-Windows SSH key for `git push` to work
without prompting — but the existing `id_ed25519` from Phase 1 works fine
if you add it to GitHub at github.com → Settings → SSH and GPG keys.)

---

## Phase 4 — VPS bootstrap (as root, ONCE)

SSH in as root using the password Ionos provided:

```powershell
ssh root@162.222.206.53
```

Get the bootstrap script onto the server. **Don't pipe-curl from chat** —
copy it via SCP so you can review:

```powershell
# from a SECOND PowerShell window (keep the SSH session open)
scp C:\Users\sport\Documents\life-os-app\deploy\bootstrap.sh root@162.222.206.53:/root/
```

Back in the SSH session, run it with your pubkey from Phase 1:

```bash
PUBKEY="ssh-ed25519 AAAA…YOUR_KEY_HERE… sport@mindlathe.xyz" bash /root/bootstrap.sh
```

The script will: update packages → install Python 3.12 + Caddy + ufw +
fail2ban → create the `life` user with your SSH key → harden sshd (no root
login, no passwords) → enable the firewall.

**Verify** (from a NEW PowerShell window — do NOT close the root SSH yet):

```powershell
ssh life@162.222.206.53
```

You should get a shell as `life` with no password prompt. If that works,
close the root SSH window. If it doesn't, fix the keys before disconnecting
root — once you log out of root SSH you can't get back in except via the
Ionos web console.

---

## Phase 5 — Clone repos + populate `.env` (as `life`)

In your `life@` SSH session:

```bash
# App repo (public — clones with HTTPS, no key needed)
cd ~
git clone https://github.com/Lifted-Truck/life-os-app.git app
cd app
python3.12 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
```

### 5a. Data-tree clone (needs a deploy key)

Generate a VPS-only SSH key for GitHub:

```bash
ssh-keygen -t ed25519 -C "vps-mindlathe-deploy" -f ~/.ssh/github_data -N ""
cat ~/.ssh/github_data.pub
```

Copy the printed pubkey. On github.com → `life-os-data` → Settings → **Deploy
keys** → Add deploy key:
- Title: `Ionos VPS (mindlathe)`
- Key: paste
- **Allow write access** ✅ (the push timer needs it)

Tell SSH to use that key for github when working in `~/data`:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github-data
    HostName github.com
    User git
    IdentityFile ~/.ssh/github_data
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config

# Accept GitHub's host key
ssh -T git@github-data 2>&1 | head -1  # expect "Hi <user>! You've successfully authenticated"

# Clone
git clone github-data:Lifted-Truck/life-os-data.git ~/data

# Identify the bot's automated commits cleanly
cd ~/data
git config user.name  "life-os-bot"
git config user.email "bot@mindlathe.xyz"
cd ~
```

### 5b. `.env`

```bash
nano ~/app/.env
```

Paste the contents of your local `.env` (Telegram token, Anthropic key,
Resend, etc.) but **change `LIFE_OS_ROOT` to `/home/life/data`**:

```ini
TELEGRAM_BOT_TOKEN=…
TELEGRAM_CHAT_ID=…
ANTHROPIC_API_KEY=…
RESEND_API_KEY=…
EMAIL_FROM=…
EMAIL_TO=…
LIFE_OS_ROOT=/home/life/data
```

Lock it down:

```bash
chmod 600 ~/app/.env
```

### 5c. Stop the local bot on your Windows machine

Telegram allows exactly **one** active long-poll per bot token. Before the
VPS bot starts you must stop the Windows one. In PowerShell (Windows):

```powershell
Get-CimInstance Win32_Process -Filter "name='python.exe' AND CommandLine LIKE '%bot.py%'" `
    | Stop-Process -Force
```

---

## Phase 6 — Install services + verify

Back on the VPS:

```bash
cd ~/app
bash deploy/install-services.sh
```

This installs eight systemd units (bot, dashboard, morning + timer, pull +
timer, push + timer), renders the Caddyfile against `mindlathe.xyz`, reloads
Caddy, and enables everything.

### Verification checklist

```bash
# 1. Services running?
systemctl status life-os-bot life-os-dashboard caddy --no-pager

# 2. Bot logs (Ctrl-C to exit)
journalctl -u life-os-bot -f

#    Expect: "Bot starting (long-polling)..." then "Application started"

# 3. Dashboard locally
curl -s http://127.0.0.1:8000/health
#    Expect: {"status":"ok"}

# 4. Dashboard over HTTPS (may take 30-90 s the first time — Caddy is
#    provisioning the Let's Encrypt cert)
curl -s https://mindlathe.xyz/health
#    Expect: {"status":"ok"}

curl -s https://mindlathe.xyz/today | python3 -m json.tool
#    Expect: JSON of today's plan

# 5. Timers
systemctl list-timers life-os-*
#    Expect: pull running every 5 min, push offset by 2 min, morning at 06:00

# 6. From Telegram on your phone: send /plan
#    Expect: the bot answers from the VPS.
```

If any step fails, `journalctl -xeu <unit>` is the first stop.

---

## Day-2 operations

- **Update the app:** SSH in, `cd ~/app && git pull && sudo systemctl restart life-os-bot life-os-dashboard`.
- **Edit the data tree from Windows:** edit, commit, push to `life-os-data`. The VPS pulls within 5 minutes.
- **See what the bot wrote back:** `cd ~/OneDrive/Documents/Life-OS && git pull` — every script-owned write the VPS made shows up as an automated commit.
- **Tail bot logs:** `journalctl -u life-os-bot -f`.
- **Force a morning run:** `systemctl start life-os-morning.service`.
- **Reset the Caddyfile** (if you change the domain): rerun `bash deploy/install-services.sh` with the new `DOMAIN=` env var.

## Troubleshooting

| Symptom | First place to look |
|---|---|
| Caddy can't get a cert | `journalctl -u caddy --no-pager` — usually means DNS hasn't propagated. Wait or check `nslookup`. |
| Bot keeps restarting | `journalctl -u life-os-bot -n 100` — usually `.env` mistakes or LIFE_OS_ROOT pointing at a missing path. |
| Push timer fails | `journalctl -u life-os-push` — typically a merge conflict between bot writes and your laptop edits. Resolve locally, push, then `sudo systemctl start life-os-push`. |
| Two bots active | Only one long-poll allowed — kill the laptop one (see Phase 5c). |
| Can't SSH in as life | Verify `~/.ssh/authorized_keys` on the VPS has your pubkey (use the Ionos web console). |

---

## What's NOT in this deployment yet

- The dashboard is a placeholder (JSON only). HTML / templates / auth go in a follow-up.
- No off-VPS backups of the data repo — GitHub is the backup.
- No alerting if a service goes down — `journalctl` is the only signal. Worth adding later (Telegram self-message via the bot on systemd failure events would be nice).
