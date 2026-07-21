#!/usr/bin/env bash
# run_all.sh: kit test suite, self-contained and rerunnable by the installer at
# Phase -1 (Preflight) BEFORE anything touches the owner's machine. Runs every
# test in this directory in sequence, prints one clean PASS/FAIL line per test
# (with indented output only on failure), and exits non-zero if any test failed.
#
# Usage: tests/run_all.sh
# Env:   PYTHON_BIN (optional) to pick a specific python3 interpreter.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

PY="${PYTHON_BIN:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "run_all.sh: python3 not found on PATH (set PYTHON_BIN to override)"
  exit 1
fi

TESTS=(
  test_config.py
  test_no_personal_data.py
  test_english_only.py
  test_sanitizer_corpus.py
  test_commit_scoped.py
  test_judge_fixtures.py
  test_aging_fixtures.py
  test_shared_paths.py
  test_cross_signatures.py
  test_queue_hygiene.py
  test_dry_run_clean.py
  test_distill_contract.py
  test_heuristics_taxonomy.py
  test_heuristics_classification.py
)

overall_rc=0
total=${#TESTS[@]}
passed=0

echo "brain-kit test suite: ${total} tests"
echo ""

for t in "${TESTS[@]}"; do
  if [ ! -f "$t" ]; then
    echo "FAIL  $t (file not found)"
    overall_rc=1
    continue
  fi
  out="$("$PY" "$t" 2>&1)"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "PASS  $t"
    passed=$((passed + 1))
  else
    echo "FAIL  $t"
    echo "$out" | sed 's/^/      /'
    overall_rc=1
  fi
done

echo ""
echo "${passed}/${total} passed"

exit $overall_rc
