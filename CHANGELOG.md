# Changelog

## v1.8.1 (2026-07-19)

Bug-fix release after the first team installs. Three issues were reported from
the field by Simone Signoretti (thank you); a full audit of the kit (static
pass, cross-module contract review, doc-vs-shipped review, and a sandboxed
end-to-end simulation of every pipeline) then surfaced the rest. Update with
`git pull` inside `~/.brain/kit`; no config or vault migration needed.

Runtime fixes:

- **Watchdog false alert (field report):** `brain_watchdog.py` read the daily
  state from `state/brain_daily.last_run` while `brain_daily.py` writes
  `cache/daily/.last_run`, so every install alerted "daily distillation has
  never run" forever. The watchdog now reads the file the daily writes.
- **Weekly telemetry section never rendered (field report):**
  `brain_weekly_auto.py` called `gate_log.compute_stats(weeks=12)` without the
  required `cfg`; the defensive try/except swallowed the `TypeError` on every
  run. Now called with the config, so the gate-telemetry section can render.
- **Silent no-op distillation:** a distillation turn that ended without a JSON
  array (e.g. the model spawned background subagents and exited before they
  returned) was parsed as "0 candidates" and marked the day successful. It is
  now a hard FAILURE (state untouched, scheduler retry covers the window, owner
  alerted), subagents are hard-disabled via `--disallowedTools`, the timeout is
  raised to 2h with `TimeoutExpired` handled, and the distillation prompt
  forbids background work explicitly.
- **Judge deleted vault scaffolding:** the skeleton's `gate-queue/_README.md`
  was picked up as a candidate and deleted by the discard path on the first
  real run. The queue collector now ignores underscore-prefixed files, and the
  watchdog counts the queue with the same criterion.
- **Self-feeding distillation (two stacked bugs):** the aging/weekly headless
  workspaces were not excluded from session collection (wrong dir name), and
  the exclusion match itself never fired because project-dir encoding turns
  every non-alphanumeric character into `-` while the filter kept the dot.
  Collection now excludes everything under the brain home using the real
  encoding.
- **Notification crash path:** `notify.send()` promised "never raises" but read
  the config outside its try; a corrupted config at notification time could
  crash a job after its real work was committed. Config access moved inside.
- **`--dry-run` wrote to the vault:** the weekly dry run still generated the
  weekly report inside the vault, and its frontmatter-fix log lines did not say
  they were simulated. Dry runs now leave the vault untouched.
- **Retrieval trigger too strict:** "what is my current focus" did not fire the
  retrieval hook (up to two words are now allowed between "my" and the target).
- **Silent flag drop:** `query.sh` in daemon-less fallback ignored `--compact`
  and `--mode` without a word; it now says so on stderr.

Docs aligned with shipped code (INSTALL.md / ARCHITECTURE.md / templates):
quarterly connection audit documented as a manual ritual (no service template
ships for it); `BRAIN_CONFIG` (not `BRAIN_VAULT_PATH`) documented as the
sandbox override; index staleness documented as 12h to match code and config;
`{{KIT_REPO_URL}}` placeholder claim removed (the URL is literal); the daemon's
nonexistent internal log file no longer referenced (it logs to stdout, and the
Windows README now says the daemon task needs an explicit redirect); one
placeholder convention across command templates, stated in INSTALL.md.

Test suite grew from 7 to 12: shared-path contracts (including the project-dir
encoding case), cross-module call contracts, queue hygiene, dry-run
cleanliness, and the distillation output contract. Each new test was verified
to FAIL against v1.8.0 before the fix landed. The English-only guard also
gained the words that had already slipped through and an explicit carve-out
for the aging verdict aliases.

## v1.8.0 (2026-07-15)

First public release.

The kit's architecture shifted in this version: **everything repeatable ships
as tested code in this repository; LLM judgment ships as versioned prompts;
the installer is an agentic bootstrapper** that interviews the owner, generates
config, renders templates and wires services. Earlier versions (v1.0 to v1.7,
private) had the installing session write the code from a spec, which made
every installation a divergent fork.

Highlights:

- 17 config-driven scripts (retrieval daemon with derived port and instance
  identity, daily capture and distillation, autonomous judge shipped dormant,
  telemetry, weekly ritual, aging pass, watchdog, sanitizer, scoped git layer).
- 5 versioned prompts (judge, daily distillation, aging audit, weekly dispatch,
  collection enrichment), language-aware via config.
- Two onboarding modes: existing Obsidian vault (read-only sweep, taxonomy
  derived from the owner's real structure, purely additive enrichment) or
  from scratch (skeleton plus seed notes from the interview).
- Multi-harness adapters: deep hook integration for Claude Code; standing
  instruction context templates for Codex, Cursor, Gemini CLI and any
  AGENTS.md-reading tool.
- Reliability hardening from a full audit of the reference installation:
  scoped commits (never `git add -A`), trust status propagated through
  retrieval, scheduler-proof detached reindex, escalation stamps, watchdog
  self-heal with alerting, first-install daemon wait.
- One-message quick start: paste a single prompt into any agent CLI
  (Claude Code, Codex, Gemini CLI) and it fetches the kit and runs the
  installer end to end; the preflight fetch is idempotent.
- Test suite that runs before install and in CI: config contract, sanitizer
  acceptance corpus, scoped-commit regression, judge and aging fixtures,
  personal-data leak guard and an English-only guard (the whole tree,
  filenames included, ships in English).

Methodology and original implementation: Gabriel Alonso.
