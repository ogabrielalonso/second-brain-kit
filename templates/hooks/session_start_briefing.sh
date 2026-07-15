#!/bin/bash
# Hook: SessionStart -> injects an automatic briefing at the start of each Claude Code
# session (owner identity, current focus, interaction preferences, latest daily note).
#
# Config contract: this hook is a pure CLIENT of scripts/brain_config.py, the single
# source of truth for config. It never opens ~/.brain/config.json directly and never
# hardcodes an owner path, name or folder. Interface used:
#   python3 "$BRAIN_CONFIG_PY" get <dot.path.key>
# prints the raw value of a config key to stdout (empty output + non-zero exit if the
# key is missing or the config file does not exist yet).
#
# Source layout read here (all under config.taxonomy.home_dir, resolved at runtime):
#   who-i-am.md               identity note (rendered from templates/vault/skeleton
#                              or mapped from the owner's real vault in MODE A)
#   current-focus.md          current priority note
#   interaction-preferences.md  optional: tone/language/format preferences
#
# Line caps (identity/current-focus/preferences: 110/80/120) plus the byte-based
# backstop below are the two layers that keep this hook under its ~4k token budget:
# the caps handle the common case, the backstop protects against any single install
# whose notes still run long.
#
# This hook is meant to be always-on (installed globally, applies to every session):
# it exits silently whenever the config or the seed notes are missing, so it is a
# no-op outside of brain-kit installs.

set -u

BRAIN_KIT_DIR="${BRAIN_KIT_DIR:-$HOME/.brain/kit}"
BRAIN_CONFIG_PY="$BRAIN_KIT_DIR/scripts/brain_config.py"

if [ ! -f "$BRAIN_CONFIG_PY" ]; then exit 0; fi

cfg() {
  python3 "$BRAIN_CONFIG_PY" get "$1" 2>/dev/null
}

mtime_epoch() {
  stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null
}

VAULT_PATH=$(cfg "vault_path")
if [ -z "$VAULT_PATH" ] || [ ! -d "$VAULT_PATH" ]; then exit 0; fi

HOME_DIR=$(cfg "taxonomy.home_dir")
HOME_DIR="${HOME_DIR:-00-HOME}"
OWNER_NAME=$(cfg "owner_name")

IDENTITY_FILE="$VAULT_PATH/$HOME_DIR/who-i-am.md"
FOCUS_FILE="$VAULT_PATH/$HOME_DIR/current-focus.md"
PREFS_FILE="$VAULT_PATH/$HOME_DIR/interaction-preferences.md"

# No identity note yet (fresh/incomplete install): nothing useful to inject.
if [ ! -f "$IDENTITY_FILE" ]; then exit 0; fi

# Approx token budget backstop: ~4k tokens ~= 16000 chars at a conservative ~4 chars/token.
MAX_CHARS=16000

TMP_BRIEF=$(mktemp)
trap 'rm -f "$TMP_BRIEF"' EXIT

{
  if [ -n "$OWNER_NAME" ]; then
    echo "=== IDENTITY ($OWNER_NAME) ==="
  else
    echo "=== IDENTITY ==="
  fi
  sed -n '/^## /,$p' "$IDENTITY_FILE" 2>/dev/null | head -110
  echo ""

  echo "=== CURRENT FOCUS ==="
  if [ -f "$FOCUS_FILE" ]; then
    focus_mtime=$(mtime_epoch "$FOCUS_FILE")
    if [ -n "$focus_mtime" ]; then
      focus_age=$(( ( $(date +%s) - focus_mtime ) / 86400 ))
      if [ "$focus_age" -gt 7 ]; then
        echo "WARNING: STALE. current-focus has not been updated in ${focus_age} days. Do not assume it is current; confirm with the owner."
      fi
    fi
    sed -n '/^# /,$p' "$FOCUS_FILE" 2>/dev/null | head -80
  else
    echo "(no current-focus note yet)"
  fi
  echo ""

  if [ -f "$PREFS_FILE" ]; then
    echo "=== INTERACTION PREFERENCES ==="
    sed -n '/^# /,$p' "$PREFS_FILE" 2>/dev/null | head -120
    echo ""
  fi

  # Latest daily note, if the taxonomy defines a journal root and it holds dated notes.
  JOURNAL_DIR=$(cfg "taxonomy.digests_dir")
  DECISIONS_DIR=$(cfg "taxonomy.decisions_dir")
  WEEKLY_DIR=$(cfg "taxonomy.weekly_dir")
  QUEUE_DIR=$(cfg "taxonomy.queue_dir")
  if [ -n "$JOURNAL_DIR" ] && [ -d "$VAULT_PATH/$JOURNAL_DIR" ]; then
    LATEST_DAILY=$(find "$VAULT_PATH/$JOURNAL_DIR" -name "20*.md" \
      -not -path "*${WEEKLY_DIR:-__none__}*" \
      -not -path "*${DECISIONS_DIR:-__none__}*" \
      -not -path "*${QUEUE_DIR:-__none__}*" 2>/dev/null | sort -r | head -1)
    if [ -n "$LATEST_DAILY" ]; then
      daily_mtime=$(mtime_epoch "$LATEST_DAILY")
      if [ -n "$daily_mtime" ]; then
        daily_age=$(( ( $(date +%s) - daily_mtime ) / 86400 ))
        if [ "$daily_age" -le 3 ]; then
          echo "=== LATEST DAILY NOTE ($(basename "$LATEST_DAILY" .md)) ==="
          head -40 "$LATEST_DAILY" 2>/dev/null
          echo ""
        fi
      fi
    fi
  fi
} > "$TMP_BRIEF"

echo "<system-context source=\"brain-session-briefing\">"
echo "Automatic brain briefing, loaded at the start of this session."
echo ""

BYTES=$(wc -c < "$TMP_BRIEF" | tr -d ' ')
if [ -n "$BYTES" ] && [ "$BYTES" -gt "$MAX_CHARS" ]; then
  head -c "$MAX_CHARS" "$TMP_BRIEF"
  echo ""
  echo "[...truncated to stay under the session hook token budget...]"
else
  cat "$TMP_BRIEF"
fi

echo ""
echo "INSTRUCTIONS:"
echo "- Use this briefing as PRIMARY CONTEXT about who the owner is right now."
echo "- The retrieval hook (UserPromptSubmit) still applies for specific questions."
echo "- Honor the interaction preferences above (tone, language, format)."
echo "</system-context>"
