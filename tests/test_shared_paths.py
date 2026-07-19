#!/usr/bin/env python3
"""Cross-module PATH contracts: files one script writes and another reads.

The v1.8.0 watchdog pointed DAILY_STATE at state/brain_daily.last_run while
brain_daily.py wrote cache/daily/.last_run, so every install alerted "daily
distillation has never run" forever (found by the first team install,
2026-07-18). This test pins the shared paths so a drift on either side fails
the suite instead of shipping.
"""
import importlib
import json
import os
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


def _sandbox_config(tmp):
    vault = tmp / "vault"
    vault.mkdir()
    cfg = {
        "owner_name": "Sandbox Owner",
        "main_language": "en",
        "vault_path": str(vault),
        "port": 8899,
        "instance_id": "sandbox0001",
        "judge_enabled": False,
    }
    cfg_path = tmp / "config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg_path


def test_daily_state_path_contract():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cfg_path = _sandbox_config(tmp)
        old = os.environ.get("BRAIN_CONFIG")
        os.environ["BRAIN_CONFIG"] = str(cfg_path)
        try:
            import brain_config
            importlib.reload(brain_config)
            wd = importlib.import_module("brain_watchdog")
            importlib.reload(wd)

            # The exact expression brain_daily.py's main() uses for its state file.
            daily_writes = brain_config.brain_home() / "cache" / "daily" / ".last_run"
            check(wd.DAILY_STATE == daily_writes,
                  f"watchdog DAILY_STATE ({wd.DAILY_STATE}) != the file brain_daily "
                  f"writes ({daily_writes}); 'never ran' will fire forever")

            # Belt and suspenders: the daily source must still build the state file
            # from cache/daily/.last_run (if this moves, update BOTH sides + here).
            src = (KIT_ROOT / "scripts" / "brain_daily.py").read_text(encoding="utf-8")
            check('cache_daily / ".last_run"' in src and '"cache" / "daily"' in src,
                  "brain_daily.py no longer derives its state file from "
                  "cache/daily/.last_run; update brain_watchdog.DAILY_STATE and this test")
        finally:
            if old is None:
                os.environ.pop("BRAIN_CONFIG", None)
            else:
                os.environ["BRAIN_CONFIG"] = old


def test_workspace_exclusion_matches_project_dir_encoding():
    # Claude Code project dirs encode EVERY non-alphanumeric char as '-'
    # (a home-dir path to .brain/daily-workspace becomes ...--brain-daily-workspace:
    # note the DOUBLE dash where the dot was). A naive slash-to-dash replace keeps
    # the dot, never matches, and the kit's own headless transcripts feed back into
    # distillation (audit 2026-07-19, bug 18).
    import brain_daily as bd
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        exclude_under = tmp / ".brainhome"
        encoded_name = "".join(c if c.isalnum() else "-" for c in str(exclude_under / "daily-workspace"))
        proj = tmp / "projects" / encoded_name
        proj.mkdir(parents=True)
        session = proj / "abc.jsonl"
        session.write_text(('{"type":"user"}\n' * 5) + ("x" * 20000), encoding="utf-8")

        got = bd.collect_recent_sessions([tmp / "projects"], hours=24, exclude_under=exclude_under)
        check(got == [],
              f"a session inside the kit's own workspace dir must be excluded, got: {got}")


def test_queue_criterion_is_shared():
    # The queue the watchdog COUNTS must be the queue the judge JUDGES:
    # both ignore underscore-prefixed scaffolding, nothing else.
    wd_src = (KIT_ROOT / "scripts" / "brain_watchdog.py").read_text(encoding="utf-8")
    check('p.name.startswith("_")' in wd_src,
          "brain_watchdog.py lost the shared underscore-scaffolding queue criterion")
    gj_src = (KIT_ROOT / "scripts" / "gate_judge.py").read_text(encoding="utf-8")
    check('p.name.startswith("_")' in gj_src,
          "gate_judge.py lost the shared underscore-scaffolding queue criterion")


def main():
    test_daily_state_path_contract()
    test_queue_criterion_is_shared()
    if failures:
        print(f"test_shared_paths: {len(failures)} failure(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("test_shared_paths: OK")


if __name__ == "__main__":
    main()
