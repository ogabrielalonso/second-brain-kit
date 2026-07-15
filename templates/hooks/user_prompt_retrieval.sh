#!/bin/bash
# Hook: UserPromptSubmit -> injects semantic-search context from the brain daemon before
# the agent answers.
#
# NEVER blocks the prompt: every network call below has a hard 3s timeout and any
# failure (daemon down, wrong instance, no trigger match) exits silently with no output.
#
# Config contract: pure CLIENT of scripts/brain_config.py (same interface documented in
# session_start_briefing.sh):
#   python3 "$BRAIN_CONFIG_PY" get <dot.path.key>
#
# Port + instance_id safety: the daemon binds 127.0.0.1 on a port derived from the
# owner's vault_path (see docs/ARCHITECTURE.md). Because more than one brain-kit install
# can exist on the same machine, this hook ALWAYS calls /health first and compares the
# returned instance_id against config.instance_id before trusting /query. A mismatch
# (or no daemon on that port) means "not my daemon" and the hook exits quietly.
#
# Trigger contract: this hook does NOT ship a personal keyword list. It reads
# ~/.brain/triggers.txt, one term or regex fragment per line (lines starting with # are
# comments, blank lines ignored), generated at install time from the interview (the
# owner's project names, client names, topic names). Those terms are OR-ed together with
# a fixed set of generic, install-independent terms (GENERIC_TRIGGERS below: brain,
# vault, decision, lesson, heuristic, pattern, "what did I decide", "remember when",
# daily note, this week's priorities...). If triggers.txt is missing, only the generic
# terms apply, so retrieval still degrades gracefully on a fresh install.
#
# status flagging: any hit whose status is not "active" (draft/stale/superseded) is
# marked inline so the agent never cites it as current truth without a caveat.
#
# stdin: harness JSON { "prompt": "..." }
# stdout: compact markdown injected as extra context (nothing on no-match/failure)

set -u

INPUT=$(cat)
USER_PROMPT=$(echo "$INPUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('prompt', d.get('user_prompt', '')))
" 2>/dev/null)

if [ -z "$USER_PROMPT" ]; then exit 0; fi

BRAIN_KIT_DIR="${BRAIN_KIT_DIR:-$HOME/.brain/kit}"
BRAIN_CONFIG_PY="$BRAIN_KIT_DIR/scripts/brain_config.py"
TRIGGERS_FILE="$HOME/.brain/triggers.txt"

if [ ! -f "$BRAIN_CONFIG_PY" ]; then exit 0; fi

cfg() {
  python3 "$BRAIN_CONFIG_PY" get "$1" 2>/dev/null
}

INSTANCE_ID=$(cfg "instance_id")
PORT=$(cfg "port")
MIN_SCORE=$(cfg "thresholds.inject_min_score")
MIN_SCORE="${MIN_SCORE:-0.52}"
VAULT_PATH=$(cfg "vault_path")

if [ -z "$INSTANCE_ID" ] || [ -z "$PORT" ] || [ "$PORT" = "0" ]; then exit 0; fi

# Generic terms that count as a trigger on every install, independent of the owner's
# projects/topics. Kept intentionally small and English-only; the interview-generated
# triggers.txt is what makes this hook fire on the owner's actual vocabulary.
GENERIC_TRIGGERS='(\bbrain\b|\bvault\b|\bobsidian\b|\bdecision\b|\blesson\b|\bheuristic\b|\bpattern\b|what did i decide|remember when|last time i|my (project|client|focus|history|priorit)|my (decisions|stack|heuristics)|daily note|this week.?s priorit)'

TRIGGER_REGEX="$GENERIC_TRIGGERS"
if [ -f "$TRIGGERS_FILE" ]; then
  OWNER_TERMS=$(grep -v '^[[:space:]]*#' "$TRIGGERS_FILE" 2>/dev/null | grep -v '^[[:space:]]*$' | paste -sd '|' -)
  if [ -n "$OWNER_TERMS" ]; then
    TRIGGER_REGEX="(${GENERIC_TRIGGERS}|${OWNER_TERMS})"
  fi
fi

if ! echo "$USER_PROMPT" | grep -iqE "$TRIGGER_REGEX"; then
  exit 0
fi

# Verify instance_id from /health BEFORE trusting anything from /query: another brain-kit
# daemon (a different vault, possibly a different owner on a shared machine) can be bound
# to this same derived port.
HEALTH=$(curl -s -m 3 "http://127.0.0.1:${PORT}/health" 2>/dev/null)
HEALTH_INSTANCE=$(echo "$HEALTH" | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('instance_id', ''))
except Exception:
    print('')
" 2>/dev/null)

if [ -z "$HEALTH_INSTANCE" ] || [ "$HEALTH_INSTANCE" != "$INSTANCE_ID" ]; then
  exit 0
fi

RESULTS=$(curl -s -m 3 -G "http://127.0.0.1:${PORT}/query" \
  --data-urlencode "q=$USER_PROMPT" \
  --data-urlencode "top_k=5" \
  --data-urlencode "min_score=$MIN_SCORE" \
  --data-urlencode "compact=1" \
  --data-urlencode "mode=auto" 2>/dev/null)

if [ -z "$RESULTS" ] || [ "$RESULTS" = "[]" ] || [ "$RESULTS" = "null" ]; then
  exit 0
fi

FORMATTED=$(echo "$RESULTS" | python3 -c '
import json, sys
try:
    rs = json.load(sys.stdin)
except Exception:
    sys.exit(1)
if not rs:
    sys.exit(1)
for c in rs:
    section = " - " + c["section"] if c.get("section") else ""
    status = c.get("status", "")
    flag = " [status:" + status + "]" if status and status != "active" else ""
    source = c.get("source") or ""
    ctype = c.get("type") or ""
    meta = " (" + source + "/" + ctype + ")" if (source or ctype) else ""
    print("- [" + str(c["score"]) + "] " + c["path"] + section + meta + flag)
' 2>/dev/null)

if [ -z "$FORMATTED" ]; then exit 0; fi

cat <<EOF
<system-context source="brain-auto-injection">
Relevant brain notes for this prompt (semantic search, score >= ${MIN_SCORE}):

$FORMATTED

INSTRUCTIONS: if the question depends on these notes, Read the 1-3 most relevant ones
(paths above are relative to the vault: ${VAULT_PATH}) before answering, and cite the
paths. If the hits look peripheral to the request, ignore them. A hit flagged
[status:stale/superseded/draft] is NOT current truth: cite it with a caveat (stale),
follow superseded_by (superseded), or treat it as an unapproved candidate (draft). If the
question needs brain info and nothing here covers it, say so explicitly instead of
guessing.
</system-context>
EOF
