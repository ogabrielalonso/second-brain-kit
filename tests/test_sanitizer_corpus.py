#!/usr/bin/env python3
"""Mandatory acceptance corpus for scripts/sanitize.py (the CODE sanitizer, run
before anything touches an LLM). Every item below must come out with TOTAL
redaction: no fragment of the secret (not even a partial substring) may
survive in the output.

Corpus categories (per docs/ARCHITECTURE.md "regras de sanitizacao"): API keys
with hyphens AND underscores, a JWT, a PEM private key block, an IBAN, EU-style
phone numbers, an email with a name embedded in the local part, and a
confidential owner pattern (from config.confidential_patterns) inside an
otherwise-ordinary long sentence.

Calling convention assumed for scripts/sanitize.py: a single entrypoint named
sanitize(text) or redact_text(text) or redact(text), optionally accepting a
second positional/keyword argument of extra confidential patterns to redact
(confidential_patterns=[...]). If the module instead splits secret-pattern
redaction from confidential-pattern redaction into two functions, this test
also tries redact_confidential(text, patterns) / apply_confidential_patterns
as a second pass. Update the NAME candidates below if the real module lands
under different names; the corpus and "must not leak" assertions stay valid
either way.
"""
import sys
import json
import inspect
import importlib
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_EXAMPLE = KIT_ROOT / "config" / "config.example.json"

UNIFIED_NAME_CANDIDATES = ["sanitize", "redact_text", "redact"]
CONFIDENTIAL_NAME_CANDIDATES = [
    "redact_confidential", "apply_confidential_patterns", "redact_owner_patterns",
]

CORPUS = [
    {
        # hyphenated vendor-style key (Anthropic shape), embedded mid-sentence
        # rather than as a standalone env line, to also confirm detection does
        # not depend on the token being at the start of a line.
        "name": "api_key_hyphenated",
        "text": (
            "Rotated key for the CI pipeline: "
            "sk-ant-api03-J8x2KpQ7mZ4vT1yN6wL9cR3hB5dF0sG2eH8iK4oP7qU1wY6z "
            "(keep this out of logs)."
        ),
        "must_not_contain": [
            "sk-ant-api03-J8x2KpQ7mZ4vT1yN6wL9cR3hB5dF0sG2eH8iK4oP7qU1wY6z",
            "J8x2KpQ7mZ4vT1yN6wL9cR3hB5dF0sG2eH8iK4oP7qU1wY6z",
            "T1yN6wL9cR3hB5dF0sG2eH8iK4oP7qU1wY6z",
        ],
    },
    {
        # underscored vendor-style key (Stripe shape), also embedded mid-sentence.
        # Assembled at runtime so no secret-shaped literal sits in this file
        # (GitHub push protection would flag it as a real vendor key).
        "name": "api_key_underscored",
        "text": "Rotate " + "_".join(["sk", "live", "51H8f2a9c3e7b1d4f60a2c9e7b1d4f60a2c"]) + " before the demo.",
        "must_not_contain": [
            "_".join(["sk", "live", "51H8f2a9c3e7b1d4f60a2c9e7b1d4f60a2c"]),
            "51H8f2a9c3e7b1d4f60a2c9e7b1d4f60a2c",
        ],
    },
    {
        "name": "jwt",
        "text": (
            "Authorization: Bearer "
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0."
            "dGhpc19pc19hX2Zha2Vfc2lnbmF0dXJlX2Zvcl90ZXN0aW5n"
        ),
        "must_not_contain": [
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0",
            "dGhpc19pc19hX2Zha2Vfc2lnbmF0dXJlX2Zvcl90ZXN0aW5n",
        ],
    },
    {
        "name": "pem_private_key_block",
        "text": (
            "Rotate this before shipping:\n"
            "-----BEGIN PRIVATE KEY-----\n"
            "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj\n"
            "MzEfYyjiWA4R4/M2bS1GB4t7NXp98C3SC6dVMvDuictGeurT8jNbvJZHtCSuYEvu\n"
            "NMoSfm76oqFvAp8Gy0iz5sxjZmSnXyCdPEovGhLa0VzMaQ8s+CLOyS56YyCFGeJZ\n"
            "-----END PRIVATE KEY-----\n"
            "That key must never reach the model."
        ),
        "must_not_contain": [
            "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcw",
            "MzEfYyjiWA4R4/M2bS1GB4t7NXp98C3SC6dVMvDuictGeurT8jNbvJZHtCSuYEvu",
            "NMoSfm76oqFvAp8Gy0iz5sxjZmSnXyCdPEovGhLa0VzMaQ8s+CLOyS56YyCFGeJZ",
        ],
    },
    {
        "name": "iban",
        "text": "Wire the retainer to IBAN LU28 0019 4006 4475 0000 before Friday.",
        "must_not_contain": [
            "LU28 0019 4006 4475 0000",
            "LU28001940064475",
            "0019 4006 4475",
        ],
    },
    {
        "name": "eu_phone_numbers",
        "text": (
            "You can reach the accountant directly at +352 691 234 567, "
            "or try the Berlin office on +49 151 2345 6789 if that line is busy."
        ),
        "must_not_contain": [
            "+352 691 234 567",
            "691 234 567",
            "+49 151 2345 6789",
            "151 2345 6789",
        ],
    },
    {
        "name": "email_with_embedded_name",
        "text": "Please cc jane.marie.doe@example-consulting.eu on the invoice thread.",
        "must_not_contain": [
            "jane.marie.doe@example-consulting.eu",
            "jane.marie.doe",
            "jane.marie",
        ],
    },
    {
        "name": "confidential_owner_pattern_in_long_sentence",
        "text": (
            "During the quarterly review we spent most of the call walking "
            "through the example-client-codename integration risks, the "
            "migration timeline, and why the vendor kept slipping deadlines "
            "on the shared workspace rollout that everyone had been anxious "
            "about since the kickoff."
        ),
        "must_not_contain": ["example-client-codename"],
        "confidential_patterns": ["example-client-codename"],
    },
]


