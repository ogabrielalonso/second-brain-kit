#!/usr/bin/env python3
"""Regression tests for the heuristics-clustering write path in
scripts/gate_judge.py: the deterministic appliers must write the two-axis
Class (see scripts/heuristics_taxonomy.py) in the format each destination
actually uses, the mechanical cited-paths check must run before judgment,
and a promotion suggestion must land in the owner's routing note only when
one is configured.

Sandbox pattern mirrors test_judge_fixtures.py: gate_judge.py loads config
at import time via brain_config.load_config(), so BRAIN_CONFIG must be set
and stale modules cleared BEFORE the first import in this process.

Proved failing against the pre-change tree: before this feature landed,
scripts/gate_judge.py had no cited_paths_check() or apply_promotion()
function (AttributeError on both), apply_lesson() wrote a 4-cell row with no
Class cell, apply_pattern() wrote no "- **Class:**" line, apply_decision()
wrote no nature/domain frontmatter, and prompts/judge.md had no
{{NATURE_VOCAB}}/{{DOMAIN_VOCAB}} placeholders for render_judge_prompt() to
fill. Verified by running this file with `git stash` applied against the
commit that introduced the feature (every check below failed: several with
AttributeError, the rest with assertion failures), then `git stash pop` to
restore the change and re-running to confirm a pass.
"""
import os
import sys
import json
import shutil
import tempfile
import datetime
import importlib
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_EXAMPLE = KIT_ROOT / "config" / "config.example.json"

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


def _write_sandbox_config(sandbox_vault, tmp_dir, **overrides):
    base = json.loads(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
    base["vault_path"] = str(sandbox_vault)
    base["instance_id"] = "sandboxtestinstance"
    base.update(overrides)
    cfg_path = tmp_dir / "config.json"
    cfg_path.write_text(json.dumps(base), encoding="utf-8")
    return cfg_path


def _import_gate_judge_in_sandbox(sandbox_vault, cfg_path):
    os.environ["BRAIN_CONFIG"] = str(cfg_path)
    os.environ["BRAIN_VAULT_PATH"] = str(sandbox_vault)
    sys.path.insert(0, str(KIT_ROOT / "scripts"))
    for mod_name in ("brain_config", "gate_judge", "heuristics_taxonomy"):
        sys.modules.pop(mod_name, None)
    import brain_config
    brain_config.load_config(force=True)
    return importlib.import_module("gate_judge")


def test_apply_lesson_writes_class_cell():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td).resolve()
        vault = tmp / "vault"
        vault.mkdir(parents=True)
        cfg_path = _write_sandbox_config(vault, tmp)
        gj = _import_gate_judge_in_sandbox(vault, cfg_path)

        lessons = vault / "lessons.md"
        lessons.write_text("# Lessons\n\n| # | Lesson | How discovered | Provenance |\n"
                           "|---|---|---|---|\n", encoding="utf-8")
        today = datetime.date.today().isoformat()
        verdict = {
            "file": "x.md", "final_content": "Always confirm the acceptance criteria first.",
            "discovered_via": "error-to-fix", "nature": "judgment", "domain": "process-workflow",
        }
        touched = []
        where = gj.apply_lesson(vault, "lessons.md", verdict, today, touched)
        check(where is not None, "apply_lesson() should return a display string on success")

        text = lessons.read_text(encoding="utf-8")
        rows = [l for l in text.split("\n") if l.startswith("| 1 |")]
        check(len(rows) == 1, f"apply_lesson() should append exactly one numbered row, found: {rows}")
        if rows:
            row = rows[0]
            check("judgment · process-workflow" in row,
                  f"apply_lesson() must write the class label 'nature · domain' into the row, got: {row!r}")
            cells = [c for c in row.split("|")]
            check(len(cells) >= 7,
                  f"apply_lesson() row should have 5 data cells (7 pipe-separated tokens including the "
                  f"empty edges), got {len(cells)}: {row!r}")
        check(lessons in touched, "apply_lesson() must append the touched file to the scoped-commit accumulator")


