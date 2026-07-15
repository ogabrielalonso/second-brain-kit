#!/usr/bin/env python3
"""Validates config/config.example.json against the config contract in
docs/ARCHITECTURE.md, and exercises scripts/brain_config.py: port derivation
from vault_path (8700 + sha256(vault_path) % 200) and the BRAIN_CONFIG env
override, both inside a temp dir (nothing touches the real ~/.brain/).

Assumes brain_config.py exposes a loader named load_config() or get_config()
returning a dict, reading the config path from the BRAIN_CONFIG env var when
set. Port resolution may live either inline in that dict (config['port']
already resolved when the file shipped 0) or in a dedicated function
(resolve_port / derive_port / compute_port / get_port); either shape passes.
If brain_config.py has not landed yet (parallel build), the two runtime
checks fail with a clear message instead of a stack trace; the structural
check of config.example.json still runs on its own.
"""
import sys
import os
import json
import hashlib
import inspect
import tempfile
import importlib
import contextlib
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_EXAMPLE = KIT_ROOT / "config" / "config.example.json"

REQUIRED_SCALAR_KEYS = [
    "owner_name", "owner_context", "main_language", "vault_path", "port",
    "instance_id", "ntfy_topic_file", "judge_enabled",
]
REQUIRED_SOURCES_KEYS = ["claude_projects", "extra_paths"]
REQUIRED_TAXONOMY_KEYS = [
    "decisions_dir", "weekly_dir", "queue_dir", "digests_dir", "heuristics",
    "home_dir", "index_targets", "index_exclude", "moc_map",
]
REQUIRED_HEURISTICS_KEYS = ["lessons", "patterns"]
REQUIRED_THRESHOLD_KEYS = [
    "inject_min_score", "index_stale_h", "queue_alert", "max_apply_per_run",
    "aging_check_interval_d", "eligibility",
]
REQUIRED_ELIGIBILITY_KEYS = ["min_n", "min_rate", "min_weeks"]

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


def test_config_example_structure():
    if not check(CONFIG_EXAMPLE.exists(), f"missing {CONFIG_EXAMPLE}"):
        return
    data = json.loads(CONFIG_EXAMPLE.read_text(encoding="utf-8"))

    for k in REQUIRED_SCALAR_KEYS:
        check(k in data, f"config.example.json missing top-level key '{k}'")

    check(isinstance(data.get("sources"), dict),
          "config.example.json 'sources' must be an object")
    for k in REQUIRED_SOURCES_KEYS:
        check(k in data.get("sources", {}),
              f"config.example.json 'sources' missing key '{k}'")

    check(isinstance(data.get("confidential_patterns"), list),
          "config.example.json 'confidential_patterns' must be a list")

    tax = data.get("taxonomy", {})
    check(isinstance(tax, dict), "config.example.json 'taxonomy' must be an object")
    for k in REQUIRED_TAXONOMY_KEYS:
        check(k in tax, f"config.example.json 'taxonomy' missing key '{k}'")
    heur = tax.get("heuristics", {})
    check(isinstance(heur, dict), "config.example.json 'taxonomy.heuristics' must be an object")
    for k in REQUIRED_HEURISTICS_KEYS:
        check(k in heur, f"config.example.json 'taxonomy.heuristics' missing key '{k}'")
    check(isinstance(tax.get("index_targets"), list),
          "config.example.json 'taxonomy.index_targets' must be a list")
    check(isinstance(tax.get("index_exclude"), list),
          "config.example.json 'taxonomy.index_exclude' must be a list")
    check(isinstance(tax.get("moc_map"), dict),
          "config.example.json 'taxonomy.moc_map' must be an object")

    th = data.get("thresholds", {})
    check(isinstance(th, dict), "config.example.json 'thresholds' must be an object")
    for k in REQUIRED_THRESHOLD_KEYS:
        check(k in th, f"config.example.json 'thresholds' missing key '{k}'")
    elig = th.get("eligibility", {})
    check(isinstance(elig, dict), "config.example.json 'thresholds.eligibility' must be an object")
    for k in REQUIRED_ELIGIBILITY_KEYS:
        check(k in elig, f"config.example.json 'thresholds.eligibility' missing key '{k}'")

    check(data.get("port") == 0,
          "config.example.json 'port' should ship as 0 (auto-derive placeholder)")
    check(data.get("judge_enabled") is False,
          "config.example.json 'judge_enabled' should ship as false (dormant by default)")


