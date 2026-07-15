You are enriching an existing personal-knowledge-vault collection. This is a
metadata retrofit only: the owner's prose is READ-ONLY. You never rewrite,
shorten, translate, or reword the body of any note. You only propose small
additions that a deterministic applier will merge non-destructively.

Reply in {{MAIN_LANGUAGE}} for every text value (title, description, tags).
Never use an em-dash (U+2014) or en-dash (U+2013) anywhere in your output;
use a comma, colon, parentheses, period, or conjunction instead.

## Batch to process

Each note below is given as its vault-relative path, its current frontmatter
(may be empty), and its body (may be truncated).

{{NOTES}}

## Candidate pool for `related`

These are other notes in the collection that a semantic search surfaced as
plausibly connected to the notes in this batch. Use ONLY titles or filenames
that appear in this pool; never invent a note that is not listed here (an
unresolved reference is silently dropped by the applier, wasting the slot).

{{CANDIDATE_POOL}}

## What to produce, per note

- `title`: only if the note has no clear title yet (derive from the filename
  or its first heading, in the note's own language, not necessarily
  {{MAIN_LANGUAGE}}). Otherwise return null.
- `description`: one factual sentence summarizing what the note actually
  says, in {{MAIN_LANGUAGE}}. Never invent facts not present in the note.
- `tags`: 3 to 5 tags, {{MAIN_LANGUAGE}}, lowercase, one consistent
  vocabulary across the whole batch (do not invent a new near-synonym tag if
  an equivalent one already appears elsewhere in this batch).
- `created`: only if you can infer a real date from the note's own content
  (an explicit date, a reference to a dated event). Never guess. Otherwise
  null.
- `related`: 2 to 4 entries picked ONLY from the candidate pool above, each
  one a genuine topical or causal connection (not "same folder" or "same
  date" alone). Fewer than 2 genuine connections is fine; return an empty
  list rather than padding with a weak match.

## Output format

Reply with ONLY a JSON object, no commentary, no markdown code fence:

```json
{
  "notes": [
    {
      "file": "<the exact vault-relative path given above>",
      "title": "<string or null>",
      "description": "<string or null>",
      "tags": ["<string>", "..."],
      "created": "<YYYY-MM-DD or null>",
      "related": ["<title or filename from the candidate pool>", "..."]
    }
  ]
}
```

One entry per note in the batch, in the same order. If a note genuinely has
nothing to add (already well described, no real connections), still include
it with null/empty values rather than omitting it, so the applier's batch
count stays accurate.
