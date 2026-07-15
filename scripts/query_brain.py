#!/usr/bin/env python3
"""Semantic search over the chunked brain index (subprocess fallback path).

Returns CHUNKS (specific decisions, specific lessons, specific sections)
rather than whole notes, grouped by parent_path for context. This is the
slow path used by query.sh when brain_daemon.py is not reachable; a live
daemon should be used instead whenever possible (see query.sh).

Usage: query_brain.py "<question>" [--top-k 10] [--source X] [--type Y] [--tag Z] [--json]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_config  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--source", help="Filter by source")
    parser.add_argument("--type", dest="type_", help="Filter by type")
    parser.add_argument("--tag", help="Filter by tag (substring)")
    parser.add_argument("--chunk-type", help="Filter by chunk_type: index|section|table_row|block")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    index_dir = brain_config.index_dir()
    npz_path = index_dir / "embeddings.npz"
    manifest_path = index_dir / "manifest.json"
    if not npz_path.exists() or not manifest_path.exists():
        print(f"ERROR: index not found at {index_dir}", file=sys.stderr)
        print("Run: scripts/embed.sh", file=sys.stderr)
        sys.exit(1)

    import numpy as np
    from sentence_transformers import SentenceTransformer

    manifest = json.loads(manifest_path.read_text())
    data = np.load(npz_path)
    embs = data["embeddings"]
    chunks = manifest["chunks"]

    # Integrity check: a partial/corrupted index must not silently return wrong results
    if len(embs) != len(chunks):
        print(
            f"ERROR: inconsistent index (embeddings={len(embs)} != chunks={len(chunks)}). "
            "Run embed.sh to reindex.",
            file=sys.stderr,
        )
        sys.exit(1)

    keep_idx = list(range(len(chunks)))
    if args.source:
        keep_idx = [i for i in keep_idx if chunks[i].get("source", "").lower() == args.source.lower()]
    if args.type_:
        keep_idx = [i for i in keep_idx if chunks[i].get("type", "").lower() == args.type_.lower()]
    if args.tag:
        tlow = args.tag.lower()
        keep_idx = [
            i for i in keep_idx
            if any(tlow in str(t).lower() for t in (chunks[i].get("tags") or []))
        ]
    if args.chunk_type:
        keep_idx = [i for i in keep_idx if chunks[i].get("chunk_type") == args.chunk_type]

    if not keep_idx:
        print("No chunks pass the filters.", file=sys.stderr)
        sys.exit(0)

    model = SentenceTransformer(manifest["model"])
    q_emb = model.encode([args.query], convert_to_numpy=True)[0]
    q_emb = q_emb / (np.linalg.norm(q_emb) + 1e-9)
    embs_n = embs[keep_idx] / (np.linalg.norm(embs[keep_idx], axis=1, keepdims=True) + 1e-9)
    sims = embs_n @ q_emb

    k = min(args.top_k, len(sims))
    top = np.argsort(-sims)[:k]
    results = [(float(sims[i]), chunks[keep_idx[i]]) for i in top]
    results = [(s, c) for s, c in results if s >= args.min_score]

    if args.json:
        out = [{"score": s, **c} for s, c in results]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"\nTop {len(results)} chunks for: '{args.query}'")
        if args.source or args.type_ or args.tag or args.chunk_type:
            print(f"   Filters: source={args.source} type={args.type_} tag={args.tag} chunk_type={args.chunk_type}")
        print()
        for i, (score, c) in enumerate(results, 1):
            section = c.get("section_id") or c.get("section_title") or "(whole note)"
            st = c.get("status", "")
            flag = f"  [status:{st}]" if st and st != "active" else ""
            print(f"{i}. [{score:.3f}] {c['parent_title'][:70]}{flag}")
            print(f"   chunk:   {c['chunk_type']} - {section[:80]}")
            print(f"   path:    {c['parent_path']}")
            print(f"   source:  {c.get('source', '-')}  type: {c.get('type', '-')}")
            tags = c.get("tags") or []
            if isinstance(tags, list):
                print(f"   tags:    {', '.join(str(t) for t in tags[:5])}")
            print()


if __name__ == "__main__":
    main()
