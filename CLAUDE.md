# CLAUDE.md — life-os-app (Life-OS automation layer)

Claude Code guide for this repo. Keep it lean — pointers + gotchas. The rich,
cross-machine project memory lives in the DATA repo; read it first.

## Read first (cross-machine memory + plans, synced)
- `../Life-OS/dev/claude-memory/` — project_life_os.md, project_vps.md,
  project_threads.md. Usually auto-loaded by the memory pipeline; if not, read them.
- `../Life-OS/dev/plans/` — planning docs (architecture-review, write-mcp, vault,
  progress-metrics, skills-era, R2/R7/R8). Read the relevant one before building.

## The one rule
AI may interpret language. AI may **NOT** make scheduling decisions.
`compile()` / `schedule()` are pure, deterministic, parameterized on `today`, and
contain no LLM calls. Skills / bot / API record and propose; the engine decides.

## This repo at a glance
- `bot.py` + `bot_handlers/` — Telegram bot (long-poll on the VPS).
- `scheduler/` — deterministic core: compile_queue, schedule, day, urgency, days,
  models, tasks_parser, domains, **fileio** (the safe write layer), mode,
  day_template, logs.
- `dashboard/app.py` — FastAPI hub (server-rendered) + `/api/*` + `/health`.
- `metrics/aggregate.py` — progress aggregation; `mcp_server.py` — read-only MCP.
- `deploy/` — systemd units, `bin/` scripts, `Caddyfile(.hidden)`, install-services.sh.

## Load-bearing gotchas
- **It's live.** Push to `master` → the VPS auto-deploys in ~1 min, **after a
  pytest gate** (it won't restart on a red suite). Run `venv/bin/python -m pytest -q`
  before pushing.
- **Hidden hub path.** The dashboard is mounted at **`/lathe`** on the VPS
  (`LIFE_OS_HUB_PREFIX`). Deploy/health checks use
  `https://mindlathe.xyz/lathe/health` — bare `/health` is now a placeholder.
- **Tests must be env-independent.** The deploy gate runs pytest *with the VPS
  `.env`* (which sets `LIFE_OS_HUB_PREFIX=/lathe`); assert against `A.HUB_PREFIX`,
  not literal paths, or the gate blocks the deploy.
- **MCP SDK: 1.x and 2.x both supported.** `mcp_server.py` imports the 2.x
  `MCPServer` with a 1.x `FastMCP` fallback (SDK 2.0 removed
  `mcp.server.fastmcp`). Keep that compat import; don't pin `mcp<2`.
- **All data-tree writes go through `scheduler/fileio.py`** (atomic + advisory
  lock). Don't add raw `write_text`/`open("a")` on the data tree.
- **Derived state** (`schedule/queue.yaml`, `today-state.yaml`) is **untracked**
  and self-heals; don't re-track it.
- **SSH** to the VPS: `ssh life@<VPS_IP>` — the address lives in your
  `~/.ssh/config`, never in this repo (public). `life` has passwordless sudo.

<!-- KNOWLEDGE-LOOP:START -->
## Self-Improving Knowledge Loop

Each session: read accumulated knowledge before acting, write distilled knowledge
after. This meta-layer sits on top of my primary role and never overrides it.

### Every session
1. **ORIENT** — Read INDEX.md in full (kept small on purpose). Pull ONLY the matching
   entries from LIBRARY.md into context. Never load all of LIBRARY by default.
2. **ACT** — Do the work, applying retrieved lessons. If a lesson proves wrong,
   correcting it outranks adding a new one.
3. **REFLECT** — Ask: "What did I learn that a future session needs and could not
   cheaply re-derive?" A lesson qualifies only if durable, evidenced (tied to a
   concrete trigger), and non-obvious. If nothing qualifies, write nothing.
4. **WRITE (atomic)** — Append the lesson to LIBRARY.md and a one-line pointer to
   INDEX.md in the same change. New lessons enter as `tier: candidate`; promote to
   `canonical` only on a second independent occurrence or human review.

### Write gate (anti-poisoning)
This loop feeds its own output back as input, so a wrong lesson, written once, is
retrieved and reinforced forever. Therefore: prefer not writing over writing
unverified; every lesson states what would falsify it; if a retrieved lesson
contradicts present evidence, trust the evidence and demote the lesson.

### Consolidation (periodic)
When LIBRARY exceeds ~30 entries, merge duplicates, delete superseded entries,
promote recurring candidates, tighten tags. Refactor it like code; don't grow it
like a log.

### LIBRARY entry template
`[Lxxxx] <title> | tier | added: YYYY-MM-DD | tags: … | lesson: … | evidence: … | falsifier: … | supersedes: …`
<!-- KNOWLEDGE-LOOP:END -->
