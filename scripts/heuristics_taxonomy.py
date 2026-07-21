#!/usr/bin/env python3
"""Two-axis heuristics clustering taxonomy, SINGLE SOURCE OF TRUTH.

Axis 1 (nature): WHERE the rule should ACT in the system. Four base types
plus a fifth, honest extension: the corpus of any real vault has dated,
one-off project choices that are not reusable rules; forcing one of them
into the four reusable types would be fabrication, so a fifth value exists
for that case alone.
Axis 2 (domain): the TYPE of decision the rule guides (deploy, design, and
so on).

Consumers: scripts/gate_judge.py (the classification criterion at daily
intake, see prompts/judge.md criterion 10) and scripts/classify_heuristics.py
(the re-runnable backfill and route audit). Changing the vocabulary here
means both consumers, prompts/judge.md and prompts/distill_daily.md pick it
up automatically (they read vocab_prompt() or the dicts directly); no other
file should ever hardcode a nature or domain value.

Note on naming: the "promotion" concept this taxonomy feeds (see
gate_judge.apply_promotion) is unrelated to gate_log.py's
"eligible_for_promotion" (the judge auto-approve eligibility rule for a
candidate type). Two different ideas share an English word; do not conflate
them when reading the code.
"""

# nature -> short description (used in prompts and reports)
NATURES = {
    "decision-tree": "a reproducible, step-by-step conditional (if X, do Y); acts as a SKILL",
    "score": "a measurable quality or approval criterion; acts as a QUALITY GATE",
    "judgment": "a decision pattern that requires weighing context; feeds agent prompts or briefs",
    "axiom": "an invariant rule (never or always); acts in GOVERNANCE (CLAUDE.md, rules, hooks)",
    "one-off-decision": "a dated choice from one project or moment, not a reusable rule; stays as a historical RECORD",
}

# domain -> short description (the type of decision it guides)
DOMAINS = {
    "verification-qa": "validation, tests, QA, checking the real thing instead of a proxy",
    "deploy-delivery": "deploy, release, production, delivery to third parties",
    "architecture-code": "system design, reuse, native versus custom, refactor",
    "ai-orchestration": "agents, subagents, workflows, model choice or cost, prompts",
    "data-facts": "evidence, fabrication, numbers, provenance, sources",
    "communication-copy": "messages, tone, language, copy, presentations",
    "security-privacy": "secrets, personal data, compliance boundaries, permissions",
    "git-versioning": "commits, branches, revert, pre-action backup, version control",
    "process-workflow": "ceremony, checkpoints, scope, intake, estimates, rituals",
    "business-strategy": "pricing, positioning, clients, partnerships, the offer",
}

# route derived DETERMINISTICALLY from nature (the model never decides the route)
ROUTE = {
    "decision-tree": "skill",
    "score": "quality-gate",
    "judgment": "agent-brain",
    "axiom": "governance",
    "one-off-decision": "record",
}


def validate(nature, domain):
    """Normalize and validate against the closed vocabulary; invalid becomes ''.

    Never invents or corrects a value: an out-of-vocabulary input is treated
    the same as a missing one.
    """
    n = (nature or "").strip().lower()
    d = (domain or "").strip().lower()
    return (n if n in NATURES else ""), (d if d in DOMAINS else "")


def class_label(nature, domain):
    """Canonical 'nature · domain' string written into lessons, patterns and
    decision notes; '' when either axis is invalid or missing.

    The middle dot (not a pipe) is deliberate: this label is written inside
    markdown table cells (lessons rows) where a literal '|' would silently
    add a phantom column.
    """
    n, d = validate(nature, domain)
    return f"{n} · {d}" if n and d else ""


def vocab_prompt():
    """Vocabulary block ready to inject into classification prompts."""
    nat = "\n".join(f"- {k}: {v}" for k, v in NATURES.items())
    dom = "\n".join(f"- {k}: {v}" for k, v in DOMAINS.items())
    return (f"NATURE axis (where the rule should ACT):\n{nat}\n\n"
            f"DOMAIN axis (the type of decision it guides), pick ONE:\n{dom}")
