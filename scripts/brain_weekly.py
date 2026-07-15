#!/usr/bin/env python3
"""brain_weekly: deterministic weekly ritual for the brain (lint + digest).

Two parts, both DETERMINISTIC (zero LLM, zero cost):
  1. LINT: vault health check (real broken links, orphans, stale candidates,
     em/en dashes, status distribution).
  2. DIGEST: what entered the canon this week (via git log), grouped by
     taxonomy, as raw input for a newsletter or dispatch package.

Writes a report to <taxonomy.weekly_dir>/Brain-Weekly-<date>.md and prints a
summary. All directories and thresholds come from ~/.brain/config.json via
brain_config.load_config(); nothing here hardcodes an owner's folder names.

Usage: python3 brain_weekly.py [--days 7] [--vault PATH]
"""
import os
import re
import sys
import glob
import argparse
import datetime
import subprocess
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import brain_config  # noqa: E402


def _default_vault():
    try:
        return str(brain_config.vault_path())
    except brain_config.ConfigError:
        return str(brain_config.load_config().get('vault_path', ''))


def nfc(s):
    return unicodedata.normalize('NFC', s)


LINKRE = re.compile(r'\[\[([^\]|#]+)')
ATTACH = re.compile(r'\.(png|jpe?g|gif|svg|pdf|excalidraw|webp|mp4|mov|xlsx?|csv)$', re.I)
PLACEHOLDER = re.compile(r'YYYY|XXXX|<|slug|example|name-of|\.\.\.', re.I)
ORPHAN_SKIP = ('moc', 'index', 'home', 'readme', '_')


def excluded(rel, index_exclude):
    return any(pat in rel for pat in (index_exclude or []))


def all_notes(vault, index_targets, index_exclude):
    out = []
    for d in index_targets:
        for p in glob.glob(os.path.join(vault, d, "**", "*.md"), recursive=True):
            rel = os.path.relpath(p, vault)
            if not excluded(rel, index_exclude):
                out.append(p)
    return out


def fm(txt):
    m = re.match(r'^---\n(.*?)\n---', txt, re.S)
    return m.group(1) if m else ""


def field(fmtxt, key):
    m = re.search(rf'^{key}:\s*(.+)$', fmtxt, re.M)
    return m.group(1).strip().strip('"') if m else None


def clean_target(tgt):
    # basename, strip escaped table pipe and spaces, normalize unicode
    return nfc(tgt.strip().split('/')[-1].rstrip('\\').strip())


def lint(vault, index_targets, index_exclude, stale_days):
    alln = all_notes(vault, index_targets, index_exclude)
    byname = {nfc(os.path.splitext(os.path.basename(p))[0]) for p in alln}
    broken = []
    status = Counter()
    dashes = 0
    targets = set()
    for p in alln:
        t = open(p, encoding='utf-8', errors='replace').read()
        for tg in LINKRE.findall(t):
            targets.add(clean_target(tg))
    now = datetime.datetime.now()
    orphans = []
    stale_cand = []
    for p in alln:
        base = os.path.splitext(os.path.basename(p))[0]
        t = open(p, encoding='utf-8', errors='replace').read()
        f = fm(t)
        st = field(f, 'status')
        status[st or 'no-status'] += 1
        dashes += t.count(chr(0x2014)) + t.count(chr(0x2013))
        for tg in LINKRE.findall(t):
            tb = clean_target(tg)
            if not tb or tb == 'wikilinks' or tb.isdigit():
                continue  # empty / syntax / numeric citation
            if ATTACH.search(tb) or PLACEHOLDER.search(tb):
                continue  # attachment or placeholder, not a note
            if tb not in byname:
                broken.append((base, tb))
        if base.lower() not in {x.lower() for x in targets} and not any(
                x in base.lower() for x in ORPHAN_SKIP):
            orphans.append(os.path.relpath(p, vault))
        if st == 'active':
            age = (now - datetime.datetime.fromtimestamp(os.path.getmtime(p))).days
            if age > stale_days:
                stale_cand.append((age, os.path.relpath(p, vault)))
    return dict(total=len(alln), broken=broken, orphans=orphans,
                stale_cand=sorted(stale_cand, reverse=True), dashes=dashes,
                status=dict(status))


