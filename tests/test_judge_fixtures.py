#!/usr/bin/env python3
"""Judge fixtures: structural validation + deterministic-layer regression.

IMPORTANT SCOPE NOTE: this test does NOT re-run the LLM judgment. The six
decisions pinned in fixtures/judge/expected.json (approve/edit/discard/
escalate per candidate) encode the escalation-precedence contract from
docs/ARCHITECTURE.md (dedup, too-specific, person-role, confidentiality,
contradiction, unknown-destination, cap) for a human or a backtest harness to
check against real judge output at install time (installer flow Phase 4). A
strong-model judgment call is not something a unit test can assert against
without calling the model itself, which this suite must not do.

What IS tested here, deterministically, against scripts/gate_judge.py:
  1. fixture structure: every .md parses with valid frontmatter and required
     fields, expected.json is well formed, files and cases match 1:1.
  2. the deterministic stamp_escalated() and apply_generic() layer, run
     against a throwaway sandbox vault (never the owner's real one).

gate_judge.py loads config at import time (`CONFIG = load_config()`) and
resolves its module-level VAULT from BRAIN_VAULT_PATH (falling back to
config.vault_path), so both env vars must be set BEFORE the module is
imported; setting them only after import is too late (this bit us once while
writing this test, see the git history of this file's sibling test).
"""
import os
import sys
import re
import json
import shutil
import tempfile
import datetime
import importlib
import inspect
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_EXAMPLE = KIT_ROOT / "config" / "config.example.json"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "judge"
EXPECTED_PATH = FIXTURES_DIR / "expected.json"
DECISION_ENUM = {"approve", "edit", "discard", "escalate"}
REQUIRED_FM_FIELDS = ["source", "type", "title", "description", "status", "created", "proposed_destination"]

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
    check(len(cases) == 6, f"expected.json should list exactly 6 cases, found {len(cases)}")

    md_files = sorted(p.name for p in FIXTURES_DIR.glob("*.md"))
    case_files = sorted(c["file"] for c in cases)
    check(md_files == case_files,
          f"fixture .md files and expected.json cases must match 1:1; "
          f"md={md_files} vs expected={case_files}")

    for c in cases:
        check(c.get("expected_decision") in DECISION_ENUM,
              f"{c.get('file')}: expected_decision '{c.get('expected_decision')}' "
              f"not in {sorted(DECISION_ENUM)}")
        fp = FIXTURES_DIR / c["file"]
        if not check(fp.exists(), f"{c['file']}: fixture file missing"):
            continue
        text = fp.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        if not check(fm is not None, f"{c['file']}: no parseable frontmatter block"):
            continue
        for field in REQUIRED_FM_FIELDS:
            check(field in fm, f"{c['file']}: frontmatter missing '{field}'")
        check(fm.get("status") == "draft", f"{c['file']}: frontmatter status should be 'draft' (pre-judgment)")

    return cases


