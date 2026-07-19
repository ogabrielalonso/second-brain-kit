#!/usr/bin/env python3
"""brain_watchdog: guardian of the autonomous brain.

The system operates without the owner in the loop; this watchdog is what
WARNS when something stops working (silence must never mean "healthy"). Runs
on the scheduler every few hours plus at boot. Self-heals where safe (daemon
restart, reindex); notifies where it needs a human.

Checks:
  1. the daily distillation ran recently (state file)
  2. last weekly report exists (weekly not silently skipped)
  3. brain-daemon answers on its derived port AND its instance_id matches
     config (self-heal: restart, re-check, notify if it persists)
  4. escalated queue: too many pending, or the oldest is too old
  5. semantic index staleness (a note newer than the index build) -> reindex

Anti-spam: each alert fires at most once per 12h (state cached on disk).

Usage: brain_watchdog.py
"""
import os
import sys
import json
import time
import platform
import datetime
import subprocess
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import brain_config  # noqa: E402

BRAIN_HOME = brain_config.brain_home()
LOG = BRAIN_HOME / "logs" / "brain-watchdog.log"
ALERTS = BRAIN_HOME / "cache" / "watchdog_alerts.json"
MANIFEST = brain_config.index_dir() / "manifest.json"
# Shared-path contract: this MUST be the exact file brain_daily.py's mark_ok()
# writes; a mismatch fires "never ran" forever even on healthy installs
# (found by the first team install, 2026-07-18). Guarded by test_shared_paths.py.
DAILY_STATE = BRAIN_HOME / "cache" / "daily" / ".last_run"
DAILY_STALE_H = 36


def log(msg):
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] [watchdog] {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def alert(key, msg, cooldown_h=12):
    """ntfy with per-key anti-spam."""
    state = {}
    if ALERTS.exists():
        try:
            state = json.loads(ALERTS.read_text())
        except json.JSONDecodeError:
            pass
    now = datetime.datetime.now()
    last = state.get(key)
    if last:
        try:
            if (now - datetime.datetime.fromisoformat(last)).total_seconds() < cooldown_h * 3600:
                log(f"alert '{key}' suppressed (cooldown): {msg}")
                return
        except ValueError:
            pass
    from notify import send
    if send(msg, title="brain watchdog", priority="high", tags="warning"):
        log(f"ALERT sent ({key}): {msg}")
    state[key] = now.isoformat()
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    ALERTS.write_text(json.dumps(state))


def check_daily():
    if not DAILY_STATE.exists():
        alert("daily-never", "brain daily distillation has never run (state file missing)")
        return
    age_h = (datetime.datetime.now().timestamp() - DAILY_STATE.stat().st_mtime) / 3600
    if age_h > DAILY_STALE_H:
        alert("daily-stalled",
              f"brain daily distillation has not run in {age_h:.0f}h "
              "(machine off at the scheduled slot?). Run it manually.")
    else:
        log(f"daily ok (last run {age_h:.1f}h ago)")


def check_weekly(vault, weekly_dir):
    today = datetime.date.today()
    last_sat = today - datetime.timedelta(days=(today.weekday() - 5) % 7)
    if today == last_sat:
        return  # Saturday itself: give the day's own job time to run
    wdir = vault / weekly_dir
    recent = sorted(wdir.glob("Brain-Weekly-2*.md")) if wdir.exists() else []
    newest = recent[-1].stem.replace("Brain-Weekly-", "") if recent else "1970-01-01"
    try:
        if datetime.date.fromisoformat(newest) >= last_sat:
            log(f"weekly ok ({newest})")
            return
    except ValueError:
        pass
    alert("weekly-missing",
          f"the weekly report for {last_sat} is missing; run brain_weekly_auto.py")


def check_daemon(port, instance_id):
    def health():
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
                data = json.loads(r.read())
                return data.get("status") == "ok" and data.get("instance_id") == instance_id
        except Exception:
            return False
    if health():
        log("daemon ok")
        return
    log("daemon down or answering for a different instance; attempting restart")
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["launchctl", "kickstart", "-k",
                        f"gui/{os.getuid()}/com.brainkit.daemon"],
                       capture_output=True, text=True)
    elif system == "Linux":
        subprocess.run(["systemctl", "--user", "restart", "brainkit-daemon.service"],
                       capture_output=True, text=True)
    else:
        alert("daemon-down-unsupported-os",
              "brain-daemon is unreachable and this OS has no self-heal wired")
        return
    time.sleep(10)
    if health():
        alert("daemon-restart",
              "brain-daemon was down and was RESTARTED successfully by the watchdog",
              cooldown_h=24)
    else:
        alert("daemon-down",
              "brain-daemon is DOWN and the restart did not fix it; semantic search unavailable")


