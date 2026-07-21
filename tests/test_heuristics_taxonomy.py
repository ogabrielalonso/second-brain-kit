#!/usr/bin/env python3
"""Regression tests for scripts/heuristics_taxonomy.py, the single source of
truth for the two-axis heuristics clustering vocabulary consumed by
gate_judge.py, classify_heuristics.py, prompts/judge.md and
prompts/distill_daily.md.

Proved failing against the pre-change tree: scripts/heuristics_taxonomy.py
did not exist before this feature landed, so `import heuristics_taxonomy`
raised ModuleNotFoundError and every check below failed at import time
(verified by running this file with `git stash` applied against the commit
that introduced heuristics_taxonomy.py, then `git stash pop` to restore it
and re-running to confirm a pass).
"""
import sys
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT_ROOT / "scripts"))

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


def test_validate_rejects_out_of_vocabulary():
    from heuristics_taxonomy import validate, NATURES, DOMAINS

    n, d = validate("decision-tree", "architecture-code")
    check(n == "decision-tree" and d == "architecture-code",
          "validate() must pass through a known nature/domain pair unchanged")

    n, d = validate("not-a-real-nature", "architecture-code")
    check(n == "", f"validate() must turn an invalid nature into '', got {n!r}")
    check(d == "architecture-code", "validate() must not punish a valid domain for an invalid nature")

    n, d = validate("decision-tree", "not-a-real-domain")
    check(d == "", f"validate() must turn an invalid domain into '', got {d!r}")

    n, d = validate(None, None)
    check(n == "" and d == "", "validate() must handle None inputs without raising")

    n, d = validate("Decision-Tree", "Architecture-Code")
    check(n == "decision-tree" and d == "architecture-code",
          "validate() must normalize case (the model may answer in any case)")

    n, d = validate("  score  ", "  data-facts  ")
    check(n == "score" and d == "data-facts",
          "validate() must strip surrounding whitespace")

    # Every value validate() can return must exist in the vocabulary dicts;
    # a silent drift here would let an invalid value slip through as valid.
    for nature in NATURES:
        vn, _ = validate(nature, "data-facts")
        check(vn == nature, f"NATURES key {nature!r} does not round-trip through validate()")
    for domain in DOMAINS:
        _, vd = validate("axiom", domain)
        check(vd == domain, f"DOMAINS key {domain!r} does not round-trip through validate()")


def test_class_label_format_and_stability():
    from heuristics_taxonomy import class_label

    label = class_label("decision-tree", "architecture-code")
    check(label == "decision-tree · architecture-code",
          f"class_label() format drifted, got: {label!r}")
    check("|" not in label,
          "class_label() must never contain a literal '|': it is written inside "
          "markdown table cells (lessons rows), where a pipe would silently add "
          "a phantom column")

    check(class_label("bogus", "architecture-code") == "",
          "class_label() must be '' when the nature is invalid")
    check(class_label("decision-tree", "bogus") == "",
          "class_label() must be '' when the domain is invalid")
    check(class_label("", "") == "", "class_label() must be '' for empty input")
    check(class_label(None, None) == "", "class_label() must handle None without raising")

    # stability: calling twice with the same input yields the same label
    check(class_label("judgment", "process-workflow") == class_label("judgment", "process-workflow"),
          "class_label() must be deterministic for the same input")


def test_vocab_prompt_covers_every_value():
    from heuristics_taxonomy import vocab_prompt, NATURES, DOMAINS

    text = vocab_prompt()
    for key in NATURES:
        check(key in text, f"vocab_prompt() is missing the nature key {key!r}")
    for key in DOMAINS:
        check(key in text, f"vocab_prompt() is missing the domain key {key!r}")
    check("NATURE" in text.upper() and "DOMAIN" in text.upper(),
          "vocab_prompt() should label both axes so a prompt reader can tell them apart")


def test_route_map_matches_natures_one_to_one():
    from heuristics_taxonomy import ROUTE, NATURES

    check(set(ROUTE.keys()) == set(NATURES.keys()),
          f"ROUTE keys must match NATURES keys exactly, got ROUTE={sorted(ROUTE)} "
          f"vs NATURES={sorted(NATURES)}")
    for nature, route in ROUTE.items():
        check(isinstance(route, str) and route,
              f"ROUTE[{nature!r}] must be a non-empty string, got {route!r}")


def main():
    test_validate_rejects_out_of_vocabulary()
    test_class_label_format_and_stability()
    test_vocab_prompt_covers_every_value()
    test_route_map_matches_natures_one_to_one()
    if failures:
        print(f"test_heuristics_taxonomy: {len(failures)} failure(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("test_heuristics_taxonomy: OK")


if __name__ == "__main__":
    main()