def _load_confidential_patterns():
    if not CONFIG_EXAMPLE.exists():
        return []
    data = json.loads(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
    return data.get("confidential_patterns", [])


def _find_unified(mod):
    for name in UNIFIED_NAME_CANDIDATES:
        fn = getattr(mod, name, None)
        if fn is not None:
            return name, fn
    return None, None


def _find_confidential(mod):
    for name in CONFIDENTIAL_NAME_CANDIDATES:
        fn = getattr(mod, name, None)
        if fn is not None:
            return name, fn
    return None, None


def _call(fn, text, patterns):
    try:
        params = len(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        params = 1
    if params >= 2:
        try:
            out = fn(text, patterns)
        except TypeError:
            out = fn(text)
    else:
        out = fn(text)
    if isinstance(out, tuple):
        out = out[0]
    return out


def main():
    sys.path.insert(0, str(KIT_ROOT / "scripts"))
    try:
        sanitize_mod = importlib.import_module("sanitize")
    except ImportError as e:
        print(f"test_sanitizer_corpus: cannot import scripts/sanitize.py yet ({e}); "
              "expected once the sanitizer module lands")
        sys.exit(1)

    unified_name, unified_fn = _find_unified(sanitize_mod)
    if unified_fn is None:
        print("test_sanitizer_corpus: sanitize.py must expose one of "
              f"{UNIFIED_NAME_CANDIDATES}")
        sys.exit(1)

    conf_name, conf_fn = _find_confidential(sanitize_mod)
    all_patterns = _load_confidential_patterns()

    failures = []
    for item in CORPUS:
        patterns = item.get("confidential_patterns", all_patterns)
        out = _call(unified_fn, item["text"], patterns)
        if not isinstance(out, str):
            failures.append(f"{item['name']}: {unified_name}() did not return a string")
            continue
        # second pass for confidential patterns, if the sanitizer splits concerns
        if item.get("confidential_patterns") and conf_fn is not None:
            out2 = _call(conf_fn, out, patterns)
            if isinstance(out2, str):
                out = out2
        leaked = [frag for frag in item["must_not_contain"] if frag in out]
        if leaked:
            failures.append(
                f"{item['name']}: partial leakage, still contains {leaked!r} "
                f"in output: {out[:160]!r}")

    if failures:
        print(f"test_sanitizer_corpus: {len(failures)} failure(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print(f"test_sanitizer_corpus: OK ({len(CORPUS)} items, total redaction confirmed)")


if __name__ == "__main__":
    main()
