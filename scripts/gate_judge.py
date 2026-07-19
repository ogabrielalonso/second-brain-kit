#!/usr/bin/env python3
"""gate_judge: autonomous judge for the brain gate.

Once config.judge_enabled is true, the owner does not review candidates day to
day: the EVALUATOR is a strong model with the owner's judgment criteria encoded
in prompts/judge.md. Three-brain split:
  - whoever DISTILLS (cheap model, brain_daily) does not judge;
  - whoever JUDGES (strong model, this script) does not write;
  - whoever WRITES is deterministic code (the apply_* functions below).

Per-candidate decisions: approve | edit | discard | escalate. Escalation and
rejection are resolved in this fixed precedence (matching docs/ARCHITECTURE.md):
dedup, then too-specific/not durable (both fold into a judge-side discard),
then a person-role/identity fact, then a confidentiality boundary, then
contradiction with an existing active note (all three escalate), then an
unknown destination the deterministic applier cannot resolve (escalate), then
a run-level safety cap (escalate the remainder). The first three of those are
the strong model's call (encoded in prompts/judge.md); the last two are
revalidated here in code, in that order, so a destination is always checked
for resolvability before the cap is allowed to consume a slot.

Escalated items STAY in the queue for the owner; everything else flows and
becomes canon with provenance approved_by: brain-judge. Reverting is cheap
(git revert).

Telemetry: every decision goes to gate_log with decider=brain-judge; the judge's
quality metric becomes the rate of after-the-fact reversion by the owner.

This script depends only on brain_config.load_config() for owner state: never a
hardcoded path, and never one of brain_config's convenience helper functions
(taxonomy(), thresholds(), etc), so it keeps working even if those helpers
change shape. It reads the raw config dict and merges its own MODE B defaults.

Usage: gate_judge.py [--model opus] [--dry-run] [--max 20]
Env: BRAIN_CONFIG overrides the config file location (see brain_config.py); the
     judge always resolves the vault, taxonomy and thresholds through
     load_config(), never a separate path override.
"""
import os
import re
import sys
import json
import argparse
import datetime
import subprocess
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain_config import load_config

KIT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
PROMPT_FILE = KIT_ROOT / "prompts" / "judge.md"
GATE_LOG = SCRIPTS_DIR / "gate_log.py"
QUERY_SH = SCRIPTS_DIR / "query.sh"
CLAUDE_BIN = "claude"

# MODE B skeleton defaults (mirrors docs/ARCHITECTURE.md's config contract).
# Duplicated here on purpose: this script merges over the raw dict from
# load_config() itself instead of depending on brain_config's own default-
# merging helpers, so it keeps working even if those helpers are renamed or
# removed later.
DEFAULT_TAXONOMY = {
    "decisions_dir": "04-Journal/Decisions",
    "digests_dir": "04-Journal",
    "queue_dir": "04-Journal/gate-queue",
    "heuristics": {"lessons": "", "patterns": ""},
    "index_exclude": ["_system/", "Inbox/", "gate-queue/", "/templates/", "/history/"],
    "moc_map": {},
}
DEFAULT_MAX_APPLY_PER_RUN = 10
VALID_DECISIONS = ("approve", "edit", "discard", "escalate")
QUEUE_INDEX_NAME = "_GATE-QUEUE.md"


def brain_home():
    """Directory holding cache, state and logs; derived from wherever config.json
    actually resolves to (BRAIN_CONFIG override honored), computed here rather
    than imported from brain_config, per the kit's dependency contract."""
    return Path(os.environ.get("BRAIN_CONFIG", "~/.brain/config.json")).expanduser().parent


def merged_taxonomy(cfg):
    merged = dict(DEFAULT_TAXONOMY)
    owner_taxonomy = cfg.get("taxonomy") or {}
    merged.update(owner_taxonomy)
    # heuristics is a nested dict; merge one level deep so a config that only
    # sets "lessons" does not lose the "patterns" default.
    heuristics = dict(DEFAULT_TAXONOMY["heuristics"])
    heuristics.update(owner_taxonomy.get("heuristics") or {})
    merged["heuristics"] = heuristics
    return merged


