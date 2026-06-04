#!/usr/bin/env bash
#
# sync-data-tree.sh — atomic data-tree sync.
#
# Replaces the previous two-timer design (life-os-pull.timer +
# life-os-push.timer), which had race windows where pull could fire
# mid-write or before push had committed, producing alerts the system
# self-healed from a cycle later. Single service serializes the cycle.
#
# Each 5-minute fire does, in order:
#   1. Commit local dirty changes (bot writes to inbox.md, daily/logs/,
#      ingest/, schedule/*.yaml, dev/bot-commands.md, etc.) under the
#      `life-os-bot` author so they're distinguishable from user commits.
#   2. Pull with rebase + autostash. --rebase replays any local commits
#      on origin's tip if origin advanced; --autostash handles any
#      tracked file edits that the bot started between step 1 and now.
#   3. Push to all configured push URLs (primary + mirror) in one
#      operation. `git push` with no args targets origin, which has
#      both URLs configured.
#
# A genuine conflict (rebase can't auto-resolve) leaves the working
# tree in a rebase-in-progress state and exits non-zero — the OnFailure
# alert fires and the user resolves manually. With `set -e` below, any
# step failure surfaces.

set -euo pipefail

DATA_DIR="${DATA_DIR:-/home/life/data}"
cd "$DATA_DIR"

# 1. Commit any local dirty changes.
if ! git diff --quiet || ! git diff --cached --quiet; then
    git add -A
    git -c user.name="life-os-bot" \
        -c user.email="bot@mindlathe.xyz" \
        commit -m "bot: $(date -u +%FT%TZ) — automated write"
fi

# 2. Sync with origin.
git pull --rebase --autostash --quiet

# 3. Push to all remotes (primary + mirror via origin's two push URLs).
git push --quiet
