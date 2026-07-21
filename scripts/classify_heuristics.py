#!/usr/bin/env python3
"""classify_heuristics: re-runnable backfill for the heuristics clustering axis.

Digests the owner's lessons and patterns banks
(config.taxonomy.heuristics.lessons / .patterns) and writes the two-axis
Class (nature · domain, vocabulary in heuristics_taxonomy.py) onto every
entry that does not carry one yet. Three-brain split:
  - this script (deterministic) parses, validates and WRITES;
  - a cheap model CLASSIFIES in batches;
  - a strong model VERIFIES a blind sample (on disagreement, the strong
    model wins) and AUDITS routes (what already acts as a skill, quality
    gate or governance rule; what is worth promoting).

Idempotent: skips rows that already carry a Class cell and sections that
already carry a "- **Class:**" line. The daily pipeline classifies at
intake (see gate_judge.py, prompts/judge.md criterion 10); this script is
the backfill and the safety net for anything that slipped through without
a class, and the only place that runs the route audit.

This script depends only on brain_config.load_config() for owner state:
never a hardcoded path, and never one of brain_config's convenience helper
functions (vault_path(), taxonomy(), etc), so it keeps working even if
those helpers change shape. It reads the raw config dict and applies its
own defaults where needed, mirroring gate_judge.py's dependency contract.

Usage: classify_heuristics.py [--dry-run] [--skip-audit] [--skip-verify]
                              [--model sonnet] [--judge-model opus]
                              [--reverify-all] [--audit-only]
Env: BRAIN_CONFIG overrides the config file location (see brain_config.py).
Output: a JSON report under <brain_home>/cache/heuristics-classify/
"""
import os
import re
import sys
import time
import json
import argparse
import datetime
import subprocess
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain_config import load_config
from heuristics_taxonomy import ROUTE, validate, vocab_prompt

CLAUDE_BIN = "claude"
BATCH = 40


def brain_home():
    """Directory holding cache, state and logs (always outside the vault);
    derived from wherever config.json actually resolves to, computed here
    rather than imported from brain_config, per the kit's dependency
    contract (see gate_judge.py and brain_daily.py for the same pattern)."""
    return Path(os.environ.get("BRAIN_CONFIG", "~/.brain/config.json")).expanduser().parent