def log(msg, log_path):
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] [judge] {msg}"
    print(line)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def notify(msg):
    try:
        from notify import send
    except Exception:
        return
    hot = "FAILED" in msg
    send(msg, title="gate-judge", priority="high" if hot else None,
         tags="warning" if hot else "brain")


def update_moc_inbox(vault, moc_map, written_rel, today, touched):
    """Deterministically register the new/touched note in the area's entry MOC,
    per config.taxonomy.moc_map. Without this, notes accumulate outside any MOC
    until the next weekly curation pass, invisible in the meantime."""
    for prefix, moc_rel in (moc_map or {}).items():
        if not written_rel.startswith(prefix):
            continue
        moc = vault / moc_rel
        if not moc.exists():
            return
        stem = Path(written_rel).stem
        txt = moc.read_text(encoding="utf-8")
        if f"[[{stem}]]" in txt or f"[[{stem}|" in txt:
            return  # already referenced in this MOC
        header = "## Recent entries (auto-gate)"
        link = f"- [[{stem}]] (auto-gate {today})"
        if header in txt:
            idx = txt.index(header) + len(header)
            txt = txt[:idx] + "\n" + link + txt[idx:]
        else:
            txt = (txt.rstrip("\n") + f"\n\n{header}\n{link}\n\n"
                   "> Section maintained by code (autonomous gate); weekly curation\n"
                   "> files these entries into the thematic sections of the MOC.\n")
        moc.write_text(txt, encoding="utf-8")
        touched.append(moc)
        return


def index_decision_row(decisions_dir, fp, title, today, touched):
    """Append the new decision's row to the decisions index (deterministic; kept
    in sync automatically instead of drifting until someone edits it by hand)."""
    index_fp = decisions_dir / "INDEX.md"
    if not index_fp.exists():
        return
    txt = index_fp.read_text(encoding="utf-8")
    if f"[[{fp.stem}" in txt:
        return
    lines = txt.split("\n")
    rows = [i for i, l in enumerate(lines) if re.match(r"^\|\s*2\d{3}-\d{2}-\d{2}\s*\|", l)]
    if not rows:
        return
    safe_title = title.replace("|", "/")[:90]
    lines.insert(rows[-1] + 1, f"| {today} | [[{fp.stem}\\|{safe_title}]] | vault | active |")
    index_fp.write_text("\n".join(lines), encoding="utf-8")
    touched.append(index_fp)


def render_judge_prompt(cands, cfg, vault):
    blob = ""
    for c in cands:
        blob += f"\n--- CANDIDATE {c['file']} (type: {c['type']}, proposed destination: {c['destination']}) ---\n{c['body'][:2000]}\n"
    prompt = PROMPT_FILE.read_text(encoding="utf-8")
    repl = {
        "{{OWNER_NAME}}": cfg.get("owner_name") or "the owner",
        "{{OWNER_CONTEXT}}": cfg.get("owner_context") or "",
        "{{MAIN_LANGUAGE}}": cfg.get("main_language") or "en-US",
        "{{VAULT}}": str(vault),
        "{{QUERY_SH}}": str(QUERY_SH),
        "{{CANDIDATES}}": blob,
    }
    for k, v in repl.items():
        prompt = prompt.replace(k, v)
    return prompt


def resolve_related(vault, names):
    """Validate the judge's proposed related notes against the REAL vault: only
    a wikilink that resolves is allowed into the canon (a broken link never
    enters). Comparison is NFC-normalized: some filesystems store names in NFD
    while the LLM tends to answer in NFC, so a naive comparison would miss real
    matches."""
    if not names:
        return []
    nfc = lambda s: unicodedata.normalize("NFC", s)
    existing = {nfc(p.stem): p.stem for p in vault.rglob("*.md")
                if "_system" not in p.parts and ".obsidian" not in p.parts}
    out = []
    for n in names:
        if isinstance(n, str) and nfc(n.strip()) in existing:
            out.append(existing[nfc(n.strip())])
    return out[:4]


