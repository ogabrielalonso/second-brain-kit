# second-brain-kit v1.8: Architecture

> Second Brain Kit. Methodology and IP: Gabriel Alonso. Contains NO personal data:
> every installation generates its own config, credentials, channels and content.
>
> Design principle (v1.8 shift): **everything repeatable ships as CODE in this repo;
> LLM judgment ships as versioned PROMPTS; the installer .md is only the agentic
> bootstrapper** (interview, config generation, service wiring, demos). In v1.7 the
> installing Claude wrote code from specs, so every install was a divergent fork.
> In v1.8 every brain runs the same tested code; installs differ only by config.

## Runtime model split (fixed)

| Layer | Runs on | Ships as |
|---|---|---|
| Retrieval, appliers, git, sanitizer, watchdog, telemetry | deterministic code (python3 + bash) | `scripts/` |
| Daily distillation | cheap model (sonnet-class) headless | `prompts/distill_daily.md` |
| Judge, aging auditor, weekly dispatch draft | strong model (opus-class) headless | `prompts/judge.md`, `prompts/aging_audit.md`, `prompts/weekly_dispatch.md` |
| Collection enrichment batches (MODE A) | cheap model | `prompts/enrich_batch.md` |
| Install-time intelligence (interview, vault mapping, adaptation) | the owner's Claude Code session | `installer/INSTALL.md` |

## Config contract (the ONLY per-owner state)

`~/.brain/config.json` (OUTSIDE the vault; `~/.brain/` also holds index, model cache,
state files, logs). Loaded by every script via `scripts/brain_config.py` (single
source of truth; no script may hardcode an owner path, name, topic or port).

**brain_config.py canonical API (fixed; arbitrated 15/jul during build, updated to
the implemented reality after module integration):**
- `load_config() -> dict`: reads the RAW JSON at `os.environ.get("BRAIN_CONFIG",
  "~/.brain/config.json")` (env override is MANDATORY: tests and sandboxes depend
  on it). Raw means: no default-merge, no path expansion; use it to fail loudly
  when a real run has no config.
- Structured helpers are the CANONICAL access path for scripts:
  `vault_path()`, `port()`, `taxonomy()`, `thresholds()`, `sources()`,
  `confidential_patterns()`, `judge_enabled()`, `owner_name()`, `owner_context()`,
  `main_language()`, `ntfy_topic()`, `instance_id()`, `brain_home()`. Helpers merge
  missing keys from `config/config.example.json` (resolved relative to the kit dir),
  expand `~`, and derive `port` when 0.
- Import-time safety: modules may compute config-derived module constants with
  helper fallbacks, but `main()` MUST revalidate with raw `load_config()` so real
  runs without a config fail loudly instead of running on defaults.

**Escalation stamp (canonical, cross-module):** the frontmatter field is
`escalated_at` (plus optional `escalated_reason`). BOTH the judge
(`gate_judge.stamp_escalated`) and the aging pass (`brain_aging.escalate`) MUST
write it, and `gate_judge.load_queue` skips any queue item that has it. One name,
everywhere; a divergent key re-surfaces escalated items to the judge forever.

```json
{
  "owner_name": "<from interview>",
  "owner_context": "<one line: role/company for judge context; may be empty>",
  "main_language": "pt-BR",
  "vault_path": "/abs/path/to/vault",
  "port": 0,
  "instance_id": "<random hex, generated at install>",
  "ntfy_topic_file": "~/.config/secrets/ntfy-topic",
  "sources": { "claude_projects": true, "extra_paths": [] },
  "confidential_patterns": ["<denylist from interview>"],
  "taxonomy": {
    "decisions_dir": "04-Journal/Decisions",
    "weekly_dir": "04-Journal/Weekly",
    "queue_dir": "04-Journal/gate-queue",
    "digests_dir": "04-Journal",
    "heuristics": { "lessons": "", "patterns": "" },
    "home_dir": "00-HOME",
    "index_targets": ["00-HOME", "01-MOCs", "02-Projects", "03-Knowledge", "04-Journal"],
    "index_exclude": ["_system/", "Inbox/", "gate-queue/", "/templates/", "/history/"],
    "moc_map": {}
  },
  "thresholds": {
    "inject_min_score": 0.52, "index_stale_h": 12, "queue_alert": 15,
    "max_apply_per_run": 10, "aging_check_interval_d": 90,
    "eligibility": { "min_n": 20, "min_rate": 0.95, "min_weeks": 6 }
  },
  "judge_enabled": false
}
```

