#!/usr/bin/env python3
"""The gate queue may contain scaffolding (_GATE-QUEUE.md index, the skeleton's
_README.md). gate_judge.load_queue must NEVER surface those as candidates: in
v1.8.0 the skeleton's _README.md was judged and DELETED by the discard path on
the first real run.
"""
import sys
import tempfile
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT_ROOT / "scripts"))

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


CANDIDATE = """---
source: personal
type: lesson
title: "A real candidate"
status: draft
created: 2026-07-19
proposed_destination: "lessons"
---

# A real candidate

Body of the candidate.
"""


def test_load_queue_ignores_scaffolding():
    import gate_judge
    with tempfile.TemporaryDirectory() as td:
        q = Path(td)
        (q / "_README.md").write_text("# About this folder\n\nScaffolding doc.\n", encoding="utf-8")
        (q / "_GATE-QUEUE.md").write_text("# Queue index\n", encoding="utf-8")
        (q / "2026-07-19-a-real-candidate.md").write_text(CANDIDATE, encoding="utf-8")

        out = gate_judge.load_queue(q, max_n=10)
        names = sorted(c["file"] for c in out)
        check(names == ["2026-07-19-a-real-candidate.md"],
              f"load_queue must return only the dated candidate, got: {names}")

        # An escalated candidate stays out too (waits for the human).
        esc = CANDIDATE.replace("---\n", "---\nescalated_at: 2026-07-18\n", 1)
        (q / "2026-07-18-escalated.md").write_text(esc, encoding="utf-8")
        out2 = gate_judge.load_queue(q, max_n=10)
        check(len(out2) == 1,
              f"escalated candidates must not be re-judged, got {len(out2)} items")


def main():
    test_load_queue_ignores_scaffolding()
    if failures:
        print(f"test_queue_hygiene: {len(failures)} failure(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("test_queue_hygiene: OK")


if __name__ == "__main__":
    main()
