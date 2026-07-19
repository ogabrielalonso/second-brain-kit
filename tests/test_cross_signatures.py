#!/usr/bin/env python3
"""Cross-module CALL contracts, exercised through the same code paths the
pipelines use (not just signature inspection).

In v1.8.0 brain_weekly_auto called gate_log.compute_stats(weeks=12) without the
required cfg; the defensive try/except swallowed the TypeError forever, so the
gate-telemetry section of the weekly report silently never rendered. Same class:
notify.send() promised "never raises" but read the config outside its try, so a
corrupted config at notification time crashed jobs after their real work.
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


def _env(cfg_path):
    old = os.environ.get("BRAIN_CONFIG")
    os.environ["BRAIN_CONFIG"] = str(cfg_path)
    return old


def _restore(old):
    if old is None:
        os.environ.pop("BRAIN_CONFIG", None)
    else:
        os.environ["BRAIN_CONFIG"] = old


def _sandbox(tmp):
    vault = tmp / "vault"
    (vault / "_system" / "telemetry").mkdir(parents=True)
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


def test_compute_stats_called_the_weekly_way():
    with tempfile.TemporaryDirectory() as td:
        cfg_path = _sandbox(Path(td))
        old = _env(cfg_path)
        try:
            import brain_config
            importlib.reload(brain_config)
            gl = importlib.import_module("gate_log")
            importlib.reload(gl)
            # Exactly the call brain_weekly_auto.gate_telemetry_section makes.
            try:
                s = gl.compute_stats(gl.load_config(), 12)
            except TypeError as e:
                failures.append(f"compute_stats signature drifted from the weekly call: {e}")
                return
            check(s is not None, "compute_stats must return a value on an empty telemetry dir")
        finally:
            _restore(old)


def test_notify_send_never_raises():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        broken = tmp / "config.json"
        broken.write_text("{ this is not json", encoding="utf-8")
        old = _env(broken)
        try:
            import notify
            importlib.reload(notify)
            try:
                got = notify.send("test message from the kit test suite")
            except Exception as e:
                failures.append(f"notify.send() raised with a corrupted config: {e!r}; "
                                "its contract is 'never raises'")
                return
            check(got is False,
                  "notify.send() with a corrupted config must return False (dropped)")
        finally:
            _restore(old)


def main():
    test_compute_stats_called_the_weekly_way()
    test_notify_send_never_raises()
    if failures:
        print(f"test_cross_signatures: {len(failures)} failure(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("test_cross_signatures: OK")


if __name__ == "__main__":
    main()
