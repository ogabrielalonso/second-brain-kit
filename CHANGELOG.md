# Changelog

## v1.9.0 (2026-07-21)

Feature release: heuristics clustering, a two-axis classification for every
heuristic, lesson, pattern and decision the gate touches.

- **Two-axis classification** (`scripts/heuristics_taxonomy.py`, new, the
  single source of truth for the vocabulary): `nature`, where a rule should
  act (`decision-tree`, `score`, `judgment`, `axiom`, or the honest fifth
  value `one-off-decision` for a dated, non-reusable project choice, each
  mapped deterministically to a route: skill, quality gate, agent-brain,
  governance, or record) and `domain`, the type of decision it guides
  (verification-qa, deploy-delivery, architecture-code, ai-orchestration,
  data-facts, communication-copy, security-privacy, git-versioning,
  process-workflow, business-strategy).
- **Judge classification criterion** (`prompts/judge.md`, criterion 10):
  classification is mandatory for every approved or edited candidate;
  `scripts/gate_judge.py` validates the model's `nature`/`domain` against the
  closed vocabulary in code (an invalid value becomes empty, it is never
  invented) before writing the label: a table cell in lessons rows, a
  "- **Class:**" line in pattern sections, and `nature`/`domain` frontmatter
  fields in decision notes.
- **Mechanical anti-fabrication check**: `gate_judge.cited_paths_check()`
  verifies on disk, before judgment, every file path a candidate cites, and
  injects the result into the candidate block the judge reads.
- **Promotion backlog**: when a rule's nature is `decision-tree`, `score` or
  `axiom` and it does not yet act on a real surface, the judge may propose a
  one-line `promotion`; `gate_judge.apply_promotion()` records it as a
  checkbox in the owner's routing note (`taxonomy.heuristics.routing`, a new
  optional config key) for the owner to decide, and only logs (never
  fabricates a file) when no routing note is configured.
- **Daily distillation** (`prompts/distill_daily.md`, `scripts/brain_daily.py`):
  the cheap model now proposes `nature`/`domain` on every candidate; drafts
  in the gate queue carry both fields in frontmatter and body.
- **Re-runnable backfill and route audit** (`scripts/classify_heuristics.py`,
  new): classifies whatever slipped through the daily pipeline without a
  class, verifies a blind sample with the judge model (on disagreement the
  judge wins), and audits which decision-tree/score/axiom rules already act
  on a real surface versus which are worth promoting. Supports `--dry-run`,
  `--skip-audit`, `--skip-verify`, `--reverify-all` (re-classifies the whole
  corpus with the judge model) and `--audit-only`. Config-driven throughout:
  no hardcoded vault path, reads `taxonomy.heuristics.lessons`/`.patterns`
  and skips gracefully when either is unset.
- **Optional per-type judge model**: a new `judge_model_heuristics` config
  key (default unset) lets `gate_judge.py` judge lesson/heuristic candidates
  with a different model than the rest of the queue, falling back to the
  base model on failure; leave it unset to judge everything with the base
  model as before.
- Test suite grew by two files: `test_heuristics_taxonomy.py` (vocabulary
  validation, class-label format and stability, route-map coverage) and
  `test_heuristics_classification.py` (the applier write path, the
  promotion backlog, the mechanical paths check, and the rendered judge
  prompt). Both were verified to FAIL against the pre-feature tree (via
  `git stash`) before landing.

Also includes two fixes already committed since v1.8.1 that had not yet
shipped in a release:

- **Weekly lint self-referential false positives**: broken-link counting no
  longer counts wikilinks written inside code spans (the weekly report lists
  broken links inside backticks, which made every following run count them
  again), and link targets now resolve against every file in the vault
  (canvas, root files, archived notes), not only indexed notes. Found while
  driving the reference vault to 0 broken links (120 of 162 reported were
  this false positive).
- Ignore the local `backups/` directory (author-local prototype bundles,
  never committed).

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