def _write_sandbox_config(sandbox_vault, tmp_dir):
    base = json.loads(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
    base["vault_path"] = str(sandbox_vault)
    base["instance_id"] = "sandboxtestinstance"
    cfg_path = tmp_dir / "config.json"
    cfg_path.write_text(json.dumps(base), encoding="utf-8")
    return cfg_path


def _import_gate_judge_in_sandbox(sandbox_vault, cfg_path):
    """gate_judge.py runs `CONFIG = load_config()` and derives VAULT at import
    time, so BRAIN_CONFIG and BRAIN_VAULT_PATH must be set before the first
    import; a stale cached brain_config module (from an earlier import in
    this same process) is also cleared so load_config() re-reads our file."""
    os.environ["BRAIN_CONFIG"] = str(cfg_path)
    os.environ["BRAIN_VAULT_PATH"] = str(sandbox_vault)
    sys.path.insert(0, str(KIT_ROOT / "scripts"))
    for mod_name in ("brain_config", "gate_judge"):
        sys.modules.pop(mod_name, None)
    import brain_config
    brain_config.load_config(force=True)  # bust the module-level cache too
    return importlib.import_module("gate_judge")


def _find_fn(mod, candidates):
    for name in candidates:
        fn = getattr(mod, name, None)
        if fn is not None:
            return name, fn
    return None, None


def test_deterministic_layer(cases):
    with tempfile.TemporaryDirectory() as td:
        # resolved up front: apply_generic() compares an unresolved VAULT against
        # a .resolve()d target path for containment, so a symlinked tmp root
        # (e.g. macOS /var -> /private/var) would make a real, correct call look
        # like it escaped the vault. Real owner vault paths are not symlinked,
        # but the sandbox must not fail on that account.
        tmp = Path(td).resolve()
        sandbox_vault = tmp / "vault"
        sandbox_vault.mkdir(parents=True, exist_ok=True)
        cfg_path = _write_sandbox_config(sandbox_vault, tmp)

        try:
            gate_judge = _import_gate_judge_in_sandbox(sandbox_vault, cfg_path)
        except Exception as e:
            failures.append(f"cannot import scripts/gate_judge.py against a sandbox config yet ({e!r})")
            return

        today = datetime.date.today().isoformat()
        queue_dir = gate_judge.QUEUE_DIR if hasattr(gate_judge, "QUEUE_DIR") else sandbox_vault / "gate-queue"
        queue_dir.mkdir(parents=True, exist_ok=True)

        target_note = sandbox_vault / "target.md"
        target_note.write_text("---\ntitle: Target\n---\n\n# Target\n\nExisting content.\n",
                                encoding="utf-8")

        # --- stamp/escalate: feed the person-role candidate (case 03) ---
        escalate_case = next((c for c in cases if c["expected_decision"] == "escalate"
                               and c["category"] == "person-role"), None)
        if escalate_case:
            src = FIXTURES_DIR / escalate_case["file"]
            draft_copy = queue_dir / escalate_case["file"]
            shutil.copy(src, draft_copy)

            stamp_name, stamp_fn = _find_fn(gate_judge, ["stamp_escalated"])
            if stamp_fn is None:
                failures.append("gate_judge.py exposes no stamp_escalated() function")
            else:
                stamp_log_path = tmp / "gate-judge-test.log"
                stamp_touched = []
                stamp_fn(draft_copy, "escalated for test", today, stamp_log_path, stamp_touched)
                stamped_text = draft_copy.read_text(encoding="utf-8")
                check("escalated_at" in stamped_text,
                      f"{stamp_name}() should add an 'escalated_at' marker to the "
                      "frontmatter of an escalated candidate")
                check(draft_copy in stamp_touched,
                      f"{stamp_name}() should append the stamped path to the scoped-commit "
                      "'touched' accumulator (hardening #1: pipelines never git add -A)")

                # hardening item #6: a stamped item must be skipped by the next load
                load_name, load_fn = _find_fn(gate_judge, ["load_queue"])
                if load_fn is not None:
                    reloaded = load_fn(queue_dir, 20)
                    still_present = any(c.get("file") == escalate_case["file"] for c in reloaded)
                    check(not still_present,
                          f"{load_name}() must skip an already-escalated queue item "
                          "(it should wait for the human, not be re-judged)")
        else:
            failures.append("no escalate/person-role case found in expected.json to drive the stamp check")

        # --- apply: feed the approved lesson candidate (case 04) into an existing target file ---
        # gate_judge.py's real applier is a two-phase design (documented at the
        # top of the "deterministic appliers" section): resolve_destination()
        # is pure and picks the target, apply_resolved() does the write. There
        # is no single flat apply_generic(); drive the real two calls the same
        # way main() does, with an explicit final_destination redirect (judge
        # criterion 9) pointing at the existing target note.
        apply_case = next((c for c in cases if c["expected_decision"] == "approve"), None)
        if apply_case:
            resolve_name, resolve_fn = _find_fn(gate_judge, ["resolve_destination"])
            apply_name, apply_fn = _find_fn(gate_judge, ["apply_resolved"])
            if resolve_fn is None or apply_fn is None:
                failures.append(
                    "gate_judge.py exposes no resolve_destination()/apply_resolved() pair")
            else:
                verdict = {
                    "file": apply_case["file"],
                    "decision": "approve",
                    "final_content": "Ask for acceptance criteria before starting a build.",
                    "title": "Ask for the acceptance criteria before starting a build",
                    "final_destination": "target.md",
                    "related": [],
                }
                cand = {"file": apply_case["file"], "type": "lesson", "destination": "",
                        "title": apply_case.get("title", "")}
                apply_taxonomy = gate_judge.merged_taxonomy(gate_judge.load_config())
                apply_touched = []
                before = target_note.read_text(encoding="utf-8")
                try:
                    resolution = resolve_fn(cand, verdict, sandbox_vault, apply_taxonomy)
                    where = (apply_fn(resolution, cand, verdict, today, sandbox_vault,
                                       apply_taxonomy, apply_touched)
                             if resolution is not None else None)
                except Exception as e:
                    failures.append(
                        f"{resolve_name}()/{apply_name}() raised on a valid existing-target call: {e!r}")
                    where = None
                after = target_note.read_text(encoding="utf-8")
                check(where is not None,
                      f"{resolve_name}()/{apply_name}() should resolve an existing target and return its path")
                check(after != before,
                      f"{apply_name}() should have appended content to the existing target note")
                check("acceptance criteria" in after,
                      f"{apply_name}() output does not contain the approved content")
        else:
            failures.append("no approve case found in expected.json to drive the apply check")


def main():
    cases = test_fixture_structure()
    if cases:
        test_deterministic_layer(cases)
    if failures:
        print(f"test_judge_fixtures: {len(failures)} failure(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("test_judge_fixtures: OK")


if __name__ == "__main__":
    main()
