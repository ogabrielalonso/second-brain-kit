# Second Brain Kit

A self-hosted "second brain" for people who work with Claude Code: a private,
searchable notes vault that an AI keeps organized for you, learns from your own
work over time, and is available in every future Claude conversation without
you re-explaining yourself.

Methodology and IP: Gabriel Alonso. This repository contains **no personal
data**: every installation generates its own configuration, credentials,
notification channel and content, from scratch, for that one owner.

## Who this is for

Anyone who uses Claude Code regularly and wants their notes, decisions and
lessons learned to accumulate automatically instead of living scattered
across chat history. No coding knowledge is required to install it: the
installer is a guided conversation with Claude, not a manual setup.

If you already keep notes in Obsidian (or any folder of markdown files),
this kit finds them, learns how you already organize things, and builds on
top without touching your existing text. If you have nothing yet, it builds
a clean skeleton for you.

## Quick start (one message, any agent CLI)

Open your agent CLI (Claude Code, Codex, Gemini CLI, or any agent that can
run shell commands) and paste this single message:

> Clone https://github.com/ogabrielalonso/second-brain-kit into ~/.brain/kit
> (download it as a zip if git is unavailable), then read
> installer/INSTALL.md inside it and follow it exactly to install my second
> brain. I am not technical: follow the communication contract strictly.

That is the whole setup. Your agent fetches the kit, proves the kit's own
test suite first, then asks a handful of yes/no questions and builds the
whole thing itself: a private notes memory, a way to find anything back in
seconds, a daily habit of quietly saving what matters, a weekly two-minute
approval message, and a safety copy of everything. Plan 30 to 45 minutes
for the guided part.

Prefer not to paste a link? The classic path works too: download the repo,
drag `installer/INSTALL.md` into your agent chat and send *"Read this file
and install my second brain. I am not technical: follow the communication
contract strictly."*

## What you end up with

After the guided install, the brain runs itself:

| Cadence | What happens | Who does it |
|---|---|---|
| Always on | Local semantic search over your notes (<100ms, on your machine) | code |
| Every session | Your AI already knows who you are and what you are working on | hooks / standing instructions |
| Daily | Your AI sessions are distilled into candidate learnings; a judge decides what enters the canon (dormant until it EARNS autonomy from your own decisions) | cheap model + strong model + code |
| Weekly | Lint, cosmetic fixes, a two-minute dispatch message on your phone | code + cheap model + you |
| Monthly | An aging pass flags notes that got stale; contradictions escalate to you | strong model + code |
| Every 6h | A watchdog checks everything and heals or alerts your phone | code |

Trust rules baked in: nothing is ever deleted or merged by a machine; wrong or
aged notes are flagged, superseding is always your call; every automated write
is a scoped git commit you can revert; facts about people's roles always wait
for a human.

## Works with more than Claude Code

The brain is plain files plus a localhost search daemon, so any agent CLI that
can run shell commands can use it. Claude Code gets the deepest integration
(automatic briefing and retrieval hooks). Codex, Cursor and any tool that reads
the AGENTS.md convention, and the Gemini CLI, get the same contract as standing
instructions rendered into their global context files. New tools (a Grok CLI,
whatever comes next) plug in the same way: one brain, one contract, many
harnesses.

## Repository layout

```
installer/INSTALL.md      the file people receive: Part 1 for the owner, Part 2 the install contract
config/config.example.json  the shape of a generated installation's config file
scripts/                  deterministic code: retrieval, appliers, git, sanitizer, watchdog, telemetry
prompts/                  versioned LLM prompts: daily distillation, judge, aging audit, weekly dispatch
templates/vault/          vault CLAUDE.md template, note schemas, skeleton folders, seed notes
templates/context/        AGENTS.md / GEMINI.md standing-instruction templates for other agent CLIs
templates/hooks/          session-start briefing, per-question retrieval, post-commit reindex
templates/services/       launchd / systemd / Windows Task Scheduler service templates
templates/commands/       ask-brain, save-brain, dispatch-weekly command files
tests/                    sanitizer acceptance corpus, judge and aging fixtures, config tests, run_all.sh
docs/ARCHITECTURE.md      binding spec for this repository
```

## How the split works

Everything that must behave the same on every install ships as tested code
in `scripts/`. Everything that requires judgment (what a candidate note
should say, whether something contradicts an existing note, how to draft the
weekly summary) ships as a versioned prompt in `prompts/`, run headless by a
model. The only thing an installing Claude session writes by hand is
per-owner glue: the generated config, rendered service files, the vault's
own `CLAUDE.md` filled in with that owner's real folder structure, and seed
notes from the interview. It never writes or patches the core logic; a
platform quirk gets reported, not silently worked around.

This means every installation runs the exact same tested pipeline; installs
differ only by configuration, never by code.

## Tests

The kit proves itself before it touches your machine: the installer's first
step runs `tests/run_all.sh`, which covers the config contract, a mandatory
sanitizer acceptance corpus (API keys, JWTs, PEM blocks, IBANs, phones,
emails, your own confidential patterns), the scoped-commit regression suite,
judge fixtures (6 canonical cases) and aging fixtures. The same suite also
guards this repository: `test_no_personal_data.py` fails the build if any
personal data pattern ever lands in the tree.

## Requirements

- **Claude Code** (the agentic app, not the chat-only product), with an
  existing paid Claude plan.
- **python3** and **git**, detected and installed by the installer if
  missing (with a one-line confirmation first).
- The `sentence-transformers` stack, for a local multilingual embedding
  model (a few hundred MB download, done once).
- A free GitHub account, for a private safety-copy repository.
- A free phone app (ntfy) for notifications.

No API keys beyond your existing Claude account, and no data ever leaves
your machine except the private GitHub backup and the ntfy notification
channel, both generated fresh for you.

## Credit and licensing

Methodology and original implementation: Gabriel Alonso.

Licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE.md): you may
use, copy, modify and share this kit freely for any noncommercial purpose;
commercial use requires the author's permission.
