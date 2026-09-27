"""Check public Git history for local identity and common credential leaks."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERIC_IDENTITY = "TransferPC <transferpc@users.noreply.github.com>"
SECRET = re.compile(rb"(?:(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})(?![A-Za-z0-9_])|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=]{40,})")


def private_markers() -> tuple[bytes, ...]:
    home = Path.home()
    # Generic container account names also occur in library text and notices.
    if home.name in {"root", "nobody"}:
        return ()
    if len(home.name) < 4:
        return (str(home).encode(),)
    return (str(home).encode(), home.name.encode())


def check_data(data: bytes) -> None:
    if any(marker in data for marker in private_markers()):
        raise ValueError("Local home path or username found")
    if SECRET.search(data):
        raise ValueError("Possible credential found")


def git(*arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def main() -> None:
    paths = git("ls-files", "-z").split(b"\0")
    excluded = {b"installer", b"build", b"dist", b".venv", b".agents", b".codex", b"__pycache__"}
    for raw in filter(None, paths):
        if any(part in excluded for part in raw.split(b"/")):
            raise ValueError("A private or generated directory is tracked")
        check_data((ROOT / raw.decode()).read_bytes())
    objects = git("rev-list", "--objects", "--all").splitlines()
    for entry in objects:
        oid = entry.split(b" ", 1)[0].decode()
        kind = git("cat-file", "-t", oid).strip()
        if kind == b"blob":
            check_data(git("cat-file", "blob", oid))
    identities = git("log", "--all", "--format=%an <%ae>%n%cn <%ce>").decode().splitlines()
    if any(identity != GENERIC_IDENTITY for identity in identities):
        raise ValueError("History contains a non-project author or committer identity")
    messages = git("log", "--all", "--format=%B")
    if re.search(rb"co-authored-by:", messages, re.I):
        raise ValueError("History contains a coauthor trailer")
    print(f"Public audit passed: {len(list(filter(None, paths)))} tracked files; history and identities checked.")


if __name__ == "__main__":
    main()
