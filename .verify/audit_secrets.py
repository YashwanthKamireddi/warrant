"""Refuse to let credential material reach a public repository.

This repo is submitted publicly and is run locally with real Razorpay test keys
in a .env file. Those two facts sit one `git add -A` apart, and .gitignore is a
single line that a future edit can break without anyone noticing.

So the check is a gate rather than a habit. It fails on:

  * .env being tracked at all
  * a credential-shaped string in any tracked file, or anywhere in history
  * a .gitignore that no longer covers .env

Obvious placeholders are allowed, because .env.example exists to show the shape
and the rail tests need a key that looks live enough to be refused. Anything that
is not clearly a placeholder is treated as real.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Shapes worth panicking about.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("razorpay key id", re.compile(r"rzp_(?:test|live)_[A-Za-z0-9]{10,}")),
    ("anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("anthropic oauth token", re.compile(r"sk-ant-oat[A-Za-z0-9_\-]{10,}")),
    ("razorpay secret assignment", re.compile(r"RAZORPAY_KEY_SECRET\s*=\s*[A-Za-z0-9]{8,}")),
    ("aws access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)

# A placeholder is anything a reader would obviously not mistake for a credential.
PLACEHOLDER = re.compile(
    r"(?:x{6,}|abcdefgh|your[_-]?secret|placeholder|example|dummy|<[^>]+>)",
    re.I,
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout


failures: list[str] = []

# 1. .env must never be tracked.
tracked = subprocess.run(
    ["git", "ls-files", "--error-unmatch", ".env"],
    cwd=ROOT,
    capture_output=True,
    text=True,
    check=False,
)
if tracked.returncode == 0:
    failures.append(".env is tracked by git. Remove it from the index immediately.")

# 2. .gitignore must still cover it.
ignored = subprocess.run(
    ["git", "check-ignore", "-q", ".env"], cwd=ROOT, capture_output=True, check=False
)
if ignored.returncode != 0:
    failures.append(".env is no longer covered by .gitignore.")

# 3. No credential shapes in tracked files or in history.
def scan(label: str, text: str) -> None:
    for name, pattern in PATTERNS:
        for match in pattern.finditer(text):
            hit = match.group(0)
            line_no = text[: match.start()].count("\n") + 1
            line = text.splitlines()[line_no - 1] if text.splitlines() else ""
            if PLACEHOLDER.search(hit) or PLACEHOLDER.search(line):
                continue
            failures.append(f"{label}: possible {name} -> {hit[:24]}…")


for path_str in _git("ls-files").splitlines():
    path = ROOT / path_str
    if not path.is_file():
        continue
    try:
        scan(path_str, path.read_text(errors="ignore"))
    except OSError:  # pragma: no cover - unreadable file
        continue

scan("git history", _git("log", "-p", "--all"))

print(f"scanned {len(_git('ls-files').splitlines())} tracked files and full history")
if failures:
    print(f"\n{len(failures)} secret-exposure problem(s):")
    for f in dict.fromkeys(failures):
        print("  -", f)
    sys.exit(1)
print("no credential material tracked, staged, or in history")
