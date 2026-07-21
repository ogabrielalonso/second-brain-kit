#!/usr/bin/env python3
"""Greps the whole kit tree for personal-data leak patterns (denylist), per the
"Sanitization guarantee for this repo" in docs/ARCHITECTURE.md. Fails listing
file:line for every hit found outside the one carved-out exception: the
methodology credit line naming the author, allowed only inside README.md,
CHANGELOG.md, installer/INSTALL.md and docs/ARCHITECTURE.md, never in code/scripts/prompts/
templates.

Two defenses against this scanner tripping over its own denylist:
1. Every denylist term is assembled from split fragments (never a literal
   contiguous glyph run in this source), the same "construct as data, never
   literal in source" rule this repo applies to em/en dashes.
2. This file's own path is still excluded from the walk as a second layer.

Dash characters (em/en) are banned everywhere, no exception: strictly banned in any
kit file per the hard rules this repo is built under.

Deliberate omission: the macOS iCloud container id for Obsidian vaults (the
literal string Apple/Obsidian use for EVERY user's synced vault folder, not
just this author's) is not on the denylist. The installer legitimately needs
to reference it verbatim to auto-detect vaults on macOS for any owner; only
the author's actual home path (the /Users/ + username combination) is
personal data, and that combination is still caught below.
"""
import sys
import re
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

SKIP_DIR_NAMES = {".git", "__pycache__", ".pytest_cache", "node_modules"}


ALLOWED_SELF_REFERENCE = "github.com/ogabrielalonso/second-brain-kit"

def _t(*parts):
    return "".join(parts)


PRIVATE_ONLY_PATHS_ALLOWED = set()

CREDIT_ALLOWED_FILES = {
    KIT_ROOT / "README.md",
    KIT_ROOT / "CHANGELOG.md",
    KIT_ROOT / "installer" / "INSTALL.md",
    KIT_ROOT / "docs" / "ARCHITECTURE.md",
}

# term -> set of files where it is allowed to appear (empty set = never allowed
# anywhere in the tree). Terms built from split fragments; see module docstring.
DENYLIST = {
    # Generic, universally-wrong patterns for a distributable kit:
    _t("/Users", "/"): set(),        # absolute macOS home paths
    _t("C:\\", "Users"): set(),      # absolute Windows home paths
    _t("/home/", ""): PRIVATE_ONLY_PATHS_ALLOWED,
    "\u2014": set(),  # em dash, no exception
    "\u2013": set(),  # en dash, no exception
}

# Author/owner-specific leak patterns (names, projects, clients, channels) are
# DELIBERATELY NOT in this public file: listing them here would itself disclose
# them. They live in an optional, gitignored local file, one pattern per line
# (lines starting with # ignored), loaded at runtime. The kit author (and any
# owner who forks this) maintains their own private pattern list; public CI
# still enforces the generic rules above.
_local = KIT_ROOT / "tests" / "denylist.local.txt"
if _local.exists():
    for _line in _local.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#"):
            allowed = CREDIT_ALLOWED_FILES if _line.startswith("!credit:") else set()
            DENYLIST[_line.removeprefix("!credit:")] = allowed

# Alphabetic-only (plus spaces) terms are matched at word boundaries to avoid
# false positives inside unrelated common words (e.g. "arca" inside "marca");
# symbol-bearing terms (paths, urls, dashes) are matched as plain substrings
# since they are unambiguous on their own.
_ALPHA_ONLY = re.compile(r"^[A-Za-z ]+$")


def _compile_terms():
    compiled = []
    for term, allowed in DENYLIST.items():
        if _ALPHA_ONLY.match(term):
            pattern = re.compile(r"\b" + re.escape(term) + r"\b")
        else:
            pattern = re.compile(re.escape(term))
        compiled.append((term, pattern, allowed))
    return compiled


def _shipped_paths():
    """The sanitization guarantee covers what SHIPS: git-tracked files.
    A gitignored, author-local file never ships and must not trip the guard
    (root-cause fix, 2026-07-21: a local backups/ file kept the suite red).
    Fallback when git is unavailable (tree copied without .git): walk the
    whole tree, which is strictly more conservative."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(KIT_ROOT), "ls-files", "-z"],
                             capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            return [KIT_ROOT / f for f in out.stdout.split("\0") if f]
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _iter_files():
    tracked = _shipped_paths()
    for p in (tracked if tracked is not None else KIT_ROOT.rglob("*")):
        if not p.is_file():
            continue
        if p.resolve() == SELF:
            continue
        # The private pattern list is, by definition, made of the patterns
        # being hunted; it is gitignored (never ships) and excluded from the walk.
        if p.resolve() == _local.resolve():
            continue
        if any(part in SKIP_DIR_NAMES for part in p.parts):
            continue
        yield p


def main():
    terms = _compile_terms()
    hits = []
    for path in _iter_files():
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable, not a text leak surface
        for term, pattern, allowed in terms:
            if term not in text and not pattern.search(text):
                continue
            if path in allowed:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if not pattern.search(line):
                    continue
                # The kit's own public repository URL is a legitimate
                # self-reference, not a personal-data leak.
                if ALLOWED_SELF_REFERENCE in line:
                    continue
                hits.append(f"{path.relative_to(KIT_ROOT)}:{lineno}: leaked pattern")

    if hits:
        print(f"test_no_personal_data: {len(hits)} leak(s) found")
        for h in hits:
            print(f"  - {h}")
        sys.exit(1)
    print("test_no_personal_data: OK")


if __name__ == "__main__":
    main()
