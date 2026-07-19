#!/usr/bin/env python3
"""brain_daily: incremental daily pipeline of the brain kit.

Keeps the brain up to date without manual triggering, up to the gate boundary:

1. (DET)  Collect recent Claude Code sessions from config.sources (default
           ~/.claude/projects, plus any configured extra_paths).
2. (DET)  Sanitize every export via sanitize.py (secrets first, then the
           owner's confidential_patterns).
3. (GEN)  Headless `claude -p` call (cheap model) distills candidates for
           decision/lesson/heuristic from the prompt in prompts/distill_daily.md,
           deduplicating against the brain via query.sh (read-only tools).
4. (DET)  Writes candidates as drafts in the gate queue (config.taxonomy.queue_dir)
           and rebuilds the queue index.
5. (DET)  If config.judge_enabled: calls gate_judge.py (a strong model judges and
           applies most candidates to the canon; only escalated items wait for the
           owner). If judge_enabled is false (the default, judge ships DORMANT):
           only notifies that candidates are waiting for manual review.

This script depends only on brain_config.load_config() for owner state: never a
hardcoded path, and never one of brain_config's convenience helper functions
(vault_path(), taxonomy(), etc), so it keeps working even if those helpers change
shape. It reads the raw config dict and applies its own defaults where needed.

Usage: python3 brain_daily.py [--hours 26] [--max-candidates 5] [--dry-run]
                              [--model sonnet] [--judge-model opus] [--force]
       --dry-run: stops after step 2 (shows what would be distilled, no LLM call)
Env: BRAIN_CONFIG overrides the config file location (see brain_config.py); the
     brain's cache/state/logs directory is always derived from wherever that
     config actually resolves to, never from a separate hardcoded path.
"""
import re
import sys
import os
import json
import argparse
import subprocess
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain_config import load_config
from sanitize import sanitize

KIT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
PROMPT_FILE = KIT_ROOT / "prompts" / "distill_daily.md"
GATE_JUDGE = SCRIPTS_DIR / "gate_judge.py"
QUERY_SH = SCRIPTS_DIR / "query.sh"
CLAUDE_BIN = "claude"

DEFAULT_QUEUE_DIR = "04-Journal/gate-queue"   # mirrors the MODE B skeleton default
MIN_BYTES = 15_000       # ignore trivial sessions
MIN_USER_MSGS = 3
MAX_CATCHUP_H = 168      # cap catch-up window at 7 days


def brain_home():
    """Directory holding cache, model index, state and logs (always outside the
    vault). Derived directly from wherever config.json resolves to (honors the
    BRAIN_CONFIG override used by tests and multi-install setups); computed here
    rather than imported from brain_config so this script depends only on the
    config dict, per the kit's dependency contract."""
    return Path(os.environ.get("BRAIN_CONFIG", "~/.brain/config.json")).expanduser().parent


def log(msg, log_path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with log_path.open('a', encoding='utf-8') as f:
        f.write(line + "\n")


def notify(msg, title="brain-daily", priority=None, tags="brain"):
    """Best-effort notification; never lets a notification failure break the run."""
    try:
        from notify import send
        send(msg, title=title, priority=priority, tags=tags)
    except Exception:
        pass


def source_roots(cfg):
    """Resolve the directories to scan for session transcripts from config.sources."""
    roots = []
    src = cfg.get('sources') or {}
    if src.get('claude_projects', True):
        roots.append(Path.home() / ".claude" / "projects")
    for p in src.get('extra_paths', []) or []:
        roots.append(Path(p).expanduser())
    return roots


def collect_recent_sessions(roots, hours, exclude_under):
    """Sessions (*.jsonl) modified in the last N hours, filtered for relevance.

    exclude_under is brain_home: EVERY headless workspace of the kit's pipelines
    (daily-workspace, the aging/weekly workspace, future ones) lives under it, so
    one prefix match excludes them all. Matching only this pipeline's own dir let
    aging/weekly transcripts feed back into distillation as fake owner sessions."""
    cutoff = datetime.datetime.now().timestamp() - hours * 3600
    # Project dirs encode EVERY non-alphanumeric char as '-' ('.brain' -> '-brain');
    # a naive '/'->'-' replace keeps the dot and never matches, silently disabling
    # this exclusion (bug 18 of the 2026-07-19 audit). Mirror the real encoding.
    excluded_encoded = re.sub(r'[^A-Za-z0-9]', '-', str(exclude_under))
    found = []
    for root in roots:
        if not root.exists():
            continue
        for proj_dir in root.iterdir():
            if not proj_dir.is_dir():
                continue
            if excluded_encoded in proj_dir.name:   # exclude the kit's own headless runs
                continue
            for sf in proj_dir.glob('*.jsonl'):
                st = sf.stat()
                if st.st_mtime < cutoff or st.st_size < MIN_BYTES:
                    continue
                user_msgs = 0
                try:
                    with sf.open(encoding='utf-8', errors='replace') as f:
                        for line in f:
                            if '"type":"user"' in line or '"type": "user"' in line:
                                user_msgs += 1
                            if user_msgs >= MIN_USER_MSGS:
                                break
                except OSError:
                    continue
                if user_msgs < MIN_USER_MSGS:
                    continue
                found.append({'path': sf, 'project': proj_dir.name, 'bytes': st.st_size,
                              'mtime': datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec='minutes')})
    return sorted(found, key=lambda s: -s['bytes'])


