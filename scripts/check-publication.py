#!/usr/bin/env python3
"""Check publishable files or the Git index; print locations, never secret values."""
import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----'),
    'provider token': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{30,}|AKIA[A-Z0-9]{16})'),
    'database contents': re.compile(rb'(?im)SQLite format 3\x00|^INSERT\s+INTO\s+[`"\[]?(?:accounts|sessions|agent_feedback)\b'),
    'stored password hash': re.compile(rb'pbkdf2_sha256\$\d+\$[a-f0-9]{32}\$[a-f0-9]{64}'),
    'credential in URL': re.compile(rb'(?i)(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s/:]+:[^\s/@]+@'),
}


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def forbidden(path):
    p = Path(path)
    example = p.name == '.env.example'
    return (
        (p.parts[0] == 'db' and path != 'db/.gitkeep')
        or (p.name.startswith('.env') and not example)
        or bool(re.search(r'(?i)\.(?:db|sqlite\d*)(?:[-.]|$)|\.(?:sql|dump|pem|key|p12|pfx|bak|backup)$', path))
        or any(part in {'backups', 'dumps', 'node_modules', '.venv'} for part in p.parts)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='inspect the full index, not working files')
    args = parser.parse_args()
    names = git('ls-files', '-z') if args.staged else git('ls-files', '-z', '--cached', '--others', '--exclude-standard')
    findings = []
    count = 0
    for name in sorted(set(names.split(b'\x00')) - {b''}):
        path = name.decode('utf-8', errors='surrogateescape')
        local = ROOT / path
        if args.staged:
            data = git('show', ':' + path)
        else:
            if not local.exists():
                continue
            if local.is_symlink():
                findings.append((path, 'symlink requires manual review'))
                continue
            data = local.read_bytes()
        count += 1
        if forbidden(path):
            findings.append((path, 'private/generated filename'))
        for kind, pattern in PATTERNS.items():
            if pattern.search(data):
                findings.append((path, kind))
    for path, kind in findings:
        print(f'BLOCK: {path}: {kind}')
    print(f'Checked {count} files; {len(findings)} findings. Heuristic check; manual review is still required.')
    return bool(findings)


if __name__ == '__main__':
    raise SystemExit(main())
