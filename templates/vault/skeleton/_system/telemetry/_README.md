# _system/telemetry

Machine-written telemetry only: judge decisions (approve/edit/discard/escalate) per run,
eligibility-rule tracking data, escalation-vs-reversion counts. Written by the
deterministic pipeline scripts, never by hand.

`_system/` as a whole is excluded from knowledge queries and retrieval indexing (see
`config.taxonomy.index_exclude`); nothing here is meant to be read as vault content.