def extract_session_text(jsonl_path, patterns, max_chars=1_500_000):
    """Extract the user/assistant conversation (no raw tool output) from a Claude
    Code session transcript and sanitize it. Returns plain text ready for an LLM."""
    parts = []
    chars = 0
    with jsonl_path.open(encoding='utf-8', errors='replace') as f:
        for line in f:
            if chars > max_chars:
                break
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get('type')
            ts = ev.get('timestamp', '')[:19]
            msg = ev.get('message', {})
            if not isinstance(msg, dict):
                continue
            content = msg.get('content', [])
            if t == 'user':
                if isinstance(content, str):
                    txt = content
                elif isinstance(content, list):
                    parts_in = []
                    for c in content:
                        if isinstance(c, dict):
                            if c.get('type') == 'text':
                                parts_in.append(c.get('text', ''))
                            elif c.get('type') == 'tool_result':
                                tr = c.get('content', '')
                                if isinstance(tr, str):
                                    parts_in.append(f'[tool_result] {tr[:500]}')
                    txt = '\n'.join(parts_in)
                else:
                    txt = str(content)
                if txt.strip():
                    parts.append(f'\n[{ts}] USER:\n{txt[:5000]}\n')
                    chars += len(txt[:5000])
            elif t == 'assistant':
                if isinstance(content, list):
                    parts_in = []
                    for c in content:
                        if isinstance(c, dict):
                            if c.get('type') == 'text':
                                parts_in.append(c.get('text', ''))
                            elif c.get('type') == 'tool_use':
                                name = c.get('name', '?')
                                inp = c.get('input', {})
                                if name == 'Bash':
                                    parts_in.append(f'[tool: Bash] {str(inp.get("command", ""))[:500]}')
                                elif name in ('Edit', 'Write'):
                                    parts_in.append(f'[tool: {name}] file={inp.get("file_path", "")}')
                                    if name == 'Edit':
                                        parts_in.append(f'  old: {str(inp.get("old_string", ""))[:300]}\n  new: {str(inp.get("new_string", ""))[:300]}')
                                else:
                                    parts_in.append(f'[tool: {name}]')
                    txt = '\n'.join(parts_in)
                    if txt.strip():
                        parts.append(f'\n[{ts}] ASSISTANT:\n{txt[:5000]}\n')
                        chars += len(txt[:5000])
    raw = ''.join(parts)
    sanitized, _ = sanitize(raw, patterns)
    return sanitized


