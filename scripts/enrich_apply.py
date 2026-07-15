#!/usr/bin/env python3
"""enrich_apply: deterministic applier for collection enrichment (Phase 1.5).

Retrieval works on raw notes, but description metadata sharpens it and the
link graph turns notes into a brain. This script is the CODE half of that
retrofit: it takes the JSON a cheap-model batch (prompts/enrich_batch.md)
produced and writes it to disk. The owner's prose is READ-ONLY:

  - Frontmatter fields (title, description, tags, created) are ADDED, never
    overwritten: a field already present in a note is left untouched.
  - `related` candidates are validated against the filesystem (NFC-normalized,
    case-folded match against real note filenames); anything unresolved is
    dropped silently, never written as a dead link.
  - Related links live inside a marker block
    (<!-- brain: related-start/end -->) at the end of the note, so reruns
    regenerate the block instead of duplicating it.
  - One scoped commit per batch (brain_git.commit_scoped): only the files this
    run touched.

It also computes a deterministic island report: notes with zero inbound AND
zero outbound wikilinks, so the owner (or a follow-up MOC pass) knows what
still needs a home.

Batch JSON contract (produced by prompts/enrich_batch.md):
  {"notes": [
    {"file": "<vault-relative path>", "title": "...", "description": "...",
     "tags": ["...", "..."], "created": "YYYY-MM-DD", "related": ["...", "..."]}
  ]}
Any field may be null/absent/empty; absent fields are simply not added.

Usage:
  enrich_apply.py --batch <path/to/batch-result.json> [--vault PATH] [--dry-run]
  enrich_apply.py --report-islands [--vault PATH]
"""
import re
import sys
import json
import argparse
import datetime
import unicodedata
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import brain_config  # noqa: E402

BRAIN_HOME = brain_config.brain_home()
LOG = BRAIN_HOME / "logs" / "enrich-apply.log"

MARKER_START = "<!-- brain: related-start -->"
MARKER_END = "<!-- brain: related-end -->"
MARKER_RE = re.compile(re.escape(MARKER_START) + r'.*?' + re.escape(MARKER_END), re.S)
FM_RE = re.compile(r'^---\n(.*?)\n---', re.S)
LINK_RE = re.compile(r'\[\[([^\]|#]+)')
FRONTMATTER_KEYS = ("title", "description", "tags", "created")


def nfc(s):
    return unicodedata.normalize('NFC', s)


