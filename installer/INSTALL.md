---
title: "Second Brain Setup Kit (agentic installer, EN, non-technical owners)"
description: "Distributable installer, v1.8. Installs vault, retrieval, capture, human gate with telemetry; judge ships dormant; language-aware; employer-confidentiality opt-in. Every install runs the same tested code from this kit; only configuration differs per owner."
---

# Your Second Brain: Setup Kit

## PART 1: FOR YOU (2 minutes, no technical knowledge needed)

**What this is.** This file sets up your "second brain": a private collection of notes that an AI keeps organized FOR you. It learns from the work you do with AI, saves only what matters (after checking it is true, new and useful), finds anything back in seconds, warns your phone if something breaks, and keeps a safety copy of everything. And from then on, **every new Claude conversation starts already knowing who you are, what you are working on, and what you have decided before**: no more re-explaining yourself. You approve things with one short message a week. That is your whole job.

**Already use Obsidian (or any notes folder)?** Even better: Claude will FIND your existing notes, learn how YOU organize them, and build on top. Your written text is never changed or translated; the upgrade only ADDS small things around it: a one-line summary label on top of each note and a "Related" list at the bottom, so years of old notes become findable and connected. Every step can be undone.

**What you will need (all guided, nothing to prepare):**
- The **Claude Code app** (the version of Claude that can actually work on your computer, not the regular chat app). Download at claude.com/claude-code (Mac/Windows). Log in with your work account: your existing paid plan covers everything, there is no separate cost for this setup.
- A small free tool called git, which keeps the unlimited-undo history working. If you do not have it yet, Claude installs it with your one-click ok.
- A free GitHub account for your private safety copy (if you don't have one, Claude creates it with you in 3 minutes, click by click).
- A free phone app called ntfy for your brain's notifications (2 minutes, guided).

**Where your things go (transparency):** your notes get a safety copy in a PRIVATE space only you can access (GitHub); notifications travel through a private channel (ntfy); and the AI processing runs through your own Claude account. Nothing is ever made public, and Claude will verify the privacy of the safety copy before using it. The tool that builds all of this (this kit) is downloaded once from its own private safety copy and proves itself with its own checks before it ever touches your computer.

**The easiest start (one pasted message):** open your agent app (Claude Code
is the smoothest; Codex or the Gemini CLI also work) and paste, in YOUR
language if you prefer:

> *Clone https://github.com/ogabrielalonso/second-brain-kit into ~/.brain/kit (download it as a zip if git is unavailable), then read installer/INSTALL.md inside it and follow it exactly to install my second brain. I am not technical: follow the communication contract strictly.*

**Or, if you were handed this file directly (3 steps):**

1. Open the **Claude Code** app and start a new conversation (pick the most capable model if it asks).
2. Attach or drag THIS file into the chat.
3. Type this and send (in YOUR language if you prefer; Claude will answer in your language):

> *Read this file and install my second brain. I am not technical: follow the communication contract strictly.*

Claude will ask a few simple yes/no questions, then work by itself. Plan ~30-45 minutes for the setup itself; if you already have a big collection of notes, the note-upgrading part keeps running in the background afterwards and Claude will tell you how long it expects. It pauses a few times to show you something working and ask "ok to continue?".

**What you'll do after setup (honestly, all of it):**
- Nothing daily. Your phone gets a short note when your brain learns something.
- Once a week, answer one message like: *"approve 1 and 3, discard 2"*. Takes 2 minutes.
- Ask your brain anything, anytime, in plain words: *"what did I decide about X?"*. It answers with sources, or honestly says it does not know.
- Changed your mind about anything? Everything is undoable, at any moment.

That's it. You can stop reading here. Everything below is instructions for the AI.

---

## PART 2: FOR THE EXECUTING CLAUDE (the owner does not need to read this)

You are the installer, running inside Claude Code (you need shell, file and scheduler access; if you are a chat-only Claude without execution tools, STOP and tell the owner to open this in the Claude Code app instead). The owner is NON-TECHNICAL. Two contracts bind you: how you COMMUNICATE and what you BUILD.

**What "install" means in v1.8:** this kit ships as a tested code repository, not as a spec you implement from scratch. Retrieval, appliers, git handling, the sanitizer, the watchdog and telemetry are all finished, versioned code in `scripts/`; the daily distillation, the judge, the aging audit and the weekly draft are all finished, versioned prompts in `prompts/`. **You do not write or patch any of that.** What you write, per owner, is: the generated `~/.brain/config.json` (via the interview), rendered service files from `templates/services/`, the vault's own `CLAUDE.md` rendered from `templates/vault/` with THIS owner's real taxonomy, seed notes from the interview, and glue inside templates explicitly marked as `{{RENDER}}` blocks. Nothing else. If something about this machine or platform does not fit the shipped code, you report the deviation plainly in your final notes; you never silently patch kit code to make it fit.

### Communication contract (violating this is failing the install)

0. **Speak the owner's language, always.** Detect it from their first message; cross-check against the dominant language of their notes; confirm once at the interview. EVERYTHING owner-facing is in their language: questions, checkpoints, reports, phone notifications, the weekly dispatch message, the final guide. This file being in English is irrelevant: English is only your instruction language. Internal identifiers (JSON keys, folder names of `_system`, script names) are NEVER translated.
1. **Zero jargon with the owner.** Never say: repo, git, RAG, index, daemon, terminal, script, JSON, cron/launchd, API, embedding, frontmatter. Analogy FIRST, term only if unavoidable: git backup = "a safety copy of every version, like unlimited undo"; the semantic index = "the brain's memory of where everything is"; the daemon = "a tiny helper that is always awake"; the gate queue = "the inbox of things waiting for your yes".
2. **Never ask a technical question.** Every question is yes/no or multiple choice WITH a recommended default. You figure out paths, tools and settings yourself. Account logins (GitHub) are guided click by click in the browser; if the owner gets stuck, create a sensible fallback (local second copy on another location) transparently and note it in the final report.
3. **Report in outcomes, not operations.** After each phase say what it MEANS for them, not what you did technically.
4. **Demonstrations and permissions.** Exactly 3 demonstration checkpoints (see phases), each showing something they can SEE working, ending with "ok to continue?". Short permission questions (like starting the collection upgrade) are allowed beyond the 3 but must be one-liners with a default.
5. **Writing style (permanent, in everything you create):** never use em-dash or en-dash; use comma, colon, parentheses.

### Installer contract

1. **Never skip a phase or its exit gate.** The order IS the methodology: autonomy is earned with telemetry, never granted upfront. The autonomous judge (phase 4) is installed DORMANT and only turns on later, per the eligibility rule defined ONCE in phase 3 part A.
2. **The kit proves itself before it proves you anything.** Phase -1 clones and tests the kit itself, before touching the owner's vault or machine state in any other way. If that fails, you STOP: you do not attempt to fix kit code, you report the failure and ask the owner whether to retry or get help.
3. **Interview first (plain language), then build autonomously** from the shipped code and templates.
4. **Adapt configuration, not code.** Detect OS/scheduler (macOS launchd, Linux systemd/cron, Windows Task Scheduler) and render the matching template from `templates/services/`. Required tooling you must detect AND install if missing (with the owner's one-line ok): python3 + pip, the sentence-transformers stack (warn: the language model download is a few hundred MB, needs disk and a few minutes), git, and GitHub access (prefer `gh` CLI; if unavailable on this platform, use plain git over HTTPS with a browser-created token, guiding the owner). The kit's code defines behavior identically on every install; you only choose and fill in the right template.
5. **Everything reversible.** Version-control the vault before anything writes to it. Every automated component commits with an audit digest message.
6. **No data of the methodology author ships here.** Every credential/topic/path is generated fresh for THIS owner. Never use the author's setup as a fixture.
7. **Verify for real.** Run each phase's acceptance test (the shipped tests where the phase has one, a live check against this real installation otherwise) and show the result (translate the outcome for the owner). Never declare done on unexercised code.

### Setup interview (plain language, defaults offered)

1. **Vault: DETECT before asking.** Search for existing Obsidian vaults (folders containing `.obsidian/`): macOS `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/*/` and `~/Documents`; Windows/Linux common Documents locations. Also accept any plain folder of `.md` notes they point to. Found: confirm plainly ("I found your notes vault '<name>' with <N> notes. Is this your main one? [yes]"). Multiple: list, let them pick. None: offer to create "My-Brain" in Documents. NEVER create a second vault when one exists.
2. **Main language: detect, then confirm.** Scan the vault (MODE A) and report the language distribution ("most of your notes are in French, some in English"). Confirm the MAIN language for everything the system writes. Permanent rules: (a) the owner's note text is NEVER translated or rewritten; every note stays in its original language forever; (b) system-written content (labels, tags, candidates, reports, notifications) uses the confirmed main language with ONE consistent tag vocabulary (never mixed-language duplicates like `meetings`/`reunioes`); (c) the embedding model is multilingual so any-language queries find any-language notes.
3. **Work sources and confidentiality.** Ask where they work with AI (default source: Claude Code sessions in `~/.claude/projects/`). Capture model, explicit: the SOURCE is the opt-in (their yes to reading their AI sessions), combined with a DENYLIST of confidential project-name patterns they give you; new personal projects are included by default so a brand-new user's brain still learns as they start using Claude Code (day one starts empty and that is normal, tell them so).
   **Confidential material inside the VAULT itself** (e.g. a Clients folder): apply this default matrix, stated to the owner in one sentence each: indexed locally YES (so they can find their own work), backed up YES (the safety copy is private and theirs), enrichment NO (client note bodies are never sent in enrichment batches), learning/capture NO (never becomes candidates). They can tighten or loosen any of the four with a word.
4. **Phone notifications:** generate a fresh secret channel (`<firstname>-brain-<16 random hex>`) at ntfy.sh; guide the app install + subscription (2 min); send a test and confirm they saw it; store the channel in `~/.config/secrets/ntfy-topic` (chmod 600). Tell them plainly: "if you ever screenshot or share this channel name by accident, tell your brain 'rotate my notification channel' and it takes one minute" (and implement that: regenerate topic, update the secret file, re-subscribe walkthrough).
5. **Safety copy:** guide GitHub account creation/login (browser flow); create a PRIVATE repository; **verify programmatically that the repository visibility is private immediately after creation and again before the first push; if not private, STOP, fix or recreate, and only then push.**

### Phase -1: Preflight (the kit proves itself first)

Before touching the owner's vault, notes or any other machine state:

1. Detect and, with a one-line ok, install missing tooling: python3 + pip, git, the sentence-transformers stack, and GitHub access (`gh` CLI preferred).
2. Fetch the kit itself into `~/.brain/kit`, IDEMPOTENTLY: if this very file is already inside a kit checkout (the owner's one-message quick start clones BEFORE you read this), verify it is a complete tree (scripts/, prompts/, templates/, tests/ present), move or link it to `~/.brain/kit` if it lives elsewhere, and `git pull` if it is a git checkout; otherwise clone `https://github.com/ogabrielalonso/second-brain-kit`, or unpack the zip file attached alongside this installer if working offline. Never clone a second copy over a working one. Tell the owner plainly: "I'm setting up the actual brain-building tool now, the same tested one every install uses."
3. Run `tests/run_all.sh` from `~/.brain/kit`. This exercises the sanitizer's mandatory acceptance corpus, the judge and aging fixtures, the scoped-commit logic and the config contract, all before anything touches the owner's machine.
4. All green: tell the owner in one line ("the tool checked itself and everything works") and continue to Phase 0. Any failure: STOP. Do not attempt to patch kit code. Report the failing check plainly and ask the owner whether to retry the download (possible corrupt fetch) or pause and get help. This is the one case where you do not improvise a workaround.

**Exit gate:** kit fetched into `~/.brain/kit`; `tests/run_all.sh` passes in full; nothing outside `~/.brain/kit` has been touched yet.

### Phase 0: Foundation (two modes; detect which applies)

**MODE A: existing vault (most common; treat as precious).** Prime directive: the owner's content and organization are the source of truth; you ADAPT to them.

0. FIRST ACT before touching anything: initialize version control and commit the current state ("your safety copy of everything exactly as it is today").
1. MAP their real structure: folders, naming, existing frontmatter, MOCs/indexes. Do not move, rename or rewrite ANY existing note. Reorganization ideas become queue proposals, never actions.
2. ADD only what is missing, in their naming style: gate-queue folder, `_system/telemetry/`, a Decisions home and Weekly home if none exist (fit INTO their structure). Precedence rule when MODE A and the MODE B skeleton disagree: the owner's structure ALWAYS wins; the skeleton is only a fallback vocabulary. Draft candidates live under `_system/` (out of the owner's sight and out of the index), never mixed with their notes.
3. Generate `~/.brain/config.json` (outside the vault) via `scripts/brain_config.py`'s contract: `taxonomy.*` is DERIVED from what you just mapped in step 1, never hardcoded and never copied from any other install. Vault-level `CLAUDE.md` rendered from `templates/vault/CLAUDE.md.template`, filled with THEIR real taxonomy, documenting the golden rule (answer only from notes; say "not found" honestly; never invent), the write contract (phase 3 version: candidates wait for the owner's yes), and the status table. Existing `CLAUDE.md`: extend, preserving every rule.
4. Seed notes ("who I am" / "current focus"): reuse equivalents if present; otherwise draft via 5-minute conversational interview.
5. Schema adoption is INCREMENTAL: new notes follow it; old notes are only touched by phase 1.5 (additive) and the weekly cosmetic lint, never a big-bang rewrite.

**MODE B: no vault.** Build the skeleton from `templates/vault/` (MODE B folder skeleton) + schema + `CLAUDE.md` + version control + seed notes; generate `~/.brain/config.json` with the skeleton defaults as `taxonomy.*`.

Folder skeleton for MODE B (display names in the owner's language if preferred):
```
00-HOME/  01-MOCs/  02-Projects/  03-Knowledge/
04-Journal/ (Decisions/, Weekly/, gate-queue/)  _system/  Inbox/
```

Note schema (knowledge notes): `source, type, title, description` (one factual retrieval sentence), `tags`. Dynamic notes add `status: draft|active|stale|superseded`, `created`, `approved_by` when a machine approves. Supersede, never delete.

**Exit gate (both modes):** `~/.brain/config.json` generated and valid against `scripts/brain_config.py`; initial commit exists; private push verified; owner approved the seed notes. **MODE A additionally:** diff against the initial commit proves zero existing notes modified in THIS phase (only additions), and the owner confirmed your 5-line summary of their organization ("did I understand your system right?").

### Phase 1: Retrieval

**What gets installed (shipped code, not written here):** `scripts/embed_brain.py` builds a local semantic index over the vault (chunked embeddings, multilingual local model, e.g. `paraphrase-multilingual-MiniLM-L12-v2`); `scripts/brain_daemon.py` serves it on localhost with `/health` and `/query?q=&top_k=`; `scripts/query_brain.py` and `query.sh` are the CLI wrapper; `embed.sh` wires reindexing to the post-commit hook from `templates/hooks/`. Your job is to render the matching service template from `templates/services/` for this OS's scheduler (launchd/systemd/Task Scheduler) so the daemon runs as a real OS-managed service with keep-alive, never as a foreground process of this install session, then run the first index build.

Carried over, unchanged, because they are the reasons past installs broke:
- **Identity, not just a port:** the port is derived per owner (hash of the vault path) by `brain_config.py`, bound strictly to 127.0.0.1; a fresh random `instance_id` goes into `/health`; every client verifies it before trusting answers. Another brain daemon may already exist on this machine; answering from someone else's brain is a critical failure.
- **Index and model cache live OUTSIDE the vault** (`~/.brain/`): vaults often sit in iCloud/Dropbox folders, and hundreds of MB of index/model inside a synced folder cause sync conflicts and bloat.
- **Not everything is canon:** `taxonomy.index_exclude` keeps `_system/`, `Inbox/`, `.obsidian/`, `CLAUDE.md`, READMEs, the gate queue, weekly dispatch packages and telemetry reports out of the index, so the judge later never reasons about its own paperwork.

**Exit gate:** health ok with chunk count; meaning-based query (not exact words) finds the right note; fresh note picked up after commit; **daemon survives a simulated restart (kill it, verify the OS brings it back)**. **Checkpoint 1 (demonstration):** the owner asks a question about THEIR OWN notes in their own words and sees the answer with the source.

### Phase 1.5: Enrich the existing collection (MODE A only; ask permission first)

Retrieval works on raw notes, but description metadata sharpens it and the link graph turns notes into a brain. This phase retrofits both, at scale, without touching what the owner wrote, using `prompts/enrich_batch.md` (cheap model, per batch) and `scripts/enrich_apply.py` (the deterministic write layer).

**Present as:** "I can read your whole collection once and give every note two upgrades: a one-line summary label for sharper finding, and connections to related notes. I never change your text: I only add a small label block on top and a Related list at the bottom, all undoable. With <N> notes this runs in the background for about <estimate>. Ok to start? [yes]"

**Spec (inviolable: the owner's prose is READ-ONLY; enrichment is purely additive):**
1. Inventory; skip non-standard files (canvases, `.excalidraw.md`, templates, attachments) and any folder the owner flags as raw archive.
2. Batches of 10-20, cheap model via `prompts/enrich_batch.md`: per note, (a) frontmatter to ADD (never overwrite existing fields): `title` (from filename/H1, note's own language), `description` (one factual sentence, owner's MAIN language), `tags` (3-5, main language, one consistent vocabulary across batches), `created` (file/git history); (b) 2-4 `related` candidates via the semantic index.
3. `enrich_apply.py` merges frontmatter non-destructively; `related` links are VALIDATED against the filesystem (NFC-normalized; unresolvable links never enter), written inside marker comments (`<!-- brain: related-start/end -->`) so reruns regenerate instead of duplicating.
4. Duplicates/near-duplicates found: NEVER merged; escalate to the queue as proposals.
5. Commit per batch ("undo per chapter"); reindex at the end; connection report (enriched count, links added, remaining islands justified vs not, duplicates escalated).
6. Optional finale with the owner's yes: propose 3-5 Maps of Content for the biggest clusters (new notes, additive).

**Exit gate:** batch commits individually revertible; diff proves zero body-text changes (only frontmatter additions and marker blocks); island count reported; owner saw before/after on 2 sample notes and approved (fold this into Checkpoint 1 if timing allows, or report async when the background run finishes).

### Phase 2: Capture

**What gets installed:** `scripts/brain_daily.py` runs headless daily (cheap model, read-only tools + `query.sh` for dedup), driven by `prompts/distill_daily.md`. It collects the owner's AI sessions ONLY from the opted-in folders (interview step 3); filters (minimum size, minimum owner messages, exclude its own headless runs); **sanitizes before any LLM call via `scripts/sanitize.py`** (strips API keys/tokens/passwords, email addresses, phone numbers, and the owner's declared confidential patterns; this step is code, not a prompt, so it cannot be argued with by the model); distills at most 5 candidates/day, all candidate content in the owner's MAIN language, into `{type, title, body, evidence, proposed_destination, reason_not_to_enter}`; writes each as `status: draft` into the gate queue; rebuilds the queue index; notifies the phone via `scripts/notify.py` in the owner's language.

**Sanitizer acceptance corpus (already proven in Phase -1, MANDATORY to re-confirm here against this owner's real config):** `tests/test_sanitizer_corpus.py` covers at least: API keys with hyphens/underscores, a JWT, a PEM block, an IBAN, EU-format phone numbers, an email with a person's name embedded, and one of the owner's declared confidential patterns inside a longer sentence, added to the fixture set now that you have it. All must be fully redacted (no partial leaks like half an email). Order matters: structural rules first, owner patterns last. Since this is presented to the owner as a security guarantee, run it once more here with their real denylist patterns before wiring capture live.
Dedup spec: a candidate is a duplicate when EITHER the semantic score passes threshold OR a deterministic word-overlap check passes (with accent-folding: "education"/"éducation" must match); never rely on the semantic score alone (fallback modes have no embeddings).
Details that broke in test installs: pluralize notification text properly ("1 new thing" vs "3 new things", in the owner's language); `proposed_destination` must be a canonical relative path (parseable by code), with any commentary in a separate field.

Robustness (shipped): last-success state file (catch-up up to 7 days), quiet-hour schedule PLUS same-day retry slot, 1-run-per-day guard, failure notification.

**Exit gate:** one real run (if the owner has no session history yet, run against a synthetic sample session you create in a sandbox, verify the pipeline end-to-end, and tell the owner their brain will learn as they work); state file present. **Checkpoint 2 (demonstration):** the phone notification arriving + one candidate shown in plain words.

### Phase 3: Human gate + telemetry (the owner's home for the next month)

**Part A (telemetry and THE eligibility rule, defined once):** `scripts/gate_log.py`: append-only JSONL decision log + policy file in `_system/telemetry/`; commands `add` (file, type, decision approved|edited|discarded, destination, note) and `stats`. **Autonomy eligibility rule (the ONLY definition; phases 1 and 4 refer here): a candidate type becomes eligible when n>=20 logged decisions, >=95% approved-unchanged, across >=6 distinct weeks.** Honor `BRAIN_VAULT_PATH` env for sandbox tests.

**Part B (weekly ritual):** `scripts/brain_weekly.py` and `scripts/brain_weekly_auto.py`: deterministic lint + cosmetic-only auto-fixes in a separate revertible commit + numbered dispatch package (candidates + recommendations, drafted with `prompts/weekly_dispatch.md`) + telemetry section + phone notification, all owner-facing text in their language. Owner answers one message; the dispatching session applies, deletes drafts, and MUST log every decision via `gate_log.py`. Install the `templates/commands/dispatch-weekly.md` command so any session knows the procedure.

**Part C (watchdog):** `scripts/brain_watchdog.py`, every 6h + at boot: alert (high priority) if daily hasn't run >36h, weekly missing, retrieval daemon down (restart first), queue >15 or oldest >30 days, index stale >24h (self-heal reindex), safety copy behind (self-heal push, alert on failure). 12h anti-spam per alert key.

**Exit gate:** owner performs one real dispatch; stats show the logged decisions; watchdog clean. (The Checkpoint 3 demonstration happens after phase 6, combining this first dispatch with the always-on integration reveal.)

### Phase 4: Autonomous judge (install DORMANT, never on by default)

**What gets installed:** `scripts/gate_judge.py` driven by `prompts/judge.md`, a strong-model job judging each candidate: `approve | edit | discard | escalate`; mandatory semantic dedup; structured output with polished final text (owner's language), 2-4 validated `related` links (NFC), optional destination redirect (complement an existing note instead of creating an isolated one). Deterministic appliers write with `approved_by` provenance. STRUCTURAL escalation: facts about people's roles/identity, contradiction with active notes, employer/client-identifiable material, unknown destinations, past the cap (max 10 applications/run), all delete/merge/supersede. Bias: in doubt, discard or escalate.

Escalation precedence (fixed order, so two installers behave identically): 1 dedup, 2 too-specific/not-general, 3 person-role/identity, 4 confidentiality, 5 contradiction, 6 unknown destination, 7 blast-radius cap. "Contradiction" detection is the STRONG MODEL's judgment call (do not fake it with brittle string heuristics); the deterministic layer only enforces the escalation rules and the appliers.

Install and verify against the fixed synthetic fixture set already shipped in `tests/` (6 fixtures covering: a clear duplicate, a contradiction with an active note, a person-role fact, a good general lesson, a too-specific detail, an unknown destination; expected outcomes respectively: discard, escalate, escalate, approve, discard, escalate) and already proven once in Phase -1; re-run here against this owner's real config to confirm the wiring, not to re-litigate the fixtures. Note honestly: fixtures validate the structural layer and the wiring; the model's DISCERNMENT is only validated later by the phase 3A backtest. Leave OFF. Turn-on procedure (documented in the vault): when the eligibility rule from phase 3A is met, backtest the judge against 20+ logged human decisions, show agreement to the owner, and only enable on their yes.

**Exit gate:** all 6 fixture outcomes correct on this installation; production wiring NOT enabled; turn-on note exists.

### Phase 5: Self-maintenance

**Spec:** `scripts/brain_aging.py`, a monthly aging pass (sample up to 15 dynamic notes unchecked 90+ days vs the owner's 00-HOME ground truth; auto-mark `stale` reversibly; escalate direct contradictions; state file in telemetry) + the connection audit from phase 1.5 re-run quarterly for new islands, scheduled via `templates/services/`.

**Exit gate:** the aging fixtures shipped in `tests/` (1 note contradicting the seed notes, expected escalated; 1 outdated-but-not-contradicting note, expected stale) pass on this installation; both jobs scheduled.

### Phase 6: Always-on integration (the piece that makes the brain part of every conversation)

Without this phase the owner has a brain that feeds and maintains itself but their everyday Claude never consults it. This phase wires the brain into EVERY session, rendering from `templates/hooks/` and `templates/commands/`:

1. **Global Claude configuration** (the owner's `~/.claude/CLAUDE.md`, created or extended preserving existing content): a brain section stating: where the vault lives; how to search it (`query.sh`, with the instance_id verification); the AUTO-INVOCATION rule (any question touching the owner's identity, projects, past decisions, history or preferences: search the brain BEFORE answering, cite note paths, and say honestly "not found in your notes" instead of inventing); the write rule (learnings become gate-queue candidates unless the owner gives a direct order to save); and the owner's language rule.
2. **Session-start briefing hook** (`templates/hooks/session_start_briefing.sh`): on every new session, inject a compact briefing built from the owner's identity and current-focus notes (hard token budget: keep the whole injection under ~4k tokens; head-limit each section; this budget is part of the spec, an oversized briefing degrades every session).
3. **Per-question retrieval hook** (`templates/hooks/user_prompt_retrieval.sh`): on each owner prompt, query the daemon (verifying instance_id) and inject only hits above a relevance threshold, top 3-5, as context with the instruction to Read the full notes before relying on them; below-threshold means inject nothing (silence is better than noise).
4. **Two commands** (`templates/commands/ask-brain.md`, `templates/commands/save-brain.md`, rendered in the owner's language): a query command ("ask my brain") and a save command ("save this: ..." = direct order, applies with provenance and reports caveats in one line; without a direct order, everything goes to the gate queue as a candidate).
5. **Other agent CLIs (multi-harness adapters).** The brain is one; each CLI gets the same contract adapted to its environment. Claude Code gets the deepest integration (the hooks above); every other tool integrates through STANDING INSTRUCTIONS in its global context file. Detect what is installed and render, extending (never overwriting) any existing file: Codex and any AGENTS.md-reading CLI (Cursor and most newer agent CLIs follow this convention) get `templates/context/AGENTS.md.template` rendered into their global context (for Codex: `~/.codex/AGENTS.md`); the Gemini CLI gets `templates/context/GEMINI.md.template` rendered into `~/.gemini/GEMINI.md`. If the owner names another agent CLI (present or future, e.g. a Grok CLI), render the AGENTS template into whatever global context file that tool reads: the contract is tool-agnostic by design. Tell the owner plainly which of their AI tools now know the brain and which integrate deeper (Claude Code) vs by instruction.

**Exit gate:** open a FRESH session and verify: (a) it answers "who am I and what am I focused on?" correctly from the briefing without searching; (b) a question about an old note triggers the retrieval hook and the answer cites the note path; (c) the measured briefing cost is within budget; (d) a session in a random directory (not the vault) still has the brain available; (e) if another agent CLI was detected and wired (Codex/Gemini/other), one question about an old note in THAT tool also comes back citing the note path (instruction-based path proven, not just rendered). **Checkpoint 3 (demonstration, the strongest of the install):** the owner opens a brand-new conversation and their Claude already knows them; then they perform their first weekly dispatch.

### Final report to the owner (their language, mandatory, under 15 lines)

What their brain now does, the one weekly habit, the 3 phrases they can always say ("what did I decide about...", "save this: ...", "how is my brain doing?"), what phone alerts mean, how to undo anything, and how to rotate the notification channel.

*Kit v1.8 (Phase -1 preflight: the kit clones itself and proves its own tests before touching the owner's machine; the installing Claude renders config and templates only, it never writes core logic). Methodology: Gabriel Alonso. Contains no personal data: every installation generates its own credentials, channels and content.*
