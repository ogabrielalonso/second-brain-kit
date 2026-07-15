#!/usr/bin/env python3
"""Indexes the vault into a local chunked index (fine-grained retrieval).

CHUNKING STRATEGY (avoids the failure mode where a large note collapses into
one vector and loses its internal structure):
  - Small note (<3 KB): 1 chunk (the whole note)
  - Note with `## ` headers (3+ content sections): 1 chunk PER SECTION
  - Large markdown table (>=20 rows): 1 chunk PER ROW, with header context
  - Otherwise: 1 chunk per ~2000-char block for notes over 4 KB
  - Every chunk always keeps an 'index' chunk for the whole note too
  - Every chunk carries: parent_note, section_id (if any), tags, status

All targets and exclusions come from config.taxonomy() (index_targets /
index_exclude); nothing here hardcodes the owner's folder names. Index is
written outside the vault, at brain_config.index_dir().

Usage:
    python3 embed_brain.py            # index with chunking
    python3 embed_brain.py --dry-run  # count chunks only, no model load
    python3 embed_brain.py --reset    # delete and rebuild the index
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_config  # noqa: E402

EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# Sections that are pure navigation (wikilink lists) rank high on retrieval
# but carry no answerable content; filtered before section-chunking.
SKIP_SECTIONS = {
    "related", "related notes", "see also", "resources", "additional resources",
    "cross links", "cross-links", "links", "sources", "references",
}


def load_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBEDDING_MODEL)


def parse_note(path: Path):
    """Returns {title, description, tags, source, type, status, body} for a note."""
    import yaml
    text = path.read_text(encoding="utf-8", errors="replace")
    fm = {}
    body = text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except Exception:
            fm = {}
        body = m.group(2)
    # Excalidraw notes: keep only the readable text elements (drawing labels),
    # drop the serialized drawing block (JSON/base64), which is pure noise for RAG.
    if path.name.endswith(".excalidraw.md") or "excalidraw-plugin" in text[:800]:
        idxs = [body.find(mk) for mk in ["%%", "## Drawing", "# Drawing", "```compressed-json", "```json"]]
        idxs = [i for i in idxs if i != -1]
        if idxs:
            body = body[: min(idxs)]
    return {
        "title": str(fm.get("title", path.stem)),
        "description": str(fm.get("description", ""))[:500],
        "tags": fm.get("tags") or [],
        "source": str(fm.get("source", "")),
        "type": str(fm.get("type", "")),
        # trust axis (draft/active/stale/superseded); travels on every chunk so the
        # daemon/retrieval hook can flag a stale hit as "not current truth"
        "status": str(fm.get("status", "") or ""),
        "body": body,
    }


def chunk_note(note_meta, path, vault):
    """Splits a note into chunks. Returns a list of dicts {chunk_id, text, parent_path, ...}."""
    body = note_meta["body"]
    parent_path = str(path.relative_to(vault))
    tags_str = ", ".join(str(t) for t in (note_meta["tags"] if isinstance(note_meta["tags"], list) else [])[:8])
    header_context = f"[from: {note_meta['title']} | tags: {tags_str}]"

    chunks = []

    # Always add an index chunk for the whole note (title + description + tags + start)
    chunks.append({
        "chunk_id": f"{parent_path}::index",
        "parent_path": parent_path,
        "parent_title": note_meta["title"],
        "section_id": None,
        "section_title": None,
        "text": f"{note_meta['title']}. {note_meta['description']}. tags: {tags_str}. {body[:500]}",
        "tags": note_meta["tags"],
        "source": note_meta["source"],
        "type": note_meta["type"],
        "status": note_meta["status"],
        "chunk_type": "index",
    })

    # Detect H2 sections
    h2_sections = []
    current = None
    for line in body.split("\n"):
        if line.startswith("## "):
            if current and current["body"].strip():
                h2_sections.append(current)
            title = line[3:].strip()
            m = re.match(r"^([A-Z]-\d{3}):\s*(.+)$", title)
            sid = m.group(1) if m else None
            sname = m.group(2) if m else title
            current = {"id": sid, "title": sname, "body": ""}
        elif current is not None:
            current["body"] += line + "\n"
    if current and current["body"].strip():
        h2_sections.append(current)

    def _is_nav(sec):
        tt = re.sub(r"^\W+", "", sec["title"].strip().lower()).rstrip(":").strip()
        if tt in SKIP_SECTIONS:
            return True
        lines = [l for l in sec["body"].split("\n") if l.strip()]
        if not lines:
            return True
        linky = sum(1 for l in lines if l.strip().startswith("[[") or re.match(r"^[\-\*\d\.\)\s]+\[\[", l.strip()))
        return linky / len(lines) > 0.8

    h2_sections = [s for s in h2_sections if not _is_nav(s)]

    # 3+ content sections (after nav filtering): one chunk per section
    if len(h2_sections) >= 3:
        for sec in h2_sections:
            chunk_text = f"{header_context} {sec['title']}. {sec['body'][:1500].strip()}"
            chunks.append({
                "chunk_id": f"{parent_path}::{sec['id'] or sec['title'][:30]}",
                "parent_path": parent_path,
                "parent_title": note_meta["title"],
                "section_id": sec["id"],
                "section_title": sec["title"][:200],
                "text": chunk_text,
                "tags": note_meta["tags"],
                "source": note_meta["source"],
                "type": note_meta["type"],
                "status": note_meta["status"],
                "chunk_type": "section",
            })
        return chunks

    # Detect large tables
    rows = []
    in_table = False
    header = None
    for line in body.split("\n"):
        if line.strip().startswith("|---"):
            in_table = True
            continue
        if in_table and line.strip().startswith("|") and line.strip().endswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not header:
                header = cells
            else:
                rows.append(cells)
        elif in_table and not line.strip().startswith("|"):
            in_table = False

    if len(rows) >= 20 and header:
        for i, row in enumerate(rows):
            if len(row) < 2:
                continue
            row_text = " | ".join(
                f"{header[j] if j < len(header) else ''}: {cell}"
                for j, cell in enumerate(row) if cell.strip()
            )
            chunks.append({
                "chunk_id": f"{parent_path}::row-{i+1:03d}",
                "parent_path": parent_path,
                "parent_title": note_meta["title"],
                "section_id": row[0] if row[0].startswith(("L-", "D-")) else None,
                "section_title": row[1][:200] if len(row) > 1 else row[0][:200],
                "text": f"{header_context} {row_text[:1500]}",
                "tags": note_meta["tags"],
                "source": note_meta["source"],
                "type": note_meta["type"],
                "status": note_meta["status"],
                "chunk_type": "table_row",
            })
        return chunks

    # Large notes with no sections and no table: chunk in ~2000-char blocks
    if len(body) > 4000:
        n_chunks = (len(body) // 2000) + 1
        for i in range(n_chunks):
            start = i * 2000
            piece = body[start:start + 2500].strip()
            if len(piece) < 200:
                continue
            chunks.append({
                "chunk_id": f"{parent_path}::part-{i+1:02d}",
                "parent_path": parent_path,
                "parent_title": note_meta["title"],
                "section_id": None,
                "section_title": f"part {i+1}",
                "text": f"{header_context} {piece[:1500]}",
                "tags": note_meta["tags"],
                "source": note_meta["source"],
                "type": note_meta["type"],
                "status": note_meta["status"],
                "chunk_type": "block",
            })

    return chunks


def collect_chunks(vault: Path, taxonomy: dict):
    """Returns the list of chunks for every note under the configured index targets."""
    targets = taxonomy.get("index_targets") or []
    exclude = taxonomy.get("index_exclude") or []
    all_chunks = []
    for sub in targets:
        d = vault / sub
        if not d.exists():
            continue
        for f in d.rglob("*.md"):
            rel = str(f.relative_to(vault))
            if any(pattern in rel for pattern in exclude):
                continue
            note = parse_note(f)
            chunks = chunk_note(note, f, vault)
            all_chunks.extend(chunks)
    # Include the vault's root CLAUDE.md, if present (context note, not excluded by targets)
    claude_md = vault / "CLAUDE.md"
    if claude_md.exists():
        note = parse_note(claude_md)
        note["title"] = note["title"] or "CLAUDE.md"
        all_chunks.extend(chunk_note(note, claude_md, vault))
    return all_chunks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    vault = brain_config.vault_path()
    taxonomy = brain_config.taxonomy()
    index_dir = brain_config.index_dir()
    index_dir.mkdir(parents=True, exist_ok=True)
    npz_path = index_dir / "embeddings.npz"
    manifest_path = index_dir / "manifest.json"

    if args.reset:
        for f in (npz_path, manifest_path):
            if f.exists():
                f.unlink()
        print("Reset: index deleted.")

    chunks = collect_chunks(vault, taxonomy)
    parents = set(c["parent_path"] for c in chunks)
    print(f"Chunks collected: {len(chunks)} from {len(parents)} notes")

    by_type = {}
    for c in chunks:
        by_type[c["chunk_type"]] = by_type.get(c["chunk_type"], 0) + 1
    print(f"  By type: {by_type}")

    if args.dry_run:
        print("DRY-RUN -- chunk sample:")
        for c in chunks[:5]:
            print(f"  [{c['chunk_type']:10s}] {c['chunk_id'][:80]}")
            print(f"      text[:120]: {c['text'][:120]}...")
        return

    if not chunks:
        print("No chunks found under the configured index_targets; nothing to index.", file=sys.stderr)
        sys.exit(1)

    print("Loading model...")
    model = load_model()

    texts = [c["text"] for c in chunks]
    print(f"Encoding {len(texts)} chunks...")
    import numpy as np
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=64, convert_to_numpy=True)
    print(f"  Shape: {embeddings.shape}")

    try:
        vault_commit = subprocess.check_output(
            ["git", "-C", str(vault), "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        vault_commit = None

    manifest = {
        "model": EMBEDDING_MODEL,
        "dim": int(embeddings.shape[1]),
        "count": len(chunks),
        "parent_count": len(parents),
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "vault_commit": vault_commit,
        "chunk_strategy": "index + section(if 3+ H2, nav filtered) + table_row(if 20+ rows) + block(if >4KB) | else 1 chunk",
        "chunks": [
            {
                "chunk_id": c["chunk_id"],
                "parent_path": c["parent_path"],
                "parent_title": c["parent_title"],
                "section_id": c["section_id"],
                "section_title": c["section_title"],
                "tags": [str(t) for t in (c["tags"] if isinstance(c["tags"], list) else [])][:8],
                "source": c["source"],
                "type": c["type"],
                "status": c.get("status", ""),
                "chunk_type": c["chunk_type"],
            }
            for c in chunks
        ],
    }

    # Atomic write: write to temp files then rename (avoids a corrupted index on interruption)
    npz_tmp = npz_path.with_name("_tmp_" + npz_path.name)
    manifest_tmp = manifest_path.with_name("_tmp_" + manifest_path.name)
    np.savez_compressed(npz_tmp, embeddings=embeddings)
    manifest_tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(npz_tmp, npz_path)
    os.replace(manifest_tmp, manifest_path)

    print(f"\nIndex written to {index_dir}")
    print(f"   {len(chunks)} chunks from {len(parents)} notes")
    print(f"   embeddings.npz: {npz_path.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
