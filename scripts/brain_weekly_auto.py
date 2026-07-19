#!/usr/bin/env python3
"""brain_weekly_auto: fully automatic weekly ritual.

Runs on the weekly scheduler slot. Does everything that does not require human
judgment and prepares the dispatch package; the only human action left is
answering the dispatch.

1. (DET)  brain_weekly.py --days 7 (lint + digest, base report)
2. (AUTO) Cosmetic fixes to the canon, in a separate 'fix(lint):' commit
          (reversible):
          a. broken links with an UNAMBIGUOUS target (NFC + casefold
             normalization, exactly 1 candidate)
          b. created/modified missing from frontmatter (derived from git log)
          c. em/en dashes: a cheap model rewrites them file by file (a
             semantic task); the write only lands if the diff touches only
             lines that had a dash
          Deletes/merges/renames/content changes: NEVER automatic (gate).
3. (GEN)  Dispatch package: a strong model summarizes the numbered gate queue
          plus a short digest draft, rendered from prompts/weekly_dispatch.md
          and appended to Brain-Weekly-<date>.md.
4. (DET)  Commit the report + notify.

Usage: python3 brain_weekly_auto.py [--dry-run] [--cheap-model sonnet]
       [--strong-model opus] [--max-dash-files 10]
"""
import sys
import json
import shutil
import argparse
import subprocess
import datetime
import unicodedata
from pathlib import Path
from importlib import import_module

sys.path.insert(0, str(Path(__file__).parent))
import brain_config  # noqa: E402

bw = import_module('brain_weekly')

DASH = (chr(0x2014), chr(0x2013))  # em-dash, en-dash (built via codepoint: never a literal glyph in source)


def claude_bin():
    return shutil.which("claude") or "claude"


BRAIN_HOME = brain_config.brain_home()
LOG = BRAIN_HOME / "logs" / "brain-weekly-auto.log"
STATE = BRAIN_HOME / "state" / "brain_weekly_auto.last_run"
WORKSPACE = BRAIN_HOME / "workspace"


def log(msg):
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] [auto] {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf-8') as f:
        f.write(line + "\n")


def ntfy(msg):
    # System notifications are deliberately English-only (short, technical);
    # owner-language content lives in the reports/digests, not in push alerts.
    from notify import send
    send(msg, title="brain-weekly", tags="calendar")


def nfc(s):
    return unicodedata.normalize('NFC', s)


# ---------- fix a: broken links with an unambiguous target ----------
def fix_broken_links(vault, index_targets, index_exclude, lint_result, dry, touched):
    notes = bw.all_notes(str(vault), index_targets, index_exclude)
    by_norm = {}
    for p in notes:
        base = Path(p).stem
        by_norm.setdefault(nfc(base).casefold(), []).append(base)
    fixed = 0
    skipped = []
    for src_base, target in lint_result['broken']:
        cands = by_norm.get(nfc(target).casefold(), [])
        if len(cands) != 1 or cands[0] == target:
            skipped.append(target)
            continue
        # unambiguous target: same normalized name, single candidate
        srcs = [p for p in notes if Path(p).stem == src_base]
        for sp in srcs:
            txt = Path(sp).read_text(encoding='utf-8')
            new = txt.replace(f'[[{target}]]', f'[[{cands[0]}]]').replace(
                f'[[{target}|', f'[[{cands[0]}|')
            if new != txt:
                if not dry:
                    Path(sp).write_text(new, encoding='utf-8')
                    touched.append(Path(sp))
                fixed += 1
                log(f"link fix: [[{target}]] -> [[{cands[0]}]] in {src_base}")
    if skipped:
        log(f"ambiguous/no-candidate links left for the gate: {len(set(skipped))}")
    return fixed


# ---------- fix b: created/modified derivable from git ----------
def fix_frontmatter_dates(vault, index_targets, index_exclude, dry, touched):
    fixed = 0
    for p in bw.all_notes(str(vault), index_targets, index_exclude):
        txt = Path(p).read_text(encoding='utf-8', errors='replace')
        f = bw.fm(txt)
        if not f or bw.field(f, 'created'):
            continue
        rel = str(Path(p).relative_to(vault))
        r = subprocess.run(
            ['git', '-C', str(vault), 'log', '--diff-filter=A', '--format=%as',
             '--follow', '--', rel],
            capture_output=True, text=True)
        created = (r.stdout.strip().splitlines() or [''])[-1]
        if not created:
            continue
        new = txt.replace('---\n' + f + '\n---', '---\n' + f + f'\ncreated: {created}\n---', 1)
        if new != txt:
            if not dry:
                Path(p).write_text(new, encoding='utf-8')
                touched.append(Path(p))
            fixed += 1
            log(f"{'dry: would fix ' if dry else ''}frontmatter fix: created:{created} in {rel}")
    return fixed


# ---------- fix c: dashes via cheap model (semantic) + deterministic validation ----------
def fix_dashes(vault, index_targets, index_exclude, model, main_language, max_files, dry, touched):
    affected = []
    for p in bw.all_notes(str(vault), index_targets, index_exclude):
        txt = Path(p).read_text(encoding='utf-8', errors='replace')
        if any(d in txt for d in DASH):
            affected.append((p, txt))
    if not affected:
        return 0, 0
    if len(affected) > max_files:
        log(f"dashes in {len(affected)} files; fixing {max_files} (rest next week)")
    fixed_files = 0
    for p, txt in affected[:max_files]:
        if dry:
            log(f"dry: would fix dashes in {Path(p).name}")
            continue
        prompt = (
            "Rewrite the text below, replacing EVERY em-dash (U+2014) and en-dash "
            "(U+2013) with the semantically correct punctuation (comma, colon, "
            "parentheses, period, or conjunction; en-dash between numbers becomes a "
            f"hyphen). Keep the text in {main_language}. Change absolutely nothing "
            "else: not a word, not an accent, not a line break, not formatting. "
            "Reply with ONLY the full rewritten text, no commentary.\n\n" + txt)
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            [claude_bin(), "-p", prompt, "--model", model, "--output-format", "json"],
            capture_output=True, text=True, timeout=600, cwd=str(WORKSPACE))
        if r.returncode != 0:
            log(f"dash fix failed for {Path(p).name}: rc={r.returncode}")
            continue
        try:
            new = json.loads(r.stdout).get('result', '')
        except json.JSONDecodeError:
            continue
        new = new.strip('\n') + '\n' if txt.endswith('\n') else new
        # deterministic validation: the diff may only touch lines that had a dash
        old_lines, new_lines = txt.splitlines(), new.splitlines()
        ok = len(old_lines) == len(new_lines) and not any(d in new for d in DASH)
        if ok:
            for o, n in zip(old_lines, new_lines):
                if o != n and not any(d in o for d in DASH):
                    ok = False
                    break
        if ok:
            Path(p).write_text(new, encoding='utf-8')
            touched.append(Path(p))
            fixed_files += 1
            log(f"dash fix: {Path(p).name}")
        else:
            log(f"dash fix REJECTED (diff outside dash lines): {Path(p).name}")
    return fixed_files, len(affected)


