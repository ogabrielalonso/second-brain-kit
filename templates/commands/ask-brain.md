---
description: USE whenever the owner asks a question about themselves, their projects, past decisions, lessons learned, work patterns, or anything specific to their brain vault. Runs a semantic search over the whole vault (local, fast, via the brain daemon). Also triggers automatically in natural language when a prompt touches personal/project context, this command is the manual interface for the same search.
---

# /ask-brain

Manual interface to the brain's semantic search. The `UserPromptSubmit` hook already
auto-injects hits above the configured score threshold; use this command to reformulate
a query, apply filters, or ask for more results than the hook injected.

## How to invoke

```bash
{{KIT_DIR}}/scripts/query.sh "<question reformulated in searchable terms>" --top-k 10 --json
```

Daemon on `127.0.0.1:<port>` (port derived from the vault path, see
`docs/ARCHITECTURE.md`). Health: `curl -s 127.0.0.1:<port>/health` (also verify
`instance_id` matches `~/.brain/config.json` before trusting the answer, in case another
brain-kit daemon is running on this machine).

After the query returns: parse the JSON, for the top 3-5 chunks with a meaningful score,
**Read the original note** (full context), then answer with that real content, **citing
paths**.

## Filters

- `--min-score 0.5` (cuts noise) · `--compact` · `--mode auto` (scales top-k with confidence)
- `--source <value>` · `--type <value>` (values come from this vault's own frontmatter, not
  a fixed list, check a few notes if unsure)
- `--tag <substring>` · `--chunk-type index|section|table_row|block`

## Reindexing

After a batch of new notes, or a structural refactor of the vault:

```bash
{{KIT_DIR}}/scripts/embed.sh
```

The daemon reloads on its own. Real counts live in the index manifest or the `/health`
endpoint, never trust a hardcoded number in a doc.

## Do NOT

- Stop at a low score (below ~0.4) without trying a reformulated query
- Rely only on title/description, chunking finds content deep inside notes too
- Name a client or a third party by their real name in output shared outside the owner's
  own tools, if the vault marks something confidential
- Invent an answer: a query with no relevant result means "I found no evidence in the
  brain about X," said plainly, in the owner's configured `main_language`
  ({{MAIN_LANGUAGE}})