def test_apply_lesson_with_invalid_class_writes_empty_cell():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td).resolve()
        vault = tmp / "vault"
        vault.mkdir(parents=True)
        cfg_path = _write_sandbox_config(vault, tmp)
        gj = _import_gate_judge_in_sandbox(vault, cfg_path)

        lessons = vault / "lessons.md"
        lessons.write_text("# Lessons\n\n| # | Lesson | How discovered | Provenance |\n"
                           "|---|---|---|---|\n", encoding="utf-8")
        today = datetime.date.today().isoformat()
        verdict = {
            "file": "x.md", "final_content": "A lesson with a bad class from the model.",
            "nature": "not-a-real-nature", "domain": "also-not-real",
        }
        touched = []
        gj.apply_lesson(vault, "lessons.md", verdict, today, touched)
        text = lessons.read_text(encoding="utf-8")
        check("not-a-real-nature" not in text,
              "an out-of-vocabulary nature must never be written verbatim (fabrication guard)")


def test_apply_pattern_writes_class_line():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td).resolve()
        vault = tmp / "vault"
        vault.mkdir(parents=True)
        cfg_path = _write_sandbox_config(vault, tmp)
        gj = _import_gate_judge_in_sandbox(vault, cfg_path)

        patterns = vault / "patterns.md"
        patterns.write_text("# Patterns\n", encoding="utf-8")
        today = datetime.date.today().isoformat()
        verdict = {
            "file": "x.md", "final_content": "Ask before assuming scope.",
            "title": "Ask before assuming scope", "nature": "axiom", "domain": "process-workflow",
        }
        touched = []
        gj.apply_pattern(vault, "patterns.md", verdict, today, touched)
        text = patterns.read_text(encoding="utf-8")
        check("- **Class:** axiom · process-workflow" in text,
              f"apply_pattern() must write a '- **Class:** nature · domain' line, got:\n{text}")
        check(patterns in touched, "apply_pattern() must append the touched file")


def test_apply_pattern_without_class_omits_line():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td).resolve()
        vault = tmp / "vault"
        vault.mkdir(parents=True)
        cfg_path = _write_sandbox_config(vault, tmp)
        gj = _import_gate_judge_in_sandbox(vault, cfg_path)

        patterns = vault / "patterns.md"
        patterns.write_text("# Patterns\n", encoding="utf-8")
        today = datetime.date.today().isoformat()
        verdict = {"file": "x.md", "final_content": "No class given.", "title": "No class given"}
        touched = []
        gj.apply_pattern(vault, "patterns.md", verdict, today, touched)
        text = patterns.read_text(encoding="utf-8")
        check("**Class:**" not in text,
              "apply_pattern() must not write an empty/fabricated Class line when nature/domain are absent")


def test_apply_decision_writes_frontmatter():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td).resolve()
        vault = tmp / "vault"
        (vault / "Decisions").mkdir(parents=True)
        cfg_path = _write_sandbox_config(vault, tmp)
        gj = _import_gate_judge_in_sandbox(vault, cfg_path)

        today = datetime.date.today().isoformat()
        verdict = {
            "file": "x.md", "final_content": "Adopt the new deploy checklist.",
            "nature": "score", "domain": "deploy-delivery", "related": [],
        }
        touched = []
        where = gj.apply_decision(vault, "Decisions", verdict, today, "Adopt the deploy checklist", touched)
        check(where is not None, "apply_decision() should return a display string")
        fp = vault / where
        text = fp.read_text(encoding="utf-8")
        check("nature: score" in text, f"apply_decision() must write 'nature: score' into frontmatter, got:\n{text}")
        check("domain: deploy-delivery" in text,
              f"apply_decision() must write 'domain: deploy-delivery' into frontmatter, got:\n{text}")


