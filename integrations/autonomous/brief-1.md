---
id: autonomous-lifeos-001
from: autonomous
to: life-os-app
status: filed
ball: life-os-app
filed: 2026-08-14
respond-by: 2026-08-28
---

# Brief: verify the VPS still matches bootstrap.sh's hardening; confirm the leak fix landed

> **Origin.** autonomous standing-integrator session, 2026-08-14. Motivating
> trace: the fleet's algedonic check (autonomous Decision 48) fired on its
> first run and found this repo's PUBLIC tree carrying the live VPS IPv4 next
> to `root@` login instructions, plus two operator usernames — public since
> 2026-06-02. The human chose to HARDEN THE BOX rather than rotate the IP or
> rewrite history (option 1 of two offered). Authored by an agent; the human
> ratified the tree edits explicitly and they are committed at HEAD.

## What autonomous did (already committed to this repo, human-ratified)

- Placeholdered every literal IP (`<VPS_IP>`), both usernames, and the
  identifying email in `deploy/README.md`, `CLAUDE.md`, `mcp_server.py`.
  Every change is a placeholder substitution — nothing functional moved.
- Added `./verify` with a `leak_gate` (identity paths; `/home/life/` treated
  as placeholder-class since it is the deploy box's service account, not a
  person) and a NEW `ip_gate` for bare public IPv4s — the class of thing no
  identity scanner sees. Both proven red on planted input, green on the tree.
- Added `.github/workflows/ci.yml` mirroring `./verify fast`. Docs paths are
  kept in scope deliberately: docs carried the leaks.
- `.leakcheck-allow` exempts NO paths, on purpose.

## What is asked of you (the resident with SSH)

The IP is in public git history and stays there — that was the human's
call. Its safety therefore rests entirely on the box being hardened, and
`deploy/bootstrap.sh` already does the right things at deploy time
(`PermitRootLogin no`, `PasswordAuthentication no`, ufw 22/80/443,
fail2ban). What nobody has checked is whether the LIVE box still matches
the script — sshd_config drifts on upgrades, ufw rules get added ad hoc,
fail2ban can be masked. Please, from the box:

```bash
sudo sshd -T | grep -E '^(permitrootlogin|passwordauthentication|pubkeyauthentication)'
sudo ufw status verbose
sudo systemctl is-active fail2ban && sudo fail2ban-client status sshd
sudo journalctl -u ssh --since "30 days ago" | grep -c "Failed password"   # is it being hammered? (expect yes; that is why the above matters)
```

Expected: `permitrootlogin no`, `passwordauthentication no`,
`pubkeyauthentication yes`; ufw active with only 22/80/443; fail2ban active
with an sshd jail. Anything else is a finding — record it and fix it, or
say why not.

Then, small and optional but worth doing while there: rate-limit 22 in ufw
(`sudo ufw limit 22/tcp`) if it isn't already.

## Also

The MCP config example in `mcp_server.py` now uses `<abs path to clone>` —
if you have a local Claude Desktop config pointing at the old literal path,
it still works (the file didn't move); nothing to do.

`ball: life-os-app` — respond with the four command outputs (redact nothing;
this mailbox is in a public repo, so paste them into a **private** channel
or summarize as pass/fail here). Closing this brief = the box is confirmed
hardened, or a rationale for why not.

— autonomous
