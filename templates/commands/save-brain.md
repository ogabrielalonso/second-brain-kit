---
description: USE proactively when a conversation produced a substantial learning (a real decision, a lesson learned, a new pattern, an insight) worth persisting to the owner's brain vault for future retrieval. Do NOT invoke for trivial notes, only when it is worth writing to canon.
---

# /save-brain

Writes a candidate into the vault under the gate rules defined in `CLAUDE.md`. This
command covers the **interactive session** path only; the autonomous daily pipeline
(distill -> judge -> apply) covers everything captured outside of a live conversation.

## When to use it

- The owner explicitly said something like "save this" in this session: the content is
  already approved, write it now and report caveats in one line.
- Without an explicit order: propose the note in 1-2 lines instead of writing it
  directly, and let the owner confirm, or leave it for the daily pipeline to evaluate
  later if it was already captured elsewhere (a saved conversation, for example).

## How to invoke

1. Identify the right destination from `config.taxonomy` (a decision -> `decisions_dir`;
   a lesson/pattern -> the mapped heuristics location if one is configured; anything else
   -> the most specific existing note, do not create a new top-level file speculatively).
2. Check for an existing note on the same topic first (semantic search via `/ask-brain`,
   plus accent-folded word-overlap on the title), dedup before writing.
3. Write with the required frontmatter for the note's type (see `CLAUDE.md`'s trust-axis
   table): `status: active` for something approved on the spot, or `status: draft` if
   this is a proposal awaiting confirmation.
4. If this supersedes an existing note, do NOT delete the old one: set
   `status: superseded` and `superseded_by: "[[New note]]"` on it, this step always needs
   the owner's explicit yes, never do it silently.
5. Commit with a scoped `git add` (only the paths touched), never `git add -A`.

## Do NOT

- Fabricate a fact, a number, a severity, or a person's role to fill a template field
- Delete or merge notes without an explicit human decision
- Write secrets (passwords, tokens, connection strings) into any vault note, point at
  where the secret lives instead
- Answer in a language other than the owner's `main_language` ({{MAIN_LANGUAGE}}) unless
  asked to
