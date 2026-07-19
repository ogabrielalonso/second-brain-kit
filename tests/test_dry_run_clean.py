#!/usr/bin/env python3
"""--dry-run means ZERO side effects inside the owner's vault.

In v1.8.0, brain_weekly_auto --dry-run still invoked brain_weekly.py, which
wrote the weekly report into the vault. This test runs the real weekly-auto in
dry mode against a throwaway git vault and asserts the working tree stays
clean. Requires git on PATH (same requirement as the kit itself).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


def git(vault, *args):
    return subprocess.run(["git", "-C", str(vault), *args],
                          capture_output=True, text=True)


def test_weekly_auto_dry_run_leaves_vault_clean():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        vault = tmp / "vault"
        for d in ("00-HOME", "03-Knowledge", "04-Journal/Weekly",
                  "04-Journal/gate-queue", "_system/telemetry"):
            (vault / d).mkdir(parents=True)
        (vault / "00-HOME" / "who-i-am.md").write_text(
            "---\ntype: identity\n---\n\n# Who I am\n\nSandbox owner.\n", encoding="utf-8")
        (vault / "03-Knowledge" / "note.md").write_text(
            "---\ntype: note\ntitle: \"A note\"\ncreated: 2026-07-01\n---\n\n# A note\n\nBody.\n",
            encoding="utf-8")

        git(vault, "init", "-q")
        git(vault, "add", "-A")
        git(vault, "-c", "user.email=kit-test@local", "-c", "user.name=kit-test",
            "commit", "-qm", "fixture")

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

        env = dict(os.environ)
        env["BRAIN_CONFIG"] = str(cfg_path)
        r = subprocess.run(
            [sys.executable, str(KIT_ROOT / "scripts" / "brain_weekly_auto.py"), "--dry-run"],
            capture_output=True, text=True, env=env, timeout=300)
        check(r.returncode == 0,
              f"weekly-auto --dry-run exited rc={r.returncode}: {r.stderr[-300:]}")

        status = git(vault, "status", "--porcelain").stdout.strip()
        check(status == "",
              f"--dry-run left changes in the vault working tree:\n{status}")


def main():
    test_weekly_auto_dry_run_leaves_vault_clean()
    if failures:
        print(f"test_dry_run_clean: {len(failures)} failure(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("test_dry_run_clean: OK")


if __name__ == "__main__":
    main()
