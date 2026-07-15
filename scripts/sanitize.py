#!/usr/bin/env python3
"""sanitize: secret and confidentiality redactor for the brain kit.

Pre-LLM safety layer. Given raw text (a session transcript, an export, anything
that might get read by an LLM or committed to the vault), replaces known secret
shapes with placeholders, deterministically, with plain regex (no LLM involved).
Owner-specific confidential terms (from config.confidential_patterns) are applied
LAST, after the generic secret patterns, so a leaked token still gets caught even
if it also happens to match a confidential term.

NEVER pass raw content to an LLM without running it through sanitize() first.

Usage as a module:
    from sanitize import sanitize
    clean_text, counts = sanitize(text, patterns=confidential_patterns)

Usage as a CLI:
    python3 sanitize.py <input.jsonl-or-txt> [output] [--check] [--patterns P [P ...]]
    python3 sanitize.py --check <input>          # only count findings, do not write
"""
import re
import sys
import json
import argparse
from pathlib import Path

# Generic secret shapes (provider-agnostic where possible). Order matters only in
# that longer/more specific patterns are listed before looser fallbacks.
SECRET_PATTERNS = [
    # Known provider API keys
    (re.compile(r'sk-ant-[A-Za-z0-9_-]{20,}'), '<ANTHROPIC_KEY>'),
    (re.compile(r'sk-[A-Za-z0-9_-]{20,}'), '<OPENAI_KEY>'),
    (re.compile(r'pcsk_[A-Za-z0-9_-]{20,}'), '<PINECONE_KEY>'),
    (re.compile(r'ghp_[A-Za-z0-9]{30,}'), '<GITHUB_TOKEN>'),
    (re.compile(r'gho_[A-Za-z0-9]{30,}'), '<GITHUB_TOKEN>'),
    (re.compile(r'github_pat_[A-Za-z0-9_]{20,}'), '<GITHUB_TOKEN>'),
    (re.compile(r'AKIA[A-Z0-9]{16}'), '<AWS_ACCESS_KEY>'),
    (re.compile(r'AIza[A-Za-z0-9_-]{30,}'), '<GOOGLE_API_KEY>'),
    (re.compile(r'GOCSPX-[A-Za-z0-9_-]{20,}'), '<GOOGLE_OAUTH_SECRET>'),
    (re.compile(r'xox[baprs]-[A-Za-z0-9-]{10,}'), '<SLACK_TOKEN>'),
    (re.compile(r'glpat-[A-Za-z0-9_-]{20,}'), '<GITLAB_TOKEN>'),
    (re.compile(r'sk_(live|test)_[A-Za-z0-9]{20,}'), '<STRIPE_KEY>'),
    # JWT tokens (three base64url segments separated by dots)
    (re.compile(r'eyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}'), '<JWT_TOKEN>'),
    # PEM private keys of any kind
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', re.DOTALL), '<PRIVATE_KEY>'),
    (re.compile(r'-----BEGIN RSA PRIVATE KEY-----.*?-----END RSA PRIVATE KEY-----', re.DOTALL), '<RSA_PRIVATE_KEY>'),
    (re.compile(r'-----BEGIN OPENSSH PRIVATE KEY-----.*?-----END OPENSSH PRIVATE KEY-----', re.DOTALL), '<SSH_PRIVATE_KEY>'),
    (re.compile(r'-----BEGIN EC PRIVATE KEY-----.*?-----END EC PRIVATE KEY-----', re.DOTALL), '<EC_PRIVATE_KEY>'),
    # Connection strings with an embedded password
    (re.compile(r'mongodb(\+srv)?://[^:]+:[^@]+@[^/\s]+'), '<MONGODB_URI>'),
    (re.compile(r'postgres(ql)?://[^:]+:[^@]+@[^/\s]+'), '<POSTGRES_URI>'),
    (re.compile(r'mysql://[^:]+:[^@]+@[^/\s]+'), '<MYSQL_URI>'),
    (re.compile(r'redis://[^:]*:[^@]+@[^/\s]+'), '<REDIS_URI>'),
    (re.compile(r'amqp://[^:]+:[^@]+@[^/\s]+'), '<AMQP_URI>'),
    # Inline password assignments: password: VALUE, senha=VALUE, etc.
    (re.compile(r'(?i)(senha|password|passwd|pwd)\s*[:=]\s*[\'"]([^\'"\n]{8,})[\'"]'), r'\1: "<REDACTED_PASSWORD>"'),
    (re.compile(r'(?i)(senha|password|passwd|pwd)\s*[:=]\s*(\S{8,})'), r'\1: <REDACTED_PASSWORD>'),
    # Typical env-var lines: SOMETHING_KEY=..., SOMETHING_SECRET=..., etc.
    (re.compile(r'(?m)^([A-Z][A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|PWD)[A-Z0-9_]*)\s*=\s*([^\s\n]+)'), r'\1=<REDACTED>'),
    # IBAN (country code + check digits + up to 30 alphanumerics)
    (re.compile(r'\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b'), '<IBAN>'),
    # Email addresses
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'), '<EMAIL>'),
    # Phone numbers: international format with a leading +
    (re.compile(r'\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}'), '<PHONE>'),
    # Phone numbers: local grouped-digit formats (7 to 11 digits, at least one separator)
    (re.compile(r'(?<!\d)\(?\d{2,4}\)?[\s.-]\d{3,4}[\s.-]\d{3,4}(?!\d)'), '<PHONE>'),
]