def fm_field(txt, field):
    m = re.search(rf"^{field}:\s*[\"']?(.*?)[\"']?\s*$", txt, re.M)
    return m.group(1) if m else ""


def load_queue(queue_dir, max_n):
    if not queue_dir.exists():
        return []
    out = []
    for p in sorted(queue_dir.glob("*.md")):
        # Underscore-prefixed files are scaffolding (the queue index, the
        # skeleton's _README.md), never candidates: judging them meant the
        # first real run DELETED the owner's _README via the discard path.
        # Same criterion as the watchdog's queue count (test_queue_hygiene.py).
        if p.name.startswith("_"):
            continue
        txt = p.read_text(encoding="utf-8")
        # already escalated in a previous round: waits for a HUMAN decision;
        # re-judging it every run would burn the strong model for nothing and
        # duplicate it in the digest
        if fm_field(txt, "escalated_at"):
            continue
        out.append({"path": p, "file": p.name, "type": fm_field(txt, "type"),
                    "title": fm_field(txt, "title"),
                    "destination": fm_field(txt, "proposed_destination"), "body": txt})
        if len(out) >= max_n:
            break
    return out


def stamp_escalated(path, reason, today, log_path, touched):
    """Mark the queue file as escalated in its frontmatter; future runs skip it."""
    txt = path.read_text(encoding="utf-8")
    if txt.startswith("---\n") and "escalated_at:" not in txt:
        extra = f'escalated_at: {today}\nescalated_reason: "{(reason or "")[:120]}"\n'
        txt = txt.replace("---\n", "---\n" + extra, 1)
        path.write_text(txt, encoding="utf-8")
    elif "escalated_at:" not in txt:
        # no standard frontmatter: cannot stamp it; without this log the item
        # would be silently re-judged forever
        log(f"WARNING: could not stamp escalated_at on {path.name} (no '---' frontmatter); it will be re-judged", log_path)
    touched.append(path)


def run_judge(cands, model, cfg, vault, workspace):
    prompt = render_judge_prompt(cands, cfg, vault)
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run([CLAUDE_BIN, "-p", prompt, "--model", model,
                            "--output-format", "json",
                            "--allowedTools", f"Read,Grep,Glob,Bash({QUERY_SH}:*)"],
                           cwd=workspace, capture_output=True, text=True, timeout=1800)
    except FileNotFoundError:
        return None, "claude binary not found on PATH"
    if r.returncode != 0:
        return None, f"judge failed rc={r.returncode}: {r.stderr[:300]}"
    try:
        result = json.loads(r.stdout).get("result", "")
    except json.JSONDecodeError:
        result = r.stdout
    m = re.search(r"\[.*\]", result, re.DOTALL)
    if not m:
        return None, f"judge returned no JSON: {result[:300]}"
    try:
        return json.loads(m.group(0)), None
    except json.JSONDecodeError as e:
        return None, f"invalid JSON from judge: {e}"


# ---------- deterministic appliers (the LLM decides, the code writes) ----------
#
# Split in two phases on purpose: resolve_destination() is pure (no disk writes)
# so the main loop can check "can this even be applied" and "is there still cap
# budget" in the right order (destination before cap, per the fixed precedence)
# before anything is committed to disk; apply_resolved() does the actual write.