# ---------- gate telemetry (gate_log.py) ----------
def gate_telemetry_section():
    """Summary of gate decision telemetry plus auto-approve promotion proposals.
    Deterministic (no LLM); returns markdown or '' if no data yet. Defensive:
    gate_log.py belongs to another module, so any shape mismatch degrades to
    an empty section instead of crashing this pipeline."""
    try:
        gl = import_module('gate_log')
        s = gl.compute_stats(gl.load_config(), 12)
    except Exception as e:
        log(f"gate telemetry unavailable (non-critical): {e}")
        return ""
    try:
        rows = s.get('types') or []
        if not rows:
            return ""
        th = s.get('threshold', {})
        lines = ["### Gate telemetry (12 weeks)", "",
                 "| type | n | approved | edited | discarded | full-approval rate | status |",
                 "|---|---|---|---|---|---|---|"]
        proposals = []
        for r in rows:
            type_name = r.get('type', 'unknown')
            n = r.get('n', 0)
            approved = r.get('approved', 0)
            edited = r.get('edited', 0)
            discarded = r.get('discarded', 0)
            rate = r.get('full_approval_rate', 0)
            eligible = r.get('eligible_for_promotion', False)
            active = r.get('auto_approve_active', False)
            status = "auto-approve ACTIVE" if active else (
                "ELIGIBLE for promotion" if eligible else "gated")
            lines.append(f"| {type_name} | {n} | {approved} | {edited} | {discarded} | "
                         f"{rate:.0%} | {status} |")
            if eligible:
                proposals.append(type_name)
        if proposals:
            min_n = th.get('min_n', '?')
            min_rate = th.get('min_rate', 0)
            min_weeks = th.get('min_weeks', 0)
            lines += ["",
                      f"**PROMOTION PROPOSAL**: type(s) {', '.join(proposals)} crossed the "
                      f"threshold (n>={min_n}, rate>={min_rate:.0%}, >={min_weeks} weeks). "
                      "If approved, the promotion is recorded in the decisions log."]
        return "\n".join(lines)
    except Exception as e:
        log(f"gate telemetry render failed (non-critical): {e}")
        return ""


# ---------- dispatch package ----------
def render_prompt(template_path, mapping):
    txt = Path(template_path).read_text(encoding='utf-8')
    for key, val in mapping.items():
        txt = txt.replace("{{" + key + "}}", val)
    return txt


