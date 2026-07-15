#!/usr/bin/env python3
"""Regression for the scoped-commit hardening (scripts/brain_git.commit_scoped):
pipelines must never `git add -A`, only the paths they touched this run.

Three scenarios, each in a throwaway git sandbox under a tmp dir (local repo
config only, the real machine git config is never touched):

  (a) a tracked file is modified AND a path is created-and-deleted in the same
      batch (the "ghost path" case) -> commits only the real change; unrelated
      dirty state in the working tree stays untouched.
  (b) deletion of a tracked file is passed in -> the deletion is committed.
  (c) nothing is actually staged (no real changes among the given paths) ->
      no commit is created (never an empty commit).

Assumes commit_scoped(vault, paths, message, log=None) -> bool, matching the
reference implementation this hardening item is ported from.
"""
import sys
import subprocess
import tempfile
import importlib
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True)


def _init_repo(repo):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "sandbox@example.invalid")
    _git(repo, "config", "user.name", "Sandbox")
    _git(repo, "commit", "--allow-empty", "-q", "-m", "init")


def _commit_count(repo):
    r = _git(repo, "rev-list", "--count", "HEAD")
    return int(r.stdout.strip() or "0")


def _import_commit_scoped():
    sys.path.insert(0, str(KIT_ROOT / "scripts"))
    mod = importlib.import_module("brain_git")
    fn = getattr(mod, "commit_scoped", None)
    if fn is None:
        raise AttributeError("brain_git.py must expose commit_scoped(vault, paths, message, log=None)")
    return fn


def test_ghost_path_and_untouched_mess(commit_scoped):
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        _init_repo(repo)

        tracked = repo / "tracked.md"
        tracked.write_text("baseline\n", encoding="utf-8")
        _git(repo, "add", "--", "tracked.md")
        _git(repo, "commit", "-q", "-m", "seed tracked file")
        before = _commit_count(repo)

        # this run's real change
        tracked.write_text("baseline\nupdated by this run\n", encoding="utf-8")

        # this run's ghost path: created and deleted before commit_scoped ever runs
        ghost = repo / "ghost.md"
        ghost.write_text("temp\n", encoding="utf-8")
        ghost.unlink()

        # unrelated mess NOT part of this run's touched paths; must stay untouched
        mess = repo / "unrelated_dirty.md"
        mess.write_text("someone else's work in progress\n", encoding="utf-8")

        ok = commit_scoped(repo, [tracked, ghost], "scoped commit: tracked + ghost")

        check(ok is True, "commit_scoped should return True when a real change was staged")
        check(_commit_count(repo) == before + 1,
              "expected exactly one new commit for the scoped run")

        show = _git(repo, "show", "--name-only", "--pretty=format:", "HEAD").stdout
        touched_files = {l for l in show.splitlines() if l.strip()}
        check(touched_files == {"tracked.md"},
              f"commit should contain only tracked.md, got {touched_files!r}")

        status = _git(repo, "status", "--porcelain").stdout
        check("unrelated_dirty.md" in status,
              "unrelated dirty file must remain in the working tree, untouched")
        check("?? unrelated_dirty.md" in status,
              "unrelated dirty file must stay untracked (never staged), got: " + status)


def test_tracked_file_deletion(commit_scoped):
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        _init_repo(repo)

        to_delete = repo / "to_delete.md"
        to_delete.write_text("will be removed\n", encoding="utf-8")
        _git(repo, "add", "--", "to_delete.md")
        _git(repo, "commit", "-q", "-m", "seed file to delete")
        before = _commit_count(repo)

        to_delete.unlink()

        ok = commit_scoped(repo, [to_delete], "scoped commit: deletion")

        check(ok is True, "commit_scoped should return True for a tracked deletion")
        check(_commit_count(repo) == before + 1, "deletion should produce exactly one commit")

        ls = _git(repo, "ls-files", "--", "to_delete.md").stdout.strip()
        check(ls == "", "deleted file must no longer be tracked after the commit")

        show = _git(repo, "show", "--name-status", "--pretty=format:", "HEAD").stdout.strip()
        check(show.startswith("D\t"), f"commit should record a deletion (D), got: {show!r}")


def test_nothing_staged_no_commit(commit_scoped):
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        _init_repo(repo)
        before = _commit_count(repo)

        # path that never existed and was never touched this run
        phantom = repo / "never_existed.md"

        ok = commit_scoped(repo, [phantom], "scoped commit: nothing real")

        check(ok is False, "commit_scoped should return False when nothing was actually staged")
        check(_commit_count(repo) == before, "no commit should be created when nothing is staged")

        ok_empty = commit_scoped(repo, [], "scoped commit: empty path list")
        check(ok_empty is False, "commit_scoped should return False for an empty path list")
        check(_commit_count(repo) == before, "empty path list must never produce a commit")


def main():
    try:
        commit_scoped = _import_commit_scoped()
    except (ImportError, AttributeError) as e:
        print(f"test_commit_scoped: cannot import scripts/brain_git.commit_scoped yet ({e}); "
              "expected once the git module lands")
        sys.exit(1)

    test_ghost_path_and_untouched_mess(commit_scoped)
    test_tracked_file_deletion(commit_scoped)
    test_nothing_staged_no_commit(commit_scoped)

    if failures:
        print(f"test_commit_scoped: {len(failures)} failure(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("test_commit_scoped: OK")


if __name__ == "__main__":
    main()