def log(msg):
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] [enrich] {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def yaml_field(key, value):
    return yaml.safe_dump({key: value}, allow_unicode=True, sort_keys=False,
                          default_flow_style=False).rstrip("\n")


def merge_frontmatter(text, note_data):
    """Add missing frontmatter fields; never touch a field that already has a
    non-empty value. Returns (new_text, changed)."""
    m = FM_RE.match(text)
    if m:
        fm_text = m.group(1)
        try:
            existing = yaml.safe_load(fm_text) or {}
        except yaml.YAMLError:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        rest = text[m.end():]
        insert_lines = []
        for key in FRONTMATTER_KEYS:
            val = note_data.get(key)
            if val in (None, "", []):
                continue
            if existing.get(key) not in (None, "", []):
                continue  # never overwrite an existing field
            insert_lines.append(yaml_field(key, val))
        if not insert_lines:
            return text, False
        new_fm = fm_text.rstrip("\n") + "\n" + "\n".join(insert_lines)
        return f"---\n{new_fm}\n---{rest}", True
    # no frontmatter block at all: create a minimal one
    insert_lines = []
    for key in FRONTMATTER_KEYS:
        val = note_data.get(key)
        if val in (None, "", []):
            continue
        insert_lines.append(yaml_field(key, val))
    if not insert_lines:
        return text, False
    return "---\n" + "\n".join(insert_lines) + "\n---\n\n" + text, True


def render_related_block(targets):
    lines = [MARKER_START, "", "**Related**", ""]
    lines += [f"- [[{t}]]" for t in targets]
    lines += ["", MARKER_END]
    return "\n".join(lines)


def apply_related(text, targets):
    if not targets:
        return text, False
    block = render_related_block(targets)
    if MARKER_RE.search(text):
        new_text = MARKER_RE.sub(block, text)
    else:
        new_text = text.rstrip("\n") + "\n\n" + block + "\n"
    return new_text, new_text != text


def iter_notes(vault, index_targets, index_exclude):
    for d in index_targets:
        root = vault / d
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            rel = str(p.relative_to(vault))
            if any(pat in rel for pat in index_exclude):
                continue
            yield p


def build_note_index(vault, index_targets, index_exclude):
    idx = {}
    for p in iter_notes(vault, index_targets, index_exclude):
        idx.setdefault(nfc(p.stem).casefold(), []).append(p.stem)
    return idx


def resolve_related(candidates, note_index, exclude_stem):
    """Validate candidates against real note filenames. Unresolved or
    ambiguous candidates are dropped silently, never written."""
    resolved = []
    for c in candidates or []:
        key = nfc(str(c).strip().strip('[]')).casefold()
        matches = [m for m in note_index.get(key, []) if m != exclude_stem]
        if len(matches) == 1 and matches[0] not in resolved:
            resolved.append(matches[0])
    return resolved


def apply_batch(vault, batch_path, index_targets, index_exclude, dry):
    raw = json.loads(Path(batch_path).read_text(encoding='utf-8'))
    notes = raw.get('notes', raw) if isinstance(raw, dict) else raw
    note_index = build_note_index(vault, index_targets, index_exclude)
    touched = []
    stats = {"frontmatter_added": 0, "related_added": 0, "skipped": 0}
    for rec in notes:
        rel = rec.get('file')
        if not rel:
            stats['skipped'] += 1
            continue
        p = vault / rel
        if not p.exists():
            log(f"batch entry skipped, file not found: {rel}")
            stats['skipped'] += 1
            continue
        original = p.read_text(encoding='utf-8', errors='replace')
        text, fm_changed = merge_frontmatter(original, rec)
        related_targets = resolve_related(rec.get('related'), note_index, p.stem)
        text, rel_changed = apply_related(text, related_targets)
        if text != original:
            if not dry:
                p.write_text(text, encoding='utf-8')
                touched.append(p)
            if fm_changed:
                stats['frontmatter_added'] += 1
            if rel_changed:
                stats['related_added'] += 1
            log(f"enriched {rel} (frontmatter={fm_changed}, related={rel_changed})")
    return touched, stats


def compute_islands(vault, index_targets, index_exclude):
    """Notes with zero inbound and zero outbound wikilinks (includes the
    related marker block, which uses ordinary [[wikilinks]])."""
    notes = list(iter_notes(vault, index_targets, index_exclude))
    stems = {nfc(p.stem).casefold(): str(p.relative_to(vault)) for p in notes}
    outbound = {}
    inbound = set()
    for p in notes:
        rel = str(p.relative_to(vault))
        txt = p.read_text(encoding='utf-8', errors='replace')
        targets = set()
        for tg in LINK_RE.findall(txt):
            key = nfc(tg.strip().split('/')[-1].rstrip('\\').strip()).casefold()
            tgt_rel = stems.get(key)
            if tgt_rel and tgt_rel != rel:
                targets.add(tgt_rel)
        outbound[rel] = targets
        inbound.update(targets)
    return sorted(rel for rel, targets in outbound.items() if not targets and rel not in inbound)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', help='JSON file produced by the enrich_batch prompt')
    ap.add_argument('--vault')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--report-islands', action='store_true',
                    help='compute and print the island report (can run standalone)')
    args = ap.parse_args()
    if not args.batch and not args.report_islands:
        sys.exit("nothing to do: pass --batch and/or --report-islands")

    vault = Path(args.vault).expanduser() if args.vault else brain_config.vault_path()
    taxonomy = brain_config.taxonomy()
    index_targets = taxonomy.get('index_targets', [])
    index_exclude = taxonomy.get('index_exclude', [])

    if args.batch:
        touched, stats = apply_batch(vault, args.batch, index_targets, index_exclude, args.dry_run)
        print(f"frontmatter added: {stats['frontmatter_added']} | "
              f"related blocks added: {stats['related_added']} | skipped: {stats['skipped']}")
        if not args.dry_run and touched:
            from brain_git import commit_scoped
            batch_name = Path(args.batch).stem
            commit_scoped(
                str(vault), touched,
                f"chore(brain): enrichment batch {batch_name} ({len(touched)} notes)\n\n"
                "Additive only: frontmatter fields merged non-destructively, related "
                "links validated against the filesystem.\n\n"
                "Co-Authored-By: enrich-apply <noreply@local>", log=log)

    if args.report_islands:
        islands = compute_islands(vault, index_targets, index_exclude)
        print(f"islands (no inbound or outbound related links): {len(islands)}")
        for rel in islands[:50]:
            print(f"  - {rel}")


if __name__ == '__main__':
    main()
