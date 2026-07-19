#!/usr/bin/env python3
"""brain_aging: monthly anti-rot pass over the canon.

The daily gate takes care of what ENTERS the canon; this pass takes care of
what is ALREADY there and has aged silently (a dated fact quietly feeding
sessions for weeks). Runs monthly (day 1) via the scheduler.

Flow:
1. (DET) Sample up to N dynamic notes not checked in 90+ days (any note with a
   `status:` field, plus project-status-style dashboards), oldest first.
2. (GEN) A strong model compares each one against the CURRENT ground truth
   (every top-level note in taxonomy.home_dir) and verdicts: current | stale |
   superseded-candidate.
3. (DET) Applies: stale -> frontmatter `status: stale` (reversible, becomes
   "cite with caution"); superseded-candidate -> ESCALATE to the queue
   (supersede is always human); current -> just record the check. State lives
   in ~/.brain/state/aging.json (never pollutes the frontmatter of healthy
   notes).
4. Notify + scoped commit.

Usage: brain_aging.py [--sample 15] [--dry-run] [--model opus]
"""
import re
import sys
import json
import shutil
import argparse
import datetime
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import brain_config  # noqa: E402

BRAIN_HOME = brain_config.brain_home()
LOG = BRAIN_HOME / "logs" / "brain-aging.log"
STATE = BRAIN_HOME / "state" / "aging.json"
WORKSPACE = BRAIN_HOME / "workspace"

STATUS_RE = re.compile(r'^status:\s*(\S+)', re.M)
FM_RE = re.compile(r'^---\n(.*?)\n---', re.S)


def claude_bin():
    return shutil.which("claude") or "claude"