def apply_lesson(vault, lessons_rel, verdict, today, touched):
    if not lessons_rel:
        return None
    fp = vault / lessons_rel
    if not fp.exists():
        return None
    txt = fp.read_text(encoding="utf-8")
    nums = [int(m) for m in re.findall(r"^\|\s*(\d+)\s*\|", txt, re.M)]
    n = (max(nums) + 1) if nums else 1
    lesson = verdict["final_content"].replace("|", "/").replace("\n", " ").strip()
    how = verdict.get("discovered_via", "auto-gate").replace("|", "/")
    row = f"| {n} | {lesson} | {how} | brain-daily+brain-judge {today} |\n"
    lines = txt.rstrip("\n").split("\n")
    table_rows = [i for i, l in enumerate(lines) if l.startswith("|")]
    if not table_rows:
        return None
    last_row = max(table_rows)
    lines.insert(last_row + 1, row.rstrip("\n"))
    fp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    touched.append(fp)
    return f"L-{n:03d} in {fp.name}"


def apply_pattern(vault, patterns_rel, verdict, today, touched):
    if not patterns_rel:
        return None
    fp = vault / patterns_rel
    if not fp.exists():
        return None
    txt = fp.read_text(encoding="utf-8")
    title = verdict.get("title") or verdict["file"].split("-", 3)[-1].replace(".md", "").replace("-", " ")
    block = (f"\n## {title.strip().capitalize()}\n{verdict['final_content'].strip()}\n"
             f"- **Provenance:** brain-daily+brain-judge {today}\n")
    fp.write_text(txt.rstrip("\n") + "\n" + block, encoding="utf-8")
    touched.append(fp)
    return f"new section in {fp.name}"


def apply_decision(vault, decisions_dir_rel, verdict, today, title, touched):
    decisions_dir = vault / decisions_dir_rel
    slug = re.sub(r"[\s_]+", "-", re.sub(r"[^\w\s-]", "", title.lower()))[:60]
    fp = decisions_dir / f"{today}-{slug}.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    rel = resolve_related(vault, verdict.get("related", []))
    rel_fm = ("\nrelated: [" + ", ".join(f'"[[{r}]]"' for r in rel) + "]") if rel else ""
    rel_body = ("\n\n## Related\n\n" + "\n".join(f"- [[{r}]]" for r in rel)) if rel else ""
    fp.write_text(f"""---
type: note
title: "{title}"
description: "Decision graduated by the autonomous gate (brain-judge) on {today}"
status: active
approved_by: brain-judge
created: {today}{rel_fm}
---

{verdict['final_content'].strip()}{rel_body}

*Graduated automatically by the autonomous gate on {today}; revert via git if needed.*
""", encoding="utf-8")
    touched.append(fp)
    index_decision_row(decisions_dir, fp, title, today, touched)
    return f"{decisions_dir_rel}/{fp.name}"


def _resolve_md_target(vault, index_exclude, destination):
    """Resolve a proposed destination string to a real, existing .md file inside
    the vault, or None. Never returns a path outside the vault or a non-.md
    file; ambiguous basename matches (more than one hit) are refused rather
    than guessed."""
    vault_resolved = vault.resolve()
    clean = re.sub(r"\s*\(.*?\)\s*", "", destination).strip().strip("`")
    target = (vault_resolved / clean).resolve()
    if not target.exists():
        base = Path(clean).name
        if base.endswith(".md"):
            excluded = [tok.strip("/") for tok in (index_exclude or []) if tok.strip("/")]
            hits = [p for p in vault_resolved.rglob(base)
                    if not any(tok in p.relative_to(vault_resolved).parts for tok in excluded)]
            if len(hits) == 1:
                target = hits[0].resolve()
    if not str(target).startswith(str(vault_resolved)) or not target.exists() or target.suffix != ".md":
        return None
    return target


