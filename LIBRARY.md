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
