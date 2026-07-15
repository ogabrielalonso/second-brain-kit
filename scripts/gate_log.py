#!/usr/bin/env python3
"""gate_log: telemetry for the brain gate decisions.

Records every decision made on a candidate (by the judge once judge_enabled is
true, or by the owner during manual review before that) and computes, per
candidate type, the rate of decisions approved without edits. When a type
crosses the eligibility threshold from config.thresholds.eligibility (min_n
decisions AND min_rate of full approval, across at least min_weeks distinct
weeks), the stats mark it ELIGIBLE for promotion. Turning the judge on for a
type is still an explicit decision by the owner; nothing here flips it
automatically (see the turn-on procedure in docs/ARCHITECTURE.md).

Files (kept in _system/ of the vault, excluded from knowledge queries):
  _system/telemetry/gate-decisions.jsonl  (append-only, one decision per line)
  _system/telemetry/gate-policy.json      (promoted types plus an audit trail)

This script depends only on brain_config.load_config() for owner state: never
a hardcoded path, and never a separate vault-path override, and never one of
brain_config's convenience helper functions (thresholds(), etc). The vault
path and the eligibility threshold both come straight from the config dict, so
this stays correct even if those helpers change shape; set BRAIN_CONFIG to
point load_config() at a different config.json for tests or sandboxes.

Usage:
  gate_log.py add --file <draft-name.md> --type <type> --decision approved|edited|discarded|escalated
                  [--destination "..."] [--note "..."]
  gate_log.py stats [--weeks 12] [--json]
"""
import sys
import json
import argparse
import datetime
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain_config import load_config

DEFAULT_ELIGIBILITY = {"min_n": 20, "min_rate": 0.95, "min_weeks": 6}


def canon_type(s):
    """Normalize a candidate type to a canonical accent-folded key, so the same
    type spelled with or without diacritics does not create two telemetry
    buckets (which would distort the eligibility statistics)."""
    s = (s or "unknown").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if not unicodedata.combining(c))


def _vault_path(cfg):
    return Path(cfg["vault_path"]).expanduser()


def _tel_dir(cfg):
    return _vault_path(cfg) / "_system" / "telemetry"


def _eligibility(cfg):
    merged = dict(DEFAULT_ELIGIBILITY)
    merged.update((cfg.get("thresholds") or {}).get("eligibility") or {})
    return merged


def default_policy(cfg):
    return {
        "auto_approve_types": [],
        "threshold": _eligibility(cfg),
        "_doc": "Types in auto_approve_types were promoted by the owner in the gate. "
                "A type is eligible when n>=min_n decisions accumulated across "
                ">=min_weeks distinct weeks AND the full-approval rate ('approved' "
                "with no edits) >= min_rate. When promoting, also record it in "
                "_promotions: [{type, date, n, approved, edited, discarded, "
                "full_approval_rate, distinct_weeks, approved_by, decision_ref}] "
                "(an audit trail of the stats at promotion time).",
    }


def load_policy(cfg):
    policy_fp = _tel_dir(cfg) / "gate-policy.json"
    if policy_fp.exists():
        try:
            return json.loads(policy_fp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return default_policy(cfg)


def load_decisions(cfg):
    decisions_fp = _tel_dir(cfg) / "gate-decisions.jsonl"
    if not decisions_fp.exists():
        return []
    out = []
    for line in decisions_fp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def cmd_add(args, cfg):
    if args.decision not in ("approved", "edited", "discarded", "escalated"):
        sys.exit("decision must be: approved | edited | discarded | escalated")
    tel_dir = _tel_dir(cfg)
    tel_dir.mkdir(parents=True, exist_ok=True)
    policy_fp = tel_dir / "gate-policy.json"
    if not policy_fp.exists():
        policy_fp.write_text(json.dumps(default_policy(cfg), ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    rec = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "file": args.file,
        "type": canon_type(args.type),
        "destination": args.destination or "",
        "decision": args.decision,
        "note": args.note or "",
    }
    decisions_fp = tel_dir / "gate-decisions.jsonl"
    with decisions_fp.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"recorded: {rec['type']} -> {rec['decision']} ({rec['file']})")


def compute_stats(cfg, weeks):
    cutoff = datetime.datetime.now() - datetime.timedelta(weeks=weeks)
    policy = load_policy(cfg)
    th = policy.get("threshold") or _eligibility(cfg)
    per_type = {}
    for r in load_decisions(cfg):
        try:
            ts = datetime.datetime.fromisoformat(r["ts"])
        except (KeyError, ValueError):
            continue
        if ts < cutoff:
            continue
        t = per_type.setdefault(canon_type(r.get("type", "unknown")),
                                {"n": 0, "approved": 0, "edited": 0, "discarded": 0,
                                 "escalated": 0, "weeks": set()})
        t["n"] += 1
        decision = r.get("decision", "approved")
        t[decision] = t.get(decision, 0) + 1
        t["weeks"].add(ts.strftime("%G-W%V"))
    auto_types = [canon_type(x) for x in policy.get("auto_approve_types", [])]
    rows = []
    for typ, t in sorted(per_type.items()):
        rate = t["approved"] / t["n"] if t["n"] else 0.0
        eligible = (t["n"] >= th["min_n"] and rate >= th["min_rate"]
                    and len(t["weeks"]) >= th.get("min_weeks", 0))
        rows.append({
            "type": typ, "n": t["n"], "approved": t["approved"],
            "edited": t["edited"], "discarded": t["discarded"],
            "escalated": t.get("escalated", 0),
            "full_approval_rate": round(rate, 3),
            "distinct_weeks": len(t["weeks"]),
            "auto_approve_active": typ in auto_types,
            "eligible_for_promotion": eligible and typ not in auto_types,
        })
    return {"weeks": weeks, "threshold": th,
            "auto_approve_types": policy.get("auto_approve_types", []), "types": rows}


def cmd_stats(args, cfg):
    s = compute_stats(cfg, args.weeks)
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return
    if not s["types"]:
        print(f"No decisions recorded in the last {args.weeks} weeks. "
              f"The log starts counting from the next dispatch.")
        return
    th = s["threshold"]
    print(f"Gate telemetry (last {args.weeks} weeks) | "
          f"threshold: n>={th['min_n']}, rate>={th['min_rate']:.0%}, weeks>={th.get('min_weeks', 0)}")
    for r in s["types"]:
        flag = " <- ELIGIBLE for auto-approve (propose in the gate)" if r["eligible_for_promotion"] else ""
        auto = " [auto-approve ACTIVE]" if r["auto_approve_active"] else ""
        print(f"  {r['type']:<12} n={r['n']:<3} approved={r['approved']} edited={r['edited']} "
              f"discarded={r['discarded']} escalated={r.get('escalated', 0)} "
              f"rate={r['full_approval_rate']:.0%} "
              f"weeks={r['distinct_weeks']}{auto}{flag}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--file", required=True)
    a.add_argument("--type", required=True)
    a.add_argument("--decision", required=True)
    a.add_argument("--destination", default="")
    a.add_argument("--note", default="")
    a.set_defaults(fn=cmd_add)
    st = sub.add_parser("stats")
    st.add_argument("--weeks", type=int, default=12)
    st.add_argument("--json", action="store_true")
    st.set_defaults(fn=cmd_stats)
    args = ap.parse_args()
    cfg = load_config()
    args.fn(args, cfg)


if __name__ == "__main__":
    main()