def _compile_confidential(patterns):
    """Compile owner-supplied confidential_patterns as case-insensitive regexes.
    Falls back to a literal (escaped) match when the entry is not valid regex, so
    a plain codename like "acme-project" works without the owner writing regex."""
    compiled = []
    for p in patterns or []:
        if not p:
            continue
        try:
            compiled.append(re.compile(p, re.IGNORECASE))
        except re.error:
            compiled.append(re.compile(re.escape(p), re.IGNORECASE))
    return compiled


def sanitize(text, patterns=None):
    """Pure function. Applies the built-in secret patterns first, then the
    owner's confidential_patterns LAST. Returns (sanitized_text, counts_by_label).
    Never raises; never touches disk or network."""
    counts = {}
    for pat, repl in SECRET_PATTERNS:
        text, n = pat.subn(repl, text)
        if n:
            counts[repl] = counts.get(repl, 0) + n
    for pat in _compile_confidential(patterns):
        text, n = pat.subn('<CONFIDENTIAL>', text)
        if n:
            counts['<CONFIDENTIAL>'] = counts.get('<CONFIDENTIAL>', 0) + n
    return text, counts


def _sanitize_obj(obj, patterns, counts):
    """Recursively walk a JSON-like structure, sanitizing every string leaf."""
    if isinstance(obj, str):
        new, c = sanitize(obj, patterns)
        for k, v in c.items():
            counts[k] = counts.get(k, 0) + v
        return new
    if isinstance(obj, dict):
        return {k: _sanitize_obj(v, patterns, counts) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_obj(x, patterns, counts) for x in obj]
    return obj


def sanitize_jsonl(in_path, out_path=None, patterns=None, check_only=False):
    """Process a JSONL file line by line, sanitizing every string field.
    Lines that are not valid JSON are still passed through the plain-text
    sanitizer (best effort) so malformed log lines are not skipped entirely."""
    in_path = Path(in_path)
    total_counts = {}
    lines_with_findings = 0
    total_lines = 0
    out_lines = []
    with in_path.open(encoding='utf-8', errors='replace') as f:
        for line in f:
            total_lines += 1
            if len(line) < 10:
                out_lines.append(line)
                continue
            counts = {}
            try:
                ev = json.loads(line)
                ev_clean = _sanitize_obj(ev, patterns, counts)
                rendered = json.dumps(ev_clean, ensure_ascii=False) + '\n'
            except json.JSONDecodeError:
                rendered, counts = sanitize(line, patterns)
            if counts:
                lines_with_findings += 1
                for k, v in counts.items():
                    total_counts[k] = total_counts.get(k, 0) + v
            if not check_only:
                out_lines.append(rendered)
    if not check_only and out_path:
        Path(out_path).write_text(''.join(out_lines), encoding='utf-8')
    return {
        'total_lines': total_lines,
        'lines_with_findings': lines_with_findings,
        'counts_by_pattern': total_counts,
        'total_redactions': sum(total_counts.values()),
    }


def _config_patterns():
    """Best-effort load of confidential_patterns from ~/.brain/config.json.
    Returns [] if brain_config is unavailable (kept optional so this module
    works standalone, e.g. under test, without the rest of the kit)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from brain_config import load_config
        return load_config().get('confidential_patterns', [])
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', help='input file (plain text or JSONL)')
    parser.add_argument('output', nargs='?', default=None, help='output file (omit for stdout)')
    parser.add_argument('--check', action='store_true', help='only count findings, do not write')
    parser.add_argument('--patterns', nargs='*', default=None,
                        help='extra confidential patterns (in addition to config)')
    parser.add_argument('--no-config', action='store_true',
                        help='skip loading confidential_patterns from config')
    args = parser.parse_args()

    patterns = [] if args.no_config else _config_patterns()
    patterns = list(patterns) + list(args.patterns or [])

    in_path = Path(args.input)
    if in_path.suffix == '.jsonl':
        result = sanitize_jsonl(args.input, args.output, patterns=patterns, check_only=args.check)
        print(f"lines: {result['total_lines']}")
        print(f"lines with findings: {result['lines_with_findings']}")
        print(f"total redactions: {result['total_redactions']}")
        if result['counts_by_pattern']:
            print("by pattern:")
            for k, v in sorted(result['counts_by_pattern'].items(), key=lambda x: -x[1]):
                print(f"  {v:5d}  {k}")
        if not args.check and args.output:
            print(f"output written to: {args.output}")
        return

    text = in_path.read_text(encoding='utf-8', errors='replace')
    clean, counts = sanitize(text, patterns)
    total = sum(counts.values())
    print(f"total redactions: {total}")
    if counts:
        print("by pattern:")
        for k, v in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"  {v:5d}  {k}")
    if not args.check:
        if args.output:
            Path(args.output).write_text(clean, encoding='utf-8')
            print(f"output written to: {args.output}")
        else:
            print(clean)


if __name__ == '__main__':
    main()