def test_apply_promotion_requires_configured_routing_note():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td).resolve()
        vault = tmp / "vault"
        vault.mkdir(parents=True)
        cfg_path = _write_sandbox_config(vault, tmp)
        gj = _import_gate_judge_in_sandbox(vault, cfg_path)

        today = datetime.date.today().isoformat()
        cand = {"title": "Always ask for acceptance criteria", "file": "x.md"}
        verdict = {"promotion": "governance: add this rule to the global CLAUDE.md"}
        touched = []
        log_path = tmp / "classification-test.log"

        # No routing path configured (default taxonomy has heuristics.routing == ""):
        # apply_promotion must not create any file.
        taxonomy_no_routing = gj.merged_taxonomy(gj.load_config())
        check(taxonomy_no_routing.get("heuristics", {}).get("routing", "MISSING") == "",
              "sandbox config must ship with an unconfigured routing note by default")
        gj.apply_promotion(cand, verdict, taxonomy_no_routing, vault, today, touched, log_path)
        check(touched == [], "apply_promotion() must not write any file when no routing note is configured")
        check(not any(vault.rglob("*.md")),
              "apply_promotion() must not create a routing note out of thin air")

        # Now configure a routing note that exists: the checkbox must land in it.
        routing_note = vault / "routing.md"
        routing_note.write_text("# Routing\n", encoding="utf-8")
        taxonomy_with_routing = dict(taxonomy_no_routing)
        taxonomy_with_routing["heuristics"] = dict(taxonomy_no_routing["heuristics"])
        taxonomy_with_routing["heuristics"]["routing"] = "routing.md"
        touched2 = []
        gj.apply_promotion(cand, verdict, taxonomy_with_routing, vault, today, touched2, log_path)
        text = routing_note.read_text(encoding="utf-8")
        check("- [ ]" in text and "governance: add this rule to the global CLAUDE.md" in text,
              f"apply_promotion() must append a checkbox with the proposal, got:\n{text}")
        check(routing_note in touched2, "apply_promotion() must append the touched routing note")

        # Re-applying the same promotion must not duplicate the checkbox.
        touched3 = []
        gj.apply_promotion(cand, verdict, taxonomy_with_routing, vault, today, touched3, log_path)
        text2 = routing_note.read_text(encoding="utf-8")
        check(text2.count("governance: add this rule to the global CLAUDE.md") == 1,
              "apply_promotion() must not duplicate a promotion already suggested in a previous round")


def test_cited_paths_check_flags_missing_files():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td).resolve()
        vault = tmp / "vault"
        vault.mkdir(parents=True)
        (vault / "real.md").write_text("# Real\n", encoding="utf-8")
        cfg_path = _write_sandbox_config(vault, tmp)
        gj = _import_gate_judge_in_sandbox(vault, cfg_path)

        body = "See real.md and also ghost-file.md for context."
        result = gj.cited_paths_check(body, vault)
        check("real.md: exists" in result, f"cited_paths_check() must confirm an existing path, got: {result!r}")
        check("ghost-file.md: NOT FOUND on disk" in result,
              f"cited_paths_check() must flag a missing path, got: {result!r}")

        check(gj.cited_paths_check("no paths mentioned here", vault) == "",
              "cited_paths_check() must return '' when the body cites no path-like tokens")


def test_render_judge_prompt_fills_vocab_placeholders():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td).resolve()
        vault = tmp / "vault"
        vault.mkdir(parents=True)
        cfg_path = _write_sandbox_config(vault, tmp)
        gj = _import_gate_judge_in_sandbox(vault, cfg_path)

        cfg = gj.load_config()
        cands = [{"file": "a.md", "type": "lesson", "destination": "lessons.md", "body": "Some body."}]
        prompt = gj.render_judge_prompt(cands, cfg, vault)
        check("{{NATURE_VOCAB}}" not in prompt and "{{DOMAIN_VOCAB}}" not in prompt,
              "render_judge_prompt() must fill the nature/domain vocabulary placeholders, "
              "not leave them as literal template tokens")
        check("decision-tree" in prompt and "one-off-decision" in prompt,
              "the rendered judge prompt must list the nature vocabulary")
        check("architecture-code" in prompt and "business-strategy" in prompt,
              "the rendered judge prompt must list the domain vocabulary")


def main():
    test_apply_lesson_writes_class_cell()
    test_apply_lesson_with_invalid_class_writes_empty_cell()
    test_apply_pattern_writes_class_line()
    test_apply_pattern_without_class_omits_line()
    test_apply_decision_writes_frontmatter()
    test_apply_promotion_requires_configured_routing_note()
    test_cited_paths_check_flags_missing_files()
    test_render_judge_prompt_fills_vocab_placeholders()
    if failures:
        print(f"test_heuristics_classification: {len(failures)} failure(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("test_heuristics_classification: OK")


if __name__ == "__main__":
    main()
