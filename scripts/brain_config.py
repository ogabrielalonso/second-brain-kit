#!/usr/bin/env python3
"""Single source of truth for owner config: ~/.brain/config.json.

Every script in this kit must go through this module to read the owner's
vault path, port, taxonomy, thresholds or any other per-install value. No
script may hardcode an owner path, name, topic or port; that data lives only
in ~/.brain/config.json (outside the vault, generated at install time).

The config location is overridable via the BRAIN_CONFIG environment variable
(used by tests and by anyone running more than one brain on the same box).
"""
import hashlib
import json
import os
from pathlib import Path

DEFAULT_CONFIG_PATH = "~/.brain/config.json"

REQUIRED_KEYS = ["owner_name", "main_language", "vault_path", "port", "instance_id"]

DEFAULT_TAXONOMY = {
    "decisions_dir": "04-Journal/Decisions",
    "weekly_dir": "04-Journal/Weekly",
    "queue_dir": "04-Journal/gate-queue",
    "digests_dir": "04-Journal",
    "heuristics": {"lessons": "", "patterns": "", "routing": ""},
    "home_dir": "00-HOME",
    "index_targets": ["00-HOME", "01-MOCs", "02-Projects", "03-Knowledge", "04-Journal"],
    "index_exclude": ["_system/", "Inbox/", "gate-queue/", "/templates/", "/history/"],
    "moc_map": {},
}

DEFAULT_THRESHOLDS = {
    "inject_min_score": 0.52,
    "index_stale_h": 12,
    "queue_alert": 15,
    "max_apply_per_run": 10,
    "aging_check_interval_d": 90,
    "eligibility": {"min_n": 20, "min_rate": 0.95, "min_weeks": 6},
}


class ConfigError(RuntimeError):
    """Raised when the config file is missing, unreadable or invalid."""


_cache = {"path": None, "mtime": None, "data": None}


def config_path() -> Path:
    """Path to config.json, honoring the BRAIN_CONFIG override (tests, multi-install)."""
    raw = os.environ.get("BRAIN_CONFIG", DEFAULT_CONFIG_PATH)
    return Path(raw).expanduser()


def brain_home() -> Path:
    """Directory holding config, index, model cache, state and logs (always outside the vault)."""
    return config_path().parent


def load_config(force: bool = False) -> dict:
    """Load and validate config.json. Cached by (path, mtime); pass force=True to bypass."""
    path = config_path()
    if not path.exists():
        raise ConfigError(
            f"Config not found at {path}. Run the installer (installer/INSTALL.md) "
            "first, or set BRAIN_CONFIG to point at a valid config.json."
        )
    try:
        mtime = path.stat().st_mtime
    except OSError as e:
        raise ConfigError(f"Could not stat config at {path}: {e}") from e

    if not force and _cache["data"] is not None and _cache["path"] == path and _cache["mtime"] == mtime:
        return _cache["data"]

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"Could not read config at {path}: {e}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Config at {path} is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ConfigError(f"Config at {path} must be a JSON object, found {type(data).__name__}.")

    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ConfigError(
            f"Config at {path} is missing required key(s): {', '.join(missing)}."
        )
    if not isinstance(data.get("vault_path"), str) or not data["vault_path"].strip():
        raise ConfigError(f"Config at {path}: 'vault_path' must be a non-empty string.")
    if not isinstance(data.get("instance_id"), str) or not data["instance_id"].strip():
        raise ConfigError(f"Config at {path}: 'instance_id' must be a non-empty string.")

    _cache["path"] = path
    _cache["mtime"] = mtime
    _cache["data"] = data
    return data


def vault_path() -> Path:
    """Owner's vault as an existing, expanded path. Raises ConfigError if it does not exist."""
    data = load_config()
    p = Path(data["vault_path"]).expanduser()
    if not p.exists():
        raise ConfigError(f"vault_path from config does not exist on disk: {p}")
    return p


def port() -> int:
    """Daemon port. Explicit config.port wins; 0 means derive deterministically from vault_path
    so two installs on the same machine do not collide (8700 + sha256(vault_path) % 200)."""
    data = load_config()
    configured = data.get("port", 0)
    try:
        configured = int(configured)
    except (TypeError, ValueError):
        raise ConfigError(f"Config 'port' must be an integer, got: {configured!r}")
    if configured:
        return configured
    digest = hashlib.sha256(str(data["vault_path"]).encode("utf-8")).hexdigest()
    return 8700 + (int(digest, 16) % 200)


