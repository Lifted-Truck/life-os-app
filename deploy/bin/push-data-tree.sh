#!/usr/bin/env bash
#
# push-data-tree.sh — commit any bot-written changes in the data tree and
# push them back to origin. Called from life-os-push.service every few
# minutes. No-op when the working tree is clean.
#
# The bot writes to: ingest/, daily/logs/, schedule/queue.yaml,
# schedule/today-state.yaml, schedule/mode.yaml, inbox.md (append),
# thresholds.yaml (value updates), dev/bot-commands.md.
#
# Committed under a generic "life-os-bot" author so it's clear in the log
# which commits came from the VPS vs. Cowork sessions on the desktop.

set -euo pipefail

DATA_DIR="${DATA_DIR:-/home/life/data}"
cd "${DATA_DIR}"

# Anything to commit?
if git diff --quiet && git diff --cached --quiet; then
    exit 0
fi

git add -A
git -c user.name="life-os-bot" \
    -c user.email="bot@mindlathe.xyz" \
    commit -m "bot: $(date -u +%FT%TZ) — automated write"
git push --quiet
