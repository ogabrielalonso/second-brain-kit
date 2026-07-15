# Changelog

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
