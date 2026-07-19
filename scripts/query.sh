#!/bin/bash
# Semantic search against the brain -- daemon-first (warm, <100ms), subprocess
# fallback (~20s cold).
#
# Usage: query.sh "<question>" [--top-k N] [--min-score F] [--source X] [--type Y]
#                               [--tag Z] [--chunk-type T] [--json] [--compact] [--mode auto]
#
# Port is derived from ~/.brain/config.json via brain_config.py (never hardcoded).
# Before trusting a daemon response, this script verifies the daemon's /health
# instance_id against the config's instance_id: another brain instance (a
# different install) could be bound to the same port on this machine. A
# mismatch, or no daemon at all, falls back to the slow subprocess path.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# brain_config.py is stdlib-only (no venv needed); query_brain.py's fallback
# path needs sentence-transformers/numpy/yaml, installed in the shared venv.
PY_SYS="python3"
VENV="$HOME/.brain/venv"
PY_VENV="$VENV/bin/python"
[ -x "$PY_VENV" ] || PY_VENV="python3"

QUERY=""
TOP_K=10
MIN_SCORE=0
SOURCE=""
TYPE=""
TAG=""
CHUNK_TYPE=""
JSON=0
COMPACT=0
MODE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --top-k)      TOP_K="$2"; shift 2 ;;
    --min-score)  MIN_SCORE="$2"; shift 2 ;;
    --source)     SOURCE="$2"; shift 2 ;;
    --type)       TYPE="$2"; shift 2 ;;
    --tag)        TAG="$2"; shift 2 ;;
    --chunk-type) CHUNK_TYPE="$2"; shift 2 ;;
    --json)       JSON=1; shift ;;
    --compact)    COMPACT=1; shift ;;
    --mode)       MODE="$2"; shift 2 ;;
    *)            QUERY="$1"; shift ;;
  esac
done

if [ -z "$QUERY" ]; then
  echo "Usage: query.sh \"<question>\" [--top-k N] [--min-score F] ..." >&2
  exit 1
fi

fallback() {
  echo "(brain-daemon unavailable or config mismatch -- using slow fallback)" >&2
  # --compact / --mode are daemon-side features; the slow path (query_brain.py)
  # does not implement them. Say so instead of silently changing output shape.
  if [ "$COMPACT" = 1 ] || [ -n "$MODE" ]; then
    echo "(warning: --compact/--mode are only available via the daemon; returning verbose results)" >&2
  fi
  FB_ARGS=("$QUERY" --top-k "$TOP_K")
  [ "$MIN_SCORE" != 0 ] && FB_ARGS+=(--min-score "$MIN_SCORE")
  [ -n "$SOURCE" ]      && FB_ARGS+=(--source "$SOURCE")
  [ -n "$TYPE" ]        && FB_ARGS+=(--type "$TYPE")
  [ -n "$TAG" ]         && FB_ARGS+=(--tag "$TAG")
  [ -n "$CHUNK_TYPE" ]  && FB_ARGS+=(--chunk-type "$CHUNK_TYPE")
  [ "$JSON" = 1 ]       && FB_ARGS+=(--json)
  exec "$PY_VENV" "$SCRIPT_DIR/query_brain.py" "${FB_ARGS[@]}"
}

PORT=$("$PY_SYS" "$SCRIPT_DIR/brain_config.py" port 2>/dev/null)
EXPECTED_ID=$("$PY_SYS" "$SCRIPT_DIR/brain_config.py" instance_id 2>/dev/null)

if [ -z "$PORT" ] || [ -z "$EXPECTED_ID" ]; then
  echo "(could not read brain config -- check BRAIN_CONFIG or ~/.brain/config.json)" >&2
  fallback
fi

DAEMON="http://127.0.0.1:${PORT}"

# --- verify the daemon on this port is actually ours before trusting it ---
HEALTH=$(curl -s -m 2 "$DAEMON/health" 2>/dev/null)
if [ -z "$HEALTH" ]; then
  fallback
fi
GOT_ID=$(echo "$HEALTH" | "$PY_SYS" -c '
import json, sys
try:
    print(json.load(sys.stdin).get("instance_id", ""))
except Exception:
    print("")
' 2>/dev/null)
if [ "$GOT_ID" != "$EXPECTED_ID" ]; then
  echo "(port $PORT answers a different brain instance -- instance_id mismatch)" >&2
  fallback
fi

# --- fast path: daemon confirmed, run the query ---
CURL_ARGS=(-s -G "$DAEMON/query"
  --data-urlencode "q=$QUERY"
  --data-urlencode "top_k=$TOP_K"
  --data-urlencode "min_score=$MIN_SCORE")
[ -n "$SOURCE" ]     && CURL_ARGS+=(--data-urlencode "source=$SOURCE")
[ -n "$TYPE" ]       && CURL_ARGS+=(--data-urlencode "type=$TYPE")
[ -n "$TAG" ]        && CURL_ARGS+=(--data-urlencode "tag=$TAG")
[ -n "$CHUNK_TYPE" ] && CURL_ARGS+=(--data-urlencode "chunk_type=$CHUNK_TYPE")
[ "$COMPACT" = 1 ]   && CURL_ARGS+=(--data-urlencode "compact=1")
[ -n "$MODE" ]       && CURL_ARGS+=(--data-urlencode "mode=$MODE")

RESP=$(curl -m 5 "${CURL_ARGS[@]}" 2>/dev/null)
# Cold-start: daemon alive but model unloaded (load takes 13-28s > the 5s timeout).
# /health already answered above, so wait out the load with a wide timeout instead
# of falling back to the subprocess path (which would load a SECOND model, slower).
if [ -z "$RESP" ]; then
  RESP=$(curl -m 45 "${CURL_ARGS[@]}" 2>/dev/null)
fi

if [ -n "$RESP" ] && echo "$RESP" | head -c 1 | grep -q '\['; then
  if [ "$JSON" = 1 ] || [ "$COMPACT" = 1 ]; then
    echo "$RESP"
  else
    echo "$RESP" | "$PY_SYS" -c '
import json, sys
results = json.load(sys.stdin)
if not results:
    print("No results above threshold.")
    sys.exit(0)
print(f"\nTop {len(results)} chunks (via brain-daemon)\n")
for i, c in enumerate(results, 1):
    sec = c.get("section_id") or c.get("section_title") or c.get("section") or "(whole note)"
    title = c.get("parent_title") or c.get("title") or "?"
    path = c.get("parent_path") or c.get("path") or "?"
    score = c.get("score", 0)
    chunk_type = c.get("chunk_type", "-")
    src = c.get("source", "-")
    typ = c.get("type", "-")
    st = c.get("status", "")
    flag = f"  [status:{st}]" if st and st != "active" else ""
    print(f"{i}. [{score:.3f}] {title[:70]}{flag}")
    print(f"   chunk:   {chunk_type} - {str(sec)[:80]}")
    print(f"   path:    {path}")
    print(f"   source:  {src}  type: {typ}")
    print()
'
  fi
  exit 0
fi

fallback