def instance_id() -> str:
    """Random hex generated at install time; clients must verify this against /health
    before trusting a daemon response (another brain instance may share the port)."""
    return load_config()["instance_id"]


def owner_name() -> str:
    return load_config().get("owner_name", "")


def owner_context() -> str:
    return load_config().get("owner_context", "")


def main_language() -> str:
    return load_config().get("main_language", "en")


def taxonomy() -> dict:
    """Owner's vault taxonomy, merged over the skeleton defaults (MODE B). MODE A installs
    always have every key explicit in config, so defaults only matter for MODE B / tests."""
    data = load_config()
    merged = dict(DEFAULT_TAXONOMY)
    merged.update(data.get("taxonomy") or {})
    return merged


def thresholds() -> dict:
    data = load_config()
    merged = dict(DEFAULT_THRESHOLDS)
    merged.update(data.get("thresholds") or {})
    return merged


def ntfy_topic() -> str:
    """Read the ntfy topic from the file config.ntfy_topic_file points at. Returns '' when
    unset or unreadable; callers must treat empty as 'notifications disabled', never fabricate
    a topic."""
    data = load_config()
    ref = data.get("ntfy_topic_file")
    if not ref:
        return ""
    p = Path(ref).expanduser()
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def sources() -> dict:
    data = load_config()
    return data.get("sources") or {"claude_projects": True, "extra_paths": []}


def confidential_patterns() -> list:
    data = load_config()
    return list(data.get("confidential_patterns") or [])


def judge_enabled() -> bool:
    return bool(load_config().get("judge_enabled", False))


def index_dir() -> Path:
    """Index storage, always outside the vault: <brain_home>/index/."""
    return brain_home() / "index"


def get_path(dotted: str):
    """Resolve a dotted config path (e.g. 'taxonomy.home_dir',
    'thresholds.inject_min_score') for shell clients (templates/hooks/*.sh use
    `brain_config.py get <dot.path.key>`). The known top-level sections route
    through the same default-merging helpers python callers use (taxonomy(),
    thresholds(), vault_path(), port(), ...), so a hook sees the identical
    value a script would; anything else falls back to a raw walk of
    load_config(). Returns None when any segment of the path is missing."""
    parts = dotted.split(".")
    if not parts or not parts[0]:
        return None
    head = parts[0]
    single_key_helpers = {
        "vault_path": lambda: str(vault_path()),
        "port": port,
        "instance_id": instance_id,
        "owner_name": owner_name,
        "owner_context": owner_context,
        "main_language": main_language,
        "ntfy_topic": ntfy_topic,
    }
    if head in single_key_helpers:
        return single_key_helpers[head]() if len(parts) == 1 else None
    if head == "taxonomy":
        node = taxonomy()
    elif head == "thresholds":
        node = thresholds()
    else:
        node = load_config().get(head)
    for key in parts[1:]:
        if isinstance(node, dict):
            node = node.get(key)
        else:
            return None
    return node


if __name__ == "__main__":
    # Tiny CLI for shell callers (query.sh, hooks, etc.):
    #   brain_config.py <field>              (legacy bare-field form)
    #   brain_config.py get <dot.path.key>    (dotted-path form used by hooks)
    import sys

    try:
        if len(sys.argv) == 3 and sys.argv[1] == "get":
            value = get_path(sys.argv[2])
            if value is None:
                sys.exit(1)
            if isinstance(value, (dict, list)):
                print(json.dumps(value))
            else:
                print(value)
        elif len(sys.argv) == 2:
            field = sys.argv[1]
            if field == "vault_path":
                print(str(vault_path()))
            elif field == "port":
                print(port())
            elif field == "instance_id":
                print(instance_id())
            elif field == "owner_name":
                print(owner_name())
            elif field == "main_language":
                print(main_language())
            elif field == "index_dir":
                print(str(index_dir()))
            else:
                print(f"Unknown field: {field}", file=sys.stderr)
                sys.exit(2)
        else:
            print("Usage: brain_config.py <owner_name|vault_path|port|instance_id|main_language|index_dir>", file=sys.stderr)
            print("       brain_config.py get <dot.path.key>", file=sys.stderr)
            sys.exit(2)
    except ConfigError as e:
        print(f"ConfigError: {e}", file=sys.stderr)
        sys.exit(1)
