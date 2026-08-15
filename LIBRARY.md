# LIBRARY.md — durable, evidence-backed lessons

Long-term memory for this repo. Append via the knowledge loop (see CLAUDE.md);
consolidate when it exceeds ~30 entries. New lessons enter as `tier: candidate`
and promote to `canonical` on a second independent occurrence or human review.
Every lesson carries a falsifier — if present evidence contradicts a lesson,
trust the evidence and demote the lesson.

Template:
`[Lxxxx] <title> | tier | added: YYYY-MM-DD | tags: … | lesson: … | evidence: … | falsifier: … | supersedes: …`

---

### [L0001] Sync dirty-check must detect untracked files, not just tracked diffs
- **tier:** candidate
- **added:** 2026-07-07
- **tags:** sync-integrity, deploy-ops
- **lesson:** The 5-min data-tree sync (`deploy/bin/sync-data-tree.sh`) guards its
  commit with a dirty-check. `git diff --quiet` sees only *tracked* changes, so a
  cycle whose only change is a NEW untracked file commits nothing and strands that
  file on the VPS indefinitely (no commit → no push → invisible everywhere else).
  Use `git status --porcelain`, which also reports untracked paths. Corollary:
  this hole was latent for months only because `queue.yaml`/`today-state.yaml`
  churn gave every cycle a tracked change that swept new files in via `git add -A`;
  gitignoring those derived files (architecture-review Tier-1B) removed the cover
  and exposed it.
- **evidence:** 2026-07-06 — a Telegram `/review` capture wrote
  `daily/reviews/2026-07-06.md` on the VPS but never reached GitHub; no `bot:`
  commit appeared across several 5-min cycles despite the file existing. Switching
  the guard to `git status --porcelain` committed it on the next cycle.
- **falsifier:** If a `git diff --quiet`-based guard ever commits a lone new,
  untracked file within one sync cycle, this lesson is wrong.
- **supersedes:** —

### [L0002] A sed on sshd_config is not sufficient hardening — cloud-init drop-ins are Included FIRST and win
- **tier:** candidate
- **added:** 2026-08-15
- **tags:** deploy-ops, security
- **lesson:** On Ubuntu cloud images `/etc/ssh/sshd_config` carries
  `Include /etc/ssh/sshd_config.d/*.conf` near the TOP, and OpenSSH applies the
  **first value it sees** for a keyword. So editing the main file (the classic
  `sed 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/'`) is
  silently overridden by any drop-in cloud-init ships — e.g.
  `50-cloud-init.conf: PasswordAuthentication yes` — because that drop-in is
  included before the line you edited. The fix is your OWN drop-in that sorts
  first (`00-<project>-hardening.conf`) so it wins over anything added later,
  and — the load-bearing part — **assert the effective config with `sshd -T`**,
  not the file contents. The file can say `no` while the daemon runs `yes`.
- **evidence:** 2026-08-15, live VPS check (autonomous-lifeos-001): `sshd -T`
  reported `passwordauthentication yes` despite `bootstrap.sh`'s sed having
  landed (`sshd_config:66` read `no`); the box had ~67k failed-password
  attempts in 30d. Diagnosis: `50-cloud-init.conf` = `yes`, included at line 12,
  ahead of line 66. Writing `00-life-os-hardening.conf` flipped the effective
  value to `no`; a fresh key login worked and an outside password probe got
  `Permission denied (publickey)`. Only bounded from becoming a breach because
  the deploy account's password was locked and root login was off.
- **falsifier:** If, on a stock Ubuntu cloud image with a conflicting
  `50-cloud-init.conf`, a sed on the main `sshd_config` alone makes `sshd -T`
  report the sed'd value, this lesson is wrong.
- **supersedes:** —
