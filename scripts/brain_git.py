#!/usr/bin/env python3
"""brain_git: scoped commits for the autonomous brain pipelines.

Rationale: autonomous pipelines (gate_judge, aging, weekly dispatch, etc.) must
never `git add -A`, because that would sweep any unrelated pending change in the
working tree into a robotic commit (a real failure mode: an unrelated batch of
notes from a manual session got signed by the autonomous gate without ever being
judged, invisible in its digest). Rule:

  - `git add` ONLY the paths this run's appliers wrote or deleted;
  - unrelated changes are left untouched in the working tree (the owner's business);
  - if nothing was staged, do not commit (avoids an empty commit).

Usage from pipelines:
    from brain_git import commit_scoped
    ok = commit_scoped(VAULT, touched_paths, message, log=log)
"""
import subprocess
from pathlib import Path


def commit_scoped(vault, paths, message, log=None):
    """Commit ONLY the given paths (absolute or relative to vault).

    Returns True if a commit was created, False otherwise. Never raises on git
    state (a pipeline cannot die here); errors go to the provided log callback.
    """
    vault = Path(vault)

    def git(*args):
        return subprocess.run(["git", "-C", str(vault), *args],
                              capture_output=True, text=True)

    def _log(msg):
        if log:
            log(f"[brain_git] {msg}")

    rels = []
    for p in paths or []:
        try:
            p = Path(p)
            rel = str(p.relative_to(vault)) if p.is_absolute() else str(p)
        except ValueError:
            _log(f"path outside the vault ignored: {p}")
            continue
        rels.append(rel)
    rels = sorted(set(rels))
    if not rels:
        _log("no paths touched this run; commit skipped")
        return False

    # Filter out paths git has nothing to register for: a file created and then
    # deleted within the same run (the normal case for an approved or discarded
    # gate candidate) that was never tracked. A pathspec with no match would make
    # a BATCH `git add` fail entirely (rc=128) without staging anything.
    def _tracked(rel):
        return git("ls-files", "--error-unmatch", "--", rel).returncode == 0

    addable = [rel for rel in rels
               if (vault / rel).exists() or _tracked(rel)]
    ghost = set(rels) - set(addable)
    if ghost:
        _log(f"{len(ghost)} path(s) created-and-deleted within the same run (nothing to register): "
             f"{sorted(ghost)[:3]}")
    if not addable:
        _log("no registrable paths; commit skipped")
        return False

    # `git add --` works for new, modified AND deleted (tracked) files
    r = git("add", "--", *addable)
    if r.returncode != 0:
        # fallback: add one at a time, so one problematic path does not sink the run
        _log(f"batch git add failed ({r.stderr.strip()[:120]}); retrying one by one")
        ok_any = False
        for rel in addable:
            ri = git("add", "--", rel)
            if ri.returncode == 0:
                ok_any = True
            else:
                _log(f"git add failed for '{rel}': {ri.stderr.strip()[:120]}")
        if not ok_any:
            _log("git add failed for ALL paths; commit aborted")
            return False

    staged = git("diff", "--cached", "--name-only").stdout.strip()
    if not staged:
        _log("nothing staged (paths had no real change); commit skipped")
        return False

    # Transparency: what was left out is logged (but NOT included in the commit).
    # After the scoped add, any line with X in {' ', '?'} is an unrelated change.
    outside = [l for l in git("status", "--porcelain").stdout.splitlines()
               if l and l[0] in ("?", " ")]
    if outside:
        _log(f"{len(outside)} unrelated change(s) left in the working tree "
             f"(e.g. {outside[0][:60]})")

    r = git("commit", "-m", message)
    if r.returncode != 0:
        _log(f"git commit failed: {r.stderr.strip()[:200]}")
        return False
    _log(f"scoped commit created ({len(staged.splitlines())} files)")
    return True
