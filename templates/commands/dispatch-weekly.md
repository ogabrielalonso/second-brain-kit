---
description: REVIEW of the weekly brain ritual. The daily gate is AUTONOMOUS (judge); the scheduled weekly job already ran lint, digest and a newsletter draft on its own. This command presents what landed in canon this week, resolves anything escalated, and refines the newsletter draft. Triggers on natural language ("review the weekly", "what landed this week", "resolve the escalations").
---

# /dispatch-weekly

Human-in-the-loop review layer on top of the autonomous weekly job
(`scripts/brain_weekly_auto.py`), which already produced a digest under
`{{WEEKLY_DIR}}` before this command runs. This command never
re-runs the judge, it reviews what the judge already decided and resolves what it
escalated.

## What it does

1. Read this week's digest note under `{{WEEKLY_DIR}}` (most recent
   file), summarize in a few lines: how many candidates were approved / edited /
   discarded / escalated.
2. List everything currently sitting in `{{QUEUE_DIR}}` (the escalation
   queue): one line per item, with the reason it was escalated (person/role fact,
   contradiction with an `active` note, unresolved destination, delete/merge request).
3. For each escalated item, ask the owner what to do (in the owner's `main_language`,
   {{MAIN_LANGUAGE}}); do not resolve escalations on your own judgment. Once decided:
   write it exactly like `/save-brain` would (correct destination, correct `status`,
   scoped commit), then remove or archive the item from the queue.
4. If a newsletter draft exists for the week, offer to refine it: tighten language,
   remove anything that reads as a client/person name that should stay anonymized per the
   vault's confidentiality patterns, confirm tone matches the owner's interaction
   preferences.

## Do NOT

- Silently resolve an escalated item without the owner's explicit decision, that defeats
  the entire point of escalation
- Re-run the daily/weekly pipeline scripts from inside this command, they are scheduled
  jobs, not something a chat session should trigger by hand except for debugging
- Treat a `draft`/`stale`/`superseded` note surfaced in the digest as current truth
