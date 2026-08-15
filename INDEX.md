# INDEX.md — knowledge retrieval map

Compact pointers into LIBRARY.md. Read this in full each session (kept small on
purpose); pull ONLY the matching LIBRARY entries into context. Never load all of
LIBRARY by default.

**Tags:** `deploy-ops` · `sync-integrity` · `write-safety` ·
`deterministic-boundary` · `content-schema` · `test-harness` · `security`

## Lessons
- **[L0001]** Sync dirty-check must detect untracked files, not just tracked
  diffs — tags: `sync-integrity`, `deploy-ops`
- **[L0002]** sshd hardening: cloud-init drop-ins are Included FIRST and win over
  a sed on the main file — write a `00-*` drop-in and assert with `sshd -T`
  — tags: `deploy-ops`, `security`