def check_escalated(vault, queue_dir, queue_alert):
    qdir = vault / queue_dir
    if not qdir.exists():
        return
    # Same criterion as gate_judge.load_queue (everything except _scaffolding):
    # the counted queue must be the judged queue, or the two disagree silently.
    pend = [p for p in qdir.glob("*.md") if not p.name.startswith("_")]
    if len(pend) > queue_alert:
        alert("queue-full", f"{len(pend)} escalated items pending in the gate "
                            f"(limit {queue_alert}); review with the weekly ritual")
        return
    if pend:
        oldest = min(p.stat().st_mtime for p in pend)
        age_d = (datetime.datetime.now().timestamp() - oldest) / 86400
        if age_d > 30:
            alert("escalated-stale",
                  f"an escalated item has been waiting {age_d:.0f} days; review with the weekly ritual")
        else:
            log(f"escalated ok ({len(pend)} pending, oldest {age_d:.0f}d)")
    else:
        log("escalated ok (queue empty)")


def check_index_fresh(vault, index_targets, index_exclude, stale_h):
    """A manual edit in the vault editor does not trigger the post-commit hook;
    if the index went stale, self-heal by reindexing (deterministic)."""
    try:
        built = datetime.datetime.fromisoformat(
            json.loads(MANIFEST.read_text())["built_at"].replace("Z", "+00:00")).timestamp()
    except Exception as e:
        log(f"manifest unreadable ({e}); skipping index check")
        return
    newest = 0
    for d in index_targets:
        root = vault / d
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            rel = str(p.relative_to(vault))
            if any(pat in rel for pat in index_exclude):
                continue
            newest = max(newest, p.stat().st_mtime)
    lag_h = (newest - built) / 3600
    if lag_h > stale_h:
        log(f"index stale ({lag_h:.0f}h behind the vault); running embed.sh")
        r = subprocess.run([str(Path(__file__).parent / "embed.sh")],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode == 0:
            alert("reindex-heal", "the index was stale and was REINDEXED by the watchdog",
                  cooldown_h=48)
        else:
            alert("reindex-fail", "the index is stale and the reindex FAILED")
    else:
        log(f"index ok (lag {max(lag_h, 0):.1f}h)")


def check_backup_remote(vault):
    """Continuous backup: the post-commit hook does a best-effort push; this is
    the safety net. If the remote is behind, try to push; if that fails
    (offline, credentials), alert."""
    r = subprocess.run(["git", "-C", str(vault), "symbolic-ref", "--short", "HEAD"],
                       capture_output=True, text=True)
    branch = r.stdout.strip() or "main"
    r = subprocess.run(["git", "-C", str(vault), "rev-list", "--count",
                        f"origin/{branch}..{branch}"], capture_output=True, text=True)
    if r.returncode != 0:
        alert("backup-no-remote", "the vault has no remote configured or origin is unreachable")
        return
    behind = int(r.stdout.strip() or 0)
    if behind == 0:
        log("backup ok (remote up to date)")
        return
    log(f"remote {behind} commits behind; attempting push")
    p = subprocess.run(["git", "-C", str(vault), "push", "origin", branch, "--quiet"],
                       capture_output=True, text=True, timeout=300)
    if p.returncode == 0:
        log(f"push ok ({behind} commits sent)")
    else:
        alert("backup-behind",
              f"the backup push FAILED with {behind} commits pending "
              "(offline? credentials?); the vault has no up-to-date backup")


def main():
    vault = brain_config.vault_path()
    taxonomy = brain_config.taxonomy()
    thresholds = brain_config.thresholds()
    port = brain_config.port()
    instance_id = brain_config.instance_id()
    weekly_dir = taxonomy.get('weekly_dir', '04-Journal/Weekly')
    queue_dir = taxonomy.get('queue_dir', '04-Journal/gate-queue')
    index_targets = taxonomy.get('index_targets', [])
    index_exclude = taxonomy.get('index_exclude', [])
    stale_h = thresholds.get('index_stale_h', 12)
    queue_alert = thresholds.get('queue_alert', 15)

    checks = [
        ("check_daily", lambda: check_daily()),
        ("check_weekly", lambda: check_weekly(vault, weekly_dir)),
        ("check_daemon", lambda: check_daemon(port, instance_id)),
        ("check_escalated", lambda: check_escalated(vault, queue_dir, queue_alert)),
        ("check_index_fresh", lambda: check_index_fresh(vault, index_targets, index_exclude, stale_h)),
        ("check_backup_remote", lambda: check_backup_remote(vault)),
    ]
    for name, fn in checks:
        try:
            fn()
        except Exception as e:
            # a broken check is a blind watchdog; it MUST reach the phone
            log(f"{name} broke: {e}")
            try:
                alert(f"check-broken-{name}", f"watchdog: check {name} BROKE ({e}); "
                     "the watchdog is partially blind")
            except Exception:
                pass


if __name__ == "__main__":
    main()