def log(msg, log_path):
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] [classify] {msg}"
    print(line, flush=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def heuristics_paths(cfg, vault):
    """Resolve the owner's lessons and patterns files from config. Either may
    be unset (MODE B ships both as ""); callers must skip gracefully rather
    than crash, since a fresh install has no heuristics bank configured yet."""
    heur = ((cfg.get("taxonomy") or {}).get("heuristics")) or {}
    lessons_rel = heur.get("lessons") or ""
    patterns_rel = heur.get("patterns") or ""
    lessons = vault / lessons_rel if lessons_rel else None
    patterns = vault / patterns_rel if patterns_rel else None
    return lessons, patterns


def unescaped_pipes(line):
    return len(re.findall(r"(?<!\\)\|", line))


def parse_rows(txt, prefix):
    """Table rows '| N | ... |'. 5 unescaped pipes = no Class cell yet (4
    columns); 6 or more = already classified."""
    items, already = [], 0
    for i, l in enumerate(txt.split("\n")):
        if not re.match(r"^\|\s*\d+\s*\|", l):
            continue
        p = unescaped_pipes(l)
        if p >= 6:
            already += 1
        elif p == 5:
            items.append({"id": f"{prefix}{i}", "line": i, "text": l.strip()[:600]})
    return items, already


def parse_sections(txt, prefix):
    """'## title' sections with real body content (skips empty markers,
    sections that contain a table, and sections already classified)."""
    lines = txt.split("\n")
    idxs = [i for i, l in enumerate(lines) if l.startswith("## ")]
    items, already = [], 0
    for j, i in enumerate(idxs):
        end = idxs[j + 1] if j + 1 < len(idxs) else len(lines)
        body_lines = lines[i + 1:end]
        body = "\n".join(body_lines).strip()
        if not body:
            continue  # an empty block marker, nothing to classify
        if any(bl.lstrip().startswith("|") for bl in body_lines):
            continue  # a section that contains a table: its rows already cover it
        if "**Class:**" in body:
            already += 1
            continue
        title = lines[i][3:].strip()
        items.append({"id": f"{prefix}{i}", "line": i, "end": end,
                      "text": (title + "\n" + body)[:700]})
    return items, already


def run_llm(prompt, model, out_dir, log_path, timeout=900):
    """3 attempts with growing backoff: a transient failure (rate limit or
    overload) drops the call with an instant non-zero return code, and an
    immediate retry dies in the same window."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2, 3):
        try:
            r = subprocess.run([CLAUDE_BIN, "-p", prompt, "--model", model,
                                "--output-format", "json",
                                "--disallowedTools", "Agent,Task"],
                               cwd=out_dir, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            log("claude binary not found on PATH", log_path)
            return None
        except subprocess.TimeoutExpired:
            log(f"timeout {timeout}s ({model}, attempt {attempt})", log_path)
            continue
        if r.returncode == 0:
            try:
                result = json.loads(r.stdout).get("result", "")
            except json.JSONDecodeError:
                result = r.stdout
            m = re.search(r"\[.*\]", result, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError as e:
                    log(f"invalid JSON ({model}, attempt {attempt}): {e}", log_path)
            else:
                log(f"no JSON array ({model}, attempt {attempt}): {result[:200]}", log_path)
        else:
            log(f"claude -p rc={r.returncode} ({model}, attempt {attempt}): "
                f"err={r.stderr[:200]} out={r.stdout[:200]}", log_path)
        time.sleep(20 * attempt)
    return None


def cls_prompt(items, owner_name):
    blob = "\n".join(f"- id {it['id']}: {it['text']}" for it in items)
    return f"""[classify-heuristics] You classify entries from {owner_name}'s heuristics, lessons and decisions catalog along two axes. Respond with ONLY a JSON array, no surrounding markdown.

{vocab_prompt()}

RULES: exactly one value per axis per item (the dominant one); never invent a value outside the vocabulary. When in doubt between decision-tree and judgment, use judgment (decision-tree requires steps reproducible without extra context). Axiom only when the rule holds ALWAYS, with no contextual exception. A dated choice from one specific project (a brand color, one site's structure, keeping or deleting one module) is a one-off-decision, not a heuristic.

ITEMS:
{blob}

Format: [{{"id": "...", "nature": "...", "domain": "..."}}] covering ALL ids."""


def classify(items, model, cfg, out_dir, log_path):
    """Classifies in batches; returns a dict id -> (nature, domain), validated."""
    owner_name = cfg.get("owner_name") or "the owner"
    got = {}
    for i in range(0, len(items), BATCH):
        batch = items[i:i + BATCH]
        log(f"classifying batch {i // BATCH + 1} ({len(batch)} items, {model})", log_path)
        res = run_llm(cls_prompt(batch, owner_name), model, out_dir, log_path) or []
        for r in res:
            n, d = validate(r.get("nature"), r.get("domain"))
            if r.get("id") and n and d:
                got[r["id"]] = (n, d)
    return got


def verify(items, got, judge_model, cfg, out_dir, log_path):
    """A blind sample re-classified by the strong model; on disagreement, the
    strong model wins."""
    owner_name = cfg.get("owner_name") or "the owner"
    sample = [it for it in items[::12] if it["id"] in got][:40]
    if not sample:
        return {"sample": 0, "disagreements": []}
    log(f"blind verification: {len(sample)} items ({judge_model})", log_path)
    res = run_llm(cls_prompt(sample, owner_name), judge_model, out_dir, log_path) or []
    div = []
    for r in res:
        iid = r.get("id")
        n, d = validate(r.get("nature"), r.get("domain"))
        if not (iid and iid in got and n and d):
            continue
        if got[iid] != (n, d):
            div.append({"id": iid, "cheap_model": " · ".join(got[iid]), "judge": f"{n} · {d}"})
            got[iid] = (n, d)  # the judge wins
    agreement = 1 - len(div) / len(sample) if sample else 1
    log(f"sample agreement: {agreement:.0%} ({len(div)} disagreements corrected)", log_path)
    return {"sample": len(sample), "agreement": round(agreement, 3), "disagreements": div}


def infra_context(vault):
    """Real surfaces where rules already act, for the route audit. Honest by
    construction: harness-specific skills, commands or hooks live outside
    this repository (per-owner install) and are not enumerable from here, so
    this only reports what the vault itself documents."""
    claude_md = ""
    p = vault / "CLAUDE.md"
    if p.exists():
        claude_md = p.read_text(encoding="utf-8")[:2800]
    return f"""- Vault-level governance rules already coded (CLAUDE.md, real excerpt):
{claude_md}
- This install's pipeline: a cheap-model daily distiller, a judge (criteria in prompts/judge.md), and deterministic appliers (scripts/gate_judge.py).
- Harness-specific skills, commands and hooks (if any) live outside this vault, per the owner's own agent setup; this audit does not have visibility into them and will not fabricate a claim about them."""


def audit(items, got, judge_model, vault, cfg, out_dir, log_path):
    """For decision-tree, score or axiom items: does a surface already
    implement the rule? Is it worth promoting? Or is a record enough?"""
    owner_name = cfg.get("owner_name") or "the owner"
    target = [it for it in items
              if got.get(it["id"], ("", ""))[0] in ("decision-tree", "score", "axiom")]
    if not target:
        return []
    ctx = infra_context(vault)
    out = []
    for i in range(0, len(target), 25):
        batch = target[i:i + 25]
        blob = "\n".join(f"- id {it['id']} [{got[it['id']][0]} · {got[it['id']][1]}]: {it['text'][:400]}"
                         for it in batch)
        log(f"route audit: batch {i // 25 + 1} ({len(batch)} items, {judge_model})", log_path)
        prompt = f"""[audit-routes] You audit the DIGESTION of {owner_name}'s heuristics: a heuristic only creates value by ACTING in the system (a skill, a quality gate, governance), not merely by being recorded. Below is the REAL existing infrastructure and items classified as decision-tree, score or axiom. Be skeptical: only "promote" when the proposed surface is concrete and clearly useful; do not propose bureaucracy.

EXISTING INFRASTRUCTURE:
{ctx}

For each item, decide:
- "acting": a surface already implements the rule (say WHICH, specifically)
- "promote": worth creating or changing a surface (a concrete one-line proposal)
- "record-ok": a record is enough (too situational to become a surface)

ITEMS:
{blob}

Respond with ONLY a JSON array: [{{"id": "...", "status": "acting|promote|record-ok", "detail": "one line: where it acts, or the proposal"}}]"""
        res = run_llm(prompt, judge_model, out_dir, log_path, timeout=1200) or []
        by_id = {it["id"]: it for it in batch}
        for r in res:
            iid = r.get("id")
            if iid in by_id and r.get("status") in ("acting", "promote", "record-ok"):
                n, d = got[iid]
                out.append({"id": iid, "nature": n, "domain": d, "route": ROUTE[n],
                            "status": r["status"], "detail": str(r.get("detail", ""))[:250],
                            "summary": by_id[iid]["text"][:180]})
    return out


def write_rows(path, rows, got):
    """Writes the Class cell into rows, extending table headers/separators."""
    lines = path.read_text(encoding="utf-8").split("\n")
    n_written = 0
    for it in rows:
        cl = got.get(it["id"])
        if not cl:
            continue
        i = it["line"]
        lines[i] = lines[i].rstrip() + f" {cl[0]} · {cl[1]} |"
        n_written += 1
    for i, l in enumerate(lines):
        if re.match(r"^\|\s*#\s*\|", l) and "Class" not in l:
            lines[i] = l.rstrip() + " Class |"
            if i + 1 < len(lines) and lines[i + 1].startswith("|---"):
                lines[i + 1] = lines[i + 1].rstrip() + "---|"
    path.write_text("\n".join(lines), encoding="utf-8")
    return n_written


def write_sections(path, secs, got):
    """Inserts '- **Class:** ...' at the end of each classified section
    (bottom to top, so earlier insertions do not shift later line numbers)."""
    lines = path.read_text(encoding="utf-8").split("\n")
    n_written = 0
    for it in sorted(secs, key=lambda x: -x["line"]):
        cl = got.get(it["id"])
        if not cl:
            continue
        last = it["line"]
        for k in range(it["line"] + 1, min(it["end"], len(lines))):
            if lines[k].strip():
                last = k
        lines.insert(last + 1, f"- **Class:** {cl[0]} · {cl[1]}")
        n_written += 1
    path.write_text("\n".join(lines), encoding="utf-8")
    return n_written


def parse_all_with_class(txt, prefix):
    """Every entry ALREADY classified, with its current class (for --reverify-all)."""
    items = []
    lines = txt.split("\n")
    for i, l in enumerate(lines):
        if re.match(r"^\|\s*\d+\s*\|", l) and unescaped_pipes(l) >= 6:
            pipes = [m.start() for m in re.finditer(r"(?<!\\)\|", l)]
            cur = l[pipes[-2] + 1:pipes[-1]].strip()
            items.append({"id": f"{prefix}{i}", "line": i, "kind": "row",
                          "class": cur, "text": l.strip()[:600]})
    idxs = [i for i, l in enumerate(lines) if l.startswith("## ")]
    for j, i in enumerate(idxs):
        end = idxs[j + 1] if j + 1 < len(idxs) else len(lines)
        body_lines = lines[i + 1:end]
        cl = [k for k in range(i + 1, end) if lines[k].strip().startswith("- **Class:**")]
        if not cl:
            continue
        cur = lines[cl[0]].split("**Class:**", 1)[1].strip()
        items.append({"id": f"{prefix}S{i}", "line": i, "kind": "sec", "cl_line": cl[0],
                      "class": cur,
                      "text": (lines[i][3:] + "\n" + "\n".join(body_lines))[:700]})
    return items


def reverify_all(cfg, vault, judge_model, out_dir, log_path):
    """Re-classifies the WHOLE already-classified corpus with the judge model
    and corrects disagreements in place (classification is a judgment call,
    so it belongs to the strong model, not the cheap one)."""
    lessons, patterns = heuristics_paths(cfg, vault)
    changed, total = [], 0
    for path, prefix in ((lessons, "L"), (patterns, "P")):
        if path is None or not path.exists():
            continue
        txt = path.read_text(encoding="utf-8")
        items = parse_all_with_class(txt, prefix)
        total += len(items)
        got = classify(items, judge_model, cfg, out_dir, log_path)
        lines = path.read_text(encoding="utf-8").split("\n")
        for it in items:
            cl = got.get(it["id"])
            if not cl:
                continue
            new = f"{cl[0]} · {cl[1]}"
            if new == it["class"]:
                continue
            if it["kind"] == "row":
                l = lines[it["line"]]
                pipes = [m.start() for m in re.finditer(r"(?<!\\)\|", l)]
                lines[it["line"]] = l[:pipes[-2] + 1] + f" {new} |"
            else:
                lines[it["cl_line"]] = f"- **Class:** {new}"
            changed.append({"id": it["id"], "from": it["class"], "to": new})
        path.write_text("\n".join(lines), encoding="utf-8")
    log(f"reverify-all ({judge_model}): {total} items, {len(changed)} corrected", log_path)
    rp = out_dir / f"reverify-report-{datetime.date.today().isoformat()}.json"
    rp.write_text(json.dumps({"total": total, "corrected": changed},
                             ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"total": total, "corrected": len(changed)}, ensure_ascii=False))


def audit_only(cfg, vault, judge_model, out_dir, log_path):
    """Runs ONLY the route audit over the classes already written to the banks
    (typically after a reverify-all)."""
    lessons, patterns = heuristics_paths(cfg, vault)
    items, got = [], {}
    for path, prefix in ((lessons, "L"), (patterns, "P")):
        if path is None or not path.exists():
            continue
        for it in parse_all_with_class(path.read_text(encoding="utf-8"), prefix):
            parts = [p.strip() for p in it["class"].split("·")]
            if len(parts) == 2:
                n, d = validate(parts[0], parts[1])
                if n and d:
                    got[it["id"]] = (n, d)
                    items.append(it)
    routes = audit(items, got, judge_model, vault, cfg, out_dir, log_path)
    rp = out_dir / f"audit-report-{datetime.date.today().isoformat()}.json"
    rp.write_text(json.dumps({"judge": judge_model, "audited": len(routes),
                              "routes": routes}, ensure_ascii=False, indent=1),
                  encoding="utf-8")
    log(f"audit-only ({judge_model}): {len(routes)} items audited; report: {rp}", log_path)
    print(json.dumps(dict(Counter(r["status"] for r in routes)), ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-audit", action="store_true")
    ap.add_argument("--skip-verify", action="store_true")
    ap.add_argument("--reverify-all", action="store_true",
                    help="re-classify the whole corpus with judge-model and correct disagreements")
    ap.add_argument("--audit-only", action="store_true",
                    help="only run the route audit over the classes already written")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--judge-model", default="opus")
    args = ap.parse_args()

    cfg = load_config()
    vault = Path(cfg["vault_path"]).expanduser()
    home = brain_home()
    out_dir = home / "cache" / "heuristics-classify"
    log_path = home / "logs" / "classify-heuristics.log"

    if args.reverify_all:
        reverify_all(cfg, vault, args.judge_model, out_dir, log_path)
        return
    if args.audit_only:
        audit_only(cfg, vault, args.judge_model, out_dir, log_path)
        return

    today = datetime.date.today().isoformat()
    lessons, patterns = heuristics_paths(cfg, vault)

    l_rows, l_secs, l_already = [], [], 0
    if lessons is not None and lessons.exists():
        l_txt = lessons.read_text(encoding="utf-8")
        l_rows, l_already = parse_rows(l_txt, "L")
        l_secs, ls_already = parse_sections(l_txt, "LS")
        l_already += ls_already
    else:
        log("no lessons bank configured or found (taxonomy.heuristics.lessons); skipping", log_path)

    p_secs, p_already = [], 0
    if patterns is not None and patterns.exists():
        p_txt = patterns.read_text(encoding="utf-8")
        p_secs, p_already = parse_sections(p_txt, "P")
    else:
        log("no patterns bank configured or found (taxonomy.heuristics.patterns); skipping", log_path)

    items = l_rows + l_secs + p_secs
    log(f"to classify: {len(l_rows)} rows + {len(l_secs)} sections (lessons), "
        f"{len(p_secs)} sections (patterns); already classified: {l_already + p_already}", log_path)
    if args.dry_run:
        return
    if not items:
        log("nothing to classify; exiting", log_path)
        return

    got = classify(items, args.model, cfg, out_dir, log_path)
    log(f"classified {len(got)}/{len(items)}", log_path)
    ver = {"sample": 0, "disagreements": []}
    if not args.skip_verify:
        ver = verify(items, got, args.judge_model, cfg, out_dir, log_path)
    routes = [] if args.skip_audit else audit(items, got, args.judge_model, vault, cfg, out_dir, log_path)

    # deterministic writes (rows first; sections last since they insert lines)
    nw = write_rows(lessons, l_rows, got) if lessons is not None and l_rows else 0
    nw += write_sections(lessons, l_secs, got) if lessons is not None and l_secs else 0
    nw += write_sections(patterns, p_secs, got) if patterns is not None and p_secs else 0

    pending = [it["id"] for it in items if it["id"] not in got]
    matrix = {}
    for n, d in got.values():
        matrix[n] = matrix.get(n, {})
        matrix[n][d] = matrix[n].get(d, 0) + 1
    report = {"date": today, "classifier": args.model, "judge": args.judge_model,
              "total_items": len(items), "written": nw, "pending": pending,
              "verification": ver, "matrix": matrix, "route_audit": routes,
              "items": {iid: {"nature": n, "domain": d} for iid, (n, d) in got.items()}}
    out_dir.mkdir(parents=True, exist_ok=True)
    rp = out_dir / f"backfill-report-{today}.json"
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"written {nw} items; {len(pending)} pending; report: {rp}", log_path)
    print(json.dumps({"matrix": matrix,
                      "promote": [r for r in routes if r["status"] == "promote"]},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