def resolve_destination(cand, verdict, vault, taxonomy):
    """Pure: decide which applier will receive this candidate; no disk writes.
    Returns a dict describing the target, or None when nothing resolves (the
    caller must then escalate: an unknown destination is never invented)."""
    lessons_rel = (taxonomy.get("heuristics") or {}).get("lessons") or ""
    patterns_rel = (taxonomy.get("heuristics") or {}).get("patterns") or ""
    decisions_dir_rel = taxonomy.get("decisions_dir") or ""
    index_exclude = taxonomy.get("index_exclude") or []

    # An EXPLICIT final_destination wins over the candidate's type (criterion 9
    # in prompts/judge.md: the judge may redirect a lesson into an existing note
    # instead of creating an isolated one).
    redirect = (verdict.get("final_destination") or "").strip()
    if redirect and redirect.endswith(".md"):
        target = _resolve_md_target(vault, index_exclude, redirect)
        if target:
            return {"kind": "generic", "target": target}

    dest = (cand["destination"] or "").strip()
    ctype = (cand["type"] or "").lower()
    if lessons_rel and dest and Path(dest).name == Path(lessons_rel).name and (vault / lessons_rel).exists():
        return {"kind": "lesson"}
    if patterns_rel and dest and Path(dest).name == Path(patterns_rel).name and (vault / patterns_rel).exists():
        return {"kind": "pattern"}
    if decisions_dir_rel and dest.startswith(decisions_dir_rel):
        return {"kind": "decision"}
    if dest.endswith(".md"):
        target = _resolve_md_target(vault, index_exclude, dest)
        if target:
            return {"kind": "generic", "target": target}
    # The type is the fallback when no destination string resolves.
    if ctype == "lesson" and lessons_rel and (vault / lessons_rel).exists():
        return {"kind": "lesson"}
    if ctype == "heuristic" and patterns_rel and (vault / patterns_rel).exists():
        return {"kind": "pattern"}
    if ctype == "decision" and decisions_dir_rel:
        return {"kind": "decision"}
    return None


def apply_resolved(resolution, cand, verdict, today, vault, taxonomy, touched):
    """Impure: perform the write described by `resolution` (from
    resolve_destination). Returns the display string for the digest, or None."""
    kind = resolution["kind"]
    if kind == "lesson":
        lessons_rel = (taxonomy.get("heuristics") or {}).get("lessons") or ""
        return apply_lesson(vault, lessons_rel, verdict, today, touched)
    if kind == "pattern":
        patterns_rel = (taxonomy.get("heuristics") or {}).get("patterns") or ""
        return apply_pattern(vault, patterns_rel, verdict, today, touched)
    if kind == "decision":
        decisions_dir_rel = taxonomy.get("decisions_dir") or ""
        return apply_decision(vault, decisions_dir_rel, verdict, today,
                              cand["title"] or "Untitled decision", touched)
    if kind == "generic":
        target = resolution["target"]
        txt = target.read_text(encoding="utf-8")
        title = verdict.get("title") or "Entry from the autonomous gate"
        rel = resolve_related(vault, verdict.get("related", []))
        rel_line = ("\nSee also: " + " | ".join(f"[[{r}]]" for r in rel) + "\n") if rel else ""
        block = f"\n## {title} (auto-gate {today})\n\n{verdict['final_content'].strip()}\n{rel_line}"
        target.write_text(txt.rstrip("\n") + "\n" + block, encoding="utf-8")
        touched.append(target)
        rel_path = str(target.relative_to(vault.resolve()))
        update_moc_inbox(vault, taxonomy.get("moc_map") or {}, rel_path, today, touched)
        return rel_path
    return None


def telemetry(file, ctype, decision, destination, reason):
    subprocess.run([sys.executable, str(GATE_LOG), "add", "--file", file, "--type", ctype or "unknown",
                    "--decision", decision, "--destination", destination or "",
                    "--note", f"decider: brain-judge; {reason[:150]}"],
                   capture_output=True, text=True)


