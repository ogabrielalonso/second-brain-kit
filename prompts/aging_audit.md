You audit the AGING of a personal knowledge vault. Notes accumulate facts
that were true when written but drift out of date silently (a role that
changed, a project that ended, a number that moved on). Below is the CURRENT
ground truth (the owner's own up-to-date identity and focus notes), followed
by a sample of dynamic notes to check against it.

Reply in {{MAIN_LANGUAGE}} for the `reason` field of each verdict. Never use
an em-dash (U+2014) or en-dash (U+2013) anywhere in your output; use a comma,
colon, parentheses, period, or conjunction instead.

## Current ground truth

{{HOME_TRUTH}}

## Notes to audit

{{NOTES}}

## Verdicts

For each note, compare it against the ground truth above and choose exactly
one verdict:

- `"current"`: the facts in the note still hold.
- `"stale"`: the note may have aged (a dated fact, a project or number that
  likely moved on); it deserves a "cite with caution" flag. This is a
  reversible, low-stakes flag.
- `"superseded-candidate"`: the note asserts something the ground truth
  DIRECTLY CONTRADICTS (a wrong role, a project treated as active when the
  ground truth says it ended). This always needs a human supersede decision.

Be conservative: `"current"` is the default. `"stale"` requires a concrete
sign of aging. `"superseded-candidate"` requires an objective contradiction,
not a guess or a tone shift.

Reply with ONLY a JSON array, no commentary, no markdown code fence:

```json
[{"file": "<the exact vault-relative path given above>",
  "verdict": "current|stale|superseded-candidate",
  "reason": "<one sentence, in {{MAIN_LANGUAGE}}>"}]
```

One entry per note given, in the same order.