Rules: `port` = 8700 + (sha256(vault_path) % 200), bind 127.0.0.1 only; every client
verifies `instance_id` from `/health` before trusting answers (another brain daemon
may exist on the machine). MODE A: `taxonomy.*` is DERIVED from the owner's real
structure during install (owner's structure always wins); MODE B uses the skeleton
defaults above. `judge_enabled` flips only via the documented turn-on procedure
(eligibility rule met + backtest + owner's yes).

## Repo layout

```
installer/INSTALL.md      the file people receive; Part 1 human, Part 2 the bootstrap contract
config/config.example.json
scripts/                  brain_config.py · embed_brain.py · brain_daemon.py · query_brain.py
                          embed.sh · query.sh · sanitize.py · brain_daily.py · gate_judge.py
                          gate_log.py · brain_git.py · brain_weekly.py · brain_weekly_auto.py
                          brain_aging.py · brain_watchdog.py · notify.py · enrich_apply.py
prompts/                  distill_daily.md · judge.md · aging_audit.md · weekly_dispatch.md · enrich_batch.md
templates/vault/          CLAUDE.md.template · note schemas · MODE B folder skeleton · seed notes
templates/hooks/          session_start_briefing.sh · user_prompt_retrieval.sh · post-commit
templates/services/       launchd 5x .plist.template · systemd 5x .service/.timer.template · README-windows.md
templates/commands/       ask-brain.md · save-brain.md · dispatch-weekly.md
tests/                    test_sanitizer_corpus.py · test_commit_scoped.py · judge fixtures (6) ·
                          aging fixtures (2) · test_config.py · run_all.sh
docs/ARCHITECTURE.md      this file
README.md
```

## Hard requirements carried from v1.7 (unchanged)

Daemon as OS service with keep-alive; index/model cache outside the vault; canon
exclusions from index; sanitizer is CODE with mandatory acceptance corpus; dedup =
semantic OR accent-folded word overlap; judge ships DORMANT with the single
eligibility rule; escalation precedence fixed (dedup → too-specific → person-role →
confidentiality → contradiction → unknown destination → cap); supersede never delete;
everything reversible (git); MODE A prime directive (owner's content/organization =
source of truth; enrichment purely additive with marker blocks); communication
contract (owner's language, zero jargon, no em/en dashes ever).

## Hardening baked into the shipped code (v1.8, from the 15/jul audit of the reference install)

1. **Scoped commits** (`brain_git.commit_scoped`): pipelines never `git add -A`;
   only paths touched this run; ghost-path filter (created-and-deleted same run);
   per-path fallback on batch failure; ntfy alert if commit fails with work applied.
2. **Trust axis travels with the data**: `status` (draft/active/stale/superseded)
   is indexed per chunk, returned by the daemon, and flagged (warning marker) by the
   retrieval hook with the instruction "not current truth".
3. **Detached reindex**: post-commit spawns reindex/push with `start_new_session=True`
   (survives scheduler process-group teardown); reindex log always appended with
   timestamps; push gets a minimal log.
4. **Watchdog**: index staleness threshold 12h (self-heal); a crashed check itself
   triggers a phone alert (a blind watchdog must never be silent).
5. **Searchable daily digest**: judge writes a per-day section into a monthly note
   (1 chunk per section); same-day rerun appends into the existing section, never a
   duplicate heading.
6. **Escalation hygiene**: escalated queue items are stamped (`escalated_at`) and
   skipped by later runs (they wait for the human); telemetry logs `escalated` as a
   first-class decision; type keys accent-folded to one canonical form.
7. **Aging**: note age = last git commit date (mtime fallback for never-committed);
   project `_STATUS`-style dashboards are IN scope; verdicts: current | stale
   (auto, reversible) | superseded-candidate (always escalate).
8. **Log hygiene**: service StandardOut path is never the same file the script
   appends to (no duplicated lines).
9. **Deterministic MOC/index upkeep**: appliers append new-note links to the mapped
   MOC section "Recent entries (auto)" and a row to the decisions index; weekly
   curation (cheap model) files them properly. Map comes from config, not code.

## Installer flow (INSTALL.md v1.8 outline)

Part 1 (owner, non-technical): unchanged spirit from v1.7 + one new prerequisite:
`git` available (installer handles install with one-line ok). The file carries the
repo location as a literal URL (forks: search-and-replace its occurrences in
installer/INSTALL.md; offline fallback: the kit folder may be shipped as a zip
alongside the .md).

Part 2 phases (exit gates and the 3 demonstration checkpoints kept from v1.7):
- Phase -1 Preflight: tooling detect/install; clone the kit repo (URL literal in INSTALL.md) to
  `~/.brain/kit` (or unpack the provided zip); run `tests/run_all.sh` BEFORE
  touching the owner's machine state (the kit proves itself first).
- Phase 0 Foundation: interview → MODE A (map their vault: full sweep read-only,
  5-line summary confirmation, derive `taxonomy` config) or MODE B (skeleton from
  templates) → generate `~/.brain/config.json` → git init/commit + private backup.
- Phase 1 Retrieval: install daemon service from templates (port derived,
  instance_id fresh), first index build, acceptance: meaning-query + restart-survival.
  Checkpoint 1.
- Phase 1.5 MODE A enrichment (permission first): batches via `prompts/enrich_batch.md`,
  applied by `enrich_apply.py` (additive, marker blocks, per-batch commits), islands
  report, optional MOC proposals.
- Phase 2 Capture: wire daily job (scheduler template), sanitizer corpus test
  mandatory, synthetic session test if no history. Checkpoint 2.
- Phase 3 Gate + telemetry + watchdog: as v1.7 (eligibility rule defined once).
- Phase 4 Judge: install DORMANT from `prompts/judge.md` + fixtures; turn-on note.
- Phase 5 Self-maintenance: aging schedule + quarterly connection audit (manual ritual, no service template).
- Phase 6 Always-on: global CLAUDE.md section, briefing hook (<4k tokens budget),
  retrieval hook (threshold, instance_id check), ask/save commands. Checkpoint 3
  (fresh session knows the owner) + first dispatch. Final report <15 lines.

## Harness adapters (multi-CLI, one brain)

The brain is files + a localhost HTTP daemon + shell CLIs, so ANY agent tool
that can run shell commands can use it. Integration depth varies by tool:

| Tool | Integration | Mechanism |
|---|---|---|
| Claude Code | deep (automatic) | SessionStart briefing hook + per-prompt retrieval hook + commands |
| Codex / any AGENTS.md-reading CLI (Cursor, newer agent CLIs) | standing instructions | `templates/context/AGENTS.md.template` rendered into the tool's global context |
| Gemini CLI | standing instructions | `templates/context/GEMINI.md.template` rendered into `~/.gemini/GEMINI.md` |
| Future tools (e.g. a Grok CLI) | standing instructions | render the AGENTS template into whatever global context file the tool reads |

Instruction-based integration means the agent is TOLD to self-brief from the
identity/focus notes, to run `query.sh` before answering personal/project
questions (verifying `instance_id`), to respect the status trust axis, and to
write only via the gate queue unless given a direct order. Same contract as the
hooks enforce, applied by the model instead of the harness. The autonomous
pipelines (daily, judge, weekly, aging) are harness-independent: they run from
the OS scheduler and call a headless LLM CLI (default: `claude -p`; the binary
and flags are code-level constants, a future config knob if another headless
CLI proves equivalent).

## What the installing Claude may still write (and nothing else)

Config values, service files rendered from templates, the vault CLAUDE.md rendered
from template with the owner's taxonomy, seed notes from the interview, and glue
the templates explicitly mark as `{{RENDER}}` blocks. Core logic is read-only; if a
platform gap forces a workaround, it must be reported in the final notes as a
deviation, never silently patched into kit code.

## Sanitization guarantee for this repo

No owner data ships: no real names (except the methodology credit), no absolute
home paths, no ntfy topics, no client/project names, no personal trigger regexes,
no personal MOC names inside code (taxonomy lives in config). CI-style check:
`tests/test_no_personal_data.py` greps the tree for a denylist of leak patterns.