def export_sessions(sessions, day_dir, patterns):
    day_dir.mkdir(parents=True, exist_ok=True)
    home_encoded = str(Path.home()).replace('/', '-')
    exported = []
    for s in sessions:
        out = day_dir / f"{s['path'].stem}.txt"
        txt = extract_session_text(s['path'], patterns)
        short_proj = s['project']
        if short_proj.startswith(home_encoded):
            short_proj = short_proj[len(home_encoded):].lstrip('-')
        header = (f"# Session: {s['path'].stem}\n# Project: {short_proj}\n"
                  f"# Modified: {s['mtime']} | {s['bytes'] // 1024} KB\n"
                  f"# Sanitizer applied\n---\n")
        out.write_text(header + txt, encoding='utf-8')
        exported.append({'file': str(out), 'project': short_proj, 'kb': s['bytes'] // 1024})
    return exported


def slugify(t):
    t = re.sub(r'[^\w\s-]', '', t.lower()).strip()
    return re.sub(r'[\s_]+', '-', t)[:60]


def render_distill_prompt(files_list, max_candidates, today, queue_dir, owner_name, main_language):
    prompt = PROMPT_FILE.read_text(encoding='utf-8')
    repl = {
        '{{OWNER_NAME}}': owner_name,
        '{{MAIN_LANGUAGE}}': main_language,
        '{{QUEUE_DIR}}': str(queue_dir),
        '{{FILES}}': files_list,
        '{{MAX}}': str(max_candidates),
        '{{DATE}}': today,
    }
    for k, v in repl.items():
        prompt = prompt.replace(k, v)
    return prompt


def run_distill(exported, max_candidates, model, today, queue_dir, owner_name, main_language, workspace, log_path):
    """Headless `claude -p`: reads exports + prompt, returns a JSON array of
    candidates. Tools are read-only plus query.sh for dedup; this script is the
    only thing that writes to the vault."""
    workspace.mkdir(parents=True, exist_ok=True)
    files_list = "\n".join(f"- {e['file']} (project: {e['project']}, {e['kb']} KB)" for e in exported)
    prompt = render_distill_prompt(files_list, max_candidates, today, queue_dir, owner_name, main_language)
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--model", model,
        "--output-format", "json",
        "--allowedTools", f"Read,Grep,Glob,Bash({QUERY_SH}:*)",
        # Subagents run in the background by default in current harnesses; in -p
        # the process exits before they return and the final JSON never arrives.
        # Hard denial here, mirrored by an instruction in prompts/distill_daily.md.
        "--disallowedTools", "Agent,Task",
    ]
    log(f"claude -p ({model}) distilling {len(exported)} sessions...", log_path)
    try:
        r = subprocess.run(cmd, cwd=workspace, capture_output=True, text=True, timeout=7200)
    except FileNotFoundError:
        log("claude binary not found on PATH", log_path)
        return None
    except subprocess.TimeoutExpired:
        log("claude -p exceeded the 7200s timeout", log_path)
        return None
    if r.returncode != 0:
        log(f"claude -p failed rc={r.returncode}: stderr={r.stderr[:300]} stdout={r.stdout[:300]}", log_path)
        return None
    return parse_candidates(r.stdout, log_path)


def parse_candidates(stdout_text, log_path=None):
    """Pure parser for the distillation output (unit-tested in
    test_distill_contract.py). Contract: the model must answer with a JSON array
    ([] is a valid empty day). Anything else means the run did NOT complete
    (e.g. the model ended its turn waiting on background subagents), so this
    returns None and the caller treats it as a FAILURE: state file untouched,
    the scheduler's retry covers the period, the owner gets an alert. Returning
    [] here instead caused 4 days of silent no-op distillation (2026-07-16/19)."""
    def _say(m):
        if log_path is not None:
            log(m, log_path)
        else:
            print(m)
    try:
        wrapper = json.loads(stdout_text)
        result = wrapper.get('result', '')
    except json.JSONDecodeError:
        result = stdout_text
    m = re.search(r'\[.*\]', result, re.DOTALL)   # first JSON array in the text
    if not m:
        _say(f"no JSON array in result, treating as FAILURE (start): {result[:300]}")
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        _say(f"invalid JSON, treating as FAILURE: {e}; start: {m.group(0)[:300]}")
        return None


def write_queue(cands, today, queue_dir):
    """Write each candidate as a draft in the gate queue and rebuild the index."""
    queue_dir.mkdir(parents=True, exist_ok=True)
    queue_index = queue_dir / "_GATE-QUEUE.md"
    written = []
    for c in cands:
        ctype = c.get('type', 'lesson')
        title = c.get('title', 'untitled')
        fname = f"{today}-{slugify(title)}.md"
        fp = queue_dir / fname
        body = f"""---
type: {ctype}
title: "{title}"
description: "Candidate from brain-daily on {today}, awaiting gate"
status: draft
created: {today}
proposed_destination: "{c.get('proposed_destination', '')}"
---

# {title}

**Type:** {ctype} | **Proposed destination:** `{c.get('proposed_destination', '?')}`
**Evidence:** {c.get('evidence', '?')} (project: {c.get('project', '?')})

{c.get('body', '')}

**Why it might NOT be admitted:** {c.get('reason_not_to_enter', 'no reservations identified')}

*Generated by brain-daily on {today}. Gate: reviewed by gate_judge (autonomous, if
enabled) or manually.*
"""
        fp.write_text(body, encoding='utf-8')
        written.append({'file': fname, 'type': ctype, 'title': title})
    pend = sorted(p.name for p in queue_dir.glob('*.md') if p.name != queue_index.name)
    lines = [
        "# Brain-daily gate queue", "",
        "> Candidates generated automatically (status: draft). If judge_enabled is",
        "> false in config, they wait here for manual review; otherwise gate_judge",
        "> applies most of them and only escalated items remain.", "",
        f"Pending: {len(pend)} (updated {today})", "",
    ]
    lines += [f"- [[{n[:-3]}]]" for n in pend]
    queue_index.write_text("\n".join(lines) + "\n", encoding='utf-8')
    return written


def prune_cache(cache_daily, days=7):
    """Housekeeping: daily exports older than N days are disposable (the original
    raw material stays in the source directories)."""
    if not cache_daily.exists():
        return
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    for d in cache_daily.iterdir():
        if d.is_dir():
            try:
                if datetime.date.fromisoformat(d.name) < cutoff:
                    for f in d.iterdir():
                        f.unlink()
                    d.rmdir()
            except ValueError:
                continue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=int, default=26)
    ap.add_argument('--max-candidates', type=int, default=5)
    ap.add_argument('--model', default='sonnet', help='cheap model for distillation')
    ap.add_argument('--judge-model', default='opus', help='strong model for gate_judge')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true', help='ignore the once-per-day guard')
    args = ap.parse_args()

    cfg = load_config()
    vault = Path(cfg["vault_path"]).expanduser()
    home = brain_home()
    cache_daily = home / "cache" / "daily"
    workspace = home / "daily-workspace"   # claude -p cwd; sessions from here are excluded from collection
    log_path = home / "logs" / "brain-daily.log"
    state_file = cache_daily / ".last_run"
    taxonomy = cfg.get("taxonomy") or {}
    queue_dir = vault / taxonomy.get("queue_dir", DEFAULT_QUEUE_DIR)
    owner_name = cfg.get("owner_name") or "the owner"
    main_language = cfg.get("main_language") or "en-US"

    def _log(msg):
        log(msg, log_path)

    # Idempotency guard: schedulers may retry (e.g. a morning slot plus a midday
    # retry, to cover a machine that was off at the scheduled time). If today's
    # run already completed, a retry exits quietly; one distillation per day is
    # the contract.
    if not args.force and not args.dry_run and state_file.exists():
        try:
            last_ok = datetime.datetime.fromtimestamp(float(state_file.read_text().strip()))
            if last_ok.date() == datetime.date.today():
                _log(f"already ran today ({last_ok.isoformat(timespec='minutes')}); exiting (retry)")
                return
        except ValueError:
            pass

    prune_cache(cache_daily)
    today = datetime.date.today().isoformat()

    # Effective window: since the last successful run (plus 1h margin), capped at
    # 7 days. If the machine was off at the scheduled time, the state file makes
    # sure nothing is silently lost the next day.
    hours = args.hours
    if state_file.exists():
        try:
            last = float(state_file.read_text().strip())
            gap_h = (datetime.datetime.now().timestamp() - last) / 3600 + 1
            hours = min(max(gap_h, args.hours), MAX_CATCHUP_H)
        except ValueError:
            pass
    if hours > args.hours + 1:
        _log(f"catch-up: covering {hours:.0f}h since the last successful run")

    def mark_ok():
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(str(datetime.datetime.now().timestamp()))

    roots = source_roots(cfg)
    sessions = collect_recent_sessions(roots, hours, home)
    if not sessions:
        _log("no relevant sessions in the last %.0fh; nothing to do" % hours)
        mark_ok()
        return
    _log(f"{len(sessions)} relevant sessions: " + ", ".join(s['project'][:40] for s in sessions[:8]))

    patterns = list(cfg.get("confidential_patterns") or [])
    exported = export_sessions(sessions, cache_daily / today, patterns)
    if args.dry_run:
        _log(f"DRY-RUN: {len(exported)} sessions exported to {cache_daily / today}; stopping before the LLM call")
        return

    cands = run_distill(exported, args.max_candidates, args.model, today, queue_dir,
                        owner_name, main_language, workspace, log_path)
    if cands is None:
        notify("brain-daily: distillation FAILED (see brain-daily.log)", priority="high", tags="warning")
        sys.exit(1)   # state NOT updated: the next run covers this window again
    if not cands:
        _log("0 candidates today (no new learning, or already covered by the brain)")
        mark_ok()
        return

    written = write_queue(cands[:args.max_candidates], today, queue_dir)
    mark_ok()
    _log(f"{len(written)} candidates in the gate queue: " + "; ".join(w['title'][:50] for w in written))

    if not bool(cfg.get("judge_enabled", False)):
        _log("judge_enabled=false: judge is dormant, candidates wait for manual review")
        notify(f"brain-daily: {len(written)} new candidate(s) waiting in the gate queue (judge dormant).")
        return

    r = subprocess.run([sys.executable, str(GATE_JUDGE), "--model", args.judge_model],
                       capture_output=True, text=True, timeout=2400)
    if r.returncode != 0:
        _log(f"gate-judge failed rc={r.returncode}; candidates remain in the queue (fail-safe)")
        notify(f"brain-daily: {len(written)} candidates generated, but the judge FAILED; they remain in the queue.",
               priority="high", tags="warning")


if __name__ == '__main__':
    main()