def bucket_for(rel, taxonomy):
    decisions_dir = taxonomy.get('decisions_dir', '')
    heur = taxonomy.get('heuristics', {}) or {}
    if decisions_dir and rel.startswith(decisions_dir):
        return "Decisions"
    for key in ('lessons', 'patterns'):
        d = heur.get(key)
        if d and rel.startswith(d):
            return "Heuristics (lessons and patterns)"
    top = rel.split('/', 1)[0]
    return f"New in {top}"


def digest(vault, days, taxonomy):
    """Notes created/modified this week via git log (more reliable than mtime)."""
    buckets = {}
    order = []
    try:
        out = subprocess.check_output(
            ['git', '-C', vault, 'log', f'--since={days} days ago',
             '--diff-filter=AM', '--name-only', '--pretty=format:'],
            text=True, stderr=subprocess.DEVNULL)
    except Exception:
        out = ''
    files = sorted({l.strip() for l in out.splitlines() if l.strip().endswith('.md')})
    index_exclude = taxonomy.get('index_exclude', [])
    for rel in files:
        if excluded(rel, index_exclude):
            continue
        p = os.path.join(vault, rel)
        if not os.path.exists(p):
            continue
        t = open(p, encoding='utf-8', errors='replace').read()
        f = fm(t)
        title = field(f, 'title') or os.path.splitext(os.path.basename(p))[0]
        desc = (field(f, 'description') or "")[:200]
        bucket = bucket_for(rel, taxonomy)
        if bucket not in buckets:
            buckets[bucket] = []
            order.append(bucket)
        buckets[bucket].append((title, desc, rel))
    return {b: buckets[b] for b in order}


def main():
    taxonomy = brain_config.taxonomy()
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=7)
    ap.add_argument('--vault', default=_default_vault())
    args = ap.parse_args()
    vault = args.vault
    index_targets = taxonomy.get('index_targets', [])
    index_exclude = taxonomy.get('index_exclude', [])
    stale_days = brain_config.thresholds().get('aging_check_interval_d', 90)

    L = lint(vault, index_targets, index_exclude, stale_days)
    D = digest(vault, args.days, taxonomy)
    today = datetime.date.today().isoformat()
    o = []
    o.append(
        "---\n"
        "type: dashboard\n"
        f"title: \"Brain Weekly {today}\"\n"
        "status: active\n"
        "tags:\n"
        "  - brain-weekly\n"
        "  - lint\n"
        "---\n"
    )
    o.append(f"# Brain Weekly, {today}\n")
    o.append("> Weekly ritual: brain health (lint) plus this week's raw input "
              "for a digest. Generated by brain_weekly.py.\n")
    o.append("## 1. Brain health (lint)\n")
    o.append(f"- Notes: **{L['total']}** | status: {L['status']}")
    o.append(f"- Em/en dashes in the vault: **{L['dashes']}** (target: 0)")
    o.append(f"- Real broken links (excludes attachments/placeholders): **{len(L['broken'])}**")
    for b, tb in L['broken'][:20]:
        o.append(f"  - `{b}` -> `[[{tb}]]`")
    o.append(f"- Orphan notes (no inbound links): **{len(L['orphans'])}**")
    for x in L['orphans'][:20]:
        o.append(f"  - {x}")
    o.append(f"- Stale candidates (active, older than {stale_days}d): **{len(L['stale_cand'])}**")
    for age, x in L['stale_cand'][:15]:
        o.append(f"  - {x} ({age}d)")
    o.append("\n## 2. This week's input (via git)\n")
    total = sum(len(v) for v in D.values())
    o.append(f"> {total} notes created/updated (committed) in the last {args.days} days.\n")
    for bucket, items in D.items():
        if not items:
            continue
        o.append(f"### {bucket} ({len(items)})")
        for title, desc, rel in items:
            o.append(f"- **{title}**")
            if desc:
                o.append(f"  - {desc}")
        o.append("")
    report = "\n".join(o) + "\n"
    weekly_dir = taxonomy.get('weekly_dir', '04-Journal/Weekly')
    wdir = os.path.join(vault, weekly_dir)
    os.makedirs(wdir, exist_ok=True)
    path = os.path.join(wdir, f"Brain-Weekly-{today}.md")
    open(path, 'w', encoding='utf-8').write(report)
    print(f"Report: {os.path.relpath(path, vault)}")
    print(f"  lint: {L['total']} notes | {L['dashes']} dashes | "
          f"{len(L['broken'])} real broken links | {len(L['orphans'])} orphans | "
          f"{len(L['stale_cand'])} stale-cand")
    print(f"  digest: {total} notes this week (git)")


if __name__ == '__main__':
    main()