def _import_brain_config():
    sys.path.insert(0, str(KIT_ROOT / "scripts"))
    return importlib.import_module("brain_config")


def _expected_port(vault_path):
    digest = hashlib.sha256(vault_path.encode("utf-8")).hexdigest()
    return 8700 + (int(digest, 16) % 200)


def _write_temp_config(tmp_path, **overrides):
    base = json.loads(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
    base["vault_path"] = str(tmp_path / "vault")
    base.update(overrides)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(base), encoding="utf-8")
    return cfg_path, base


def _find_loader(bc):
    return getattr(bc, "load_config", None) or getattr(bc, "get_config", None)


def _find_port_fn(bc):
    # bare 'port' first: that is the name the reference contract in
    # docs/ARCHITECTURE.md implies ("Loaded by every script via brain_config.py");
    # the others are kept as fallbacks in case of a naming difference.
    for name in ("port", "resolve_port", "derive_port", "compute_port", "get_port"):
        fn = getattr(bc, name, None)
        if fn is not None:
            return fn
    return None


@contextlib.contextmanager
def _brain_config_env(cfg_path):
    """Points BRAIN_CONFIG at a sandbox config file for the whole block, so every
    call made inside (load_config(), port(), ...) resolves against it consistently;
    a partial override (set for one call, restored before a related second call)
    would silently fall back to the real ~/.brain/config.json mid-test."""
    old_env = os.environ.get("BRAIN_CONFIG")
    os.environ["BRAIN_CONFIG"] = str(cfg_path)
    try:
        yield
    finally:
        if old_env is None:
            os.environ.pop("BRAIN_CONFIG", None)
        else:
            os.environ["BRAIN_CONFIG"] = old_env


def test_port_derivation_and_env_override():
    try:
        bc = _import_brain_config()
    except ImportError as e:
        failures.append(
            f"cannot import scripts/brain_config.py yet ({e}); expected once "
            "the config module lands (this test then runs for real)")
        return

    loader = _find_loader(bc)
    if not check(loader is not None,
                 "brain_config.py must expose load_config() or get_config()"):
        return

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cfg_path, base = _write_temp_config(tmp, port=0, owner_name="Sandbox Owner")
        expected = _expected_port(base["vault_path"])
        port_fn = _find_port_fn(bc)

        with _brain_config_env(cfg_path):
            cfg = loader(force=True) if _accepts_force(loader) else loader()
            check(isinstance(cfg, dict), "load_config()/get_config() must return a dict")
            if not isinstance(cfg, dict):
                return
            check(cfg.get("owner_name") == "Sandbox Owner",
                  "BRAIN_CONFIG env override was not honored (wrong owner_name loaded)")

            if port_fn is not None:
                try:
                    if len(inspect.signature(port_fn).parameters) >= 1:
                        try:
                            got = port_fn(cfg)
                        except (TypeError, KeyError, AttributeError):
                            got = port_fn(base["vault_path"])
                    else:
                        got = port_fn()
                except (TypeError, ValueError):
                    got = None
                check(got == expected,
                      f"derived port mismatch: expected {expected}, got {got}")
            else:
                got = cfg.get("port")
                check(got == expected,
                      f"load_config() should resolve port=0 to {expected} "
                      f"(8700 + sha256(vault_path) % 200), got {got}")


def _accepts_force(fn):
    try:
        return "force" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def test_manual_port_wins_over_derivation():
    try:
        bc = _import_brain_config()
    except ImportError:
        return  # already reported by test_port_derivation_and_env_override

    loader = _find_loader(bc)
    if loader is None:
        return  # already reported above

    port_fn = _find_port_fn(bc)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cfg_path, _base = _write_temp_config(tmp, port=9999)
        with _brain_config_env(cfg_path):
            cfg = loader(force=True) if _accepts_force(loader) else loader()
            if not isinstance(cfg, dict):
                return
            check(cfg.get("port") == 9999,
                  "an explicit non-zero port in config must win over derivation (no clobbering)")
            if port_fn is not None and len(inspect.signature(port_fn).parameters) == 0:
                check(port_fn() == 9999,
                      "port() must return the explicit config value, not a derived one, "
                      "when config.port is non-zero")


def main():
    test_config_example_structure()
    test_port_derivation_and_env_override()
    test_manual_port_wins_over_derivation()
    if failures:
        print(f"test_config: {len(failures)} failure(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("test_config: OK")


if __name__ == "__main__":
    main()
