#!/usr/bin/env python3
"""Everything in this repository ships in English. This guard fails on
Portuguese (the methodology's origin language) leaking into any file:
accented characters common to Portuguese, and a small list of Portuguese
words chosen to avoid English collisions.

Carve-outs, each deliberate:
- installer/INSTALL.md may contain the French word used as the canonical
  accent-folding example in the dedup spec (an i18n feature illustration,
  not a language leak).
- Lines tagged pt-verdict-alias (brain_aging.py and its fixture _doc) may
  name the two Portuguese verdict strings the aging apply-layer accepts as
  aliases for robustness (the judge model sometimes answers in the owner's
  language); those literals are a feature, not a leak.
- tests/denylist.local.txt (gitignored, author-local) is excluded: it never
  ships.
- This file excludes itself: it must name the patterns it hunts.
"""
import re
import sys
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
LOCAL_DENYLIST = KIT_ROOT / "tests" / "denylist.local.txt"
SKIP_DIR_NAMES = {".git", "__pycache__", ".pytest_cache", "node_modules"}

ACCENTS = re.compile(r"[ãõçáéíóúâêôà"
                     r"ÃÕÇÁÉÍÓÚÂÊÔÀ]")
ALLOWED_ACCENT_LINES = {
    # the accent-folding feature example in the dedup spec
    (KIT_ROOT / "installer" / "INSTALL.md", "accent-folding"),
}

# Portuguese words with no common English collision, word-boundary matched.
PT_WORDS = re.compile(
    r"\b(você|não|nao existe|arquivo|arquivos|fila|pasta|pastas|aprovado|descartado|"
    r"escalado|julgar|julga|conteúdo|conteudo|seção|secao|lição|licao|"
    r"proibido|travessão|travessao|semanal|diário|destilar|veredito|motivo|"
    r"pessoal|decisão|revisão|atual|candidata|candidatos|aprender|regra)\b",
    re.IGNORECASE,
)
ALLOWED_PT_LINES = {
    # the aging apply-layer's Portuguese verdict aliases (see module docstring)
    (KIT_ROOT / "scripts" / "brain_aging.py", "pt-verdict-alias"),
    (KIT_ROOT / "tests" / "fixtures" / "aging" / "expected.json", "pt-verdict-alias"),
}


def _shipped_paths():
    """English-only applies to what SHIPS: git-tracked files. A gitignored,
    author-local file never ships and must not trip the guard (root-cause
    fix, 2026-07-21). Fallback without git: whole-tree walk (conservative)."""
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
        r = p.resolve()
        if r == SELF or r == LOCAL_DENYLIST.resolve():
            continue
        if any(part in SKIP_DIR_NAMES for part in p.parts):
            continue
        yield p


def main():
    hits = []
    for path in _iter_files():
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        # filenames must be English/ASCII too
        if ACCENTS.search(path.name) or PT_WORDS.search(path.name.replace("-", " ").replace("_", " ")):
            hits.append(f"{path.relative_to(KIT_ROOT)}: non-English filename")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ACCENTS.search(line):
                if any(path == ap and marker in line for ap, marker in ALLOWED_ACCENT_LINES):
                    continue
                hits.append(f"{path.relative_to(KIT_ROOT)}:{lineno}: accented (non-English) text")
                continue
            if PT_WORDS.search(line):
                if any(path == ap and marker in line for ap, marker in ALLOWED_PT_LINES):
                    continue
                hits.append(f"{path.relative_to(KIT_ROOT)}:{lineno}: Portuguese word")

    if hits:
        print(f"test_english_only: {len(hits)} non-English finding(s)")
        for h in hits:
            print(f"  - {h}")
        sys.exit(1)
    print("test_english_only: OK")


if __name__ == "__main__":
    main()
