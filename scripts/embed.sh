#!/bin/bash
# Wrapper: runs embed_brain.py using the kit's dedicated venv (~/.brain/venv),
# where sentence-transformers/numpy/yaml are installed at install time.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$HOME/.brain/venv"
PY="$VENV/bin/python"

if [ ! -x "$PY" ]; then
  echo "ERROR: venv not found at $VENV (expected $PY)." >&2
  echo "Run the installer, or create it: python3 -m venv $VENV && $PY -m pip install sentence-transformers numpy pyyaml" >&2
  exit 1
fi

exec "$PY" "$SCRIPT_DIR/embed_brain.py" "$@"
