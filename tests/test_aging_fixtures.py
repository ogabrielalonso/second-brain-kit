#!/usr/bin/env python3
"""Aging fixtures: structural validation + deterministic-layer regression.

IMPORTANT SCOPE NOTE: this test does NOT re-run the LLM aging auditor. The
verdicts pinned in fixtures/aging/expected.json ("superseded-candidate" for
the note that contradicts the ground truth, "stale" for the note that is
merely old) are the judgment call docs/ARCHITECTURE.md assigns to a strong
model comparing each note against 00-HOME; that comparison is backtested at
install time (installer flow Phase 5), not something a unit test can assert
without calling the model.

What IS tested here, deterministically, against scripts/brain_aging.py:
  1. fixture structure: both .md fixtures parse with frontmatter, expected.json
     is well formed and matches the fixture files 1:1.
  2. fed a canned "stale" verdict, mark_stale(vault, rel, reason, today) stamps
     status: stale into the note's frontmatter (reversible, never a delete).
  3. fed a canned "superseded-candidate" verdict, escalate(vault, queue_dir,
     rel, reason, today) writes a NEW queue entry rather than editing or
     deleting the contradicted note directly ("supersede is never automatic"),
     and that entry carries the escalated_at marker gate_judge.load_queue()
     relies on to never re-surface an already-escalated item (hardening #6).
     If it does not, that is a real cross-module interop gap to report, not a
     reason to soften this check.

brain_aging.py takes vault/queue_dir as explicit parameters (no module-level
globals to patch), so the sandbox here is just a temp directory passed
straight in; nothing touches the owner's real vault.
"""
import sys
import re
import json
import tempfile
import datetime
import importlib
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "aging"
EXPECTED_PATH = FIXTURES_DIR / "expected.json"
VERDICT_ENUM = {"current", "stale", "superseded-candidate"}

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


def _parse_frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None
    fm = {}
    for line in m.group(1).splitlines():
        mm = re.match(r'^([A-Za-z_]+):\s*"?(.*?)"?\s*$', line)
        if mm:
            fm[mm.group(1)] = mm.group(2)
    return fm


def test_fixture_structure():
    if not check(EXPECTED_PATH.exists(), f"missing {EXPECTED_PATH}"):
        return None
    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    cases = expected.get("cases", [])
    check(len(cases) == 2, f"expected.json should list exactly 2 cases, found {len(cases)}")

    md_files = sorted(p.name for p in FIXTURES_DIR.glob("*.md"))
    case_files = sorted(c["file"] for c in cases)
    check(md_files == case_files,
          f"fixture .md files and expected.json cases must match 1:1; "
          f"md={md_files} vs expected={case_files}")

    for c in cases:
        check(c.get("expected_verdict") in VERDICT_ENUM,
              f"{c.get('file')}: expected_verdict '{c.get('expected_verdict')}' not in {sorted(VERDICT_ENUM)}")
        fp = FIXTURES_DIR / c["file"]
        if not check(fp.exists(), f"{c['file']}: fixture file missing"):
            continue
        fm = _parse_frontmatter(fp.read_text(encoding="utf-8"))
        if not check(fm is not None, f"{c['file']}: no parseable frontmatter block"):
            continue
        check(fm.get("status") == "active",
              f"{c['file']}: fixture should start as status: active (pre-audit)")

    return cases


def _find_fn(mod, candidates):
    for name in candidates:
        fn = getattr(mod, name, None)
        if fn is not None:
            return name, fn
    return None, None


def test_deterministic_layer(cases):
    sys.path.insert(0, str(KIT_ROOT / "scripts"))
    try:
        brain_aging = importlib.import_module("brain_aging")
    except ImportError as e:
        print(f"test_aging_fixtures: cannot import scripts/brain_aging.py yet ({e}); "
              "expected once the aging module lands (deterministic-layer check skipped for now)")
        failures.append("scripts/brain_aging.py not importable yet")
        return

    today = datetime.date.today().isoformat()

    with tempfile.TemporaryDirectory() as td:
        sandbox_vault = Path(td).resolve() / "vault"
        sandbox_vault.mkdir(parents=True, exist_ok=True)
        sandbox_queue = sandbox_vault / "gate-queue"
        sandbox_queue.mkdir(parents=True, exist_ok=True)

        stale_case = next((c for c in cases if c["expected_verdict"] == "stale"), None)
        escalate_case = next((c for c in cases if c["expected_verdict"] == "superseded-candidate"), None)

        # --- stale: fed a canned "stale" verdict, frontmatter gets status: stale ---
        if stale_case:
            stale_name, stale_fn = _find_fn(brain_aging, ["mark_stale"])
            if stale_fn is None:
                failures.append("brain_aging.py exposes no mark_stale() function")
            else:
                rel = stale_case["file"]
                note_path = sandbox_vault / rel
                note_path.write_text(
                    (FIXTURES_DIR / stale_case["file"]).read_text(encoding="utf-8"),
                    encoding="utf-8")
                try:
                    stale_fn(sandbox_vault, rel, "aged, no contradiction found", today)
                except TypeError as e:
                    failures.append(f"{stale_name}(vault, rel, reason, today) call failed: {e}")
                else:
                    after = note_path.read_text(encoding="utf-8")
                    check("status: stale" in after,
                          f"{stale_name}() should set status: stale in the note's frontmatter")
        else:
            failures.append("no 'stale' case found in expected.json to drive the mark_stale check")

        # --- escalate: fed a canned contradiction verdict, a queue entry appears ---
        if escalate_case:
            escalate_name, escalate_fn = _find_fn(brain_aging, ["escalate"])
            if escalate_fn is None:
                failures.append("brain_aging.py exposes no escalate() function")
            else:
                rel = escalate_case["file"]
                note_path = sandbox_vault / rel
                original_text = (FIXTURES_DIR / escalate_case["file"]).read_text(encoding="utf-8")
                note_path.write_text(original_text, encoding="utf-8")

                before_queue = set(sandbox_queue.glob("*.md"))
                try:
                    result = escalate_fn(sandbox_vault, sandbox_queue, rel,
                                          "contradicts current ground truth", today)
                except TypeError as e:
                    failures.append(f"{escalate_name}(vault, queue_dir, rel, reason, today) call failed: {e}")
                    result = None
                after_queue = set(sandbox_queue.glob("*.md"))
                new_files = after_queue - before_queue

                check(note_path.read_text(encoding="utf-8") == original_text,
                      "escalate() must never edit the contradicted note directly "
                      "(supersede is always a human decision)")
                check(bool(new_files) or (result and Path(str(result)).exists()),
                      f"{escalate_name}() should create a new escalation queue entry, "
                      "not modify the note in place")

                new_file = next(iter(new_files), Path(str(result)) if result else None)
                if new_file is not None and new_file.exists():
                    entry_text = new_file.read_text(encoding="utf-8")
                    check("escalated_at" in entry_text,
                          f"{escalate_name}() output has no 'escalated_at' marker; "
                          "gate_judge.load_queue()/stamp_escalated() key off exactly that "
                          "field name, so an aging escalation would never be recognized "
                          "as already-escalated and could be re-surfaced to the judge "
                          "forever (cross-module interop gap, not a test artifact)")
        else:
            failures.append(
                "no 'superseded-candidate' case found in expected.json to drive the escalate check")


def main():
    cases = test_fixture_structure()
    if cases:
        test_deterministic_layer(cases)
    if failures:
        print(f"test_aging_fixtures: {len(failures)} failure(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("test_aging_fixtures: OK")


if __name__ == "__main__":
    main()