def build_dispatch(vault, taxonomy, model, main_language, report_path, dry):
    queue_dir = vault / taxonomy.get('queue_dir', '04-Journal/gate-queue')
    queue = sorted(queue_dir.glob('2*.md')) if queue_dir.exists() else []
    if dry:
        log(f"dry: dispatch package would cover {len(queue)} candidates")
        return len(queue)
    queue_txt = ""
    for i, qf in enumerate(queue, 1):
        queue_txt += f"\n--- CANDIDATE {i} ({qf.name}) ---\n{qf.read_text(encoding='utf-8')[:1500]}\n"
    digest_txt = report_path.read_text(encoding='utf-8')[:6000] if report_path.exists() else ""
    prompt_path = Path(__file__).parent.parent / "prompts" / "weekly_dispatch.md"
    prompt = render_prompt(prompt_path, {
        "MAIN_LANGUAGE": main_language,
        "QUEUE": queue_txt if queue_txt else "(queue empty)",
        "DIGEST": digest_txt,
    })
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [claude_bin(), "-p", prompt, "--model", model, "--output-format", "json"],
        capture_output=True, text=True, timeout=900, cwd=str(WORKSPACE))
    if r.returncode == 0:
        try:
            package = json.loads(r.stdout).get('result', '')
            telemetry = gate_telemetry_section()
            with report_path.open('a', encoding='utf-8') as f:
                f.write(f"\n\n---\n\n# Dispatch package (generated "
                        f"{datetime.date.today().isoformat()})\n\n"
                        f"> Reply in one session: \"dispatch the weekly: approve 1,3; "
                        f"edit 2; discard 4\".\n\n{package}\n")
                if telemetry:
                    f.write(f"\n{telemetry}\n")
            log("dispatch package appended to the report")
        except json.JSONDecodeError:
            log("dispatch: invalid JSON from claude -p")
    else:
        log(f"dispatch failed rc={r.returncode}")
    return len(queue)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--cheap-model', default='sonnet')
    ap.add_argument('--strong-model', default='opus')
    ap.add_argument('--max-dash-files', type=int, default=10)
    args = ap.parse_args()
    dry = args.dry_run
    today = datetime.date.today().isoformat()

    vault = brain_config.vault_path()
    taxonomy = brain_config.taxonomy()
    main_language = brain_config.main_language()

    # 1. deterministic lint + digest (generates the base report)
    # brain_weekly.py WRITES the report into the vault, so a dry run must skip it:
    # dry means zero side effects inside the vault (guarded by test_dry_run_clean.py).
    if not dry:
        subprocess.run([sys.executable, str(Path(__file__).parent / "brain_weekly.py"),
                        '--days', '7'], capture_output=True, text=True)
    report = vault / taxonomy.get('weekly_dir', '04-Journal/Weekly') / f"Brain-Weekly-{today}.md"
    index_targets = taxonomy.get('index_targets', [])
    index_exclude = taxonomy.get('index_exclude', [])
    stale_days = brain_config.thresholds().get('aging_check_interval_d', 90)
    lint_result = bw.lint(str(vault), index_targets, index_exclude, stale_days)
    log(f"lint: {len(lint_result['broken'])} broken links, {lint_result['dashes']} dashes")

    # 2. cosmetic fixes (approved class); SCOPED commit to touched paths only
    # (never `git add -A`: unrelated pending work must stay untouched)
    from brain_git import commit_scoped
    touched = []
    n_links = fix_broken_links(vault, index_targets, index_exclude, lint_result, dry, touched)
    n_dates = fix_frontmatter_dates(vault, index_targets, index_exclude, dry, touched)
    n_dash, n_dash_total = fix_dashes(vault, index_targets, index_exclude, args.cheap_model,
                                       main_language, args.max_dash_files, dry, touched)
    if not dry and (n_links or n_dates or n_dash):
        commit_scoped(
            str(vault), touched,
            f"fix(lint): weekly cosmetic auto-fix ({n_links} links, {n_dates} "
            f"frontmatter, {n_dash} files without dashes)\n\n"
            "Cosmetic class, reversible with git revert.\n\n"
            "Co-Authored-By: brain-weekly-auto <noreply@local>", log=log)

    # 3. dispatch package (numbered queue + digest draft)
    n_queue = build_dispatch(vault, taxonomy, args.strong_model, main_language, report, dry)

    # 4. commit the report + notify
    if not dry:
        subprocess.run(['git', '-C', str(vault), 'add',
                        str(report.relative_to(vault))], capture_output=True, text=True)
        subprocess.run(
            ['git', '-C', str(vault), 'commit', '-m',
             f"docs(weekly): Brain Weekly {today} with dispatch package\n\n"
             "Co-Authored-By: brain-weekly-auto <noreply@local>"],
            capture_output=True, text=True)
        ntfy(f"Brain weekly ready: {n_queue} candidates in the gate, auto-fixes: "
             f"{n_links} links + {n_dash}/{n_dash_total} dash files + "
             f"{n_dates} frontmatter. Reply to dispatch.")
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(datetime.datetime.now().isoformat(timespec='seconds'), encoding='utf-8')
    log(f"weekly-auto done (dry={dry})")


if __name__ == '__main__':
    main()
