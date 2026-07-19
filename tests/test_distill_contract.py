#!/usr/bin/env python3
"""Contract of the distillation output parser (brain_daily.parse_candidates).

The model must answer with a JSON array; [] is a valid empty day. Anything else
(e.g. the model ended its turn "waiting for background subagents") means the run
did NOT complete and must parse as None -> FAILURE, so the state file stays
untouched and the scheduler retry covers the window. In v1.8.0 this parsed as []
-> fake success, which silently skipped distillation for 4 days (2026-07-16/19).
"""
import json
import sys
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT_ROOT / "scripts"))

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


def wrap(result_text):
    """Mimic `claude -p --output-format json` stdout."""
    return json.dumps({"result": result_text})


def test_parse_candidates():
    import brain_daily as bd

    cands = [{"type": "lesson", "title": "T", "body": "B"}]

    # 1. valid array inside the CLI JSON wrapper
    got = bd.parse_candidates(wrap("Here you go:\n" + json.dumps(cands)))
    check(got == cands, f"valid array must parse, got: {got!r}")

    # 2. explicit empty day
    check(bd.parse_candidates(wrap("[]")) == [],
          "[] is a valid empty day and must parse as an empty list, not a failure")

    # 3. no array at all (turn ended waiting on subagents) -> FAILURE
    check(bd.parse_candidates(wrap("Waiting for the background agents to finish.")) is None,
          "output without a JSON array must be None (failure), not []")

    # 4. malformed array -> FAILURE
    check(bd.parse_candidates(wrap('[{"type": }]')) is None,
          "invalid JSON inside the array must be None (failure), not []")

    # 5. raw (non-wrapper) stdout still parses
    check(bd.parse_candidates("noise [1, 2] noise") == [1, 2],
          "array embedded in raw stdout must parse")


def main():
    test_parse_candidates()
    if failures:
        print(f"test_distill_contract: {len(failures)} failure(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("test_distill_contract: OK")


if __name__ == "__main__":
    main()