def rebuild_index(queue_dir, today, touched):
    queue_index = queue_dir / QUEUE_INDEX_NAME
    pend = sorted(p.name for p in queue_dir.glob("*.md") if p.name != QUEUE_INDEX_NAME)
    lines = ["# Brain gate queue", "",
             "> Dispatch is AUTONOMOUS (brain-judge) once judge_enabled is true. This",
             "> queue holds only ESCALATED items: cases that require human judgment",
             "> (a person's identity or role, contradiction with canon, unknown",
             "> destination). Review whenever convenient.", "",
             f"Escalated pending: {len(pend)} (updated {today})", ""]
    lines += [f"- [[{n[:-3]}]]" for n in pend] if pend else ["_No escalated items pending._"]
    queue_index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    touched.append(queue_index)


def write_digest_note(vault, digests_dir_rel, stats, digest, today, touched):
    """The day's digest as a dated section in a searchable monthly note (before
    this, 'what did the gate decide' lived only in commit messages, invisible to
    retrieval). One chunk per '## ' section keeps daily granularity searchable."""
    month = today[:7]
    fp = vault / digests_dir_rel / f"Gate-Digests-{month}.md"
    if not fp.exists():
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(f"""---
type: note
title: "Gate Digests {month}"
description: "Daily digest of the autonomous gate (brain-judge) for {month}: what entered the canon, what was discarded, and what escalated for review"
status: active
generated_by: gate-judge-pipeline
created: {today}
tags:
  - autonomous-gate
  - digest
  - decision
---

# Gate Digests {month}

> One section per day, generated by the autonomous gate (gate_judge.py). Review
> after the fact: revert via git anything you disagree with; escalated items
> live in the gate queue index.
""", encoding="utf-8")
    txt = fp.read_text(encoding="utf-8")
    line = (f"approved: {stats['approved']} | edited: {stats['edited']} | "
            f"discarded: {stats['discarded']} | escalated: {stats['escalated']}")
    if f"## {today}" in txt:
        # additional run the same day (a retry slot): appended INTO the existing
        # section (always the last one, chronological order); a second heading
        # for the same day would duplicate the daily chunk in retrieval
        hour = datetime.datetime.now().strftime("%H:%M")
        block = (f"\n**Additional run ({hour}):** {line}\n\n"
                 + "\n".join(f"- {d}" for d in digest) + "\n")
    else:
        block = f"\n## {today}\n\n{line}\n\n" + "\n".join(f"- {d}" for d in digest) + "\n"
    fp.write_text(txt.rstrip("\n") + "\n" + block, encoding="utf-8")
    touched.append(fp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="opus")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int, default=20)
    args = ap.parse_args()
    today = datetime.date.today().isoformat()

    cfg = load_config()
    vault = Path(cfg["vault_path"]).expanduser()
    taxonomy = merged_taxonomy(cfg)
    home = brain_home()
    log_path = home / "logs" / "gate-judge.log"
    workspace = home / "daily-workspace"
    queue_dir = vault / taxonomy["queue_dir"]

    def _log(msg):
        log(msg, log_path)

    touched = []

    cands = load_queue(queue_dir, args.max)
    if not cands:
        _log("queue empty; nothing to judge")
        return

    # Blast-radius cap: maximum applications to the canon per run
    # (config.thresholds.max_apply_per_run, default 10); approved items ABOVE
    # this cap escalate instead. Protects the canon from a hallucinating judge
    # on a catch-up day with a large queue. Read straight from config: this is
    # the single documented source for the value (gate_log's own policy file
    # tracks auto-approve promotions, a different concern).
    cap = (cfg.get("thresholds") or {}).get("max_apply_per_run", DEFAULT_MAX_APPLY_PER_RUN)
    _log(f"judging {len(cands)} candidates with {args.model} (apply cap: {cap}/run)")

    verdicts, err = run_judge(cands, args.model, cfg, vault, workspace)
    if err:
        _log(err)
    if verdicts is None:
        notify("gate-judge: judge FAILED (see gate-judge.log); queue untouched")
        return
    by_file = {v.get("file", ""): v for v in verdicts}

    stats = {"approved": 0, "edited": 0, "discarded": 0, "escalated": 0}
    digest = []
    for c in cands:
        v = by_file.get(c["file"])
        if not v:
            stats["escalated"] += 1
            digest.append(f"ESCALATED (no verdict from judge): {c['title']}")
            continue
        decision = v.get("decision", "escalate")
        if decision not in VALID_DECISIONS:
            # a verdict outside the enum would become a ghost item (no branch
            # handles it); house rule: when unsure, escalate
            v["reason"] = f"invalid verdict '{decision}' from judge; " + v.get("reason", "")
            decision = "escalate"
        if args.dry_run:
            digest.append(f"DRY {decision.upper()}: {c['title']} ({v.get('reason', '')})")
            continue

        if decision in ("approve", "edit"):
            # Fixed precedence: check whether a destination resolves BEFORE
            # spending a cap slot on it (unknown destination escalates
            # independently of how much cap budget remains).
            resolution = resolve_destination(c, v, vault, taxonomy)
            if resolution is None:
                decision = "escalate"
                v["reason"] = "unknown destination: the applier could not resolve a target; " + v.get("reason", "")
            elif (stats["approved"] + stats["edited"]) >= cap:
                decision = "escalate"
                v["reason"] = f"safety cap ({cap} applications/run) reached; " + v.get("reason", "")
            else:
                where = apply_resolved(resolution, c, v, today, vault, taxonomy, touched)
                if where is None:
                    decision = "escalate"
                    v["reason"] = "unknown destination: the applier could not resolve a target; " + v.get("reason", "")
                else:
                    c["path"].unlink()
                    touched.append(c["path"])
                    key = "approved" if decision == "approve" else "edited"
                    stats[key] += 1
                    telemetry(c["file"], c["type"], key, c["destination"], v.get("reason", ""))
                    digest.append(f"{key.upper()}: {c['title']} -> {where}")

        if decision == "discard":
            c["path"].unlink()
            touched.append(c["path"])
            stats["discarded"] += 1
            telemetry(c["file"], c["type"], "discarded", c["destination"], v.get("reason", ""))
            digest.append(f"DISCARDED: {c['title']} ({v.get('reason', '')})")
        elif decision == "escalate":
            stats["escalated"] += 1
            stamp_escalated(c["path"], v.get("reason", ""), today, log_path, touched)
            telemetry(c["file"], c["type"], "escalated", c["destination"], v.get("reason", ""))
            digest.append(f"ESCALATED: {c['title']} ({v.get('reason', '')})")

    if args.dry_run:
        print("\n".join(digest))
        return

    rebuild_index(queue_dir, today, touched)
    write_digest_note(vault, taxonomy.get("digests_dir", "04-Journal"), stats, digest, today, touched)

    # scoped commit: only this round's paths; unrelated changes stay with the owner
    from brain_git import commit_scoped
    ok = commit_scoped(
        vault, touched,
        f"feat(brain): autonomous gate {today}: {stats['approved']} approved, {stats['edited']} edited, "
        f"{stats['discarded']} discarded, {stats['escalated']} escalated\n\n"
        f"Judge: brain-judge (gate_judge.py). Digest:\n" + "\n".join(f"- {d}" for d in digest) +
        "\n\nCo-Authored-By: gate-judge <noreply@local>", log=_log)
    if not ok and touched:
        # canon written to disk but WITHOUT a commit means no reindex, no backup,
        # no auditable digest; this needs to reach the owner
        notify("gate-judge: changes applied but the COMMIT FAILED (see gate-judge.log); "
               "canon on disk without version control")
    _log("; ".join(f"{k}={v}" for k, v in stats.items()))
    notify(f"gate-judge: {stats['approved'] + stats['edited']} entered the canon, "
           f"{stats['discarded']} discarded, {stats['escalated']} escalated for review. Digest in git log.")


if __name__ == "__main__":
    main()