def log(msg):
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] [aging] {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def ntfy(msg):
    from notify import send
    send(msg, title="brain-aging", tags="hourglass")


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def git_last_edit(vault, rel):
    """Date of the last commit that touched the note (real content age).
    A never-committed note falls back to mtime (not 0, which would place it
    in 1970 and jump the queue ahead of everything else)."""
    r = subprocess.run(["git", "-C", str(vault), "log", "-1", "--format=%ct", "--", rel],
                       capture_output=True, text=True)
    out = r.stdout.strip()
    if out.isdigit():
        return int(out)
    try:
        return int((vault / rel).stat().st_mtime)
    except OSError:
        return int(datetime.datetime.now().timestamp())


def is_dynamic(txt, name):
    """A note is in scope for aging if it declares a `status:` field, or is a
    project-status-style dashboard (filename starts with _STATUS)."""
    if name.startswith("_STATUS"):
        return True
    m = FM_RE.match(txt)
    if not m:
        return False
    return bool(STATUS_RE.search(m.group(1)))


def collect_sample(vault, index_targets, index_exclude, n, interval_days, exclude_ops):
    """`exclude_ops` are taxonomy dirs that are operational paperwork, not
    canon facts about the owner (weekly dispatch packages, the gate queue
    itself): aging must never reason about its own output, or the judge's."""
    state = load_state()
    now = datetime.datetime.now().timestamp()
    cands = []
    for d in index_targets:
        root = vault / d
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            rel = str(p.relative_to(vault))
            if any(pat in rel for pat in index_exclude):
                continue
            if any(rel.startswith(op) for op in exclude_ops if op):
                continue
            if p.name.startswith("_") and not p.name.startswith("_STATUS"):
                continue
            last = state.get(rel, 0)
            if now - last < interval_days * 86400:
                continue
            txt = p.read_text(encoding="utf-8", errors="replace")
            if "status: superseded" in txt or "status: stale" in txt:
                continue  # already handled
            if not is_dynamic(txt, p.name):
                continue
            cands.append((git_last_edit(vault, rel), rel))
    cands.sort()  # oldest first (by real last commit, not mtime)
    return [rel for _, rel in cands[:n]]


def load_home_truth(vault, home_dir):
    home = ""
    root = vault / home_dir
    if not root.exists():
        return home
    for p in sorted(root.glob("*.md")):
        home += f"\n=== {p.relative_to(vault)} ===\n{p.read_text(encoding='utf-8', errors='replace')[:4000]}\n"
    return home


def render_prompt(template_path, mapping):
    txt = Path(template_path).read_text(encoding='utf-8')
    for key, val in mapping.items():
        txt = txt.replace("{{" + key + "}}", val)
    return txt


def run_verdicts(vault, sample, model, home_dir, main_language):
    home = load_home_truth(vault, home_dir)
    notes = ""
    for rel in sample:
        notes += f"\n--- NOTE {rel} ---\n{(vault / rel).read_text(encoding='utf-8', errors='replace')[:2500]}\n"
    prompt_path = Path(__file__).parent.parent / "prompts" / "aging_audit.md"
    prompt = render_prompt(prompt_path, {
        "HOME_TRUTH": home,
        "NOTES": notes,
        "MAIN_LANGUAGE": main_language,
    })
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [claude_bin(), "-p", prompt, "--model", model, "--output-format", "json",
         "--allowedTools", "Read,Grep,Glob"],
        cwd=WORKSPACE, capture_output=True, text=True, timeout=1200)
    if r.returncode != 0:
        log(f"auditor failed rc={r.returncode}")
        return None
    try:
        result = json.loads(r.stdout).get("result", "")
    except json.JSONDecodeError:
        result = r.stdout
    m = re.search(r"\[.*\]", result, re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def mark_stale(vault, rel, reason, today):
    p = vault / rel
    txt = p.read_text(encoding="utf-8")
    if re.search(r"^status:\s*\w+", txt, re.M):
        new = re.sub(r"^status:\s*\w+.*$", "status: stale", txt, count=1, flags=re.M)
    elif txt.startswith("---\n"):
        new = txt.replace("---\n", "---\nstatus: stale\n", 1)
    else:
        new = f"---\nstatus: stale\n---\n\n{txt}"
    new = new.replace("---\nstatus: stale", f"---\nstatus: stale  # aging {today}: {reason[:80]}", 1)
    p.write_text(new, encoding="utf-8")


def escalate(vault, queue_dir, rel, reason, today):
    slug = re.sub(r"[^\w-]", "-", Path(rel).stem.lower())[:50]
    fp = queue_dir / f"{today}-aging-supersede-{slug}.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(f"""---
type: escalated
title: "Aging: possible supersede of {Path(rel).stem}"
description: "Monthly aging audit found a contradiction with the current ground truth"
status: draft
created: {today}
escalated_at: {today}
escalated_reason: "{(reason or '')[:120]}"
proposed_destination: "human decision: supersede/update {rel}"
---

# Contradiction with the current ground truth: `{rel}`

{reason}

*Escalated by brain-aging on {today}. Supersede is never automatic.*
""", encoding="utf-8")
    return fp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=15)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default="opus")
    args = ap.parse_args()
    today = datetime.date.today().isoformat()

    vault = brain_config.vault_path()
    taxonomy = brain_config.taxonomy()
    main_language = brain_config.main_language()
    index_targets = taxonomy.get('index_targets', [])
    index_exclude = taxonomy.get('index_exclude', [])
    home_dir = taxonomy.get('home_dir', '00-HOME')
    queue_dir_rel = taxonomy.get('queue_dir', '04-Journal/gate-queue')
    queue_dir = vault / queue_dir_rel
    weekly_dir_rel = taxonomy.get('weekly_dir', '04-Journal/Weekly')
    interval_days = brain_config.thresholds().get('aging_check_interval_d', 90)

    sample = collect_sample(vault, index_targets, index_exclude, args.sample,
                            interval_days, [queue_dir_rel, weekly_dir_rel])
    if not sample:
        log("no eligible note (all checked less than the interval ago)")
        return
    log(f"sample: {len(sample)} notes (oldest first)")
    if args.dry_run:
        for s in sample:
            print("  ", s)
        return

    verdicts = run_verdicts(vault, sample, args.model, home_dir, main_language)
    if verdicts is None:
        ntfy("brain-aging: audit FAILED (see brain-aging.log)")
        return
    state = load_state()
    now = datetime.datetime.now().timestamp()
    stats = {"current": 0, "stale": 0, "superseded-candidate": 0}
    touched = []
    for v in verdicts:
        rel = v.get("file", "")
        ver = v.get("verdict", v.get("verdict", "current"))
        # accept both the PT-BR-labeled and EN-labeled verdict values the
        # prompt may echo back
        ver = {"atual": "current", "superseded-candidata": "superseded-candidate"}.get(ver, ver)  # pt-verdict-alias
        if not (vault / rel).exists():
            continue
        stats[ver] = stats.get(ver, 0) + 1
        reason = v.get("reason", v.get("reason", ""))
        if ver == "stale":
            mark_stale(vault, rel, reason, today)
            touched.append(vault / rel)
        elif ver == "superseded-candidate":
            fp = escalate(vault, queue_dir, rel, reason, today)
            touched.append(fp)
        state[rel] = now
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    touched.append(STATE)

    from brain_git import commit_scoped
    commit_scoped(
        str(vault), touched,
        f"chore(brain): aging pass {today}: {stats['current']} current, "
        f"{stats['stale']} stale, {stats['superseded-candidate']} escalated\n\n"
        "Co-Authored-By: brain-aging <noreply@local>", log=log)
    log(f"aging: {stats}")
    ntfy(f"Monthly brain-aging: {stats['current']} current, {stats['stale']} marked "
         f"stale, {stats['superseded-candidate']} contradictions escalated to you.")


if __name__ == "__main__":
    main()
